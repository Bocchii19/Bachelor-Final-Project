"""
PTZ Patrol — Main Entry Point.

Kết hợp giám sát xâm nhập (treo_rao) với PTZ phản ứng tự động:
  Fixed cameras detect xâm nhập → trigger PTZ → zoom → face capture

Usage:
    # Monitor mode — giám sát tự động
    python3 -m src.backend.modules.ptz_patrol --config config/patrol.yaml

    # No PTZ (dry-run) — chỉ giám sát fixed cameras
    python3 -m src.backend.modules.ptz_patrol --no-ptz

    # Preset Manager — quản lý preset (interactive GUI)
    python3 -m src.backend.modules.ptz_patrol --preset-manager
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from queue import Queue

from src.backend.core.config import RESULTS_DIR
from src.backend.core.ai.yolo import resolve_model_path, path_for_ultralytics_load
from src.backend.modules.fence.geometry import build_cam_roi_refs

from .config import load_patrol_config
from .monitor import IntrusionMonitor, TriggerEvent
from .tracker import PatrolTracker, PTZStreamReader, IntrusionEvent
from .ptz_control import PTZController
from .face_capture import FaceCapture

logger = logging.getLogger(__name__)


def on_intrusion_event(event: IntrusionEvent) -> None:
    """Callback khi xử lý xong 1 intrusion."""
    print(
        f"\n{'='*50}\n"
        f"  ⚠️  INTRUSION EVENT\n"
        f"  Preset:  [{event.preset_id}] {event.preset_name}\n"
        f"  Camera:  {event.fixed_camera_id}\n"
        f"  Persons: {event.total_persons}\n"
        f"  Faces:   {len(event.face_captures)}\n"
        f"  Time:    {event.duration_ms:.0f}ms\n"
        f"{'='*50}"
    )
    for cap in event.face_captures:
        paths = cap.get("paths", {})
        print(
            f"  Person {cap['person_index']}: "
            f"conf={cap['face_confidence']:.2f} "
            f"→ {paths.get('face_path', 'N/A')}"
        )
    print(f"{'='*50}\n")


def run_monitor(config: dict, args) -> None:
    """
    Run monitor mode:
    - N threads IntrusionMonitor (1 per fixed cam)
    - 1 PatrolTracker waiting for triggers
    """

    # ── Load presets ──
    presets = config.get("presets", [])
    valid_presets = [
        p for p in presets
        if p.get("fixed_camera_url") and p.get("enabled", True) is not False
    ]
    skipped = [p.get("name", p.get("id")) for p in presets if p.get("enabled") is False]
    if skipped:
        logger.info("Skipped disabled presets: %s", skipped)

    if not valid_presets:
        logger.error(
            "No presets with fixed_camera_url configured!\n"
            "Check config/patrol.yaml presets section."
        )
        sys.exit(1)

    logger.info("Loaded %d preset(s) with fixed cameras", len(valid_presets))

    # ── YOLO Model ──
    det_cfg = config.get("detection", {})
    user_model = Path(args.model) if args.model else None
    try:
        model_path = resolve_model_path(user_model)
    except FileNotFoundError as e:
        logger.error("Model not found: %s", e)
        sys.exit(1)

    load_path = path_for_ultralytics_load(model_path)

    from src.backend.core.ai.yolo_shared import SharedYOLO
    logger.info("Loading YOLO (shared session): %s", load_path)
    yolo = SharedYOLO(load_path)

    conf = det_cfg.get("confidence_threshold", 0.5)
    device = det_cfg.get("device", "0")
    imgsz = det_cfg.get("imgsz", 640)

    # Warmup: initialize single ONNX CUDA session BEFORE spawning threads
    yolo.warmup(device=device, imgsz=imgsz)

    # ── PTZ Controller ──
    ptz_cfg = config.get("ptz_camera", {})
    ptz = PTZController(
        host=ptz_cfg.get("ip", "127.0.0.1"),
        port=ptz_cfg.get("port", 80),
        username=ptz_cfg.get("username", "admin"),
        password=ptz_cfg.get("password", ""),
    )

    if not args.no_ptz:
        if not ptz.connect():
            logger.error("PTZ connection failed!")
            sys.exit(1)

    # ── PTZ Stream ──
    ptz_rtsp = ptz_cfg.get("rtsp_url", "")
    stream = PTZStreamReader(ptz_rtsp)
    if ptz_rtsp and not args.no_ptz:
        stream.open()

    # ── Face Capture ──
    face_cfg = config.get("face_recognition", {})
    face = FaceCapture(
        save_dir=face_cfg.get("save_dir", "results/captures"),
        min_face_size=face_cfg.get("min_face_size", 50),
    )
    face.initialize()

    # ── Shared Queue ──
    trigger_queue: Queue[TriggerEvent] = Queue()

    # ── ROI data ──
    cameras = config.get("_cameras", {})
    rtsp_list = [(cam_id, url) for cam_id, url in cameras.items()]
    polygon_yaml = config.get("_polygon_yaml", Path("config/polygon.yaml"))
    configs_yaml = config.get("_configs_yaml", Path("src/backend/api/configs.yaml"))
    roi_by_cam = build_cam_roi_refs(rtsp_list, polygon_yaml, configs_yaml)

    results_dir = config.get("_results_dir", RESULTS_DIR)
    patrol_cfg = config.get("patrol", {})
    cooldown = patrol_cfg.get("cooldown", 10.0)

    # ── Webhook Dispatcher ──
    from src.backend.core.webhook import AsyncWebhookDispatcher
    webhook_dispatcher = AsyncWebhookDispatcher()

    # ── Start Fixed Camera Monitors ──
    monitors: list[IntrusionMonitor] = []
    region2_schedule = config.get("region2_schedule")

    for preset in valid_presets:
        cam_id = preset.get("fixed_camera_id", "")
        roi = roi_by_cam.get(cam_id)
        cam_conf = preset.get("conf", conf)  # Per-camera override

        monitor = IntrusionMonitor(
            preset=preset,
            model=yolo,
            trigger_queue=trigger_queue,
            roi=roi,
            cooldown=cooldown,
            conf=cam_conf,
            device=device,
            imgsz=imgsz,
            results_dir=results_dir,
            webhook_dispatcher=webhook_dispatcher,
            region2_schedule=region2_schedule,
        )
        monitors.append(monitor)
        monitor.start()
        logger.info(
            "  ✅ Monitor started: Preset %d (%s) → %s [conf=%.2f]",
            preset["id"], preset.get("name", ""), cam_id, cam_conf,
        )

    # ── Build Patrol Tracker ──
    zoom_cfg = config.get("zoom_track", {})

    # Load PTZ fence lines from polygon.yaml → ptz_presets section
    ptz_fence_lines: dict = {}
    try:
        import yaml
        poly_data = yaml.safe_load(polygon_yaml.read_text(encoding="utf-8"))
        ptz_presets_data = poly_data.get("ptz_presets", {}) if isinstance(poly_data, dict) else {}
        for pid_str, pnode in ptz_presets_data.items():
            if not isinstance(pnode, dict):
                continue
            pid = int(pid_str)
            line = pnode.get("line", [])
            res = pnode.get("resolution", {})
            res_w = int(res.get("width", 640)) if isinstance(res, dict) else 640
            res_h = int(res.get("height", 360)) if isinstance(res, dict) else 360
            if isinstance(line, list) and len(line) >= 2:
                parsed = [[float(p[0]), float(p[1])] for p in line if isinstance(p, list) and len(p) == 2]
                if len(parsed) >= 2:
                    ptz_fence_lines[pid] = {
                        "line": parsed,
                        "resolution": (res_w, res_h),
                    }
                    logger.info(
                        "  PTZ fence line: preset %d (%s) — %d points",
                        pid, pnode.get("preset_name", ""), len(parsed),
                    )
    except Exception as e:
        logger.warning("Failed to load PTZ fence lines: %s", e)

    tracker = PatrolTracker(
        ptz=ptz,
        model=yolo,
        stream=stream,
        face=face,
        trigger_queue=trigger_queue,
        presets=valid_presets,
        target_bbox_ratio=zoom_cfg.get("target_bbox_ratio", 0.6),
        max_zoom_steps=zoom_cfg.get("max_zoom_steps", 25),
        zoom_step=zoom_cfg.get("zoom_step", 5),
        zoom_duration=zoom_cfg.get("zoom_duration", 0.3),
        center_tolerance=zoom_cfg.get("center_tolerance", 0.15),
        disable_tracking=zoom_cfg.get("disable_tracking", False),
        control_mode=zoom_cfg.get("control_mode", "pid"),
        pid_gains=zoom_cfg.get("pid", None),
        pid_settle=zoom_cfg.get("pid_settle", 0.35),
        conf=conf,
        device=device,
        imgsz=imgsz,
        ptz_fence_lines=ptz_fence_lines,
        webhook_dispatcher=webhook_dispatcher,
        ptz_device_name=ptz_cfg.get("device_name", ""),
        on_intrusion=on_intrusion_event,
    )

    # ── Graceful shutdown ──
    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        tracker.stop()
        for m in monitors:
            m.stop()
        webhook_dispatcher.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(
        f"\n{'='*60}\n"
        f"  PTZ PATROL — Intrusion Detection + Face Capture\n"
        f"  {len(monitors)} fixed camera(s) monitoring\n"
        f"  PTZ: {'connected' if ptz.is_connected else 'disabled (--no-ptz)'}\n"
        f"  Waiting for intrusion triggers...\n"
        f"{'='*60}\n"
    )

    # ── Run Tracker (blocking) ──
    tracker.run()

    # ── Cleanup ──
    for m in monitors:
        m.stop()
    stream.release()
    ptz.disconnect()
    logger.info("Done.")


def main():
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="PTZ Patrol — Intrusion Detection + PTZ Face Capture"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Config file (default: config/patrol.yaml)",
    )
    parser.add_argument(
        "--no-ptz",
        action="store_true",
        help="Disable PTZ connection (monitor-only mode)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to YOLO model (.onnx/.engine/.pt)",
    )
    parser.add_argument(
        "--preset-manager",
        action="store_true",
        help="Run Preset Manager GUI (from ptz_patrol)",
    )

    args = parser.parse_args()
    config = load_patrol_config(args.config)

    if args.preset_manager:
        # Delegate to original preset manager
        try:
            from ptz_patrol.src.ray_engine import PresetManagerApp
            app = PresetManagerApp(config)
            app.run()
        except ImportError:
            logger.error(
                "Preset Manager requires ptz_patrol package.\n"
                "Run from project root: python3 -m ptz_patrol.src.ray_engine"
            )
            sys.exit(1)
    else:
        run_monitor(config, args)


if __name__ == "__main__":
    main()
