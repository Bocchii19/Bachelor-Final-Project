"""
draw_line — Interactive fence-line editor for RTSP cameras.

Opens camera feeds and lets you click points to define a fence line.
Saves to polygon.yaml under cameras.*.line.

Usage:
    python -m src.backend.tools.draw_line
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


class LineDrawer:
    """Interactive line drawer on camera frames."""

    def __init__(self, frame: np.ndarray, cam_id: str, window_name: str):
        self.frame = frame.copy()
        self.display = frame.copy()
        self.cam_id = cam_id
        self.window_name = window_name
        self.points: list[list[int]] = []
        self.done = False

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
            cv2.circle(self.display, (p[0], p[1]), 5, (0, 0, 255), -1)
            cv2.putText(self.display, str(i), (p[0] + 8, p[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        if len(self.points) >= 2:
            pts = np.array(self.points, dtype=np.int32)
            cv2.polylines(self.display, [pts], isClosed=False, color=(0, 0, 255), thickness=2)
        cv2.putText(self.display, f"{self.cam_id}: Left=add, Right=undo, Enter=save, Esc=skip",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    def run(self) -> list[list[int]] | None:
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)
        self._redraw()
        while True:
            cv2.imshow(self.window_name, self.display)
            key = cv2.waitKey(30) & 0xFF
            if key == 27:  # Esc
                cv2.destroyWindow(self.window_name)
                return None
            elif key == 13:  # Enter
                cv2.destroyWindow(self.window_name)
                return self.points if len(self.points) >= 2 else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive fence-line editor for RTSP cameras")
    parser.add_argument("--polygon-yaml", type=Path, default=POLYGON_YAML)
    parser.add_argument("--no-hwaccel", action="store_true")
    args = parser.parse_args()

    use_hw = not args.no_hwaccel
    yaml_path = args.polygon_yaml.resolve()

    # Load existing yaml
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

        drawer = LineDrawer(frame, cam_id, f"Draw Line - {cam_id}")
        line_pts = drawer.run()
        cap.release()

        if line_pts is not None and len(line_pts) >= 2:
            if cam_id not in data["cameras"]:
                data["cameras"][cam_id] = {"rtsp_url": url}
            data["cameras"][cam_id]["line"] = line_pts
            data["cameras"][cam_id]["resolution"] = {"width": iw, "height": ih}
            logger.info("%s: saved %d line points.", cam_id, len(line_pts))
        else:
            logger.info("%s: skipped.", cam_id)

    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    logger.info("Saved: %s", yaml_path)


if __name__ == "__main__":
    main()
