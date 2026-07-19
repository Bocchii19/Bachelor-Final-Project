#!/usr/bin/env python3
"""
PTZ Preset Manager — Display PTZ live feed, điều khiển và lưu preset.

Hiển thị live feed từ camera PTZ, cho phép điều khiển bằng bàn phím
và lưu preset cho từng vị trí camera cố định.

Usage:
    cd Hiep/
    python3 src/tools/ptz_preset.py
    python3 src/tools/ptz_preset.py --show-fixed     # Hiện thêm feed camera cố định

Keyboard Controls:
    ← → ↑ ↓       Pan / Tilt
    + / -           Zoom in / out
    w               Zoom wide max (zoom ra hết)
    f               Autofocus
    1-9             Goto preset theo thứ tự trong system.yaml
    g               Goto preset ID bất kỳ (nhập từ terminal, ví dụ 254)
    s               Save preset tại vị trí hiện tại (gợi ý slot 254 trở xuống)
    Tab             Chuyển camera cố định (khi --show-fixed)
    q / ESC         Thoát
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Setup sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import cv2
import numpy as np

from src.backend.core.config import SRC_CONFIG_DIR
from src.backend.core.camera.stream import open_capture
from src.backend.core.logger import get_logger
from src.backend.modules.fence.ptz_control import PTZController

logger = get_logger(__name__)

HOME_PRESET_ID = 255
SAVE_PRESET_START_ID = 254


# ── Config loader ──────────────────────────────────────────────

def load_fence_config() -> dict:
    """Load system.yaml for PTZ camera info."""
    import yaml
    fence_path = SRC_CONFIG_DIR / "system.yaml"
    if not fence_path.exists():
        logger.error("Config not found: %s", fence_path)
        sys.exit(1)
    data = yaml.safe_load(fence_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_fixed_cameras() -> list[tuple[str, str]]:
    """Load fixed camera URLs from system.yaml."""
    import yaml
    sys_path = SRC_CONFIG_DIR / "system.yaml"
    if not sys_path.exists():
        return []
    data = yaml.safe_load(sys_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    cameras = data.get("cameras", [])
    return [(c["id"], c["rtsp_url"]) for c in cameras if "id" in c and "rtsp_url" in c]


def preset_for_shortcut(presets: list[dict], key: int) -> dict | None:
    """Map number keys 1-9 to configured presets in list order."""
    idx = key - ord("1")
    if 0 <= idx < min(len(presets), 9):
        preset = presets[idx]
        return preset if int(preset.get("id", 0)) != HOME_PRESET_ID else None
    return None


def default_save_preset(presets: list[dict], fixed_label: str) -> dict | None:
    """Use the currently displayed fixed camera as the default preset target."""
    if fixed_label:
        match = next((p for p in presets if p.get("fixed_camera_id") == fixed_label), None)
        if match:
            return match
    return next((p for p in presets if int(p.get("id", 0)) != HOME_PRESET_ID), None)


def save_slot_for_preset(presets: list[dict], target: dict | None) -> int:
    """Return the new-save slot for a preset order: 254, 253, 252..."""
    active = [p for p in presets if int(p.get("id", 0)) != HOME_PRESET_ID]
    if target in active:
        return SAVE_PRESET_START_ID - active.index(target)
    return SAVE_PRESET_START_ID


# ── Overlay drawing ────────────────────────────────────────────

def draw_overlay(frame: np.ndarray, ptz: PTZController, presets: list[dict],
                 current_preset: int | None, status_msg: str,
                 det_device: str = "0") -> np.ndarray:
    """Draw control overlay on PTZ frame."""
    out = frame.copy()
    h, w = out.shape[:2]

    # Background panel
    panel_h = 90 + len(presets) * 12
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (280, panel_h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.7, out, 0.3, 0, out)

    y = 14
    cv2.putText(out, "PTZ PRESET MANAGER", (6, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)

    y += 16
    connected = "CONNECTED" if ptz.is_connected else "DISCONNECTED"
    color = (0, 255, 0) if ptz.is_connected else (0, 0, 255)
    cv2.putText(out, f"PTZ: {ptz.host} [{connected}] | device: {det_device}", (6, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, color, 1, cv2.LINE_AA)

    y += 14
    preset_text = f"Current Preset: {current_preset}" if current_preset else "No preset selected"
    cv2.putText(out, preset_text, (6, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1, cv2.LINE_AA)

    y += 14
    cv2.putText(out, "Arrows:Pan/Tilt  +/-:Zoom  1-9:Goto cfg", (6, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)
    y += 12
    cv2.putText(out, "G:Goto ID  S:Save  F:Focus  W:Wide  Q:Quit", (6, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.28, (180, 180, 180), 1, cv2.LINE_AA)

    # Preset list
    y += 14
    for idx, p in enumerate(presets[:9], start=1):
        pid = p.get("id", 0)
        pname = p.get("name", "")
        marker = " <<" if current_preset == pid else ""
        cv2.putText(out, f"  {idx}: [{pid}] {pname}{marker}", (6, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.28, (200, 200, 200), 1, cv2.LINE_AA)
        y += 12

    # Status message (bottom)
    if status_msg:
        cv2.rectangle(out, (0, h - 24), (w, h), (0, 100, 0), -1)
        cv2.putText(out, status_msg, (6, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

    return out


# ── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PTZ Preset Manager — Live View & Control")
    parser.add_argument("--show-fixed", action="store_true",
                        help="Hiện thêm feed camera cố định bên cạnh")
    parser.add_argument("--pan-step", type=int, default=4, help="Tốc độ pan (1-8)")
    parser.add_argument("--tilt-step", type=int, default=4, help="Tốc độ tilt (1-8)")
    parser.add_argument("--move-duration", type=float, default=0.3, help="Thời gian di chuyển (s)")
    args = parser.parse_args()

    # ── Load config ──
    cfg = load_fence_config()
    ptz_cfg = cfg.get("ptz_camera", {})
    presets = cfg.get("presets", [])

    ptz_host = ptz_cfg.get("ip", "127.0.0.1")
    ptz_port = ptz_cfg.get("port", 80)
    ptz_user = ptz_cfg.get("username", "admin")
    ptz_pass = ptz_cfg.get("password", "")
    ptz_rtsp = ptz_cfg.get("rtsp_url", "")

    if not ptz_rtsp:
        print("❌ PTZ RTSP URL not configured in config/system.yaml")
        sys.exit(1)

    # ── Connect PTZ ──
    ptz = PTZController(host=ptz_host, port=ptz_port,
                        username=ptz_user, password=ptz_pass)

    print(f"\n🔗 Connecting to PTZ: {ptz_host}:{ptz_port}...")
    if not ptz.connect():
        print("❌ PTZ connection failed! Continuing in view-only mode.")

    # ── Open PTZ stream ──
    print(f"📹 Opening PTZ stream: {ptz_rtsp}")
    ptz_cap, mode, _ = open_capture(ptz_rtsp, use_hwaccel=True, debug_label="PTZ")
    if ptz_cap is None:
        print("❌ Cannot open PTZ stream!")
        sys.exit(1)
    print(f"✅ PTZ stream opened ({mode})")

    # ── Open fixed camera (optional) ──
    fixed_cameras = load_fixed_cameras() if args.show_fixed else []
    fixed_cap = None
    fixed_idx = 0
    fixed_label = ""

    if fixed_cameras:
        cam_id, cam_url = fixed_cameras[0]
        fixed_label = cam_id
        print(f"📹 Opening fixed camera: {cam_id}")
        fixed_cap, fmode, _ = open_capture(cam_url, use_hwaccel=True, debug_label=cam_id)
        if fixed_cap:
            print(f"✅ Fixed camera opened ({fmode})")

    # ── Main loop ──
    current_preset = None
    status_msg = "Ready — Use arrows to control PTZ"
    status_time = time.time()
    det_device = cfg.get("detection", {}).get("device", "0")
    window_name = "PTZ Preset Manager"

    print(f"\n{'='*50}")
    print(f"  PTZ PRESET MANAGER")
    print(f"  Presets: {len(presets)}")
    print(f"  Press Q or ESC to quit")
    print(f"{'='*50}\n")

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    try:
        while True:
            # Read PTZ frame
            ret, ptz_frame = ptz_cap.read()
            if not ret or ptz_frame is None:
                time.sleep(0.05)
                continue

            # Clear old status
            if time.time() - status_time > 3.0:
                status_msg = ""

            # Draw overlay
            display = draw_overlay(ptz_frame, ptz, presets, current_preset, status_msg,
                                   det_device=det_device)

            # Side-by-side with fixed camera
            if fixed_cap is not None and fixed_cap.isOpened():
                fret, fframe = fixed_cap.read()
                if fret and fframe is not None:
                    # Resize fixed to match PTZ height
                    ph, pw = display.shape[:2]
                    fh, fw = fframe.shape[:2]
                    scale = ph / fh
                    fframe_resized = cv2.resize(fframe, (int(fw * scale), ph))

                    # Label fixed camera with device ID
                    preset_info = next((p for p in presets if p.get("fixed_camera_id") == fixed_label), None)
                    preset_str = f" | Preset {preset_info['id']}" if preset_info else ""
                    label_text = f"{fixed_label}{preset_str}"
                    label_w = max(220, len(label_text) * 10 + 20)
                    cv2.rectangle(fframe_resized, (0, 0), (label_w, 30), (20, 20, 20), -1)
                    cv2.putText(fframe_resized, label_text, (5, 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)

                    display = np.hstack([display, fframe_resized])

            cv2.imshow(window_name, display)

            # ── Handle keyboard ──
            key = cv2.waitKey(30) & 0xFF

            if key == ord('q') or key == 27:  # Q or ESC
                break

            # Arrow keys (special keys)
            elif key == 81 or key == 2:  # Left arrow
                ptz.move_direction("kCmdLeft", step=args.pan_step, duration=args.move_duration)
                status_msg = f"← Pan Left (step={args.pan_step})"
                status_time = time.time()

            elif key == 83 or key == 3:  # Right arrow
                ptz.move_direction("kCmdRight", step=args.pan_step, duration=args.move_duration)
                status_msg = f"→ Pan Right (step={args.pan_step})"
                status_time = time.time()

            elif key == 82 or key == 0:  # Up arrow
                ptz.move_direction("kCmdUp", step=args.tilt_step, duration=args.move_duration)
                status_msg = f"↑ Tilt Up (step={args.tilt_step})"
                status_time = time.time()

            elif key == 84 or key == 1:  # Down arrow
                ptz.move_direction("kCmdDown", step=args.tilt_step, duration=args.move_duration)
                status_msg = f"↓ Tilt Down (step={args.tilt_step})"
                status_time = time.time()

            elif key == ord('+') or key == ord('='):  # Zoom in
                ptz.zoom_in(step=3, duration=0.3)
                status_msg = "🔍 Zoom In"
                status_time = time.time()

            elif key == ord('-') or key == ord('_'):  # Zoom out
                ptz.zoom_out(step=3, duration=0.3)
                status_msg = "🔍 Zoom Out"
                status_time = time.time()

            elif key == ord('w'):  # Zoom wide max
                ptz.zoom_wide_max(duration=2.0)
                status_msg = "🔍 Zoom Wide Max"
                status_time = time.time()

            elif key == ord('f'):  # Autofocus
                ptz.autofocus()
                status_msg = "🎯 Autofocus"
                status_time = time.time()

            elif key == ord('g'):  # Goto preset by numeric ID
                print("\n" + "="*40)
                try:
                    raw_pid = input("  Enter preset ID to goto: ").strip()
                    if not raw_pid:
                        print("  Cancelled.")
                        status_msg = "Cancelled"
                    else:
                        pid = int(raw_pid)
                        if ptz.goto_preset(pid):
                            current_preset = pid
                            status_msg = f"➡️ Goto preset [{pid}]"
                            print(f"  ✅ Goto preset {pid}")
                        else:
                            status_msg = f"❌ Failed goto preset {pid}"
                            print(f"  ❌ Failed goto preset {pid}")
                except (ValueError, EOFError):
                    status_msg = "Cancelled"
                    print("  Cancelled.")
                print("="*40 + "\n")
                status_time = time.time()

            elif key == ord('s'):  # Save preset (interactive)
                print("\n" + "="*40)
                try:
                    target = default_save_preset(presets, fixed_label)
                    default_id = save_slot_for_preset(presets, target)
                    default_name = target.get("name", f"preset{default_id}") if target else f"preset{default_id}"
                    raw_pid = input(f"  Enter preset ID to save [{default_id}]: ").strip()
                    pid = int(raw_pid) if raw_pid else default_id
                    if pid == HOME_PRESET_ID:
                        print(f"  ❌ Preset {HOME_PRESET_ID} is reserved for HOME.")
                        status_msg = f"❌ Preset {HOME_PRESET_ID} is HOME"
                        status_time = time.time()
                        print("="*40 + "\n")
                        continue
                    pname = input(f"  Enter preset name [{default_name}]: ").strip()
                    if not pname:
                        pname = default_name
                    if ptz.set_preset(pid, pname):
                        status_msg = f"✅ Saved preset [{pid}] {pname}"
                        print(f"  ✅ Preset {pid} saved!")
                    else:
                        status_msg = f"❌ Failed to save preset {pid}"
                        print(f"  ❌ Failed!")
                except (ValueError, EOFError):
                    status_msg = "Cancelled"
                    print("  Cancelled.")
                print("="*40 + "\n")
                status_time = time.time()

            elif key == 9:  # Tab — switch fixed camera
                if fixed_cameras and len(fixed_cameras) > 1:
                    if fixed_cap:
                        fixed_cap.release()
                    fixed_idx = (fixed_idx + 1) % len(fixed_cameras)
                    cam_id, cam_url = fixed_cameras[fixed_idx]
                    fixed_label = cam_id
                    fixed_cap, _, _ = open_capture(cam_url, use_hwaccel=True, debug_label=cam_id)
                    status_msg = f"📹 Switched to: {cam_id}"
                    status_time = time.time()

            # Number keys 1-9: goto configured preset shortcuts
            elif ord('1') <= key <= ord('9'):
                preset = preset_for_shortcut(presets, key)
                if not preset:
                    status_msg = "❌ No configured preset for this key"
                    status_time = time.time()
                    continue
                pid = int(preset["id"])
                if ptz.goto_preset(pid):
                    current_preset = pid
                    preset_name = preset.get("name", "")
                    status_msg = f"➡️ Goto preset [{pid}] {preset_name}"
                else:
                    status_msg = f"❌ Failed goto preset {pid}"
                status_time = time.time()

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        ptz_cap.release()
        if fixed_cap:
            fixed_cap.release()
        ptz.disconnect()
        cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    main()
