#!/usr/bin/env python3
"""
Reset PTZ Presets — Set lại preset mới từ slot 254 trở xuống.

Usage:
    cd Hiep/
    python3 src/tools/reset_presets.py

Flow:
    1. Connect PTZ
    2. Clear planned new preset slots (254, 253, ...), giữ 255 làm HOME
    3. Mở live feed PTZ + feed fixed camera fence8
    4. Di chuyển PTZ bằng arrow keys để canh vị trí
    5. Nhấn S để save preset tại vị trí hiện tại
    6. Lặp lại cho fence9, fence10

Keyboard:
    ← → ↑ ↓    Pan / Tilt
    + / -        Zoom in / out
    w            Zoom wide max
    f            Autofocus
    1-9          Goto preset theo thứ tự trong system.yaml
    s            Save preset (nhập ID từ terminal)
    n            Next fixed camera
    q / ESC      Quit
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import cv2
import numpy as np

from src.backend.core.config import SRC_CONFIG_DIR
from src.backend.core.camera.stream import open_capture
from src.backend.modules.fence.ptz_control import PTZController

HOME_PRESET_ID = 255
SAVE_PRESET_START_ID = 254


def load_config():
    import yaml
    fence_path = SRC_CONFIG_DIR / "system.yaml"
    data = yaml.safe_load(fence_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_fixed_cameras():
    import yaml
    sys_path = SRC_CONFIG_DIR / "system.yaml"
    if not sys_path.exists():
        return []
    data = yaml.safe_load(sys_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    cameras = data.get("cameras", [])
    return [(c["id"], c["rtsp_url"]) for c in cameras if "id" in c and "rtsp_url" in c]


def active_presets(presets: list[dict]) -> list[dict]:
    return [p for p in presets if int(p.get("id", 0)) != HOME_PRESET_ID]


def save_slot_for_preset(presets: list[dict], target: dict | None) -> int:
    active = active_presets(presets)
    if target in active:
        return SAVE_PRESET_START_ID - active.index(target)
    return SAVE_PRESET_START_ID


def preset_for_shortcut(presets: list[dict], key: int) -> dict | None:
    idx = key - ord("1")
    if 0 <= idx < min(len(presets), 9):
        preset = presets[idx]
        return preset if int(preset.get("id", 0)) != HOME_PRESET_ID else None
    return None


def main():
    cfg = load_config()
    ptz_cfg = cfg.get("ptz_camera", {})
    presets = cfg.get("presets", [])

    # Connect PTZ
    ptz = PTZController(
        host=ptz_cfg.get("ip", "127.0.0.1"),
        port=ptz_cfg.get("port", 80),
        username=ptz_cfg.get("username", "admin"),
        password=ptz_cfg.get("password", ""),
    )

    print(f"\n🔗 Connecting PTZ: {ptz_cfg.get('ip')}...")
    if not ptz.connect():
        print("❌ PTZ connection failed!")
        sys.exit(1)
    print("✅ PTZ connected")

    # Step 1: Clear planned new preset slots only. Preset 255 is HOME.
    preset_ids = [save_slot_for_preset(presets, p) for p in active_presets(presets)]
    print("\n" + "=" * 50)
    print(f"  Step 1: CLEARING NEW PRESET SLOTS {preset_ids}")
    print("=" * 50)
    for pid in preset_ids:
        ok = ptz.clear_preset(pid)
        print(f"  Preset {pid}: {'✓ cleared' if ok else '✗ failed'}")
    print("✅ New preset slots cleared. Existing 1-9 and preset 255 HOME were not touched.\n")

    # Step 2: Zoom wide max
    print("🔍 Zooming out to wide view...")
    ptz.zoom_wide_max(duration=3.0)
    time.sleep(1)

    # Step 3: Open PTZ stream
    ptz_rtsp = ptz_cfg.get("rtsp_url", "")
    print(f"📹 Opening PTZ stream: {ptz_rtsp}")
    ptz_cap, mode, _ = open_capture(ptz_rtsp, use_hwaccel=True, debug_label="PTZ")
    if ptz_cap is None:
        print("❌ Cannot open PTZ stream!")
        ptz.disconnect()
        sys.exit(1)
    print(f"✅ PTZ stream opened ({mode})")

    # Load fixed cameras
    fixed_cameras = load_fixed_cameras()
    fixed_caps = {}
    for cam_id, cam_url in fixed_cameras:
        cap, _, _ = open_capture(cam_url, use_hwaccel=True, debug_label=cam_id)
        if cap:
            fixed_caps[cam_id] = cap
            print(f"📹 Fixed camera {cam_id}: opened")

    # State
    current_fixed_idx = 0
    fixed_ids = list(fixed_caps.keys())
    saved_presets = set()
    status_msg = "Move PTZ → press S to save preset"
    status_time = time.time()

    win = "PTZ Preset Reset"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1600, 600)

    print(f"\n{'=' * 50}")
    print(f"  Step 2: SET NEW PRESETS")
    print(f"  Presets needed:")
    for p in presets:
        print(
            f"    current [{p['id']}] → new [{save_slot_for_preset(presets, p)}] "
            f"{p['name']} → camera {p.get('fixed_camera_id', '?')}"
        )
    print(f"\n  Move PTZ to match fixed camera view, then press S to save")
    print(f"  Press N to switch fixed camera reference")
    print(f"{'=' * 50}\n")

    try:
        while True:
            # Read PTZ
            ret, ptz_frame = ptz_cap.read()
            if not ret or ptz_frame is None:
                time.sleep(0.03)
                continue

            # Draw info
            display = ptz_frame.copy()
            h, w = display.shape[:2]

            # Info panel
            panel_lines = [
                "PTZ PRESET RESET",
                f"Saved: {sorted(saved_presets)} / Need: {preset_ids}",
                f"Move PTZ → S to save | N to switch cam | Q to quit",
            ]
            cv2.rectangle(display, (0, 0), (500, 60), (20, 20, 20), -1)
            for i, line in enumerate(panel_lines):
                color = (0, 255, 255) if i == 0 else (220, 220, 220)
                cv2.putText(display, line, (8, 16 + i * 16),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)

            # Status bar
            if status_msg and time.time() - status_time < 3.0:
                cv2.rectangle(display, (0, h - 24), (w, h), (0, 100, 0), -1)
                cv2.putText(display, status_msg, (6, h - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

            # Side-by-side with fixed camera
            if fixed_ids:
                cam_id = fixed_ids[current_fixed_idx]
                cap = fixed_caps[cam_id]
                fret, fframe = cap.read()
                if fret and fframe is not None:
                    ph = display.shape[0]
                    fh, fw = fframe.shape[:2]
                    scale = ph / fh
                    fframe_r = cv2.resize(fframe, (int(fw * scale), ph))

                    # Label
                    preset_info = next((p for p in presets if p.get("fixed_camera_id") == cam_id), None)
                    label = f"FIXED: {cam_id}"
                    if preset_info:
                        label += f" | Save slot [{save_slot_for_preset(presets, preset_info)}]"
                    cv2.rectangle(fframe_r, (0, 0), (400, 28), (0, 0, 180), -1)
                    cv2.putText(fframe_r, label, (5, 18),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

                    display = np.hstack([display, fframe_r])

            cv2.imshow(win, display)

            # Keyboard
            key = cv2.waitKey(30) & 0xFF

            if key == ord('q') or key == 27:
                break

            elif key == 81 or key == 2:
                ptz.move_direction("kCmdLeft", step=4, duration=0.3)
            elif key == 83 or key == 3:
                ptz.move_direction("kCmdRight", step=4, duration=0.3)
            elif key == 82 or key == 0:
                ptz.move_direction("kCmdUp", step=4, duration=0.3)
            elif key == 84 or key == 1:
                ptz.move_direction("kCmdDown", step=4, duration=0.3)

            elif key == ord('+') or key == ord('='):
                ptz.zoom_in(step=3, duration=0.3)
                status_msg = "Zoom In"
                status_time = time.time()
            elif key == ord('-') or key == ord('_'):
                ptz.zoom_out(step=3, duration=0.3)
                status_msg = "Zoom Out"
                status_time = time.time()
            elif key == ord('w'):
                ptz.zoom_wide_max(duration=2.0)
                status_msg = "Zoom Wide Max"
                status_time = time.time()
            elif key == ord('f'):
                ptz.autofocus()
                status_msg = "Autofocus"
                status_time = time.time()

            elif key == ord('n'):
                if fixed_ids:
                    current_fixed_idx = (current_fixed_idx + 1) % len(fixed_ids)
                    status_msg = f"Switched to: {fixed_ids[current_fixed_idx]}"
                    status_time = time.time()

            elif key == ord('s'):
                print("\n" + "=" * 40)
                try:
                    target = None
                    if fixed_ids:
                        cam_id = fixed_ids[current_fixed_idx]
                        target = next((p for p in presets if p.get("fixed_camera_id") == cam_id), None)
                    if target is None:
                        target = next((p for p in presets if int(p.get("id", 0)) != HOME_PRESET_ID), None)
                    default_id = save_slot_for_preset(presets, target)
                    default_name = target.get("name", f"preset{default_id}") if target else f"preset{default_id}"
                    raw_pid = input(f"  Enter preset ID to save [{default_id}]: ").strip()
                    pid = int(raw_pid) if raw_pid else default_id
                    if pid == HOME_PRESET_ID:
                        print(f"  ❌ Preset {HOME_PRESET_ID} is reserved for HOME.")
                        status_msg = f"❌ Preset {HOME_PRESET_ID} is HOME"
                        status_time = time.time()
                        print("=" * 40 + "\n")
                        continue
                    pname = input(f"  Preset name [{default_name}]: ").strip()
                    if not pname:
                        pname = default_name
                    if ptz.set_preset(pid, pname):
                        saved_presets.add(pid)
                        status_msg = f"✅ Saved preset [{pid}] {pname}"
                        print(f"  ✅ Preset {pid} saved as '{pname}'!")
                    else:
                        status_msg = f"❌ Failed preset {pid}"
                        print(f"  ❌ Failed!")
                except (ValueError, EOFError):
                    print("  Cancelled.")
                print("=" * 40 + "\n")
                status_time = time.time()

            # Goto planned new preset shortcut (test)
            elif ord('1') <= key <= ord('9'):
                preset = preset_for_shortcut(presets, key)
                if not preset:
                    status_msg = "❌ No configured preset for this key"
                    status_time = time.time()
                    continue
                pid = save_slot_for_preset(presets, preset)
                if ptz.goto_preset(pid):
                    status_msg = f"→ Goto preset [{pid}]"
                else:
                    status_msg = f"❌ Preset {pid} failed"
                status_time = time.time()

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        ptz_cap.release()
        for cap in fixed_caps.values():
            cap.release()
        ptz.disconnect()
        cv2.destroyAllWindows()

    # Summary
    print(f"\n{'=' * 50}")
    print(f"  SUMMARY")
    print(f"  Presets saved: {sorted(saved_presets)}")
    needed = set(preset_ids)
    missing = needed - saved_presets
    if missing:
        print(f"  ⚠️ Missing: {sorted(missing)}")
    else:
        print(f"  ✅ All presets configured!")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
