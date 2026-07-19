"""
record_rtsp — Record RTSP streams to segmented MP4 files.

Usage:
    python -m src.backend.tools.record_rtsp
    python -m src.backend.tools.record_rtsp --duration 300 --segment-minutes 5
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import cv2

from src.backend.core.config import RTSP_URLS, RESULTS_DIR
from src.backend.core.camera import open_capture
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record RTSP streams to MP4 files")
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "recordings")
    parser.add_argument("--duration", type=float, default=0, help="Total duration in seconds (0=infinite)")
    parser.add_argument("--segment-minutes", type=float, default=10, help="Minutes per segment file")
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--no-hwaccel", action="store_true")
    args = parser.parse_args()

    use_hw = not args.no_hwaccel
    output_root = args.output.expanduser().resolve()
    segment_seconds = args.segment_minutes * 60.0

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

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writers: dict[str, cv2.VideoWriter | None] = {}
    writer_start_times: dict[str, float] = {}

    def _new_writer(cam_id: str, w: int, h: int) -> cv2.VideoWriter:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = output_root / cam_id / f"{cam_id}_{ts}.mp4"
        writer = cv2.VideoWriter(str(out_path), fourcc, args.fps, (w, h))
        logger.info("%s: new segment -> %s", cam_id, out_path)
        return writer

    start_time = time.time()
    try:
        while True:
            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                logger.info("Duration reached. Stopping.")
                break

            for cam_id, cap in caps:
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                ih, iw = int(frame.shape[0]), int(frame.shape[1])

                # Check if we need a new segment
                now = time.time()
                if cam_id not in writers or writers[cam_id] is None:
                    writers[cam_id] = _new_writer(cam_id, iw, ih)
                    writer_start_times[cam_id] = now
                elif now - writer_start_times.get(cam_id, 0) >= segment_seconds:
                    writers[cam_id].release()
                    writers[cam_id] = _new_writer(cam_id, iw, ih)
                    writer_start_times[cam_id] = now

                writers[cam_id].write(frame)

    except KeyboardInterrupt:
        logger.info("Stopped.")
    finally:
        for _, cap in caps:
            cap.release()
        for w in writers.values():
            if w is not None:
                w.release()
    logger.info("Recordings saved to: %s", output_root)


if __name__ == "__main__":
    main()
