"""
test_model — YOLO model test on RTSP streams with live display.

Opens cameras, runs inference, and shows bounding boxes on screen.

Usage:
    cd ~/Desktop/UBQN
    python3 -m src.test.test_model
    python3 -m src.test.test_model --conf 0.4
    python3 -m src.test.test_model --cam ptz
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.camera.stream import open_capture
from src.backend.core.ai.yolo import resolve_model_path, path_for_ultralytics_load
from src.backend.core.ai.detection import has_any_detection
from src.backend.core.logger import get_logger

logger = get_logger(__name__)

# Colors (BGR)
CLR_BBOX = (0, 200, 255)       # Orange
CLR_TEXT_BG = (30, 30, 30)

# ── Danh sách camera cần test — thêm/sửa thủ công ở đây ────────
RTSP_URLS: list[tuple[str, str]] = [
    ("ptz", "rtsp://admin:Hanet123@10.128.55.237:554/media/live/105"),

    # Thêm các luồng camera khác vào đây nếu muốn...
    # ("fence8", "rtsp://admin:Hanet123@10.128.55.225:554/media/live/105"),
    # ("fence9", "rtsp://admin:Hanet123@10.128.55.222:554/media/live/105"),
]


def draw_detections(frame: np.ndarray, results) -> int:
    """Draw person bboxes on frame. Returns person count."""
    if results is None or not hasattr(results, "boxes") or results.boxes is None:
        return 0

    count = 0
    for i in range(len(results.boxes)):
        cls_id = int(results.boxes.cls[i].item())
        if cls_id != 0:  # Only person
            continue
        count += 1
        x1, y1, x2, y2 = [int(v) for v in results.boxes.xyxy[i].tolist()]
        conf = float(results.boxes.conf[i].item())

        cv2.rectangle(frame, (x1, y1), (x2, y2), CLR_BBOX, 2, cv2.LINE_AA)
        label = f"person {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), CLR_BBOX, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLO model test with live display")
    parser.add_argument("--model", type=Path, default=None, help="Model path (auto from system.yaml)")
    parser.add_argument("--conf", type=float, default=0.45, help="Confidence threshold")
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--cam", type=str, default=None, help="Camera ID filter (e.g. ptz, fence8)")
    parser.add_argument("--no-display", action="store_true", help="Disable cv2 display")
    args = parser.parse_args()

    # ── Load model ──
    try:
        model_path = resolve_model_path(args.model)
    except FileNotFoundError as e:
        logger.error(str(e))
        raise SystemExit(1) from e

    load_path = path_for_ultralytics_load(model_path)
    logger.info("Loading model: %s", load_path)

    from ultralytics import YOLO
    yolo = YOLO(str(load_path))
    logger.info("✅ Model loaded")

    # ── Get cameras ──
    urls = RTSP_URLS
    if not urls:
        logger.error("No cameras in RTSP_URLS! Edit the list at top of file.")
        return

    logger.info("Testing %d camera(s): %s", len(urls), [c[0] for c in urls])

    # ── Open streams ──
    caps: list[tuple[str, cv2.VideoCapture]] = []
    for cam_id, url in urls:
        cap, mode, _ = open_capture(url, use_hwaccel=True, debug_label=cam_id)
        if cap is None:
            logger.warning("%s: cannot open", cam_id)
            continue
        logger.info("%s: ✅ opened (%s)", cam_id, mode)
        caps.append((cam_id, cap))

    if not caps:
        logger.error("No streams opened!")
        return

    # ── Create windows ──
    if not args.no_display:
        for cam_id, _ in caps:
            win = f"YOLO Test - {cam_id}"
            cv2.namedWindow(win, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(win, 960, 540)

    # ── Main loop ──
    logger.info("Running... Press Q to quit")
    frame_count = 0

    try:
        while True:
            for cam_id, cap in caps:
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue

                # Run YOLO
                t0 = time.time()
                results = yolo(frame, conf=args.conf, device=args.device,
                               imgsz=args.imgsz, verbose=False)
                dt = (time.time() - t0) * 1000
                res = results[0] if results else None

                # Draw bboxes
                n_person = draw_detections(frame, res)

                # HUD
                ih, iw = frame.shape[:2]
                info = f"{cam_id} | {iw}x{ih} | {dt:.0f}ms | persons: {n_person}"
                cv2.rectangle(frame, (0, 0), (len(info) * 10 + 10, 28), CLR_TEXT_BG, -1)
                cv2.putText(frame, info, (6, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

                if not args.no_display:
                    cv2.imshow(f"YOLO Test - {cam_id}", frame)

                frame_count += 1
                if frame_count % 100 == 0:
                    logger.info("%s: %d frames, %.0f ms/frame, %d persons",
                                cam_id, frame_count, dt, n_person)

            # Check for quit
            if not args.no_display:
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == ord('Q') or key == 27:
                    break

            time.sleep(0.03)  # ~30 FPS cap

    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        for _, cap in caps:
            cap.release()
        if not args.no_display:
            cv2.destroyAllWindows()
        logger.info("Done! %d total frames processed", frame_count)


if __name__ == "__main__":
    main()
