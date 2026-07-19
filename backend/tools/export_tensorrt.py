"""
export_tensorrt — Convert a PyTorch YOLO model (.pt) to TensorRT (.engine).

Usage:
    python -m src.backend.tools.export_tensorrt
    python -m src.backend.tools.export_tensorrt --model models/best_UBQN_V4.pt --imgsz 640 --half
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.backend.core.config import MODELS_DIR, MODEL_STEM
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export YOLO PT → TensorRT engine")
    parser.add_argument("--model", type=Path, default=MODELS_DIR / f"{MODEL_STEM}.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--half", action="store_true", help="FP16 quantization")
    parser.add_argument("--int8", action="store_true", help="INT8 quantization")
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--workspace", type=int, default=4, help="GiB workspace for TRT builder")
    parser.add_argument("--device", type=str, default="0")
    args = parser.parse_args()

    pt_path = args.model.expanduser().resolve()
    if not pt_path.is_file():
        logger.error("Model file not found: %s", pt_path)
        raise SystemExit(1)

    from ultralytics import YOLO

    logger.info("Loading: %s", pt_path)
    yolo = YOLO(str(pt_path))

    logger.info("Exporting to TensorRT (imgsz=%d, half=%s, int8=%s, batch=%d)...",
                args.imgsz, args.half, args.int8, args.batch)
    yolo.export(
        format="engine",
        imgsz=args.imgsz,
        half=args.half,
        int8=args.int8,
        batch=args.batch,
        workspace=args.workspace,
        device=args.device,
    )
    logger.info("Done. Engine file saved next to the .pt file.")


if __name__ == "__main__":
    main()
