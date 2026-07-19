#!/usr/bin/env python3
"""
test_fence_live.py — Visual fence detection test (4-camera grid).

Shows 2×2 grid: 3 fixed cameras + PTZ.
YOLO inference runs on the selected camera (highlighted).
Press Tab to cycle active detection camera.
When intrusion detected → PTZ goto preset → zoom & center on person.

Usage:
    cd Hiep/
    python3 src/tools/test_fence_live.py --model /path/to/model.onnx
    python3 src/tools/test_fence_live.py --no-ptz --model /path/to/model.onnx
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.backend.core.config import CONFIG_DIR
from src.backend.core.camera.stream import open_capture
from src.backend.core.ai.yolo import resolve_model_path, path_for_ultralytics_load
from src.backend.core.logger import get_logger
from src.backend.modules.fence.config import load_patrol_config
from src.backend.modules.fence.geometry import build_cam_roi_refs
from src.backend.modules.fence.monitor import (
    IntrusionAlertState, AlertFrameFeat,
    evaluate_intrusion_alert, largest_person_box_xyxy,
)
from src.backend.modules.fence.ptz_control import PTZController
from src.backend.core.utils.polygon import scale_polygon_xy, apply_region1_zero_inside
from src.backend.core.webhook import AsyncWebhookDispatcher, FENCE_INTRUSION_ALARM_CODE

logger = get_logger(__name__)


def foot_below_fence_polyline(fx, fy, pts, iw, ih):
    from src.backend.modules.fence.geometry import foot_below_fence_polyline as _fn
    return _fn(fx, fy, pts, iw, ih)


def draw_cam_label(frame, label, is_active, streak=0):
    """Draw device label + active indicator on a camera tile."""
    h, w = frame.shape[:2]

    # Active border
    if is_active:
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 255, 255), 3)

    # Label background
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (min(w, 280), 22), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    # Device name
    color = (0, 255, 255) if is_active else (180, 180, 180)
    active_marker = " [DETECT]" if is_active else ""
    cv2.putText(frame, f"{label}{active_marker}", (4, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

    # Alert banner
    if streak >= 3:
        cv2.rectangle(frame, (0, h - 22), (w, h), (0, 0, 200), -1)
        cv2.putText(frame, "!! INTRUSION !!", (w // 2 - 55, h - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

    return frame


def draw_detections(frame, results, roi, iw, ih):
    """Draw YOLO boxes, fence line, ROI polygon on frame."""
    # Fence line
    if roi and roi.fence_line is not None:
        frw, frh = roi.fence_line_ref
        sx = float(iw) / float(frw) if frw > 0 else 1.0
        sy = float(ih) / float(frh) if frh > 0 else 1.0
        pts = np.array([[p[0] * sx, p[1] * sy] for p in roi.fence_line], dtype=np.int32)
        cv2.polylines(frame, [pts], isClosed=False, color=(0, 255, 255), thickness=2)

    # Config polygon
    if roi and roi.config_poly is not None and len(roi.config_poly) >= 3:
        cfs = scale_polygon_xy(roi.config_poly, roi.config_ref[0], roi.config_ref[1], iw, ih)
        if cfs is not None:
            cv2.polylines(frame, [cfs.astype(np.int32)], isClosed=True,
                          color=(255, 0, 255), thickness=1)

    # Region1 boundary
    if roi and roi.region1 is not None and len(roi.region1) >= 3:
        r1s = scale_polygon_xy(roi.region1, roi.region1_ref[0], roi.region1_ref[1], iw, ih)
        if r1s is not None:
            cv2.polylines(frame, [r1s.astype(np.int32)], isClosed=True,
                          color=(100, 100, 100), thickness=1)

    # YOLO boxes
    if results is not None:
        res = results[0] if results else None
        if res is not None and res.boxes is not None:
            for box in res.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf_val = float(box.conf[0])
                cls = int(box.cls[0])
                if cls == 0:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"{conf_val:.2f}", (x1, y1 - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 0), 1, cv2.LINE_AA)
                    cx = (x1 + x2) // 2
                    cv2.circle(frame, (cx, y2), 3, (0, 0, 255), -1)

    return frame


def draw_ptz_detections(frame: np.ndarray, results, n_persons_total: int) -> tuple[np.ndarray, int]:
    """Draw YOLO detections on PTZ frame (same style as test_ptz_v5)."""
    out = frame.copy()
    h, w = out.shape[:2]
    n_persons = 0

    if results is not None:
        res = results[0] if results else None
        if res is not None and res.boxes is not None:
            names = getattr(res, "names", {}) or {}
            for box in res.boxes:
                try:
                    xy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], "cpu") else box.xyxy[0].numpy()
                    x1, y1, x2, y2 = int(xy[0]), int(xy[1]), int(xy[2]), int(xy[3])
                except Exception:
                    continue
                try:
                    cls_id = int(box.cls[0].item() if hasattr(box.cls[0], "item") else int(box.cls[0]))
                except (TypeError, ValueError, IndexError):
                    cls_id = -1
                try:
                    cf = float(box.conf[0].item() if hasattr(box.conf[0], "item") else float(box.conf[0]))
                except (TypeError, ValueError, IndexError):
                    cf = 0.0

                label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id)

                if cls_id == 0:  # person
                    color = (0, 255, 0)
                    n_persons += 1
                else:
                    color = (255, 165, 0)

                # Bbox
                cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

                # Label + confidence
                cap_text = f"{label} {cf:.2f}"
                (tw, th_t), _ = cv2.getTextSize(cap_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                cv2.rectangle(out, (x1, y1 - th_t - 6), (x1 + tw + 4, y1), color, -1)
                cv2.putText(out, cap_text, (x1 + 2, y1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

                # Foot point (bottom center)
                cx = (x1 + x2) // 2
                cv2.circle(out, (cx, y2), 4, (0, 0, 255), -1)

    # Person count badge (top-right)
    if n_persons > 0:
        count_text = f"{n_persons} person{'s' if n_persons > 1 else ''}"
        (tw, th_t), _ = cv2.getTextSize(count_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        rx = w - tw - 12
        ry = 26
        cv2.rectangle(out, (rx - 6, ry - th_t - 6), (w, ry + 6), (0, 0, 180), -1)
        cv2.putText(out, count_text, (rx, ry),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)

    return out, n_persons


# ---------------------------------------------------------------------------
# PTZ Zoom & Center (runs inline with display update)
# ---------------------------------------------------------------------------

def zoom_and_center_ptz(
    ptz: PTZController,
    ptz_cap,
    yolo,
    conf: float,
    device: str,
    imgsz: int,
    zoom_cfg: dict,
    *,
    win_name: str,
    fixed_caps: dict,
    active_cam_ids: list,
    active_idx: int,
    alert_states: dict,
    roi_by_cam: dict,
    TILE_W: int = 640,
    TILE_H: int = 360,
) -> bool:
    """
    Zoom & center PTZ on detected person.

    Runs the loop inline — reads PTZ frame, detects, centers, zooms —
    while updating the 4-cam grid display so the user can see progress.
    Returns True if zoom succeeded.
    """
    target_ratio = zoom_cfg.get("target_bbox_ratio", 0.6)
    max_steps = zoom_cfg.get("max_zoom_steps", 25)
    z_step = zoom_cfg.get("zoom_step", 5)
    z_dur = zoom_cfg.get("zoom_duration", 0.3)
    center_tol = zoom_cfg.get("center_tolerance", 0.15)

    for step_i in range(max_steps):
        # Flush PTZ buffer & read latest frame
        if ptz_cap is not None and ptz_cap.isOpened():
            for _ in range(5):
                ptz_cap.grab()
            ret, ptz_frame = ptz_cap.read()
        else:
            return False

        if not ret or ptz_frame is None:
            time.sleep(0.2)
            continue

        # Detect person on PTZ stream
        ptz_results = yolo(ptz_frame, conf=conf, device=device, imgsz=imgsz, verbose=False)
        ptz_res = ptz_results[0] if ptz_results else None

        # Find largest person bbox
        persons = []
        if ptz_res is not None and ptz_res.boxes is not None:
            for box in ptz_res.boxes:
                cls_id = int(box.cls[0])
                if cls_id != 0:
                    continue
                xy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = int(xy[0]), int(xy[1]), int(xy[2]), int(xy[3])
                cf = float(box.conf[0])
                persons.append((x1, y1, x2, y2, cf))

        if not persons:
            # Draw PTZ tile with status and update display
            _update_grid_display(
                ptz_frame, ptz_results, f"ZOOM step {step_i}: no person",
                win_name, fixed_caps, active_cam_ids, active_idx,
                alert_states, roi_by_cam, TILE_W, TILE_H,
            )
            time.sleep(0.3)
            if step_i >= 3:  # Give up after 3 empty steps
                print("  ⚠️  Lost person during zoom")
                return False
            continue

        # Use largest person
        best = max(persons, key=lambda d: (d[2] - d[0]) * (d[3] - d[1]))
        x1, y1, x2, y2, _ = best
        fh, fw = ptz_frame.shape[:2]

        bbox_cx = (x1 + x2) / 2
        bbox_cy = (y1 + y2) / 2
        bbox_h = y2 - y1
        frame_cx = fw / 2
        frame_cy = fh / 2

        offset_x = (bbox_cx - frame_cx) / fw
        offset_y = (bbox_cy - frame_cy) / fh
        bbox_ratio = bbox_h / fh

        status = f"ZOOM {step_i}: ratio={bbox_ratio:.2f} offset=({offset_x:.2f},{offset_y:.2f})"
        print(f"  🔍 {status}")

        # Draw YOLO boxes on PTZ tile
        for (bx1, by1, bx2, by2, bcf) in persons:
            cv2.rectangle(ptz_frame, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
            cv2.putText(ptz_frame, f"{bcf:.2f}", (bx1, by1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 0), 1)
        # Highlight target person
        cv2.rectangle(ptz_frame, (x1, y1), (x2, y2), (0, 255, 255), 3)

        _update_grid_display(
            ptz_frame, None, status,
            win_name, fixed_caps, active_cam_ids, active_idx,
            alert_states, roi_by_cam, TILE_W, TILE_H,
        )

        # Check if target reached
        if bbox_ratio >= target_ratio:
            print(f"  ✅ Zoom target reached: ratio={bbox_ratio:.2f}")
            # Autofocus after zoom
            ptz.autofocus()
            return True

        # Center if offset is too large
        if abs(offset_x) > center_tol or abs(offset_y) > center_tol:
            if abs(offset_x) > center_tol:
                pan_step = min(8, max(2, int(abs(offset_x) * 24)))
                pan_dur = min(0.6, max(0.15, abs(offset_x) * 1.2))
                cmd = "kCmdRight" if offset_x > 0 else "kCmdLeft"
                ptz.move_direction(cmd, step=pan_step, duration=pan_dur)
                time.sleep(0.15)

            if abs(offset_y) > center_tol:
                tilt_step = min(8, max(2, int(abs(offset_y) * 24)))
                tilt_dur = min(0.6, max(0.15, abs(offset_y) * 1.2))
                cmd = "kCmdDown" if offset_y > 0 else "kCmdUp"
                ptz.move_direction(cmd, step=tilt_step, duration=tilt_dur)
                time.sleep(0.15)
        else:
            # Centered enough → zoom in
            ptz.zoom_in(step=z_step, duration=z_dur)
            time.sleep(0.15)

        time.sleep(0.2)

    print("  ⚠️  Max zoom steps reached")
    return False


def _update_grid_display(
    ptz_frame, ptz_results, ptz_status,
    win_name, fixed_caps, active_cam_ids, active_idx,
    alert_states, roi_by_cam, TILE_W, TILE_H,
):
    """Render and show the 4-cam grid (helper for zoom loop)."""
    tiles = []
    for cam_id in active_cam_ids:
        cap = fixed_caps.get(cam_id)
        if cap is not None and cap.isOpened():
            ok, frame = cap.read()
            if not ok or frame is None:
                frame = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
        else:
            frame = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
        tile = cv2.resize(frame, (TILE_W, TILE_H))
        is_active = (cam_id == active_cam_ids[active_idx])
        st = alert_states.get(cam_id)
        streak = (st.consec_above if st and st.consec_above > 0 else (st.consec_any if st else 0))
        draw_cam_label(tile, cam_id, is_active, streak)
        tiles.append(tile)

    # PTZ tile
    ptz_tile = cv2.resize(ptz_frame, (TILE_W, TILE_H))
    # Status banner
    cv2.rectangle(ptz_tile, (0, TILE_H - 24), (TILE_W, TILE_H), (0, 120, 0), -1)
    cv2.putText(ptz_tile, ptz_status, (4, TILE_H - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
    draw_cam_label(ptz_tile, "PTZ [ZOOMING]", False, 0)

    while len(tiles) < 3:
        blank = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
        tiles.append(blank)
    tiles.append(ptz_tile)

    row1 = np.hstack([tiles[0], tiles[1]])
    row2 = np.hstack([tiles[2], tiles[3]])
    grid = np.vstack([row1, row2])
    cv2.imshow(win_name, grid)
    cv2.waitKey(1)


def main():
    parser = argparse.ArgumentParser(description="Visual fence detection test (4-cam grid)")
    parser.add_argument("--model", type=str, default=None, help="Model path (.onnx/.engine/.pt)")
    parser.add_argument("--no-ptz", action="store_true", help="Disable PTZ")
    parser.add_argument("--hw-decode", action="store_true",
                        help="Use HW decoder for fixed cameras (default: SW to save GPU RAM)")
    args = parser.parse_args()

    # Load config
    config = load_patrol_config(None)
    presets = config.get("presets", [])

    # All cameras
    cameras = config.get("_cameras", {})
    cam_list = list(cameras.items())  # [(cam_id, rtsp_url), ...]
    if not cam_list:
        print("❌ No cameras configured!")
        sys.exit(1)

    print(f"📹 Found {len(cam_list)} fixed camera(s): {[c[0] for c in cam_list]}")

    # Load YOLO
    user_model = Path(args.model) if args.model else None
    model_path = resolve_model_path(user_model)
    load_path = path_for_ultralytics_load(model_path)

    from ultralytics import YOLO
    print(f"🤖 Loading YOLO: {load_path}")
    yolo = YOLO(str(load_path), task="detect")

    det_cfg = config.get("detection", {})
    conf = det_cfg.get("confidence_threshold", 0.5)
    device = det_cfg.get("device", "0")
    imgsz = det_cfg.get("imgsz", 640)

    # Warmup
    print("🔥 Warmup inference...")
    dummy = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
    yolo(dummy, conf=conf, device=device, imgsz=imgsz, verbose=False)
    print("✅ Model ready")

    # Webhook dispatcher (background workers)
    webhook_dispatcher = AsyncWebhookDispatcher()
    print("📡 Webhook dispatcher ready")

    # PTZ
    ptz_cfg = config.get("ptz_camera", {})
    ptz = PTZController(
        host=ptz_cfg.get("ip", "127.0.0.1"),
        port=ptz_cfg.get("port", 80),
        username=ptz_cfg.get("username", "admin"),
        password=ptz_cfg.get("password", ""),
    )
    ptz_rtsp = ptz_cfg.get("rtsp_url", "")
    ptz_cap = None

    if not args.no_ptz:
        print(f"🔗 Connecting PTZ: {ptz_cfg.get('ip')}...")
        if ptz.connect():
            print("✅ PTZ connected")
            ptz_cap, _, _ = open_capture(ptz_rtsp, use_hwaccel=True, debug_label="PTZ")
        else:
            print("⚠️  PTZ connection failed")

    # ROI data
    rtsp_list = [(cam_id, url) for cam_id, url in cameras.items()]
    polygon_yaml = config.get("_polygon_yaml", Path("config/polygon.yaml"))
    configs_yaml = config.get("_configs_yaml", Path("src/backend/api/configs.yaml"))
    roi_by_cam = build_cam_roi_refs(rtsp_list, polygon_yaml, configs_yaml)

    # Open ALL fixed cameras (SW decode by default to save GPU memory)
    fixed_hwaccel = args.hw_decode
    decode_mode = "HW" if fixed_hwaccel else "SW"
    print(f"📹 Opening fixed cameras ({decode_mode} decode)...")
    fixed_caps = {}
    for cam_id, cam_url in cam_list:
        print(f"  📹 {cam_id}...")
        cap, mode, _ = open_capture(cam_url, use_hwaccel=fixed_hwaccel, debug_label=cam_id)
        if cap is not None:
            fixed_caps[cam_id] = cap
            print(f"  ✅ {cam_id} opened ({mode})")
        else:
            print(f"  ❌ Failed to open {cam_id}")

    if not fixed_caps:
        print("❌ No cameras could be opened!")
        sys.exit(1)

    # Per-camera alert state
    alert_states = {cam_id: IntrusionAlertState() for cam_id in fixed_caps}

    # Active camera index (for YOLO detection)
    active_idx = 0
    active_cam_ids = list(fixed_caps.keys())
    cooldown = config.get("patrol", {}).get("cooldown", 10.0)
    last_trigger_time = 0.0

    # Window
    win_name = "Fence Detection Test (4-cam)"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, 1280, 720)

    frame_count = 0
    t_start = time.time()

    print(f"\n{'='*50}")
    print(f"  4-CAMERA GRID | Tab=switch active | Q=quit")
    print(f"  Active detection: {active_cam_ids[active_idx]}")
    print(f"  Device: {device}")
    print(f"{'='*50}\n")

    TILE_W = 640
    TILE_H = 360

    try:
        while True:
            tiles = []
            active_cam_id = active_cam_ids[active_idx]

            # Read & process each fixed camera
            for cam_id in active_cam_ids:
                cap = fixed_caps[cam_id]
                ok, frame = cap.read()
                if not ok or frame is None:
                    frame = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
                    cv2.putText(frame, f"{cam_id} — NO SIGNAL", (20, TILE_H // 2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)

                ih, iw = frame.shape[:2]
                is_active = (cam_id == active_cam_id)
                roi = roi_by_cam.get(cam_id)
                alert_state = alert_states[cam_id]
                streak = alert_state.consec_above if alert_state.consec_above > 0 else alert_state.consec_any

                # Run YOLO only on active camera
                if is_active and ok:
                    frame_count += 1
                    r1s = None
                    if roi and roi.region1 is not None and len(roi.region1) >= 3:
                        r1s = scale_polygon_xy(roi.region1, roi.region1_ref[0], roi.region1_ref[1], iw, ih)
                    masked = apply_region1_zero_inside(frame.copy(), r1s)

                    results = yolo(masked, conf=conf, device=device, imgsz=imgsz, verbose=False)
                    res = results[0] if results else None

                    # Alert evaluation
                    bbox = largest_person_box_xyxy(res) if res is not None else None
                    had_person = bbox is not None
                    bot_in_cfg = False
                    below_ln = False
                    center_above = False
                    has_fl = roi is not None and roi.fence_line is not None

                    if bbox is not None:
                        bx = (bbox[0] + bbox[2]) / 2.0
                        by = bbox[3]
                        cx_pt = bx
                        cy_pt = (bbox[1] + bbox[3]) / 2.0

                        if roi and roi.config_poly is not None and len(roi.config_poly) >= 3:
                            cfs = scale_polygon_xy(roi.config_poly, roi.config_ref[0], roi.config_ref[1], iw, ih)
                            if cfs is not None and cfs.shape[0] >= 3:
                                bot_in_cfg = cv2.pointPolygonTest(cfs, (bx, by), False) >= 0

                        if roi and roi.fence_line is not None:
                            frw, frh = roi.fence_line_ref
                            sx = float(iw) / float(frw) if frw > 0 else 1.0
                            sy = float(ih) / float(frh) if frh > 0 else 1.0
                            pts_scaled = [[p[0] * sx, p[1] * sy] for p in roi.fence_line]
                            below_ln = foot_below_fence_polyline(bx, by, pts_scaled, iw, ih)
                            center_above = not foot_below_fence_polyline(cx_pt, cy_pt, pts_scaled, iw, ih)

                    event_fired = evaluate_intrusion_alert(
                        alert_state,
                        AlertFrameFeat(
                            had_person=had_person,
                            bottom_in_cfg_polygon=bot_in_cfg,
                            person_below_fence_line=below_ln,
                            center_above_fence_line=center_above,
                            has_fence_line=has_fl,
                        ),
                        cam_label=cam_id,
                    )

                    # Webhook + PTZ trigger
                    if event_fired:
                        # Gửi webhook ngay khi phát hiện xâm nhập
                        webhook_dispatcher.enqueue(
                            frame, cam_id, FENCE_INTRUSION_ALARM_CODE
                        )
                        print(f"📡 Webhook queued: {FENCE_INTRUSION_ALARM_CODE} | {cam_id}")

                        # PTZ trigger (nếu bật)
                        if not args.no_ptz and ptz.is_connected:
                            now = time.time()
                            if now - last_trigger_time >= cooldown:
                                last_trigger_time = now
                                preset_match = next((p for p in presets if p.get("fixed_camera_id") == cam_id), None)
                                if preset_match:
                                    pid = preset_match["id"]
                                    settle = preset_match.get("settle_time", 2.0)
                                    print(f"🚨 TRIGGER → PTZ goto preset {pid} ({cam_id})")
                                    ptz.goto_preset(pid)
                                    print(f"  ⏳ Waiting {settle}s for PTZ to settle...")
                                    time.sleep(settle)

                                    # Zoom & center on person
                                    zoom_cfg = config.get("zoom_track", {})
                                    print(f"  🔍 Starting zoom & center (target_ratio={zoom_cfg.get('target_bbox_ratio', 0.6)})...")
                                    zoom_ok = zoom_and_center_ptz(
                                        ptz, ptz_cap, yolo, conf, device, imgsz,
                                        zoom_cfg,
                                        win_name=win_name,
                                        fixed_caps=fixed_caps,
                                        active_cam_ids=active_cam_ids,
                                        active_idx=active_idx,
                                        alert_states=alert_states,
                                        roi_by_cam=roi_by_cam,
                                        TILE_W=TILE_W,
                                        TILE_H=TILE_H,
                                    )
                                    if zoom_ok:
                                        print(f"  ✅ PTZ zoom complete!")
                                    else:
                                        print(f"  ⚠️  PTZ zoom did not reach target")

                    # Draw detections
                    draw_detections(frame, results, roi, iw, ih)
                    streak = alert_state.consec_above if alert_state.consec_above > 0 else alert_state.consec_any

                # Resize tile
                tile = cv2.resize(frame, (TILE_W, TILE_H))
                draw_cam_label(tile, cam_id, is_active, streak)
                tiles.append(tile)

            # PTZ tile — run YOLO detection (like test_ptz_v5)
            ptz_tile = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
            ptz_n_persons = 0
            if ptz_cap is not None:
                ret, pf = ptz_cap.read()
                if ret and pf is not None:
                    # Run YOLO on PTZ frame
                    ptz_results = yolo(pf, conf=conf, device=device, imgsz=imgsz, verbose=False)
                    pf_drawn, ptz_n_persons = draw_ptz_detections(pf, ptz_results, 0)
                    ptz_tile = cv2.resize(pf_drawn, (TILE_W, TILE_H))
            ptz_label = f"PTZ [{ptz_n_persons}p]" if ptz_n_persons > 0 else "PTZ"
            draw_cam_label(ptz_tile, ptz_label, False, 0)

            # Pad tiles to 4 if needed
            while len(tiles) < 3:
                blank = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
                cv2.putText(blank, "No Camera", (TILE_W // 2 - 50, TILE_H // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)
                tiles.append(blank)

            tiles.append(ptz_tile)

            # 2×2 grid
            row1 = np.hstack([tiles[0], tiles[1]])
            row2 = np.hstack([tiles[2], tiles[3]])
            grid = np.vstack([row1, row2])

            # FPS + controls overlay (top-right)
            fps = frame_count / max(time.time() - t_start, 0.001)
            info = f"FPS: {fps:.1f} | device: {device} | Tab=switch | Q=quit"
            cv2.putText(grid, info, (grid.shape[1] - 420, 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1, cv2.LINE_AA)

            cv2.imshow(win_name, grid)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
            elif key == 9:  # Tab
                active_idx = (active_idx + 1) % len(active_cam_ids)
                alert_states[active_cam_ids[active_idx]] = IntrusionAlertState()
                print(f"🔄 Active: {active_cam_ids[active_idx]}")
                frame_count = 0
                t_start = time.time()

    except KeyboardInterrupt:
        print("\n⏹  Stopped")
    finally:
        webhook_dispatcher.stop(timeout=3.0)
        for cap in fixed_caps.values():
            cap.release()
        if ptz_cap:
            ptz_cap.release()
        ptz.disconnect()
        cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    main()
