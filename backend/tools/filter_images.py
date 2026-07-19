"""
filter_images — Batch-filter images by YOLO detection.

Reads images from a folder, runs YOLO, and copies/moves images that
have person detections to an output folder.

Usage:
    python -m src.backend.tools.filter_images --input results/record/cam_1 --output results/filtered/cam_1
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import cv2

from src.backend.core.config import IMG_EXTS
from src.backend.core.model import (
    resolve_model_path, path_for_ultralytics_load, is_tensorrt_path,
    maybe_empty_cuda_cache,
)
from src.backend.core.detection import has_any_detection, person_class_ids
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter images by YOLO person detection")
    parser.add_argument("--input", type=Path, required=True, help="Input image folder")
    parser.add_argument("--output", type=Path, required=True, help="Output folder for positives")
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--move", action="store_true", help="Move instead of copy")
    args = parser.parse_args()

    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMG_EXTS
    )
    if not images:
        logger.info("No images found in %s", input_dir)
        return

    try:
        model_path = resolve_model_path(args.model)
    except FileNotFoundError as e:
        logger.error(str(e))
        raise SystemExit(1) from e

    trt = is_tensorrt_path(model_path)
    load_path = path_for_ultralytics_load(model_path)
    use_half = bool(args.half) and not trt

    from ultralytics import YOLO
    logger.info("Loading model: %s", load_path)
    yolo = YOLO(str(load_path))

    count = 0
    total = len(images)
    for idx, img_path in enumerate(images):
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue

        maybe_empty_cuda_cache()
        results = yolo(frame, conf=args.conf, device=args.device, imgsz=args.imgsz,
                       half=use_half, verbose=False)
        if results and has_any_detection(results[0]):
            pids = person_class_ids(results[0])
            has_person = False
            for box in results[0].boxes:
                try:
                    cls_id = int(box.cls[0].item() if hasattr(box.cls[0], "item") else int(box.cls[0]))
                except (TypeError, ValueError, IndexError):
                    continue
                if cls_id in pids:
                    has_person = True
                    break
            if has_person:
                dest = output_dir / img_path.name
                if args.move:
                    shutil.move(str(img_path), str(dest))
                else:
                    shutil.copy2(str(img_path), str(dest))
                count += 1

        if (idx + 1) % 50 == 0:
            logger.info("Processed %d/%d, found %d positives", idx + 1, total, count)

    logger.info("Done: %d/%d images with person detections -> %s", count, total, output_dir)


if __name__ == "__main__":
    main()
