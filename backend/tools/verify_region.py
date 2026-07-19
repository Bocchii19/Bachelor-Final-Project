#!/usr/bin/env python3
"""
Interactive Region Drawing Tool

Vẽ lại 3 region cho camera:
  1. Region1 (Cyan)   — vùng mask (bên ngoài hàng rào)
  2. Region2 (Green)  — vùng an toàn (bên trong hàng rào)
  3. Fence Line (Red)  — đường ranh giới hàng rào

Controls:
  - Left click  : thêm điểm
  - Right click  : xóa điểm cuối (undo)
  - N            : chuyển sang region tiếp theo
  - R            : reset region hiện tại
  - S            : lưu tất cả vào polygon.yaml + reload backend
  - Q / ESC      : thoát (không lưu)

Usage:
  python3 scripts/draw_regions_fence9.py                    # fence9 (default)
  python3 scripts/draw_regions_fence9.py --cam fence8       # fence8
  python3 scripts/draw_regions_fence9.py --cam fence10      # fence10
"""

import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
import yaml
import copy

# ── Config ──────────────────────────────────────────────────────────────────
POLYGON_YAML = PROJECT_ROOT / "src" / "config" / "polygon.yaml"
SYSTEM_YAML = PROJECT_ROOT / "src" / "config" / "system.yaml"
BACKEND_URL = "http://localhost:9000"

# ── Lookup RTSP URL from system.yaml ────────────────────────────────────────
def _lookup_rtsp(cam_key: str) -> str:
    """Find RTSP URL from system.yaml cameras list, or polygon.yaml."""
    # Try system.yaml first
    if SYSTEM_YAML.exists():
        data = yaml.safe_load(SYSTEM_YAML.read_text(encoding="utf-8")) or {}
        for cam in data.get("cameras", []):
            if isinstance(cam, dict) and cam.get("id") == cam_key:
                return cam.get("rtsp_url", "")
    # Fallback to polygon.yaml
    if POLYGON_YAML.exists():
        data = yaml.safe_load(POLYGON_YAML.read_text(encoding="utf-8")) or {}
        cam = data.get("cameras", {}).get(cam_key, {})
        if isinstance(cam, dict):
            return cam.get("rtsp_url", "")
    return ""

# Parse args
import argparse
parser = argparse.ArgumentParser(description="Interactive region drawing tool")
parser.add_argument("--cam", default="fence9", help="Camera key in polygon.yaml (default: fence9)")
parser.add_argument("--rtsp", default="", help="RTSP URL (auto-detected from system.yaml if empty)")
parser.add_argument("--image", default="", help="Use existing image instead of RTSP capture")
args = parser.parse_args()
CAM_KEY = args.cam
RTSP_URL = args.rtsp or _lookup_rtsp(CAM_KEY)
WINDOW_NAME = f"Draw Regions — {CAM_KEY}"

if not RTSP_URL and not args.image:
    print(f"❌ Cannot find RTSP URL for '{CAM_KEY}' in system.yaml or polygon.yaml")
    print(f"   Use --rtsp or --image to specify manually")
    sys.exit(1)

# ── Colors (BGR) ────────────────────────────────────────────────────────────
COLORS = {
    "region1":    (255, 255, 0),    # Cyan
    "region2":    (0, 255, 0),      # Green
    "fence_line": (0, 0, 255),      # Red
}
LABELS = {
    "region1":    "Region1 (vùng mask — bên ngoài)",
    "region2":    "Region2 (vùng an toàn — bên trong)",
    "fence_line": "Fence Line (đường ranh giới)",
}
REGION_KEYS = ["region1", "region2", "fence_line"]

# ── State ───────────────────────────────────────────────────────────────────
current_region_idx = 0
points: dict[str, list[tuple[int, int]]] = {k: [] for k in REGION_KEYS}
base_frame: np.ndarray | None = None
display_frame: np.ndarray | None = None


def capture_frame(url: str) -> np.ndarray | None:
    """Capture frame from RTSP using GStreamer hw decode."""
    pipeline = (
        f'rtspsrc location="{url}" protocols=tcp latency=300 '
        "tcp-timeout=20000000 do-rtsp-keep-alive=true ! "
        "application/x-rtp,media=video,encoding-name=H264 ! "
        "rtph264depay ! h264parse config-interval=-1 ! "
        "nvv4l2decoder disable-dpb=true ! "
        "nvvidconv interpolation-method=1 ! "
        "video/x-raw,format=BGRx ! "
        "videoconvert n-threads=2 ! video/x-raw,format=BGR ! "
        "appsink max-buffers=2 drop=true sync=false"
    )
    print(f"  Opening stream (GStreamer)...")
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if cap.isOpened():
        for _ in range(40):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                cap.release()
                return frame
        cap.release()

    print(f"  ⚠ GStreamer failed, trying raw OpenCV...")
    cap = cv2.VideoCapture(url)
    if cap.isOpened():
        for _ in range(40):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                cap.release()
                return frame
        cap.release()
    return None


