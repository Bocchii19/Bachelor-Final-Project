"""
test_algorithm — ByteTrack + region-transition intrusion detection.

Uses region1/region2 from polygon.yaml. A person tracked via ByteTrack is
flagged if their center transitions from region2 → region1.

Usage:
    python -m src.test.test_algorithm
    python -m src.test.test_algorithm --model /path/to/model.engine
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from src.backend.core.config import RTSP_URLS, POLYGON_YAML, CONFIGS_YAML, RESULTS_DIR
from src.backend.core.camera import open_capture
from src.backend.core.model import (
    resolve_model_path, path_for_ultralytics_load, is_tensorrt_path,
    maybe_empty_cuda_cache,
)
from src.backend.core.detection import has_any_detection, person_class_ids
from src.backend.core.polygon import (
    load_regions_by_camera, load_ref_resolution_by_camera,
    scale_polygon_xy, apply_region1_zero_inside, extract_ip_from_rtsp,
)
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tracking / region-transition logic
# ---------------------------------------------------------------------------

class RegionTracker:
    """Track per-object region transitions for intrusion rules."""

    def __init__(self):
        self.track_regions: dict[int, list[str]] = defaultdict(list)

    def update(self, track_id: int, region: str) -> None:
        history = self.track_regions[track_id]
        if not history or history[-1] != region:
            history.append(region)
            if len(history) > 10:
                history[:] = history[-10:]

    def has_transition(self, track_id: int, from_region: str, to_region: str) -> bool:
        history = self.track_regions.get(track_id, [])
        for i in range(len(history) - 1):
            if history[i] == from_region and history[i + 1] == to_region:
                return True
        return False

    def cleanup(self, active_ids: set[int]) -> None:
        dead = [k for k in self.track_regions if k not in active_ids]
        for k in dead:
            del self.track_regions[k]


def classify_region(cx: float, cy: float, regions: dict[str, np.ndarray]) -> str:
    """Determine which named region a point falls into (priority: region1 > region2 > region3)."""
    for rname in ("region1", "region2", "region3"):
        poly = regions.get(rname)
        if poly is not None and len(poly) >= 3:
            if cv2.pointPolygonTest(poly, (cx, cy), False) >= 0:
                return rname
    return "outside"


# ---------------------------------------------------------------------------
# Main inference loop
# ---------------------------------------------------------------------------

def run(
    model,
    caps: list[cv2.VideoCapture | None],
    cam_ids: list[str],
    regions_by_cam: dict[str, dict[str, np.ndarray]],
    ref_resolutions: dict[str, tuple[int, int]],
    out_root: Path,
    conf: float,
    device: str | None,
    imgsz: int,
    use_half: bool,
) -> None:
    """Process each camera frame, run detection + tracking, check region transitions."""
    n = len(caps)
    region_trackers = [RegionTracker() for _ in range(n)]
    out_root = out_root.resolve()
    for i in range(1, n + 1):
        (out_root / "event" / f"cam_{i}").mkdir(parents=True, exist_ok=True)

    while True:
        for i in range(n):
            cap = caps[i]
            cam_id = cam_ids[i]
            if cap is None or not cap.isOpened():
                continue
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            ih, iw = int(frame.shape[0]), int(frame.shape[1])
            cam_regions = regions_by_cam.get(cam_id, {})
            ref_res = ref_resolutions.get(cam_id, (1920, 1080))

            # Scale region polygons to frame resolution
            scaled_regions: dict[str, np.ndarray] = {}
            for rname, rpoly in cam_regions.items():
                scaled_regions[rname] = scale_polygon_xy(rpoly, ref_res[0], ref_res[1], iw, ih)

            # Apply mask (zero out region1)
            r1_scaled = scaled_regions.get("region1")
            masked_frame = apply_region1_zero_inside(frame, r1_scaled)

            # Inference
            maybe_empty_cuda_cache()
            results = model.track(
                masked_frame, conf=conf, device=device, imgsz=imgsz,
                half=use_half, verbose=False, persist=True,
                tracker="bytetrack.yaml",
            )
            if not results:
                continue
            res = results[0]
            if not has_any_detection(res):
                continue

            pids = person_class_ids(res)
            active_ids: set[int] = set()

            for box in res.boxes:
                try:
                    cls_id = int(box.cls[0].item() if hasattr(box.cls[0], "item") else int(box.cls[0]))
                except (TypeError, ValueError, IndexError):
                    continue
                if cls_id not in pids:
                    continue
                try:
                    track_id = int(box.id[0].item() if hasattr(box.id[0], "item") else int(box.id[0]))
                except Exception:
                    continue
                active_ids.add(track_id)

                xy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], "cpu") else box.xyxy[0].numpy()
                cx = float((xy[0] + xy[2]) / 2.0)
                cy = float((xy[1] + xy[3]) / 2.0)

                region = classify_region(cx, cy, scaled_regions)
                region_trackers[i].update(track_id, region)

                if region_trackers[i].has_transition(track_id, "region2", "region1"):
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    ev_dir = out_root / "event" / f"cam_{i + 1}"
                    cv2.imwrite(str(ev_dir / f"{ts}_intrusion_track{track_id}.jpg"), frame)
                    logger.warning(
                        "[INTRUSION] cam_%d (%s): track_id=%d crossed region2->region1",
                        i + 1, cam_id, track_id,
                    )

            region_trackers[i].cleanup(active_ids)


def main() -> None:
    try:
        cv2.setNumThreads(1)
    except Exception:
        pass
    try:
        cv2.ocl.setUseOpenCL(False)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="ByteTrack + region-transition intrusion detection")
    parser.add_argument("--results", type=Path, default=RESULTS_DIR)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--no-hwaccel", action="store_true")
    parser.add_argument("--polygon-yaml", type=Path, default=POLYGON_YAML)
    args = parser.parse_args()

    use_hw = not args.no_hwaccel

    try:
        model_path = resolve_model_path(args.model)
    except FileNotFoundError as e:
        logger.error(str(e))
        raise SystemExit(1) from e

    trt = is_tensorrt_path(model_path)
    load_path = path_for_ultralytics_load(model_path)
    use_half = bool(args.half) and not trt

    from ultralytics import YOLO
    logger.info("Loading (%s): %s", "TensorRT" if trt else "PyTorch", load_path)
    yolo = YOLO(str(load_path))

    # Load regions from polygon.yaml, mapping by camera IP
    yaml_regions = load_regions_by_camera(args.polygon_yaml)
    yaml_ref_res = load_ref_resolution_by_camera(args.polygon_yaml)

    # Map by camera ID using IP matching
    regions_by_cam: dict[str, dict[str, np.ndarray]] = {}
    ref_res_by_cam: dict[str, tuple[int, int]] = {}
    ip_to_cam_key: dict[str, str] = {}

    # Build IP → polygon.yaml camera key mapping
    from src.backend.core.polygon import load_yaml
    yaml_data = load_yaml(args.polygon_yaml)
    cams_data = yaml_data.get("cameras", {})
    for cam_key, node in (cams_data.items() if isinstance(cams_data, dict) else []):
        ip = extract_ip_from_rtsp(str(node.get("rtsp_url", "") if isinstance(node, dict) else ""))
        if ip:
            ip_to_cam_key[ip] = str(cam_key)

    # Map RTSP cam IDs to regions
    for cam_id, url in RTSP_URLS:
        ip = extract_ip_from_rtsp(url)
        yaml_key = ip_to_cam_key.get(ip, "") if ip else ""
        if yaml_key and yaml_key in yaml_regions:
            regions_by_cam[cam_id] = yaml_regions[yaml_key]
        if yaml_key and yaml_key in yaml_ref_res:
            ref_res_by_cam[cam_id] = yaml_ref_res[yaml_key]
        else:
            ref_res_by_cam[cam_id] = (1920, 1080)

    caps: list[cv2.VideoCapture | None] = []
    cam_ids: list[str] = []
    for cam_id, url in RTSP_URLS:
        c, mode, _ = open_capture(url, use_hwaccel=use_hw, debug_label=cam_id)
        if c is None:
            logger.warning("%s: cannot open stream.", cam_id)
        else:
            logger.info("%s: OK (%s)", cam_id, mode)
        caps.append(c)
        cam_ids.append(cam_id)

    try:
        run(
            yolo, caps, cam_ids, regions_by_cam, ref_res_by_cam,
            args.results, args.conf, args.device, args.imgsz, use_half,
        )
    except KeyboardInterrupt:
        logger.info("Stopped.")
    finally:
        for c in caps:
            if c is not None:
                c.release()


if __name__ == "__main__":
    main()
