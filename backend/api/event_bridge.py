"""
EventBridge — Cầu nối giữa fence detection threads và WebSocket clients.

Nhận TriggerEvent từ IntrusionMonitor queue → convert sang JSON →
broadcast tới tất cả connected WebSocket clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any, Callable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class EventBridge:
    """
    Thread-safe bridge: monitor queue → WebSocket broadcast.

    Usage:
        bridge = EventBridge()
        bridge.set_trigger_queue(queue)  # from fence monitors
        bridge.start()                   # start consumer thread

        # In FastAPI WebSocket endpoint:
        await bridge.register(websocket)
        ...
        bridge.unregister(websocket)
    """

    def __init__(self) -> None:
        self._queue: Queue | None = None
        self._ptz_queue: Queue | None = None  # Forward original triggers to PTZ
        self._ws_clients: set[WebSocket] = set()
        self._ws_lock = threading.Lock()
        self._consumer_thread: threading.Thread | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event_history: list[dict] = []  # Keep last 50 events
        self._on_event_callbacks: list[Callable[[dict], None]] = []

    def set_trigger_queue(self, queue: Queue) -> None:
        """Set the trigger queue from IntrusionMonitor."""
        self._queue = queue

    def set_ptz_queue(self, queue: Queue | None) -> None:
        """Set a secondary queue to forward original TriggerEvent for PTZ."""
        self._ptz_queue = queue

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the asyncio event loop for WebSocket broadcasting."""
        self._loop = loop

    def add_callback(self, callback: Callable[[dict], None]) -> None:
        """Add a callback invoked on each event (sync)."""
        self._on_event_callbacks.append(callback)

    def start(self) -> None:
        """Start the queue consumer thread."""
        if self._running:
            return
        self._running = True
        self._consumer_thread = threading.Thread(
            target=self._consume_loop, daemon=True, name="EventBridge"
        )
        self._consumer_thread.start()
        logger.info("EventBridge started")

    def stop(self) -> None:
        """Stop the consumer thread."""
        self._running = False
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=2.0)
        logger.info("EventBridge stopped")

    async def register(self, ws: WebSocket) -> None:
        """Register a WebSocket client. Send recent event history."""
        with self._ws_lock:
            self._ws_clients.add(ws)
        logger.info("WebSocket client connected (total: %d)", len(self._ws_clients))

        # Send recent history
        for event in self._event_history[-20:]:
            try:
                await ws.send_json(event)
            except Exception:
                break

    def unregister(self, ws: WebSocket) -> None:
        """Unregister a WebSocket client."""
        with self._ws_lock:
            self._ws_clients.discard(ws)
        logger.info("WebSocket client disconnected (total: %d)", len(self._ws_clients))

    @property
    def client_count(self) -> int:
        return len(self._ws_clients)

    def _consume_loop(self) -> None:
        """Background thread: poll queue and broadcast."""
        while self._running:
            if self._queue is None:
                time.sleep(0.5)
                continue

            try:
                trigger = self._queue.get(timeout=0.2)
            except Empty:
                continue

            # Forward original trigger to PTZ queue (if set)
            if self._ptz_queue is not None:
                try:
                    self._ptz_queue.put_nowait(trigger)
                    logger.info(
                        "[EventBridge] ➡ Forwarded trigger to PTZ queue (preset=%s, qsize=%d)",
                        getattr(trigger, "preset_id", "?"),
                        self._ptz_queue.qsize(),
                    )
                except Exception as fwd_err:
                    logger.warning("[EventBridge] PTZ queue full, skipped: %s", fwd_err)
            else:
                logger.debug("[EventBridge] No PTZ queue set — PTZ forwarding disabled")

            # Convert TriggerEvent to JSON-serializable dict
            event_data = self._trigger_to_event(trigger)

            # Store in history
            self._event_history.append(event_data)
            if len(self._event_history) > 50:
                self._event_history = self._event_history[-50:]

            # Invoke sync callbacks
            for cb in self._on_event_callbacks:
                try:
                    cb(event_data)
                except Exception as e:
                    logger.error("Event callback error: %s", e)

            # Broadcast to WebSocket clients
            self._broadcast(event_data)

    def _trigger_to_event(self, trigger: Any) -> dict:
        """Convert a TriggerEvent (or dict) to EventItem JSON format."""
        # Handle both TriggerEvent dataclass and dict
        if hasattr(trigger, "preset_id"):
            cam_id = getattr(trigger, "fixed_camera_id", "unknown")
            preset_name = getattr(trigger, "preset_name", "")
            persons = getattr(trigger, "persons_count", 1)
            ts = getattr(trigger, "timestamp", time.time())
        elif isinstance(trigger, dict):
            cam_id = trigger.get("fixed_camera_id", "unknown")
            preset_name = trigger.get("preset_name", "")
            persons = trigger.get("persons_count", 1)
            ts = trigger.get("timestamp", time.time())
        else:
            cam_id = "unknown"
            preset_name = ""
            persons = 1
            ts = time.time()

        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        created_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        # Event image URL — served by /api/events/{cam_id}/latest
        image_url = f"/api/events/{cam_id}/latest?ts={int(ts * 1000)}"

        return {
            "id": event_id,
            "cameraId": cam_id,
            "cameraName": preset_name or cam_id,
            "core": "fenceClimb",
            "message": f"Phát hiện trèo rào — {persons} người",
            "severity": "high",
            "createdAt": created_at,
            "isNew": True,
            "imageUrl": image_url,
        }

    def _broadcast(self, event_data: dict) -> None:
        """Broadcast event to all connected WebSocket clients."""
        if not self._ws_clients:
            return

        message = json.dumps(event_data, ensure_ascii=False)

        with self._ws_lock:
            clients = list(self._ws_clients)

        loop = self._loop
        if loop is None or loop.is_closed():
            return

        for ws in clients:
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send_text(message), loop
                )
            except Exception:
                # Client probably disconnected
                with self._ws_lock:
                    self._ws_clients.discard(ws)


# Singleton instance
event_bridge = EventBridge()