def load_existing_points() -> dict[str, list[tuple[int, int]]]:
    """Load existing polygon data from yaml."""
    if not POLYGON_YAML.exists():
        return {k: [] for k in REGION_KEYS}

    data = yaml.safe_load(POLYGON_YAML.read_text(encoding="utf-8")) or {}
    cam = data.get("cameras", {}).get(CAM_KEY, {})
    if not cam:
        return {k: [] for k in REGION_KEYS}

    result: dict[str, list[tuple[int, int]]] = {k: [] for k in REGION_KEYS}

    # Region1
    regions = cam.get("regions", {})
    for rkey in ["region1", "region2"]:
        raw = regions.get(rkey, [])
        if isinstance(raw, list):
            for p in raw:
                if isinstance(p, list) and len(p) == 2:
                    result[rkey].append((int(p[0]), int(p[1])))

    # Fence line
    fl_raw = cam.get("line", [])
    if isinstance(fl_raw, list):
        for p in fl_raw:
            if isinstance(p, list) and len(p) == 2:
                result["fence_line"].append((int(p[0]), int(p[1])))

    return result


def redraw():
    """Redraw the frame with all regions."""
    global display_frame
    if base_frame is None:
        return
    display_frame = base_frame.copy()
    ih, iw = display_frame.shape[:2]

    # Draw completed regions (not currently editing)
    for idx, key in enumerate(REGION_KEYS):
        pts_list = points[key]
        color = COLORS[key]
        is_current = (idx == current_region_idx)

        if len(pts_list) == 0:
            continue

        pts_arr = np.array(pts_list, dtype=np.int32)

        if key == "fence_line":
            # Fence line = polyline (not closed polygon)
            if len(pts_list) >= 2:
                cv2.polylines(display_frame, [pts_arr], False, color, 2 if not is_current else 3, cv2.LINE_AA)
            for pt in pts_list:
                r = 6 if is_current else 4
                cv2.circle(display_frame, pt, r, color, -1, cv2.LINE_AA)
                if is_current:
                    cv2.circle(display_frame, pt, r + 2, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            # Region = closed polygon with fill
            if len(pts_list) >= 3:
                overlay = display_frame.copy()
                cnt = pts_arr.reshape(-1, 1, 2)
                alpha = 0.25 if is_current else 0.15
                cv2.fillPoly(overlay, [cnt], color)
                cv2.addWeighted(overlay, alpha, display_frame, 1 - alpha, 0, display_frame)
                cv2.polylines(display_frame, [cnt], True, color, 2 if not is_current else 3, cv2.LINE_AA)
            elif len(pts_list) >= 2:
                cv2.polylines(display_frame, [pts_arr], False, color, 2, cv2.LINE_AA)

            for pt in pts_list:
                r = 6 if is_current else 4
                cv2.circle(display_frame, pt, r, color, -1, cv2.LINE_AA)
                if is_current:
                    cv2.circle(display_frame, pt, r + 2, (255, 255, 255), 1, cv2.LINE_AA)

    # ── HUD ──
    cur_key = REGION_KEYS[current_region_idx]
    cur_color = COLORS[cur_key]
    cur_label = LABELS[cur_key]
    cur_count = len(points[cur_key])

    # Background panel
    cv2.rectangle(display_frame, (0, 0), (620, 120), (20, 20, 20), -1)

    # Title
    cv2.putText(display_frame, f"Drawing: {cur_label}",
                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, cur_color, 1, cv2.LINE_AA)
    cv2.putText(display_frame, f"Points: {cur_count}",
                (10, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

    # Status of all regions
    y = 66
    for idx, key in enumerate(REGION_KEYS):
        c = COLORS[key]
        n = len(points[key])
        marker = ">>>" if idx == current_region_idx else "   "
        status = f"{n} pts" if n > 0 else "empty"
        cv2.putText(display_frame, f"{marker} {LABELS[key]}: {status}",
                    (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, c, 1, cv2.LINE_AA)
        y += 16

    # Controls
    cv2.putText(display_frame, "LClick=add  RClick=undo  N=next  R=reset  S=save  Q=quit",
                (10, ih - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)

    cv2.imshow(WINDOW_NAME, display_frame)


def mouse_callback(event, x, y, flags, param):
    global current_region_idx
    cur_key = REGION_KEYS[current_region_idx]

    if event == cv2.EVENT_LBUTTONDOWN:
        points[cur_key].append((x, y))
        print(f"  + {cur_key}[{len(points[cur_key])-1}] = ({x}, {y})")
        redraw()

    elif event == cv2.EVENT_RBUTTONDOWN:
        if points[cur_key]:
            removed = points[cur_key].pop()
            print(f"  - undo {cur_key}: ({removed[0]}, {removed[1]})")
            redraw()


def save_to_yaml():
    """Save drawn regions back to polygon.yaml."""
    if not POLYGON_YAML.exists():
        print("  ❌ polygon.yaml not found!")
        return False

    data = yaml.safe_load(POLYGON_YAML.read_text(encoding="utf-8")) or {}
    cameras = data.setdefault("cameras", {})
    cam = cameras.setdefault(CAM_KEY, {})

    # Preserve existing data
    cam.setdefault("rtsp_url", RTSP_URL)
    cam.setdefault("resolution", {"width": 1920, "height": 1080})

    # Update regions
    regions = cam.setdefault("regions", {})

    if points["region1"]:
        regions["region1"] = [[p[0], p[1]] for p in points["region1"]]
        print(f"  ✅ region1: {len(points['region1'])} points")
    else:
        print(f"  ⚠ region1: empty, keeping old data")

    if points["region2"]:
        regions["region2"] = [[p[0], p[1]] for p in points["region2"]]
        print(f"  ✅ region2: {len(points['region2'])} points")
    else:
        print(f"  ⚠ region2: empty, keeping old data")

    if points["fence_line"]:
        cam["line"] = [[p[0], p[1]] for p in points["fence_line"]]
        print(f"  ✅ fence_line: {len(points['fence_line'])} points")
    else:
        print(f"  ⚠ fence_line: empty, keeping old data")

    cam["updated_at"] = datetime.now().isoformat()

    # Write back
    POLYGON_YAML.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"\n  ✅ Saved to: {POLYGON_YAML}")
    return True


def main():
    global base_frame, current_region_idx, points

    print(f"═══════════════════════════════════════════════")
    print(f"  Draw Regions — {CAM_KEY}")
    print(f"  RTSP: {RTSP_URL}")
    print(f"  YAML: {POLYGON_YAML}")
    print(f"═══════════════════════════════════════════════")

    # ── Step 1: Capture frame ──
    if args.image:
        print(f"\n[1/3] Loading image: {args.image}")
        base_frame = cv2.imread(args.image)
        if base_frame is None:
            print(f"  ❌ Cannot read image!")
            sys.exit(1)
    else:
        print(f"\n[1/3] Capturing frame from RTSP...")
        base_frame = capture_frame(RTSP_URL)
        if base_frame is None:
            print(f"  ❌ Cannot capture frame!")
            sys.exit(1)

    ih, iw = base_frame.shape[:2]
    print(f"  Frame: {iw}x{ih}")

    # ── Step 2: Load existing data ──
    print(f"\n[2/3] Loading existing polygon data...")
    existing = load_existing_points()
    for key in REGION_KEYS:
        n = len(existing[key])
        print(f"  {key}: {n} points {'(loaded)' if n > 0 else '(empty)'}")

    # Ask user: start fresh or edit existing?
    has_data = any(len(existing[k]) > 0 for k in REGION_KEYS)
    if has_data:
        print(f"\n  [L] Load existing points and edit")
        print(f"  [F] Start fresh (empty)")
        print(f"  Press key in the window...")

        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, min(iw, 1400), min(ih, 900))

        # Show frame with existing overlay
        points = copy.deepcopy(existing)
        redraw()

        while True:
            key = cv2.waitKey(0) & 0xFF
            if key == ord('l') or key == ord('L'):
                points = copy.deepcopy(existing)
                print("  → Loaded existing points")
                break
            elif key == ord('f') or key == ord('F'):
                points = {k: [] for k in REGION_KEYS}
                print("  → Starting fresh")
                break
            elif key == 27 or key == ord('q'):
                print("  Cancelled.")
                cv2.destroyAllWindows()
                return
    else:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, min(iw, 1400), min(ih, 900))

    # ── Step 3: Interactive drawing ──
    print(f"\n[3/3] Interactive drawing mode")
    print(f"  Left click  = add point")
    print(f"  Right click  = undo last point")
    print(f"  N           = next region")
    print(f"  R           = reset current region")
    print(f"  S           = save all to polygon.yaml")
    print(f"  Q / ESC     = quit without saving")
    print()

    cv2.setMouseCallback(WINDOW_NAME, mouse_callback)
    current_region_idx = 0
    redraw()

    while True:
        key = cv2.waitKey(30) & 0xFF

        if key == 27 or key == ord('q') or key == ord('Q'):
            print("\n  Quit without saving.")
            break

        elif key == ord('n') or key == ord('N'):
            current_region_idx = (current_region_idx + 1) % len(REGION_KEYS)
            cur_key = REGION_KEYS[current_region_idx]
            print(f"\n  → Switched to: {LABELS[cur_key]}")
            redraw()

        elif key == ord('r') or key == ord('R'):
            cur_key = REGION_KEYS[current_region_idx]
            points[cur_key] = []
            print(f"\n  → Reset: {cur_key}")
            redraw()

        elif key == ord('s') or key == ord('S'):
            print(f"\n  Saving...")
            if save_to_yaml():
                # Auto-reload backend overlay
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        f"{BACKEND_URL}/api/overlay/reload", method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        print(f"  🔄 Backend overlay reloaded: {resp.read().decode()}")
                except Exception as e:
                    print(f"  ⚠ Backend reload failed (is it running?): {e}")
                    print(f"    Manual reload: curl -X POST {BACKEND_URL}/api/overlay/reload")
            break

    cv2.destroyAllWindows()
    print("Done!")


if __name__ == "__main__":
    main()
