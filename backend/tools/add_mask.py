"""
add_mask — Apply polygon/fence-line mask overlays to existing images.

Reads images from results/record/ or results/event/, applies the
configured polygon mask from polygon.yaml, and saves the masked images.

Usage:
    python -m src.backend.tools.add_mask --input results/record/cam_1 --output results/masked/cam_1
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from src.backend.core.config import IMG_EXTS, POLYGON_YAML, CONFIGS_YAML
from src.backend.core.polygon import (
    load_polygon_yaml_region1_by_ip, load_polygon_yaml_fence_line_by_ip,
    load_configs_yaml_treo_polygon_by_ip, scale_polygon_xy,
    apply_region1_zero_inside, extract_ip_from_rtsp,
)
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply polygon mask overlays to images")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--camera-ip", type=str, required=True, help="Camera IP to look up polygon")
    parser.add_argument("--polygon-yaml", type=Path, default=POLYGON_YAML)
    parser.add_argument("--configs-yaml", type=Path, default=CONFIGS_YAML)
    parser.add_argument("--draw-fence", action="store_true", help="Also draw fence line overlay")
    args = parser.parse_args()

    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    r1_map = load_polygon_yaml_region1_by_ip(args.polygon_yaml.resolve())
    fence_map = load_polygon_yaml_fence_line_by_ip(args.polygon_yaml.resolve())

    r1_data = r1_map.get(args.camera_ip)
    fence_data = fence_map.get(args.camera_ip) if args.draw_fence else None

    if r1_data is None:
        logger.warning("No region1 polygon found for IP=%s in %s", args.camera_ip, args.polygon_yaml)

    images = sorted(
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMG_EXTS
    )
    if not images:
        logger.info("No images found in %s", input_dir)
        return

    count = 0
    for img_path in images:
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
        ih, iw = int(frame.shape[0]), int(frame.shape[1])

        # Apply mask
        if r1_data is not None:
            poly, ref = r1_data
            poly_scaled = scale_polygon_xy(poly, ref[0], ref[1], iw, ih)
            frame = apply_region1_zero_inside(frame, poly_scaled)

        # Draw fence line
        if fence_data is not None:
            fl, fl_ref = fence_data
            sx = float(iw) / float(fl_ref[0]) if fl_ref[0] > 0 else 1.0
            sy = float(ih) / float(fl_ref[1]) if fl_ref[1] > 0 else 1.0
            pts = np.array([[int(p[0] * sx), int(p[1] * sy)] for p in fl], dtype=np.int32)
            cv2.polylines(frame, [pts], isClosed=False, color=(0, 0, 255), thickness=2)

        cv2.imwrite(str(output_dir / img_path.name), frame)
        count += 1

    logger.info("Processed %d images -> %s", count, output_dir)


if __name__ == "__main__":
    main()
