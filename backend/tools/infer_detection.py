"""
infer_detection — Run YOLO detection on images and save results with bounding boxes.

Usage:
    python -m src.backend.tools.infer_detection --input results/record/cam_1 --output results/inferred/cam_1
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from src.backend.core.config import IMG_EXTS
from src.backend.core.model import (
    resolve_model_path, path_for_ultralytics_load, is_tensorrt_path,
    maybe_empty_cuda_cache,
)
from src.backend.core.detection import has_any_detection, draw_model_boxes_bgr, save_person_image_and_yolo
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YOLO detection on images, save with bounding boxes")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--device", type=str, default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--save-labels", action="store_true", help="Also save YOLO label .txt files")
    args = parser.parse_args()

    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.save_labels:
        (output_dir / "labels").mkdir(parents=True, exist_ok=True)

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
    for idx, img_path in enumerate(images):
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue

        maybe_empty_cuda_cache()
        results = yolo(frame, conf=args.conf, device=args.device, imgsz=args.imgsz,
                       half=use_half, verbose=False)
        if results and has_any_detection(results[0]):
            vis = draw_model_boxes_bgr(frame, results[0])
            cv2.imwrite(str(output_dir / img_path.name), vis)
            if args.save_labels:
                ts = img_path.stem
                save_person_image_and_yolo(frame, results[0], output_dir / "labels", ts, None)
            count += 1
        if (idx + 1) % 50 == 0:
            logger.info("Processed %d/%d", idx + 1, len(images))

    logger.info("Done: %d images with detections -> %s", count, output_dir)


if __name__ == "__main__":
    main()
