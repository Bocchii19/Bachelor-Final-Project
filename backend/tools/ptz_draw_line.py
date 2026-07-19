#!/usr/bin/env python3
"""
ptz_draw_line — Interactive fence-line editor for PTZ preset captures.

Loads the captured images from results/ptz_captures/ (taken by ptz_capture_presets.py),
lets you draw fence lines on each preset image, then saves them to polygon.yaml
under `ptz_presets.<preset_id>.line`.

Each line is only active for its corresponding PTZ preset.

Usage:
    cd Hiep/
    python3 -m src.backend.tools.ptz_draw_line
    python3 -m src.backend.tools.ptz_draw_line --capture-dir results/ptz_captures
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

# ── Project path setup ──
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.backend.core.config import SRC_CONFIG_DIR, RESULTS_DIR
from src.backend.core.utils.polygon import load_yaml
from src.backend.core.logger import get_logger

logger = get_logger(__name__)

CAPTURE_DIR = RESULTS_DIR / "ptz_captures"
POLYGON_YAML = SRC_CONFIG_DIR / "polygon.yaml"


class PTZLineDrawer:
    """Interactive line drawer on a static image."""

    def __init__(self, image: np.ndarray, preset_id: int, preset_name: str, window_name: str):
        self.original = image.copy()
        self.display = image.copy()
        self.preset_id = preset_id
        self.preset_name = preset_name
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
        self.display = self.original.copy()

        # Draw points
        for i, p in enumerate(self.points):
            cv2.circle(self.display, (p[0], p[1]), 6, (0, 0, 255), -1)
            cv2.circle(self.display, (p[0], p[1]), 8, (255, 255, 255), 1)
            cv2.putText(self.display, str(i), (p[0] + 10, p[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # Draw line segments
        if len(self.points) >= 2:
            pts = np.array(self.points, dtype=np.int32)
            cv2.polylines(self.display, [pts], isClosed=False, color=(0, 0, 255), thickness=2, lineType=cv2.LINE_AA)

        # Instructions
        h, w = self.display.shape[:2]
        overlay = self.display.copy()
        cv2.rectangle(overlay, (0, 0), (w, 40), (30, 30, 30), -1)
        cv2.addWeighted(overlay, 0.7, self.display, 0.3, 0, self.display)

        info = f"Preset {self.preset_id} ({self.preset_name}) | Left=add, Right=undo, Enter=save, Esc=skip | Points: {len(self.points)}"
        cv2.putText(self.display, info,
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    def run(self) -> list[list[int]] | None:
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, 1280, 720)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)
        self._redraw()

        while True:
            cv2.imshow(self.window_name, self.display)
            key = cv2.waitKey(30) & 0xFF
            if key == 27:  # Esc — skip
                cv2.destroyWindow(self.window_name)
                return None
            elif key == 13:  # Enter — save
                cv2.destroyWindow(self.window_name)
                return self.points if len(self.points) >= 2 else None


def find_preset_images(capture_dir: Path) -> list[tuple[int, str, Path]]:
    """
    Scan capture_dir for preset images named like preset<ID>_<name>.jpg.
    Returns list of (preset_id, preset_name, image_path).
    """
    results = []
    for img_path in sorted(capture_dir.glob("preset*.*")):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
            continue
        stem = img_path.stem  # e.g. "preset1_cam1"
        parts = stem.split("_", 1)
        if len(parts) < 2:
            continue
        try:
            preset_id = int(parts[0].replace("preset", ""))
        except ValueError:
            continue
        preset_name = parts[1]
        results.append((preset_id, preset_name, img_path))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive fence-line editor for PTZ preset captures"
    )
    parser.add_argument(
        "--capture-dir", type=Path, default=CAPTURE_DIR,
        help=f"Directory with captured preset images (default: {CAPTURE_DIR})"
    )
    parser.add_argument(
        "--polygon-yaml", type=Path, default=POLYGON_YAML,
        help=f"Output polygon YAML file (default: {POLYGON_YAML})"
    )
    args = parser.parse_args()

    capture_dir = args.capture_dir.resolve()
    yaml_path = args.polygon_yaml.resolve()

    if not capture_dir.exists():
        print(f"❌ Capture directory not found: {capture_dir}")
        print("   Run ptz_capture_presets.py first to capture preset images.")
        sys.exit(1)

    # Find preset images
    preset_images = find_preset_images(capture_dir)
    if not preset_images:
        print(f"❌ No preset images found in: {capture_dir}")
        print("   Expected files like: preset1_cam1.jpg, preset2_cam2.jpg")
        sys.exit(1)

    print(f"\n🔍 Found {len(preset_images)} preset image(s):")
    for pid, pname, ppath in preset_images:
        print(f"   Preset {pid} ({pname}): {ppath.name}")

    # Load existing polygon.yaml
    data = load_yaml(yaml_path)
    if "ptz_presets" not in data:
        data["ptz_presets"] = {}

    # Draw lines on each preset image
    for preset_id, preset_name, img_path in preset_images:
        print(f"\n📐 Drawing line for Preset {preset_id} ({preset_name})...")

        image = cv2.imread(str(img_path))
        if image is None:
            print(f"   ❌ Cannot read image: {img_path}")
            continue

        ih, iw = image.shape[:2]
        print(f"   Resolution: {iw}x{ih}")

        drawer = PTZLineDrawer(
            image, preset_id, preset_name,
            f"PTZ Line - Preset {preset_id} ({preset_name})"
        )
        line_pts = drawer.run()

        preset_key = str(preset_id)

        if line_pts is not None and len(line_pts) >= 2:
            if preset_key not in data["ptz_presets"]:
                data["ptz_presets"][preset_key] = {}

            data["ptz_presets"][preset_key]["preset_id"] = preset_id
            data["ptz_presets"][preset_key]["preset_name"] = preset_name
            data["ptz_presets"][preset_key]["line"] = line_pts
            data["ptz_presets"][preset_key]["resolution"] = {"width": iw, "height": ih}
            data["ptz_presets"][preset_key]["updated_at"] = datetime.now().isoformat()

            print(f"   ✅ Saved {len(line_pts)} line points for Preset {preset_id}")
        else:
            print(f"   ⏭️  Skipped Preset {preset_id}")

    # Save to polygon.yaml
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8"
    )
    print(f"\n💾 Saved to: {yaml_path}")

    # Show summary
    ptz_data = data.get("ptz_presets", {})
    if ptz_data:
        print(f"\n📋 PTZ Preset Lines Summary:")
        for key, val in ptz_data.items():
            line = val.get("line", [])
            res = val.get("resolution", {})
            print(f"   Preset {key} ({val.get('preset_name', '?')}): "
                  f"{len(line)} points, {res.get('width', '?')}x{res.get('height', '?')}")

    print(f"\n✅ Done!\n")


if __name__ == "__main__":
    main()
