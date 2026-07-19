"""
Patrol Tracker — Event-driven PTZ response.

Chờ trigger từ IntrusionMonitor → PTZ goto preset → detect → zoom → capture bullet → webhook.

Adapted from ptz_patrol/src/ray_sweep_tracker.py PatrolTracker.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, Optional

import cv2
import numpy as np

from .ptz_control import PTZController
from .face_capture import FaceCapture
from .monitor import TriggerEvent
from .control import PID, TargetTracker, map_effort

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IntrusionEvent:
    """Result of processing one intrusion trigger."""
    preset_id: int = 0
    preset_name: str = ""
    fixed_camera_id: str = ""
    timestamp: float = 0.0
    total_persons: int = 0
    face_captures: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0


class TrackerState(Enum):
    IDLE = "idle"
    MOVING = "moving"
    DETECTING = "detecting"
    ZOOMING = "zooming"
    FACE_CAPTURE = "face_capture"
    STOPPED = "stopped"


# ---------------------------------------------------------------------------
# PTZ Stream Reader
# ---------------------------------------------------------------------------

class PTZStreamReader:
    """Read frames from PTZ camera RTSP stream with buffer flush."""

    def __init__(self, rtsp_url: str) -> None:
        self._url = rtsp_url
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> bool:
        """Open PTZ stream (software decode to save GPU memory)."""
        from src.backend.core.camera import open_capture
        cap, mode, _ = open_capture(
            self._url,
            use_hwaccel=False,
            debug_label="PTZ-stream",
        )
        if cap is not None:
            self._cap = cap
            logger.info("PTZ stream opened (%s): %s", mode, self._url)
            return True
        logger.error("Cannot open PTZ stream: %s", self._url)
        return False

    def capture_latest_frame(self) -> np.ndarray | None:
        """Capture latest frame (flush buffer first)."""
        if self._cap is None or not self._cap.isOpened():
            return None
        # Flush old frames
        for _ in range(5):
            self._cap.grab()
        ret, frame = self._cap.read()
        if not ret:
            logger.warning("PTZ frame capture failed.")
            return None
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()


# ---------------------------------------------------------------------------
# Patrol Tracker
# ---------------------------------------------------------------------------

class PatrolTracker:
    """
    Event-driven PTZ tracker.

    Chờ trigger từ Queue → PTZ goto preset → detect → center → zoom → face.
    """

    def __init__(
        self,
        ptz: PTZController,
        model,
        stream: PTZStreamReader,
        face: FaceCapture,
        trigger_queue: Queue,
        presets: list[dict],
        # Zoom config
        target_bbox_ratio: float = 0.6,
        max_zoom_steps: int = 25,
        zoom_step: int = 5,
        zoom_duration: float = 0.3,
        center_tolerance: float = 0.15,
        # Detection
        conf: float = 0.5,
        device: str | None = "0",
        imgsz: int = 640,
        # PTZ fence lines {preset_id: {"line": [[x,y],...], "resolution": (w,h)}}
        ptz_fence_lines: dict | None = None,
        # Webhook
        webhook_dispatcher=None,
        ptz_device_name: str = "",
        # Tracking behavior
        disable_tracking: bool = False,
        # Closed-loop control (1a): "pid" = PID + target tracking, "step" = legacy stepping
        control_mode: str = "pid",
        pid_gains: dict | None = None,
        pid_settle: float = 0.35,
        # Direction inversion (for ceiling-mounted cameras)
        invert_pan: bool = True,
        invert_tilt: bool = True,
        # Callbacks
        on_intrusion: Callable[[IntrusionEvent], None] | None = None,
    ) -> None:
        self._ptz = ptz
        self._model = model
        self._stream = stream
        self._face = face
        self._queue = trigger_queue
        self._presets = {p["id"]: p for p in presets}
        self._ptz_fence_lines = ptz_fence_lines or {}

        self._target_bbox_ratio = target_bbox_ratio
        self._max_zoom_steps = max_zoom_steps
        self._zoom_step = zoom_step
        self._zoom_duration = zoom_duration
        self._center_tolerance = center_tolerance
        self._conf = conf
        self._device = device
        self._imgsz = imgsz

        self._webhook_dispatcher = webhook_dispatcher
        self._ptz_device_name = ptz_device_name
        self._disable_tracking = disable_tracking
        self._invert_pan = invert_pan
        self._invert_tilt = invert_tilt

        # ── Closed-loop control (1a) ──
        self._control_mode = (control_mode or "pid").lower()
        self._pid_settle = max(0.05, float(pid_settle))
        gains = pid_gains or {}
        pan_g = gains.get("pan", {"kp": 2.2, "ki": 0.0, "kd": 0.4})
        tilt_g = gains.get("tilt", {"kp": 2.2, "ki": 0.0, "kd": 0.4})
        zoom_g = gains.get("zoom", {"kp": 2.0, "ki": 0.0, "kd": 0.0})
        # Deadband on pan/tilt = center tolerance (no jitter once centered).
        self._pid_pan = PID(
            kp=pan_g.get("kp", 2.2), ki=pan_g.get("ki", 0.0), kd=pan_g.get("kd", 0.4),
            output_limit=1.0, integral_limit=0.5, deadband=self._center_tolerance,
        )
        self._pid_tilt = PID(
            kp=tilt_g.get("kp", 2.2), ki=tilt_g.get("ki", 0.0), kd=tilt_g.get("kd", 0.4),
            output_limit=1.0, integral_limit=0.5, deadband=self._center_tolerance,
        )
        self._pid_zoom = PID(
            kp=zoom_g.get("kp", 2.0), ki=zoom_g.get("ki", 0.0), kd=zoom_g.get("kd", 0.0),
            output_limit=1.0, integral_limit=0.5, deadband=0.03,
        )

        self._on_intrusion = on_intrusion
        self._state = TrackerState.IDLE
        self._running = False
        self._manual_override_until = 0.0  # timestamp until which manual mode active

    @property
    def state(self) -> TrackerState:
        return self._state

    def run(self) -> None:
        """Main loop: wait for triggers from Queue."""
        self._running = True
        self._state = TrackerState.IDLE

        logger.info(
            "PATROL TRACKER — Event-Driven\n"
            "  Presets registered: %s\n"
            "  Waiting for triggers from PTZ queue...",
            list(self._presets.keys()),
        )
        logger.info(
            "[TRACKER] Face capture: %s",
            "ENABLED" if self._face is not None else "DISABLED (no InsightFace)",
        )
        logger.info(
            "[TRACKER] PTZ stream: %s",
            "OPEN" if self._stream.is_open else "CLOSED",
        )

        try:
            while self._running:
                # Check manual override — keep triggers in queue for after override
                if time.time() < self._manual_override_until:
                    time.sleep(0.3)
                    continue

                try:
                    event = self._queue.get(timeout=0.3)
                except Empty:
                    continue

                # Drain queue — only process the LATEST trigger
                drained = 0
                while True:
                    try:
                        newer = self._queue.get_nowait()
                        self._queue.task_done()  # mark old one done
                        event = newer
                        drained += 1
                    except Empty:
                        break

                if drained > 0:
                    logger.info("[TRIGGER] Drained %d stale trigger(s), using latest", drained)

                logger.info(
                    "[TRIGGER] ⚡ Processing: preset=%d (%s), cam=%s, persons=%d",
                    event.preset_id, event.preset_name,
                    event.fixed_camera_id, event.persons_count,
                )
                try:
                    self._handle_trigger(event)
                except Exception as e:
                    logger.error("[TRIGGER] Error handling trigger: %s", e, exc_info=True)
                self._queue.task_done()
                self._return_home_if_idle(idle_seconds=5.0)

        except KeyboardInterrupt:
            logger.info("Tracker interrupted.")
        except Exception as e:
            logger.error("[TRACKER] Unexpected error: %s", e, exc_info=True)
        finally:
            self._state = TrackerState.STOPPED
            self._running = False
            logger.info("[TRACKER] Stopped")

    def stop(self) -> None:
        self._running = False

    def pause_for_manual(self, duration: float = 7.0) -> None:
        """Pause patrol for `duration` seconds to allow manual PTZ control."""
        self._manual_override_until = time.time() + duration
        logger.info("[TRACKER] ⏸ Manual override for %.0fs (patrol paused)", duration)

    def resume_patrol(self) -> None:
        """Resume patrol immediately after manual override."""
        self._manual_override_until = 0.0
        logger.info("[TRACKER] ▶ Patrol resumed")

    @property
    def is_manual_override(self) -> bool:
        return time.time() < self._manual_override_until

    # ── Handle Trigger ──

    def _handle_trigger(self, trigger: TriggerEvent) -> None:
        """Process one trigger: goto preset → detect → zoom → face."""
        start_time = time.time()
        preset = self._presets.get(trigger.preset_id)
        if preset is None:
            logger.error("Preset %d not found!", trigger.preset_id)
            return

        settle_time = preset.get("settle_time", 3.5)
        event = IntrusionEvent(
            preset_id=preset["id"],
            preset_name=preset.get("name", ""),
            fixed_camera_id=trigger.fixed_camera_id,
            timestamp=start_time,
        )

        # ── Step 1: Zoom wide + PTZ goto preset ──
        self._state = TrackerState.MOVING
        logger.info("[PTZ] Zoom wide → Goto preset %d...", preset["id"])

        # Reset zoom to wide angle before moving to preset
        self._ptz.zoom_wide_max(duration=1.5)
        time.sleep(0.5)

        if not self._ptz.goto_preset(preset["id"]):
            logger.error("[PTZ] Goto preset failed!")
            self._state = TrackerState.IDLE
            return

        logger.info("[PTZ] Waiting %.1fs for PTZ to settle...", settle_time)
        time.sleep(settle_time)

        # ── Step 2: Detect person on PTZ stream ──
        self._state = TrackerState.DETECTING
        logger.info("[PTZ] Detecting person on PTZ stream...")

        # Flush stale frames from RTSP buffer to get fresh post-settle frame
        for _ in range(8):
            self._stream.capture_latest_frame()

        frame = None
        persons = []
        for _ in range(10):
            frame = self._stream.capture_latest_frame()
            if frame is None:
                time.sleep(0.2)
                continue
            persons = self._detect_persons(frame)
            if persons:
                break
            time.sleep(0.3)

        if not persons or frame is None:
            logger.warning("[PTZ] No person found after goto preset — no webhook sent.")
            self._state = TrackerState.IDLE
            return

        event.total_persons = len(persons)

        # Overview frame (for face capture display only, no webhook)
        overview = FaceCapture.draw_persons(frame, persons)

        # Sort by confidence score (highest first = most reliable detection)
        sorted_persons = sorted(
            persons,
            key=lambda d: d[4],  # conf score
            reverse=True,
        )
        logger.info(
            "[PTZ] %d person(s) — sorted by confidence (best=%.2f)",
            len(sorted_persons), sorted_persons[0][4] if sorted_persons else 0,
        )

        # ── Process each person ──
        preset_info = {"id": preset["id"], "name": preset.get("name", "")}

        for idx, person in enumerate(sorted_persons):
            if not self._running:
                break

            # Reset to preset for subsequent persons
            if idx > 0:
                self._ptz.goto_preset(preset["id"])
                time.sleep(settle_time)
                new_frame = self._stream.capture_latest_frame()
                if new_frame is None:
                    continue
                new_persons = self._detect_persons(new_frame)
                new_sorted = sorted(
                    new_persons,
                    key=lambda d: (d[2] - d[0]) * (d[3] - d[1]),
                    reverse=True,
                )
                if idx >= len(new_sorted):
                    break
                person = new_sorted[idx]
                frame = new_frame

            # ── Step 3-4: Zoom & Center ──
            self._state = TrackerState.ZOOMING
            self._zoom_and_center(person, frame.shape)

            # ── Step 5: Capture bullet + Face (optional) ──
            self._state = TrackerState.FACE_CAPTURE
            time.sleep(0.3)
            self._ptz.autofocus()
            time.sleep(0.5)

            zoomed_frame = self._stream.capture_latest_frame()
            if zoomed_frame is None:
                continue

            # ── Re-detect person on zoomed frame → crop → webhook ──
            zoomed_persons = self._detect_persons(zoomed_frame)
            if zoomed_persons:
                # Pick largest person in zoomed frame
                best_person = max(
                    zoomed_persons,
                    key=lambda d: (d[2] - d[0]) * (d[3] - d[1]),
                )
                zx1, zy1, zx2, zy2 = best_person[0], best_person[1], best_person[2], best_person[3]

                # Draw only largest bbox on zoomed frame
                webhook_zoomed = zoomed_frame.copy()
                zconf = float(best_person[4]) if len(best_person) > 4 else 0.0
                cv2.rectangle(webhook_zoomed, (zx1, zy1), (zx2, zy2), (0, 255, 0), 2)
                cv2.putText(
                    webhook_zoomed, f"INTRUSION {zconf:.2f}",
                    (zx1, max(zy1 - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
                )
                logger.info(
                    "[PERSON %d] Zoomed frame with bbox: %dx%d",
                    idx, webhook_zoomed.shape[1], webhook_zoomed.shape[0],
                )

                # Webhook: send full zoomed frame with largest bbox
                self._send_zoomed_webhook(webhook_zoomed, preset)
            else:
                # No person detected after zoom — send full frame as fallback
                logger.warning("[PERSON %d] No person in zoomed frame, sending full frame", idx)
                self._send_zoomed_webhook(zoomed_frame, preset)

            if self._face is not None:
                faces = self._face.detect_faces(zoomed_frame)

                if faces:
                    best_face = max(
                        faces,
                        key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]),
                    )
                    paths = self._face.save_capture(
                        face_info=best_face,
                        full_frame=zoomed_frame,
                        preset_info=preset_info,
                        person_index=idx,
                        overview_frame=overview if idx == 0 else None,
                    )
                    event.face_captures.append({
                        "person_index": idx,
                        "face_confidence": best_face["confidence"],
                        "paths": paths,
                    })
                    logger.info(
                        "[PERSON %d] ✅ Face captured! conf=%.2f",
                        idx, best_face["confidence"],
                    )
                else:
                    logger.warning("[PERSON %d] ❌ No face detected.", idx)
                    # Save full frame anyway
                    self._face.save_capture(
                        face_info={
                            "bbox": (0, 0, 0, 0),
                            "confidence": 0.0,
                            "face_crop": zoomed_frame,
                            "embedding": None,
                        },
                        full_frame=zoomed_frame,
                        preset_info=preset_info,
                        person_index=idx,
                        overview_frame=overview if idx == 0 else None,
                    )
            else:
                logger.info("[PERSON %d] ⏭ FaceCapture disabled — skipped", idx)

        # ── Done ──
        event.duration_ms = (time.time() - start_time) * 1000

        # Zoom back to wide angle for surveillance
        logger.info("[PTZ] Zoom wide (reset for next trigger)...")
        self._ptz.zoom_wide_max(duration=1.5)
        time.sleep(0.5)

        self._state = TrackerState.IDLE

        logger.info(
            "[DONE] %d faces in %.0fms",
            len(event.face_captures), event.duration_ms,
        )

        if self._on_intrusion:
            try:
                self._on_intrusion(event)
            except Exception as e:
                logger.error("Callback error: %s", e)

    # ── Auto-return Home ──

    def _return_home_if_idle(self, idle_seconds: float = 5.0) -> None:
        """
        Sau khi gửi xong webhook, đợi `idle_seconds` giây.
        Nếu không có trigger mới trong queue → PTZ về Home (preset 255).
        Nếu có trigger mới đến → thoát ngay, để run() xử lý.
        """
        logger.info(
            "[HOME] Chờ %.0fs — nếu không có trigger mới sẽ về Home...",
            idle_seconds,
        )
        deadline = time.time() + idle_seconds
        while time.time() < deadline:
            if not self._running:
                return
            # Có trigger mới → không về Home, để vòng lặp chính xử lý
            if not self._queue.empty():
                logger.info("[HOME] Có trigger mới trong queue — bỏ qua về Home.")
                return
            time.sleep(0.2)

        # Kiểm tra lần cuối trước khi về Home
        if not self._queue.empty():
            logger.info("[HOME] Trigger xuất hiện vừa kịp — bỏ qua về Home.")
            return

        logger.info("[HOME] 🏠 Không có trigger mới sau %.0fs → PTZ về Home (preset 255)", idle_seconds)
        try:
            self._ptz.goto_preset(255)
        except Exception as e:
            logger.warning("[HOME] Lỗi khi về Home: %s", e)

    # ── Webhook helper ──

    def _send_zoomed_webhook(
        self,
        zoomed_frame: np.ndarray,
        preset: dict,
    ) -> None:
        """Gửi ảnh (full frame + bbox) qua webhook + broadcast event lên UI."""
        # ── Webhook to server ──
        if self._webhook_dispatcher is not None:
            try:
                from src.backend.core.webhook import FENCE_INTRUSION_ALARM_CODE
                device_name = self._ptz_device_name or "PTZ"
                self._webhook_dispatcher.enqueue(
                    zoomed_frame, device_name, FENCE_INTRUSION_ALARM_CODE,
                )
                logger.info(
                    "[PTZ] 📡 Webhook queued: device=%s, preset=%d",
                    device_name, preset.get("id", 0),
                )
            except Exception as e:
                logger.warning("[PTZ] Webhook error: %s", e)

        # ── UI event via EventBridge ──
        try:
            from src.backend.api.event_bridge import event_bridge
            import uuid
            from datetime import datetime, timezone

            now = time.time()
            cam_id = f"ptz_preset{preset.get('id', 0)}"
            preset_name = preset.get("name", "PTZ")
            event_data = {
                "id": f"evt-{uuid.uuid4().hex[:12]}",
                "cameraId": cam_id,
                "cameraName": f"PTZ → {preset_name}",
                "core": "fenceClimb",
                "message": f"PTZ phát hiện xâm nhập — preset {preset_name}",
                "severity": "high",
                "createdAt": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
                "isNew": True,
                "imageUrl": f"/api/events/{cam_id}/latest?ts={int(now * 1000)}",
            }
            event_bridge._broadcast(event_data)
            logger.info("[PTZ] 🔔 UI event broadcast: %s", preset_name)

            # Save event image for UI
            ev_dir = Path("results/event") / cam_id
            ev_dir.mkdir(parents=True, exist_ok=True)
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            cv2.imwrite(str(ev_dir / f"{ts_str}.jpg"), zoomed_frame)
        except Exception as e:
            logger.warning("[PTZ] UI event error: %s", e)

    # ── Fence distance helper ──

    @staticmethod
    def _distance_to_fence(
        bbox: tuple,
        fence_line: list[list[float]],
    ) -> float:
        """
        Calculate minimum distance from person bbox bottom-center to fence polyline.
        
        Uses tâm cạnh dưới bbox (bottom-center) — represents feet position.
        Closest person to fence is most likely the intruder climbing.
        """
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = float(bbox[3])  # bottom-center (tâm cạnh dưới)

        min_dist = float("inf")
        for i in range(len(fence_line) - 1):
            x1, y1 = fence_line[i]
            x2, y2 = fence_line[i + 1]

            # Point-to-line-segment distance
            dx, dy = x2 - x1, y2 - y1
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq < 1e-6:
                dist = ((cx - x1) ** 2 + (cy - y1) ** 2) ** 0.5
            else:
                t = max(0, min(1, ((cx - x1) * dx + (cy - y1) * dy) / seg_len_sq))
                proj_x = x1 + t * dx
                proj_y = y1 + t * dy
                dist = ((cx - proj_x) ** 2 + (cy - proj_y) ** 2) ** 0.5

            min_dist = min(min_dist, dist)

        return min_dist

    # ── Detection helper ──

    def _detect_persons(
        self, frame: np.ndarray,
    ) -> list[tuple[int, int, int, int, float]]:
        """Run YOLO on frame, return person bboxes."""
        try:
            results = self._model(
                frame,
                conf=self._conf,
                device=self._device,
                imgsz=self._imgsz,
                verbose=False,
            )
            res = results[0] if results else None
            if res is None:
                return []

            persons = []
            for box in res.boxes:
                cls_id = int(box.cls[0])
                if cls_id != 0:  # person class
                    continue
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                persons.append((int(x1), int(y1), int(x2), int(y2), conf))
            return persons
        except Exception as e:
            logger.error("YOLO detect error: %s", e)
            return []

    # ── Zoom & Center ──

    def _do_center(self, offset_x: float, offset_y: float) -> None:
        """Pan/tilt PTZ to center person — sequential commands with motor settle.

        PTZ API handles one command at a time. Each command: start → wait → stop.
        """
        if abs(offset_x) > self._center_tolerance:
            pan_step = min(8, max(3, int(abs(offset_x) * 40)))
            cmd = "kCmdRight" if offset_x > 0 else "kCmdLeft"
            logger.info("[CENTER] Pan %s step=%d dur=0.20 (offset=%.3f)", cmd, pan_step, offset_x)
            self._ptz.move_direction(cmd, step=pan_step, duration=0.2)
            time.sleep(0.3)  # settle after pan

        if abs(offset_y) > self._center_tolerance:
            tilt_step = min(8, max(3, int(abs(offset_y) * 40)))
            cmd = "kCmdDown" if offset_y > 0 else "kCmdUp"
            logger.info("[CENTER] Tilt %s step=%d dur=0.20 (offset=%.3f)", cmd, tilt_step, offset_y)
            self._ptz.move_direction(cmd, step=tilt_step, duration=0.2)
            time.sleep(0.3)  # settle after tilt

    def _zoom_and_center(
        self,
        bbox: tuple,
        frame_shape: tuple,
    ) -> bool:
        """Zoom & center the target — dispatch to PID or legacy step controller."""
        if self._control_mode == "pid":
            return self._zoom_and_center_pid(bbox, frame_shape)
        return self._zoom_and_center_step(bbox, frame_shape)

    def _zoom_and_center_pid(
        self,
        bbox: tuple,
        frame_shape: tuple,
    ) -> bool:
        """Closed-loop zoom & center (1a upgrade).

        A PID drives pan, tilt and zoom continuously toward the setpoint
        (bottom-center at 58% frame height, bbox ratio = target). A
        :class:`TargetTracker` locks onto ONE person by id so the loop keeps
        following the same intruder across re-detections instead of re-picking
        the largest box each frame.
        """
        TARGET_Y_RATIO = 0.58

        frame_h, frame_w = frame_shape[:2]
        x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]

        self._pid_pan.reset()
        self._pid_tilt.reset()
        self._pid_zoom.reset()

        # Seed the tracker with our target so it owns the locked id.
        tracker = TargetTracker(iou_threshold=0.2, max_age=8)
        seeded = tracker.update([(x1, y1, x2, y2, 1.0)])
        locked_id = seeded[0].id if seeded else None
        lost = 0
        cmd_count = 0
        last_t = time.time()

        for step_i in range(self._max_zoom_steps):
            bbox_cx = (x1 + x2) / 2
            bbox_cy = y2  # bottom-center (tâm cạnh dưới = vị trí chân)
            bbox_h = y2 - y1
            frame_cx = frame_w / 2
            target_cy = frame_h * TARGET_Y_RATIO

            offset_x = (bbox_cx - frame_cx) / frame_w
            offset_y = (bbox_cy - target_cy) / frame_h
            bbox_ratio = bbox_h / frame_h

            logger.info(
                "[ZOOM-PID] Step %d: ratio=%.2f offset=(%.2f, %.2f) lock=%s cmds=%d",
                step_i, bbox_ratio, offset_x, offset_y, locked_id, cmd_count,
            )

            if bbox_ratio >= self._target_bbox_ratio:
                logger.info("[ZOOM-PID] ✅ Target reached: ratio=%.2f (%d cmds)", bbox_ratio, cmd_count)
                return True

            # Guard: if person touches frame edge, stop zooming (same as step mode).
            EDGE_MARGIN = 0.03
            touches_edge = (
                x1 < frame_w * EDGE_MARGIN
                or x2 > frame_w * (1 - EDGE_MARGIN)
                or y1 < frame_h * EDGE_MARGIN
                or y2 > frame_h * (1 - EDGE_MARGIN)
            )
            if touches_edge and bbox_ratio > 0.15:
                logger.info("[ZOOM-PID] ⚠ Person at frame edge (ratio=%.2f) — stop", bbox_ratio)
                return True

            now = time.time()
            dt = now - last_t
            last_t = now

            # ── PID: pan / tilt ──
            u_x = self._pid_pan.update(offset_x, dt)
            u_y = self._pid_tilt.update(offset_y, dt)
            if u_x != 0.0:
                step, dur = map_effort(u_x)
                cmd = "kCmdRight" if u_x > 0 else "kCmdLeft"
                self._ptz.move_direction(cmd, step=step, duration=dur)
                cmd_count += 1
            if u_y != 0.0:
                step, dur = map_effort(u_y)
                cmd = "kCmdDown" if u_y > 0 else "kCmdUp"
                self._ptz.move_direction(cmd, step=step, duration=dur)
                cmd_count += 1

            # ── PID: zoom (positive effort → too small → zoom in) ──
            u_z = self._pid_zoom.update(self._target_bbox_ratio - bbox_ratio, dt)
            if u_z > 0.0:
                step, dur = map_effort(u_z, dur_min=0.15, dur_max=0.4)
                self._ptz.zoom_in(step=step, duration=dur)
                cmd_count += 1

            # Brief settle, then flush stale frames and re-detect.
            time.sleep(self._pid_settle)
            for _ in range(3):
                self._stream.capture_latest_frame()

            new_frame = None
            new_persons: list = []
            for _ in range(3):
                new_frame = self._stream.capture_latest_frame()
                if new_frame is None:
                    time.sleep(0.15)
                    continue
                new_persons = self._detect_persons(new_frame)
                if new_persons:
                    break
                time.sleep(0.15)

            if not new_persons or new_frame is None:
                lost += 1
                if lost >= 3:
                    logger.warning("[ZOOM-PID] Lost target after retries!")
                    return False
                continue
            lost = 0

            # ── Track association → keep locked id ──
            live = tracker.update([(p[0], p[1], p[2], p[3], p[4]) for p in new_persons])
            target = tracker.get(locked_id) if locked_id is not None else None
            if target is None or target.time_since_update != 0:
                # Lock lost this frame → re-lock to the track nearest the setpoint.
                if live:
                    fh, fw = new_frame.shape[:2]
                    sx, sy = fw / 2.0, fh * TARGET_Y_RATIO
                    target = min(
                        live,
                        key=lambda t: (t.center[0] - sx) ** 2 + (t.center[1] - sy) ** 2,
                    )
                    if target.id != locked_id:
                        logger.info("[ZOOM-PID] Re-locked target: %s → %d", locked_id, target.id)
                    locked_id = target.id
                else:
                    lost += 1
                    if lost >= 3:
                        return False
                    continue

            x1, y1, x2, y2 = target.bbox
            frame_h, frame_w = new_frame.shape[:2]

        logger.warning("[ZOOM-PID] Max steps reached (%d cmds).", cmd_count)
        return False

    def _zoom_and_center_step(
        self,
        bbox: tuple,
        frame_shape: tuple,
    ) -> bool:
        """Legacy fixed-step zoom & center (control_mode="step").

        Target: bottom-center of bbox (tâm cạnh dưới) → below frame center (58% height).
        ~65-70% of bbox will be in the lower half of the frame.
        """
        # Target point: center X, below center Y
        # 0.58 → with bbox_ratio 0.4: top=38%, bottom=78% → 70% below midline
        TARGET_Y_RATIO = 0.58

        frame_h, frame_w = frame_shape[:2]
        x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
        centered_once = False  # For disable_tracking: center 1 lần rồi khóa

        for step_i in range(self._max_zoom_steps):
            bbox_cx = (x1 + x2) / 2
            bbox_cy = y2  # tâm cạnh dưới bbox (bottom-center)
            bbox_h = y2 - y1
            frame_cx = frame_w / 2
            target_cy = frame_h * TARGET_Y_RATIO

            offset_x = (bbox_cx - frame_cx) / frame_w
            offset_y = (bbox_cy - target_cy) / frame_h
            bbox_ratio = bbox_h / frame_h

            logger.info(
                "[ZOOM] Step %d: ratio=%.2f, offset=(%.2f, %.2f), bbox_bottom_center=(%.0f, %.0f), target=(%.0f, %.0f)",
                step_i, bbox_ratio, offset_x, offset_y,
                bbox_cx, bbox_cy, frame_cx, target_cy,
            )

            if bbox_ratio >= self._target_bbox_ratio:
                logger.info("[ZOOM] ✅ Target reached: ratio=%.2f", bbox_ratio)
                return True

            need_center = (
                abs(offset_x) > self._center_tolerance
                or abs(offset_y) > self._center_tolerance
            )

            # Emergency re-center threshold (2x normal tolerance)
            EDGE_THRESHOLD = self._center_tolerance * 2.5
            at_edge = abs(offset_x) > EDGE_THRESHOLD or abs(offset_y) > EDGE_THRESHOLD

            # Guard: if person bbox touches frame edge, stop zooming
            EDGE_MARGIN = 0.03  # 3% of frame
            touches_edge = (
                x1 < frame_w * EDGE_MARGIN
                or x2 > frame_w * (1 - EDGE_MARGIN)
                or y1 < frame_h * EDGE_MARGIN
                or y2 > frame_h * (1 - EDGE_MARGIN)
            )
            if touches_edge and bbox_ratio > 0.15:
                logger.info("[ZOOM] ⚠ Person at frame edge (ratio=%.2f) — stopping zoom", bbox_ratio)
                return True  # Accept current position

            if self._disable_tracking:
                # Center ONCE only, then lock and just zoom
                if need_center and not centered_once:
                    logger.info("[ZOOM] Center (one-shot, then lock)...")
                    self._do_center(offset_x, offset_y)
                    centered_once = True
                # Only zoom (no more centering)
                self._ptz.zoom_in(
                    step=self._zoom_step,
                    duration=self._zoom_duration,
                )
                time.sleep(0.15)
            else:
                # Full tracking: center then zoom in same step
                if need_center:
                    self._do_center(offset_x, offset_y)
                # Always zoom after centering (or if already centered)
                self._ptz.zoom_in(
                    step=self._zoom_step,
                    duration=self._zoom_duration,
                )
                time.sleep(0.15)

            # Re-detect after movement — wait for PTZ to settle
            time.sleep(1.0)
            # Flush stale frames from buffer
            for _ in range(5):
                self._stream.capture_latest_frame()
            retries = 0
            while retries < 3:
                new_frame = self._stream.capture_latest_frame()
                if new_frame is None:
                    retries += 1
                    time.sleep(0.2)
                    continue
                new_persons = self._detect_persons(new_frame)
                if new_persons:
                    break
                retries += 1
                time.sleep(0.2)
            else:
                logger.warning("[ZOOM] Lost person after retries!")
                return False

            best = max(
                new_persons,
                key=lambda d: (d[2] - d[0]) * (d[3] - d[1]),
            )
            x1, y1, x2, y2 = best[0], best[1], best[2], best[3]
            frame_h, frame_w = new_frame.shape[:2]

        logger.warning("[ZOOM] Max steps reached.")
        return False

    @property
    def is_running(self) -> bool:
        return self._running
