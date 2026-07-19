"""
save_image — Capture and save frames from RTSP streams at intervals.

Useful for building training datasets or periodic monitoring.

Usage:
    python -m src.backend.tools.save_image
    python -m src.backend.tools.save_image --interval 5.0 --duration 3600
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from src.backend.core.config import RTSP_URLS, RESULTS_DIR
from src.backend.core.camera import open_capture
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture and save frames from RTSP streams")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "saved_frames")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between captures")
    parser.add_argument("--duration", type=float, default=0, help="Total duration in seconds (0=infinite)")
    parser.add_argument("--no-hwaccel", action="store_true")
    args = parser.parse_args()

    use_hw = not args.no_hwaccel
    output_root = args.output.expanduser().resolve()

    caps: list[tuple[str, cv2.VideoCapture]] = []
    for cam_id, url in RTSP_URLS:
        cap, mode, _ = open_capture(url, use_hwaccel=use_hw, debug_label=cam_id)
        if cap is None:
            logger.warning("%s: cannot open stream, skipping.", cam_id)
            continue
        logger.info("%s: OK (%s)", cam_id, mode)
        cam_dir = output_root / cam_id
        cam_dir.mkdir(parents=True, exist_ok=True)
        caps.append((cam_id, cap))

    if not caps:
        logger.error("No cameras available.")
        return

    start_time = time.time()
    try:
        while True:
            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                logger.info("Duration reached (%0.0f s). Stopping.", args.duration)
                break

            for cam_id, cap in caps:
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                out_path = output_root / cam_id / f"{ts}.jpg"
                cv2.imwrite(str(out_path), frame)

            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Stopped.")
    finally:
        for _, cap in caps:
            cap.release()
    logger.info("Saved to: %s", output_root)


if __name__ == "__main__":
    main()
