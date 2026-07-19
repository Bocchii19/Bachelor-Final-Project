"""
get_polygon — Interactive polygon (ROI) editor for RTSP cameras.

Opens camera feeds and lets you click points to define region polygons.
Saves to polygon.yaml under cameras.*.regions.region1.

Usage:
    python -m src.backend.tools.get_polygon
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml

from src.backend.core.config import RTSP_URLS, POLYGON_YAML
from src.backend.core.camera import open_capture
from src.backend.core.polygon import load_yaml
from src.backend.core.logging_config import get_logger

logger = get_logger(__name__)


class PolygonDrawer:
    """Interactive polygon drawer on camera frames."""

    def __init__(self, frame: np.ndarray, cam_id: str, region_name: str, window_name: str):
        self.frame = frame.copy()
        self.display = frame.copy()
        self.cam_id = cam_id
        self.region_name = region_name
        self.window_name = window_name
        self.points: list[list[int]] = []

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.points.append([x, y])
            self._redraw()
        elif event == cv2.EVENT_RBUTTONDOWN:
            if self.points:
                self.points.pop()
                self._redraw()

    def _redraw(self):
        self.display = self.frame.copy()
        for i, p in enumerate(self.points):
            cv2.circle(self.display, (p[0], p[1]), 5, (0, 255, 0), -1)
            cv2.putText(self.display, str(i), (p[0] + 8, p[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        if len(self.points) >= 2:
            pts = np.array(self.points, dtype=np.int32)
            cv2.polylines(self.display, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        if len(self.points) >= 3:
            overlay = self.display.copy()
            cnt = np.array(self.points, dtype=np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(overlay, [cnt], (0, 255, 0))
            cv2.addWeighted(overlay, 0.2, self.display, 0.8, 0, self.display)
        cv2.putText(self.display,
                    f"{self.cam_id} [{self.region_name}]: Left=add, Right=undo, Enter=save, Esc=skip",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    def run(self) -> list[list[int]] | None:
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)
        self._redraw()
        while True:
            cv2.imshow(self.window_name, self.display)
            key = cv2.waitKey(30) & 0xFF
            if key == 27:
                cv2.destroyWindow(self.window_name)
                return None
            elif key == 13:
                cv2.destroyWindow(self.window_name)
                return self.points if len(self.points) >= 3 else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive polygon (ROI) editor")
    parser.add_argument("--polygon-yaml", type=Path, default=POLYGON_YAML)
    parser.add_argument("--no-hwaccel", action="store_true")
    parser.add_argument("--regions", nargs="+", default=["region1"],
                        help="Region names to draw (default: region1)")
    args = parser.parse_args()

    use_hw = not args.no_hwaccel
    yaml_path = args.polygon_yaml.resolve()
    data = load_yaml(yaml_path)
    if "cameras" not in data:
        data["cameras"] = {}

    for cam_id, url in RTSP_URLS:
        cap, mode, first_frame = open_capture(url, use_hwaccel=use_hw, debug_label=cam_id)
        if cap is None or first_frame is None:
            logger.warning("%s: cannot open, skipping.", cam_id)
            continue
        logger.info("%s: OK (%s)", cam_id, mode)

        frame = np.asarray(first_frame)
        ih, iw = int(frame.shape[0]), int(frame.shape[1])

        if cam_id not in data["cameras"]:
            data["cameras"][cam_id] = {"rtsp_url": url}
        if "regions" not in data["cameras"][cam_id]:
            data["cameras"][cam_id]["regions"] = {}

        for region_name in args.regions:
            drawer = PolygonDrawer(frame, cam_id, region_name, f"Polygon - {cam_id} - {region_name}")
            poly_pts = drawer.run()
            if poly_pts is not None:
                data["cameras"][cam_id]["regions"][region_name] = poly_pts
                logger.info("%s [%s]: saved %d polygon points.", cam_id, region_name, len(poly_pts))
            else:
                logger.info("%s [%s]: skipped.", cam_id, region_name)

        data["cameras"][cam_id]["resolution"] = {"width": iw, "height": ih}
        cap.release()

    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    logger.info("Saved: %s", yaml_path)


if __name__ == "__main__":
    main()
