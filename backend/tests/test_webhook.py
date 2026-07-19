#!/usr/bin/env python3
"""
test_webhook — Gửi thử webhook với ảnh test.

Usage:
    cd ~/Desktop/UBQN
    python3 -m src.test.test_webhook
    python3 -m src.test.test_webhook --image path/to/image.jpg
    python3 -m src.test.test_webhook --cam ptz          # capture từ RTSP
    python3 -m src.test.test_webhook --device "TEST_DEVICE"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests

# ── Config (copy từ webhook.py) ──
WEBHOOK_URL = "http://10.128.55.254/rest/img/webhook"
WEBHOOK_API_KEY = "7f3b8a9c0d4e1a6b2f9c7d0a1e4b0"

# Camera RTSP URLs for --cam option
CAMERA_URLS = {
    "ptz":     "rtsp://admin:Hanet123@10.128.55.237:554/media/live/105",
    "fence8":  "rtsp://admin:Hanet123@10.128.55.225:554/media/live/105",
    "fence9":  "rtsp://admin:Hanet123@10.128.55.222:554/media/live/105",
    "fence10": "rtsp://admin:Hanet123@10.128.55.223:554/media/live/105",
}


def capture_frame(rtsp_url: str) -> np.ndarray | None:
    """Capture 1 frame from RTSP."""
    print(f"  Opening RTSP: {rtsp_url}")
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        print("  ❌ Cannot open RTSP")
        return None
    for _ in range(30):
        ok, frame = cap.read()
        if ok and frame is not None:
            cap.release()
            return frame
    cap.release()
    return None


def send_test_webhook(
    frame: np.ndarray,
    device_name: str,
    alarm_minor: str = "INTRUSION",
) -> None:
    """Send webhook exactly like webhook.py does."""
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        print("❌ Cannot encode JPEG")
        return

    image_bytes = buf.tobytes()
    alarm_time_ms = int(time.time() * 1000)
    filename = time.strftime(
        "%Y-%m-%d-%H-%M-%S.jpg", time.localtime(alarm_time_ms / 1000.0)
    )

    alarm_info_payload = {
        "alarm_major": "alert_alarm",
        "alarm_minor": alarm_minor,
        "device_name": device_name,
        "alarm_time": str(alarm_time_ms),
        "timestamp": str(alarm_time_ms),
        "additional": {
            "alarm_major": "alert_alarm",
            "alarm_minor": alarm_minor,
            "device_name": device_name,
            "alarm_time": str(alarm_time_ms),
            "timestamp": str(alarm_time_ms),
        },
    }
    alarm_info_json = json.dumps(alarm_info_payload, ensure_ascii=False)

    files = {
        "alarm_info": (None, alarm_info_json),
        "timestamp": (None, str(alarm_time_ms)),
        "picture": (filename, image_bytes, "image/jpeg"),
    }

    headers = {
        "X-Api-Key": WEBHOOK_API_KEY,
    }

    print(f"\n{'='*60}")
    print(f"  URL:         {WEBHOOK_URL}")
    print(f"  Device:      {device_name}")
    print(f"  Alarm:       {alarm_minor}")
    print(f"  Timestamp:   {alarm_time_ms}")
    print(f"  Image size:  {len(image_bytes)} bytes ({frame.shape[1]}x{frame.shape[0]})")
    print(f"  Filename:    {filename}")
    print(f"  API Key:     {WEBHOOK_API_KEY[:10]}...")
    print(f"{'='*60}")

    print("\n  Sending...")
    try:
        # ── Method 1: Original (timestamp in files dict) ──
        print("\n  ── Method 1: timestamp in files (None, value) ──")
        resp1 = requests.post(WEBHOOK_URL, files=files, headers=headers, timeout=10)
        print(f"     Status: {resp1.status_code} | {resp1.text[:200]}")

        # ── Method 2: timestamp as data (separate form field) ──
        print("\n  ── Method 2: timestamp in data={} ──")
        files_no_ts = {
            "alarm_info": (None, alarm_info_json),
            "picture": (filename, image_bytes, "image/jpeg"),
        }
        data_ts = {"timestamp": str(alarm_time_ms)}
        resp2 = requests.post(WEBHOOK_URL, files=files_no_ts, data=data_ts, headers=headers, timeout=10)
        print(f"     Status: {resp2.status_code} | {resp2.text[:200]}")

        # ── Method 3: timestamp as query parameter ──
        print("\n  ── Method 3: timestamp as ?timestamp= query param ──")
        url_with_ts = f"{WEBHOOK_URL}?timestamp={alarm_time_ms}"
        resp3 = requests.post(url_with_ts, files=files_no_ts, headers=headers, timeout=10)
        print(f"     Status: {resp3.status_code} | {resp3.text[:200]}")

        # ── Method 4: timestamp in alarm_info only (no separate field) ──
        print("\n  ── Method 4: timestamp only inside alarm_info JSON ──")
        files_minimal = {
            "alarm_info": (None, alarm_info_json),
            "picture": (filename, image_bytes, "image/jpeg"),
        }
        resp4 = requests.post(WEBHOOK_URL, files=files_minimal, headers=headers, timeout=10)
        print(f"     Status: {resp4.status_code} | {resp4.text[:200]}")

        # ── Method 5: all fields as data + picture as file ──
        print("\n  ── Method 5: alarm_info + timestamp as data, picture as file ──")
        data_all = {
            "alarm_info": alarm_info_json,
            "timestamp": str(alarm_time_ms),
        }
        files_pic = {
            "picture": (filename, image_bytes, "image/jpeg"),
        }
        resp5 = requests.post(WEBHOOK_URL, files=files_pic, data=data_all, headers=headers, timeout=10)
        print(f"     Status: {resp5.status_code} | {resp5.text[:200]}")

        # ── Method 6: timestamp as X-Timestamp header ──
        print("\n  ── Method 6: X-Timestamp header ──")
        headers6 = {**headers, "X-Timestamp": str(alarm_time_ms)}
        resp6 = requests.post(WEBHOOK_URL, files=files, headers=headers6, timeout=10)
        print(f"     Status: {resp6.status_code} | {resp6.text[:200]}")

        # ── Method 7: timestamp as Timestamp header ──
        print("\n  ── Method 7: Timestamp header ──")
        headers7 = {**headers, "Timestamp": str(alarm_time_ms)}
        resp7 = requests.post(WEBHOOK_URL, files=files, headers=headers7, timeout=10)
        print(f"     Status: {resp7.status_code} | {resp7.text[:200]}")

        # ── Method 8: timestamp in X-Api-Key header (key:timestamp format) ──
        print("\n  ── Method 8: X-Api-Key = 'key:timestamp' ──")
        headers8 = {"X-Api-Key": f"{WEBHOOK_API_KEY}:{alarm_time_ms}"}
        resp8 = requests.post(WEBHOOK_URL, files=files_no_ts, headers=headers8, timeout=10)
        print(f"     Status: {resp8.status_code} | {resp8.text[:200]}")

        # ── Method 9: timestamp as X-Request-Timestamp ──
        print("\n  ── Method 9: X-Request-Timestamp header ──")
        headers9 = {**headers, "X-Request-Timestamp": str(alarm_time_ms)}
        resp9 = requests.post(WEBHOOK_URL, files=files_no_ts, headers=headers9, timeout=10)
        print(f"     Status: {resp9.status_code} | {resp9.text[:200]}")

        # ── Method 10: timestamp in seconds (not ms) ──
        print("\n  ── Method 10: X-Timestamp (seconds, not ms) ──")
        ts_sec = str(int(time.time()))
        headers10 = {**headers, "X-Timestamp": ts_sec}
        resp10 = requests.post(WEBHOOK_URL, files=files, headers=headers10, timeout=10)
        print(f"     Status: {resp10.status_code} | {resp10.text[:200]}")

        # Summary
        results = [
            ("Method 1 (files tuple)",     resp1.status_code),
            ("Method 2 (data dict)",       resp2.status_code),
            ("Method 3 (query param)",     resp3.status_code),
            ("Method 4 (no ts field)",     resp4.status_code),
            ("Method 5 (data+file)",       resp5.status_code),
            ("Method 6 (X-Timestamp hdr)", resp6.status_code),
            ("Method 7 (Timestamp hdr)",   resp7.status_code),
            ("Method 8 (key:ts in ApiKey)", resp8.status_code),
            ("Method 9 (X-Request-Ts hdr)", resp9.status_code),
            ("Method 10 (X-Ts seconds)",    resp10.status_code),
        ]
        print(f"\n{'='*50}")
        print("  SUMMARY:")
        for name, code in results:
            mark = "✅" if code < 300 else "❌"
            print(f"    {mark} {name}: {code}")
        print(f"{'='*50}")

    except requests.exceptions.ConnectionError as e:
        print(f"\n  ❌ Connection failed: {e}")
        print(f"     Is webhook server reachable at {WEBHOOK_URL}?")
    except requests.exceptions.Timeout:
        print(f"\n  ❌ Timeout (10s)")
    except Exception as e:
        print(f"\n  ❌ Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Test webhook sender")
    parser.add_argument("--image", default="", help="Path to test image")
    parser.add_argument("--cam", default="", help="Camera ID (ptz, fence8, fence9, fence10)")
    parser.add_argument("--device", default="TEST_WEBHOOK_DEVICE", help="Device name")
    parser.add_argument("--alarm", default="INTRUSION", help="Alarm minor code")
    parser.add_argument("--url", default="", help="Override webhook URL")
    args = parser.parse_args()

    if args.url:
        global WEBHOOK_URL
        WEBHOOK_URL = args.url

    print("╔══════════════════════════════════════╗")
    print("║      WEBHOOK TEST                    ║")
    print("╚══════════════════════════════════════╝")

    # Get test frame
    frame = None

    if args.image:
        print(f"\n[1] Loading image: {args.image}")
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"  ❌ Cannot read image: {args.image}")
            sys.exit(1)
    elif args.cam:
        url = CAMERA_URLS.get(args.cam)
        if not url:
            print(f"  ❌ Unknown camera: {args.cam}")
            print(f"     Available: {list(CAMERA_URLS.keys())}")
            sys.exit(1)
        print(f"\n[1] Capturing from {args.cam}...")
        frame = capture_frame(url)
        if frame is None:
            sys.exit(1)
    else:
        # Generate test image with text
        print("\n[1] Generating test image (no --image or --cam specified)")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (40, 40, 40)
        cv2.putText(frame, "WEBHOOK TEST", (120, 200),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
        cv2.putText(frame, time.strftime("%Y-%m-%d %H:%M:%S"), (150, 300),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)

    print(f"  Frame: {frame.shape[1]}x{frame.shape[0]}")

    # Send
    print(f"\n[2] Sending webhook...")
    send_test_webhook(frame, args.device, args.alarm)


if __name__ == "__main__":
    main()
