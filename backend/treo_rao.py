"""
Treo Rao — Intrusion detection on RTSP streams using YOLO.

Main script: processes RTSP camera feeds, applies ROI masking,
runs YOLO inference, and triggers alerts when persons are detected
above the fence line for 3+ consecutive frames.

Usage:
    python -m src.backend.treo_rao
    python -m src.backend.treo_rao --dump-roi-frame
    python -m src.backend.treo_rao --record-frames --debug-roi
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from src.backend.core.config import RTSP_URLS, POLYGON_YAML, CONFIGS_YAML, RESULTS_DIR
from src.backend.core.camera import open_capture
from src.backend.core.model import (
    resolve_model_path, path_for_ultralytics_load, is_tensorrt_path,
    maybe_empty_cuda_cache, extract_trt_imgsz_from_assertion,
)
from src.backend.core.detection import (
    has_any_detection, person_class_ids, point_in_polygon,
    draw_model_boxes_bgr, save_person_image_and_yolo, largest_person_box_xyxy,
)
from src.backend.core.polygon import (
    CameraRoiRefs, build_cam_roi_refs,
    scale_polygon_xy, apply_region1_zero_inside, draw_roi_overlay_bgr,
    foot_below_fence_polyline,
)
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Alert logic
# ---------------------------------------------------------------------------

@dataclass
class AlertFrameFeat:
    had_person: bool
    bottom_in_cfg_polygon: bool
    person_below_fence_line: bool
    center_above_fence_line: bool
    has_fence_line: bool


@dataclass
class IntrusionAlertState:
    consec_any: int = 0
    consec_above: int = 0
    consec_bottom_cfg: int = 0
    history: deque[AlertFrameFeat] = field(default_factory=lambda: deque(maxlen=32))


def should_suppress_warn_from_history(history: deque[AlertFrameFeat]) -> bool:
    """Suppress alert if person was below fence line in recent history."""
    if len(history) < 8:
        return False
    pre5 = list(history)[-8:-3]
    for h in pre5:
        if h.had_person and h.person_below_fence_line:
            return True
    return False


def evaluate_intrusion_alert(
    state: IntrusionAlertState,
    frame_feat: AlertFrameFeat,
    *,
    cam_label: str,
) -> bool:
    """
    Update state and trigger alert.
    - With fence line: trigger when bbox center above line >= 3 consecutive frames.
    - Without fence line (fallback): trigger when person detected >= 3 consecutive frames.
    Returns True only at frame #3 of a streak (to save event image once).
    """
    if frame_feat.had_person:
        state.consec_any += 1
    else:
        state.consec_any = 0

    if frame_feat.center_above_fence_line:
        state.consec_above += 1
    else:
        state.consec_above = 0

    if frame_feat.bottom_in_cfg_polygon:
        state.consec_bottom_cfg += 1
    else:
        state.consec_bottom_cfg = 0

    state.history.append(frame_feat)

    suppressed = (
        state.consec_bottom_cfg >= 3 and should_suppress_warn_from_history(state.history)
    )

    if frame_feat.has_fence_line:
        trigger = state.consec_above
        cond_str = "tam bbox tren line"
    else:
        trigger = state.consec_any
        cond_str = "phat hien nguoi (khong co line)"

    if trigger >= 3 and not suppressed:
        logger.warning("[CANH BAO] %s: %s %d frame lien tiep.", cam_label, cond_str, trigger)
        return trigger == 3
    return False


# ---------------------------------------------------------------------------
# Inference loop
# ---------------------------------------------------------------------------

def run_inference_loop(
    model,
    caps: list[cv2.VideoCapture | None],
    cam_ids: list[str],
    roi_by_cam: dict[str, CameraRoiRefs],
    alert_states: list[IntrusionAlertState],
    out_root: Path,
    conf: float,
    device: str | None,
    imgsz: int,
    use_batch: bool,
    use_half: bool,
    *,
    event_save_masked_with_boxes: bool = False,
    debug_roi: bool = False,
    use_cfg_polygon: bool = True,
    record_frames: bool = False,
    record_interval: float = 1.0,
) -> None:
    n = len(caps)
    assert len(cam_ids) == n
    assert len(alert_states) == n
    out_root = out_root.resolve()
    for i in range(1, n + 1):
        (out_root / "event" / f"cam_{i}").mkdir(parents=True, exist_ok=True)
        (out_root / "event" / f"cam_{i}" / "person").mkdir(parents=True, exist_ok=True)
    if record_frames:
        for i in range(1, n + 1):
            (out_root / "record" / f"cam_{i}").mkdir(parents=True, exist_ok=True)
    half = bool(use_half) and (device is not None) and str(device).lower() != "cpu"
    last_record_time: list[float] = [0.0] * n

    while True:
        frames_orig: list[np.ndarray] = []
        for cap in caps:
            if cap is None or not cap.isOpened():
                frames_orig.append(np.zeros((480, 640, 3), dtype=np.uint8))
                continue
            ok, f = cap.read()
            if not ok or f is None:
                frames_orig.append(np.zeros((480, 640, 3), dtype=np.uint8))
            else:
                frames_orig.append(f)

        inference_frames: list[np.ndarray] = []
        cfg_polys_scaled: list[np.ndarray | None] = []
        for i, cam_id in enumerate(cam_ids):
            f = frames_orig[i]
            ih, iw = int(f.shape[0]), int(f.shape[1])
            roi = roi_by_cam.get(cam_id) or CameraRoiRefs(None, (1920, 1080), None, (1920, 1080))
            r1 = roi.region1
            if r1 is not None and len(r1) >= 3:
                r1s = scale_polygon_xy(r1, roi.region1_ref[0], roi.region1_ref[1], iw, ih)
            else:
                r1s = None
            inference_frames.append(apply_region1_zero_inside(f, r1s))

            cf = roi.config_poly
            if use_cfg_polygon and cf is not None and len(cf) >= 3:
                cfs = scale_polygon_xy(cf, roi.config_ref[0], roi.config_ref[1], iw, ih)
            else:
                cfs = None
            cfg_polys_scaled.append(cfs)

        if use_batch:
            maybe_empty_cuda_cache()
            results = model(
                inference_frames, batch=n, conf=conf, device=device,
                imgsz=imgsz, half=half, verbose=False,
            )
        else:
            results = []
            for f in inference_frames:
                maybe_empty_cuda_cache()
                r = model(f, conf=conf, device=device, imgsz=imgsz, half=half, verbose=False)
                results.append(r[0] if r else None)

        for i, res in enumerate(results):
            f_orig = frames_orig[i]
            cam_id = cam_ids[i]
            cfs = cfg_polys_scaled[i]
            roi = roi_by_cam.get(cam_id) or CameraRoiRefs(None, (1920, 1080), None, (1920, 1080))

            # Record frames at interval
            if record_frames and np.any(f_orig):
                now_t = time.time()
                if now_t - last_record_time[i] >= record_interval:
                    last_record_time[i] = now_t
                    ts_rec = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    rec_path = out_root / "record" / f"cam_{i + 1}" / f"{ts_rec}.jpg"
                    cv2.imwrite(str(rec_path), f_orig)

            dead = res is None or not np.any(f_orig)
            bbox = None
            had_person = False
            bot_in_cfg = False
            below_ln = False
            center_above = False
            has_fl = roi.fence_line is not None
            if not dead:
                bbox = largest_person_box_xyxy(res)
                had_person = bbox is not None
                if bbox is not None:
                    bx = (bbox[0] + bbox[2]) / 2.0
                    by = bbox[3]
                    cx_center = bx
                    cy_center = (bbox[1] + bbox[3]) / 2.0
                    if use_cfg_polygon and cfs is not None and cfs.shape[0] >= 3:
                        bot_in_cfg = cv2.pointPolygonTest(cfs, (bx, by), False) >= 0
                    if roi.fence_line is not None:
                        frw, frh = roi.fence_line_ref[0], roi.fence_line_ref[1]
                        sx = float(f_orig.shape[1]) / float(frw) if frw > 0 else 1.0
                        sy = float(f_orig.shape[0]) / float(frh) if frh > 0 else 1.0
                        pts_scaled = [[p[0] * sx, p[1] * sy] for p in roi.fence_line]
                        ih2, iw2 = int(f_orig.shape[0]), int(f_orig.shape[1])
                        below_ln = foot_below_fence_polyline(bx, by, pts_scaled, iw2, ih2)
                        center_above = not foot_below_fence_polyline(
                            cx_center, cy_center, pts_scaled, iw2, ih2
                        )

            event_fired = evaluate_intrusion_alert(
                alert_states[i],
                AlertFrameFeat(
                    had_person=had_person, bottom_in_cfg_polygon=bot_in_cfg,
                    person_below_fence_line=below_ln, center_above_fence_line=center_above,
                    has_fence_line=has_fl,
                ),
                cam_label=f"{cam_id} (cam_{i + 1})",
            )

            if event_fired and not dead:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                ev_cam = out_root / "event" / f"cam_{i + 1}"
                ev_cam.mkdir(parents=True, exist_ok=True)
                (ev_cam / "person").mkdir(parents=True, exist_ok=True)
                out_ev = ev_cam / f"{ts}.jpg"
                f_save = f_orig
                if event_save_masked_with_boxes:
                    f_mask = inference_frames[i].copy()
                    if res is not None and has_any_detection(res):
                        f_save = draw_model_boxes_bgr(f_mask, res)
                    else:
                        f_save = f_mask
                if debug_roi:
                    ih_fr, iw_fr = int(f_save.shape[0]), int(f_save.shape[1])
                    r1s_dbg = None
                    if roi.region1 is not None and len(roi.region1) >= 3:
                        r1s_dbg = scale_polygon_xy(roi.region1, roi.region1_ref[0], roi.region1_ref[1], iw_fr, ih_fr)
                    cfs_dbg = None
                    if roi.config_poly is not None and len(roi.config_poly) >= 3:
                        cfs_dbg = scale_polygon_xy(roi.config_poly, roi.config_ref[0], roi.config_ref[1], iw_fr, ih_fr)
                    fl_dbg = None
                    if roi.fence_line is not None:
                        frw, frh = roi.fence_line_ref
                        sx = float(iw_fr) / float(frw) if frw > 0 else 1.0
                        sy = float(ih_fr) / float(frh) if frh > 0 else 1.0
                        fl_dbg = [[p[0] * sx, p[1] * sy] for p in roi.fence_line]
                    f_save = draw_roi_overlay_bgr(f_save, r1s_dbg, cfs_dbg, fl_dbg, f"{cam_id} (cam_{i+1})")
                if cv2.imwrite(str(out_ev), f_save):
                    logger.info("cam_%d: event saved -> %s", i + 1, out_ev)
                if res is not None and has_any_detection(res):
                    n_ev = save_person_image_and_yolo(f_save, res, ev_cam / "person", ts, cfs)
                    if n_ev:
                        logger.info("  event person: %d box(es) -> %s/%s.jpg + .txt", n_ev, ev_cam / "person", ts)


# ---------------------------------------------------------------------------
# ROI check dump
# ---------------------------------------------------------------------------

def dump_roi_check_frames(
    caps: list[cv2.VideoCapture | None],
    cam_ids: list[str],
    roi_by_cam: dict[str, CameraRoiRefs],
    out_root: Path,
) -> None:
    """Grab 1 frame from each camera and save ROI overlay images for verification."""
    roi_dir = out_root / "roi_check"
    roi_dir.mkdir(parents=True, exist_ok=True)
    logger.info("[dump-roi-frame] Saving ROI check images -> %s", roi_dir)
    for i, (cam_id, cap) in enumerate(zip(cam_ids, caps)):
        if cap is not None and cap.isOpened():
            ok, f = cap.read()
            frame = f if (ok and f is not None and f.size > 0) else np.zeros((1080, 1920, 3), dtype=np.uint8)
        else:
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        ih, iw = int(frame.shape[0]), int(frame.shape[1])
        roi = roi_by_cam.get(cam_id) or CameraRoiRefs(None, (1920, 1080), None, (1920, 1080))

        r1s = scale_polygon_xy(roi.region1, roi.region1_ref[0], roi.region1_ref[1], iw, ih) if roi.region1 is not None and len(roi.region1) >= 3 else None
        cfs = scale_polygon_xy(roi.config_poly, roi.config_ref[0], roi.config_ref[1], iw, ih) if roi.config_poly is not None and len(roi.config_poly) >= 3 else None
        fl_scaled = None
        if roi.fence_line is not None:
            frw, frh = roi.fence_line_ref
            sx = float(iw) / float(frw) if frw > 0 else 1.0
            sy = float(ih) / float(frh) if frh > 0 else 1.0
            fl_scaled = [[p[0] * sx, p[1] * sy] for p in roi.fence_line]

        label = f"{cam_id} (cam_{i + 1})"
        orig_overlay = draw_roi_overlay_bgr(frame, r1s, cfs, fl_scaled, label)
        cv2.imwrite(str(roi_dir / f"cam_{i + 1}_orig.jpg"), orig_overlay)

        masked = apply_region1_zero_inside(frame, r1s)
        masked_overlay = draw_roi_overlay_bgr(masked, r1s, cfs, fl_scaled, label + " [MASKED]")
        cv2.imwrite(str(roi_dir / f"cam_{i + 1}_masked.jpg"), masked_overlay)

        logger.info("  cam_%d (%s): saved orig + masked", i + 1, cam_id)
    logger.info("[dump-roi-frame] Done.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        cv2.setNumThreads(1)
    except Exception:
        pass
    try:
        cv2.ocl.setUseOpenCL(False)
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="YOLO RTSP: intrusion alert (3-frame person streak); save events to results/event/.",
    )
    parser.add_argument("--results", type=Path, default=RESULTS_DIR)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batched", action="store_true")
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--no-hwaccel", action="store_true")
    parser.add_argument("--polygon-yaml", type=Path, default=POLYGON_YAML)
    parser.add_argument("--configs-yaml", type=Path, default=CONFIGS_YAML)
    parser.add_argument("--no-cfg-polygon", action="store_true")
    parser.add_argument("--event-masked-viz", action="store_true")
    parser.add_argument("--debug-roi", action="store_true")
    parser.add_argument("--record-frames", action="store_true")
    parser.add_argument("--record-interval", type=float, default=1.0)
    parser.add_argument("--dump-roi-frame", action="store_true")
    args = parser.parse_args()

    use_hw = not args.no_hwaccel

    if args.dump_roi_frame:
        caps_early: list[cv2.VideoCapture | None] = []
        cam_ids_early: list[str] = []
        for cam_id, url in RTSP_URLS:
            c, mode, _ = open_capture(url, use_hwaccel=use_hw, debug_label=cam_id)
            if c is None:
                logger.warning("%s: cannot open stream, using black frame.", cam_id)
            else:
                logger.info("%s: OK (%s)", cam_id, mode)
            caps_early.append(c)
            cam_ids_early.append(cam_id)
        roi_early = build_cam_roi_refs(RTSP_URLS, args.polygon_yaml.resolve(), args.configs_yaml.resolve())
        dump_roi_check_frames(caps_early, cam_ids_early, roi_early, args.results)
        for c in caps_early:
            if c is not None:
                c.release()
        return

    try:
        model_path = resolve_model_path(args.model)
    except FileNotFoundError as e:
        logger.error(str(e))
        raise SystemExit(1) from e

    trt = is_tensorrt_path(model_path)
    load_path = path_for_ultralytics_load(model_path)
    if trt and str(args.device).lower() in ("cpu", ""):
        args.device = "0"
    use_half = bool(args.half) and not trt

    from ultralytics import YOLO
    logger.info("Loading (%s): %s", "TensorRT" if trt else "PyTorch", load_path)
    yolo = YOLO(str(load_path))

    caps: list[cv2.VideoCapture | None] = []
    cam_ids: list[str] = []
    for cam_id, url in RTSP_URLS:
        c, mode, _ = open_capture(url, use_hwaccel=use_hw, debug_label=cam_id)
        if c is None:
            logger.warning("%s: cannot open stream, using black frame.", cam_id)
        else:
            logger.info("%s: OK (%s)", cam_id, mode)
        caps.append(c)
        cam_ids.append(cam_id)

    roi_by_cam = build_cam_roi_refs(RTSP_URLS, args.polygon_yaml.resolve(), args.configs_yaml.resolve())
    alert_states = [IntrusionAlertState() for _ in cam_ids]

    logger.info("Inference mode: %s, imgsz=%d, half=%s",
                "batch" if args.batched else "sequential", args.imgsz, use_half)
    logger.info("Ctrl+C to stop.")

    current_imgsz = int(args.imgsz)
    retried_with_engine_size = False
    try:
        while True:
            try:
                run_inference_loop(
                    yolo, caps, cam_ids, roi_by_cam, alert_states, args.results,
                    args.conf, args.device, imgsz=current_imgsz,
                    use_batch=args.batched, use_half=use_half,
                    event_save_masked_with_boxes=args.event_masked_viz,
                    debug_roi=args.debug_roi,
                    use_cfg_polygon=not args.no_cfg_polygon,
                    record_frames=args.record_frames,
                    record_interval=args.record_interval,
                )
                break
            except AssertionError as e:
                if not trt:
                    raise
                engine_imgsz = extract_trt_imgsz_from_assertion(e)
                if engine_imgsz is None or retried_with_engine_size:
                    raise
                logger.warning("TRT engine expects imgsz=%d, auto-switching from %d...",
                               engine_imgsz, current_imgsz)
                current_imgsz = engine_imgsz
                retried_with_engine_size = True
    except KeyboardInterrupt:
        logger.info("Stopped.")
    finally:
        for c in caps:
            if c is not None:
                c.release()


if __name__ == "__main__":
    main()
