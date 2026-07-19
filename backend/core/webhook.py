"""
Webhook utility — POST multipart alarm_info + ảnh JPEG đến server webhook.

Dùng chung cho các module detection (fence intrusion, camera occlusion, …).
Pattern giống main_face_recognition.send_webhook.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np
import requests

logger = logging.getLogger(__name__)

# ── Webhook constants ────────────────────────────────────────────────────────
WEBHOOK_URL = "http://10.128.55.254/rest/img/webhook"

WEBHOOK_API_KEY_INLINE = "7f3b8a9c0d4e1a6b2f9c7d0a1e4b0"
WEBHOOK_API_KEY = (os.environ.get("WEBHOOK_API_KEY") or WEBHOOK_API_KEY_INLINE).strip()
WEBHOOK_API_HEADER = os.environ.get("WEBHOOK_API_KEY_HEADER", "X-Api-Key").strip() or "X-Api-Key"
WEBHOOK_API_HEADER_TEMPLATE = os.environ.get("WEBHOOK_API_HEADER_TEMPLATE", "").strip()

# Alarm codes
FENCE_INTRUSION_ALARM_CODE = "INTRUSION"

# Dispatcher defaults
WEBHOOK_QUEUE_MAXSIZE = 128
WEBHOOK_WORKERS = 4


# ── Signing helper ────────────────────────────────────────────────────────

def compute_sign_key(api_key: str, timestamp_ms: str) -> str:
    """
    Compute HMAC-SHA256 sign key for webhook authentication.
    sign_key = HMAC-SHA256(api_key, timestamp_ms)
    """
    import hashlib
    import hmac
    return hmac.new(
        api_key.encode("utf-8"),
        timestamp_ms.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ── Synchronous sender ───────────────────────────────────────────────────────

def send_webhook_frame(
    frame: np.ndarray,
    device_name: str,
    alarm_minor: str,
) -> bool:
    """
    POST multipart giống main_face_recognition.send_webhook.

    Ảnh lấy từ BGR frame tại thời điểm gọi.
    Returns True nếu server trả 2xx.
    """
    if frame is None or frame.size == 0:
        return False
    try:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            return False
        image_bytes = buf.tobytes()

        alarm_time_ms = int(time.time() * 1000)
        ts_str = str(alarm_time_ms)
        filename = time.strftime(
            "%Y-%m-%d-%H-%M-%S.jpg", time.localtime(alarm_time_ms / 1000.0)
        )

        alarm_info_payload = {
            "alarm_major": "alert_alarm",
            "alarm_minor": alarm_minor,
            "device_name": device_name,
            "alarm_time": ts_str,
            "timestamp": ts_str,
            "additional": {
                "alarm_major": "alert_alarm",
                "alarm_minor": alarm_minor,
                "device_name": device_name,
                "alarm_time": ts_str,
                "timestamp": ts_str,
            },
        }
        alarm_info_json = json.dumps(alarm_info_payload, ensure_ascii=False)

        files = {
            "alarm_info": (None, alarm_info_json),
            "timestamp": (None, ts_str),
            "picture": (filename, image_bytes, "image/jpeg"),
        }

        # ── Auth header ──
        headers: dict[str, str] = {}
        if WEBHOOK_API_KEY:
            headers[WEBHOOK_API_HEADER] = WEBHOOK_API_KEY

        resp = requests.post(WEBHOOK_URL, files=files, headers=headers, timeout=5)
        if resp.status_code < 300:
            logger.info("[WEBHOOK] OK %s | %s", alarm_minor, device_name)
            return True
        logger.warning("[WEBHOOK] Loi %s: %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.warning("[WEBHOOK] Exception: %s", e)
        return False



# ── Async dispatcher ─────────────────────────────────────────────────────────

class AsyncWebhookDispatcher:
    """Background webhook sender with parallel workers to keep detection loop responsive."""

    def __init__(
        self,
        maxsize: int = WEBHOOK_QUEUE_MAXSIZE,
        num_workers: int = WEBHOOK_WORKERS,
    ):
        self._q: queue.Queue[Tuple[np.ndarray, str, str]] = queue.Queue(
            maxsize=max(1, int(maxsize))
        )
        self._stop = threading.Event()
        self._num_workers = max(1, int(num_workers))
        self._threads: List[threading.Thread] = []
        for worker_idx in range(self._num_workers):
            thread = threading.Thread(
                target=self._worker,
                daemon=True,
                name=f"WebhookWorker-{worker_idx + 1}",
            )
            thread.start()
            self._threads.append(thread)
        logger.info(
            "[WEBHOOK] Started %d worker(s), queue maxsize=%d",
            self._num_workers,
            self._q.maxsize,
        )

    def enqueue(
        self,
        frame: np.ndarray,
        device_name: str,
        alarm_minor: str,
    ) -> None:
        """Freeze frame content at event time; skip if queue full."""
        if frame is None:
            return
        try:
            self._q.put_nowait((frame.copy(), str(device_name), str(alarm_minor)))
        except queue.Full:
            logger.warning("[WEBHOOK] Queue full, drop event | %s", device_name)

    def _worker(self) -> None:
        while not self._stop.is_set() or not self._q.empty():
            try:
                frame, device_name, alarm_minor = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                send_webhook_frame(frame, device_name, alarm_minor)
            except Exception as e:
                logger.warning("[WEBHOOK] Worker error: %s", e)
            finally:
                self._q.task_done()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        per_thread_timeout = max(0.1, float(timeout))
        for thread in self._threads:
            thread.join(timeout=per_thread_timeout)
