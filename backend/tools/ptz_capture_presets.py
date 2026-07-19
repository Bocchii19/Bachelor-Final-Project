#!/usr/bin/env python3
"""
Capture PTZ at preset positions — goto configured presets rồi lưu ảnh.

Usage:
    cd Hiep/
    python3 src/tools/ptz_capture_presets.py
"""

from __future__ import annotations

import sys
import time
import argparse
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import cv2
import yaml

from src.backend.core.config import SRC_CONFIG_DIR, RESULTS_DIR
from src.backend.core.camera.stream import open_capture
from src.backend.core.logger import get_logger
from src.backend.modules.fence.ptz_control import PTZController

logger = get_logger(__name__)

CAPTURE_DIR = RESULTS_DIR / "ptz_captures"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture PTZ images after moving to preset positions."
    )
    parser.add_argument(
        "--presets",
        nargs="+",
        type=int,
        default=None,
        help=(
            "Preset IDs or 1-based shortcuts to capture. "
            "Default: first two presets from system.yaml"
        ),
    )
    parser.add_argument(
        "--settle-min",
        type=float,
        default=8.0,
        help="Minimum seconds to wait after goto preset before capture (default: 8)",
    )
    parser.add_argument(
        "--hwaccel",
        action="store_true",
        help="Use nvv4l2decoder hardware decoding. Default is software decode.",
    )
    return parser.parse_args()


def resolve_preset_ids(requested: list[int] | None, presets: list[dict]) -> list[int]:
    configured_ids = [int(p["id"]) for p in presets if "id" in p and int(p["id"]) != 255]
    if requested is None:
        return configured_ids[:2]

    configured_set = set(configured_ids)
    resolved = []
    for item in requested:
        if item in configured_set:
            resolved.append(item)
        elif 1 <= item <= len(configured_ids):
            resolved.append(configured_ids[item - 1])
        else:
            resolved.append(item)
    return resolved


def main():
    args = parse_args()

    # ── Load config ──
    fence_cfg = yaml.safe_load((SRC_CONFIG_DIR / "system.yaml").read_text())
    ptz_cfg = fence_cfg.get("ptz_camera", {})
    presets = fence_cfg.get("presets", [])

    ptz_host = ptz_cfg.get("ip")
    ptz_port = ptz_cfg.get("port", 80)
    ptz_user = ptz_cfg.get("username", "admin")
    ptz_pass = ptz_cfg.get("password", "")
    ptz_rtsp = ptz_cfg.get("rtsp_url", "")
    capture_preset_ids = resolve_preset_ids(args.presets, presets)

    # ── Connect PTZ ──
    print(f"\n🔗 Connecting to PTZ: {ptz_host}:{ptz_port}...")
    ptz = PTZController(host=ptz_host, port=ptz_port,
                        username=ptz_user, password=ptz_pass)
    if not ptz.connect():
        print("❌ PTZ connection failed!")
        sys.exit(1)
    print("✅ PTZ connected")

    # ── Open PTZ stream ──
    print(f"📹 Opening PTZ stream...")
    cap, mode, _ = open_capture(ptz_rtsp, use_hwaccel=args.hwaccel, debug_label="PTZ")
    if cap is None:
        print("❌ Cannot open PTZ stream!")
        sys.exit(1)
    print(f"✅ Stream opened ({mode})")

    # ── Capture at requested presets ──
    for preset_id in capture_preset_ids:
        preset_info = next((p for p in presets if p["id"] == preset_id), {})
        preset_name = preset_info.get("name", f"preset{preset_id}")
        settle_time = max(float(preset_info.get("settle_time", 3.0)), args.settle_min)

        print(f"\n➡️  Goto preset {preset_id} ({preset_name})...")
        if not ptz.goto_preset(preset_id):
            print(f"❌ Failed goto preset {preset_id}")
            continue

        # Wait for camera to settle
        print(f"⏳ Waiting {settle_time}s for camera to settle...")
        time.sleep(settle_time)

        # Flush old frames from buffer
        for _ in range(15):
            cap.read()

        # Capture clean frame
        ret, frame = cap.read()
        if ret and frame is not None:
            filename = f"preset{preset_id}_{preset_name}.jpg"
            filepath = CAPTURE_DIR / filename
            cv2.imwrite(str(filepath), frame)
            print(f"📸 Saved: {filepath}")
            print(f"   Resolution: {frame.shape[1]}x{frame.shape[0]}")
        else:
            print(f"❌ Failed to capture at preset {preset_id}")

    # ── Cleanup ──
    cap.release()
    ptz.disconnect()
    print(f"\n✅ Done! Captures saved to: {CAPTURE_DIR}\n")


if __name__ == "__main__":
    main()
