"""
Intrusion Monitor — Fixed camera giám sát xâm nhập.

Tái sử dụng logic treo_rao:
- Mở RTSP stream (src.backend.core.camera)
- Apply ROI masking (src.backend.core.polygon)
- YOLO detect person (src.backend.core.detection)
- Alert engine: 3-frame consecutive streak → trigger PTZ

Mỗi fixed camera chạy 1 thread riêng.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Optional

import cv2
import numpy as np

from src.backend.core.camera.stream import open_capture
from src.backend.core.ai.detection import (
    has_any_detection,
    largest_person_box_xyxy,
    save_person_image_and_yolo,
)
from src.backend.modules.fence.geometry import (
    CameraRoiRefs,
    build_cam_roi_refs,
    foot_below_fence_polyline,
)
from src.backend.core.utils.polygon import apply_region1_zero_inside, scale_polygon_xy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Region2 schedule helper
# ---------------------------------------------------------------------------

def is_region2_active(schedule_cfg: dict | None) -> bool:
    """Check if region2 detection should be active based on time schedule.
    
    Args:
        schedule_cfg: dict with 'enabled' and 'time_ranges' keys.
            time_ranges: list of {start: "HH:MM", end: "HH:MM"}
            Supports overnight ranges (e.g. 18:00 → 06:00).
    
    Returns True if current time falls within any configured range.
    """
    if schedule_cfg is None or not schedule_cfg.get("enabled", False):
        return False
    
    from datetime import datetime
    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute
    
    for tr in schedule_cfg.get("time_ranges", []):
        start_str = str(tr.get("start", ""))
        end_str = str(tr.get("end", ""))
        try:
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, end_str.split(":"))
        except (ValueError, AttributeError):
            continue
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        
        if start_min <= end_min:
            # Same day range: e.g. 08:00 → 18:00
            if start_min <= now_minutes < end_min:
                return True
        else:
            # Overnight range: e.g. 18:00 → 06:00
            if now_minutes >= start_min or now_minutes < end_min:
                return True
    
    return False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TriggerEvent:
    """Sự kiện trigger từ fixed camera khi phát hiện xâm nhập."""
    preset_id: int
    preset_name: str
    fixed_camera_url: str
    fixed_camera_id: str
    persons_count: int
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class AlertFrameFeat:
    """Feature vector cho 1 frame — dùng cho alert logic."""
    had_person: bool
    bottom_in_cfg_polygon: bool
    person_below_fence_line: bool
    center_above_fence_line: bool
    has_fence_line: bool
    person_in_region2: bool = False


@dataclass
class IntrusionAlertState:
    """State tracking cho alert engine."""
    consec_any: int = 0
    consec_above: int = 0
    consec_bottom_cfg: int = 0
    consec_region2: int = 0
    history: deque = field(default_factory=lambda: deque(maxlen=32))


# ---------------------------------------------------------------------------
# Alert logic (from treo_rao.py)
# ---------------------------------------------------------------------------

def _should_suppress(history: deque) -> bool:
    """Suppress alert if person was below fence line in recent history."""
    if len(history) < 8:
        return False
    pre5 = list(history)[-8:-3]
    return any(h.had_person and h.person_below_fence_line for h in pre5)


def evaluate_intrusion_alert(
    state: IntrusionAlertState,
    feat: AlertFrameFeat,
    *,
    cam_label: str,
) -> str | None:
    """
    Update state and decide whether to trigger.
    Returns trigger source string only at frame #3 of a streak:
      - "fence"   → fence line / mask intrusion (should trigger PTZ)
      - "region2" → region2 night-mode intrusion (alert only, no PTZ)
      - None      → no trigger

    Logic:
    - Fixed camera only needs mask (region1) — person detected = intrusion
    - If fence_line exists → trigger when person CENTER is ABOVE fence line
    - If NO fence_line → trigger when any person detected (mask handles filtering)
    """
    if feat.had_person:
        state.consec_any += 1
    else:
        state.consec_any = 0

    if feat.center_above_fence_line:
        state.consec_above += 1
    else:
        state.consec_above = 0

    if feat.bottom_in_cfg_polygon:
        state.consec_bottom_cfg += 1
    else:
        state.consec_bottom_cfg = 0

    if feat.person_in_region2:
        state.consec_region2 += 1
    else:
        state.consec_region2 = 0

    state.history.append(feat)

    suppressed = (
        state.consec_bottom_cfg >= 3
        and _should_suppress(state.history)
    )

    if feat.has_fence_line:
        trigger = state.consec_above
    else:
        # No fence_line — do NOT trigger on any person
        # Only region2 (if configured) can trigger alerts
        trigger = 0

    # Region2 night mode: also trigger if person inside region2
    r2_trigger = state.consec_region2

    if (trigger >= 3 or r2_trigger >= 3) and not suppressed:
        source = "region2" if r2_trigger >= 3 and trigger < 3 else "fence"
        logger.warning(
            "[ALERT] %s: intrusion detected (%s) — %d consecutive frames",
            cam_label, source, max(trigger, r2_trigger),
        )
        if trigger == 3 or r2_trigger == 3:  # Fire only once at frame #3
            return source
    return None


# ---------------------------------------------------------------------------
# Fixed Camera Monitor Thread
# ---------------------------------------------------------------------------

class IntrusionMonitor(threading.Thread):
    """
    Thread giám sát 1 fixed camera.

    Chạy YOLO detect liên tục. Khi phát hiện xâm nhập (3-frame streak)
    → push TriggerEvent vào shared Queue → PTZ sẽ phản ứng.
    """

    def __init__(
        self,
        preset: dict,
        model,
        trigger_queue: Queue,
        roi: CameraRoiRefs | None,
        cooldown: float = 10.0,
        poll_interval: float = 0.3,
        conf: float = 0.5,
        device: str | None = "0",
        imgsz: int = 640,
        results_dir: Path | None = None,
        webhook_dispatcher=None,
        region2_schedule: dict | None = None,
    ) -> None:
        super().__init__(daemon=True)

        self._preset = preset
        self._model = model
        self._queue = trigger_queue
        self._roi = roi or CameraRoiRefs(None, (1920, 1080), None, (1920, 1080))
        self._cooldown = cooldown
        self._poll_interval = poll_interval
        self._conf = conf
        self._device = device
        self._imgsz = imgsz
        self._results_dir = results_dir
        self._webhook_dispatcher = webhook_dispatcher
        self._region2_schedule = region2_schedule
        self._running = False

        self._preset_id = preset["id"]
        self._preset_name = preset.get("name", f"Preset {self._preset_id}")
        self._cam_id = preset.get("fixed_camera_id", f"cam{self._preset_id}")
        self._rtsp_url = preset.get("fixed_camera_url", "")
        self._device_name = preset.get("device_name", self._cam_id)
        self._webhook_enabled = preset.get("webhook", True)

        self.name = f"Monitor-{self._cam_id}"

    def run(self) -> None:
        if not self._rtsp_url:
            logger.error("[%s] No RTSP URL configured!", self.name)
            return

        logger.info("[%s] Opening stream: %s", self.name, self._rtsp_url)

        cap, mode, _ = open_capture(
            self._rtsp_url,
            use_hwaccel=False,
            debug_label=self.name,
        )
        if cap is None:
            logger.error("[%s] Cannot open stream!", self.name)
            return

        logger.info("[%s] ✅ Stream opened (%s)", self.name, mode)
        self._running = True
        alert_state = IntrusionAlertState()
        last_trigger_time = 0.0
        frame_count = 0

        # Prepare event output directory
        if self._results_dir:
            ev_dir = self._results_dir / "event" / self._cam_id
            ev_dir.mkdir(parents=True, exist_ok=True)
            (ev_dir / "person").mkdir(parents=True, exist_ok=True)

        try:
            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    logger.warning("[%s] Frame read failed, retrying...", self.name)
                    time.sleep(1.0)
                    cap.release()
                    cap, _, _ = open_capture(
                        self._rtsp_url,
                        use_hwaccel=False,
                        debug_label=self.name,
                    )
                    if cap is None:
                        logger.error("[%s] Reconnect failed!", self.name)
                        break
                    continue

                frame_count += 1
                ih, iw = frame.shape[:2]

                # ── Apply ROI masking ──
                r1 = self._roi.region1
                r1s = None
                if r1 is not None and len(r1) >= 3:
                    r1s = scale_polygon_xy(
                        r1, self._roi.region1_ref[0], self._roi.region1_ref[1],
                        iw, ih,
                    )
                masked = apply_region1_zero_inside(frame, r1s)

                # ── Config polygon ──
                cf = self._roi.config_poly
                cfs = None
                if cf is not None and len(cf) >= 3:
                    cfs = scale_polygon_xy(
                        cf, self._roi.config_ref[0], self._roi.config_ref[1],
                        iw, ih,
                    )

                # ── YOLO detect ──
                results = self._model(
                    masked,
                    conf=self._conf,
                    device=self._device,
                    imgsz=self._imgsz,
                    verbose=False,
                )
                res = results[0] if results else None

                # ── Publish detection bboxes for overlay ──
                self._publish_detections(res, ih, iw)

                # ── Alert evaluation ──
                bbox = largest_person_box_xyxy(res) if res is not None else None
                had_person = bbox is not None
                bot_in_cfg = False
                below_ln = False
                center_above = False
                has_fl = self._roi.fence_line is not None
                person_in_region2 = False

                if bbox is not None:
                    bx = (bbox[0] + bbox[2]) / 2.0
                    by = bbox[3]
                    cx = bx
                    cy = (bbox[1] + bbox[3]) / 2.0

                    if cfs is not None and cfs.shape[0] >= 3:
                        bot_in_cfg = cv2.pointPolygonTest(cfs, (bx, by), False) >= 0

                    if self._roi.fence_line is not None:
                        frw, frh = self._roi.fence_line_ref
                        sx = float(iw) / float(frw) if frw > 0 else 1.0
                        sy = float(ih) / float(frh) if frh > 0 else 1.0
                        pts_scaled = [[p[0] * sx, p[1] * sy] for p in self._roi.fence_line]
                        below_ln = foot_below_fence_polyline(bx, by, pts_scaled, iw, ih)
                        center_above = not foot_below_fence_polyline(cx, cy, pts_scaled, iw, ih)

                    # ── Region2 check (schedule-based) ──
                    if (self._roi.region2 is not None
                            and len(self._roi.region2) >= 3
                            and is_region2_active(self._region2_schedule)):
                        r2s = scale_polygon_xy(
                            self._roi.region2,
                            self._roi.region2_ref[0], self._roi.region2_ref[1],
                            iw, ih,
                        )
                        if r2s is not None and r2s.shape[0] >= 3:
                            person_in_region2 = cv2.pointPolygonTest(
                                r2s.reshape(-1, 1, 2).astype(np.float32),
                                (float(cx), float(cy)), False
                            ) >= 0
                            if person_in_region2:
                                logger.info(
                                    "[%s] 🌙 Night mode: person in region2!",
                                    self.name,
                                )

                trigger_source = evaluate_intrusion_alert(
                    alert_state,
                    AlertFrameFeat(
                        had_person=had_person,
                        bottom_in_cfg_polygon=bot_in_cfg,
                        person_below_fence_line=below_ln,
                        center_above_fence_line=center_above,
                        has_fence_line=has_fl,
                        person_in_region2=person_in_region2,
                    ),
                    cam_label=self.name,
                )
                event_fired = trigger_source is not None

                # ── Save event image ──
                if event_fired and self._results_dir:
                    from datetime import datetime
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    ev_dir = self._results_dir / "event" / self._cam_id
                    ev_dir.mkdir(parents=True, exist_ok=True)
                    ev_path = ev_dir / f"{ts}.jpg"
                    # Draw bbox on event image so UI shows detection
                    ev_frame = frame.copy()
                    if bbox is not None:
                        bx1, by1 = int(bbox[0]), int(bbox[1])
                        bx2, by2 = int(bbox[2]), int(bbox[3])
                        cv2.rectangle(ev_frame, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
                        cv2.putText(
                            ev_frame, "INTRUSION",
                            (bx1, max(by1 - 8, 15)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
                        )
                    cv2.imwrite(str(ev_path), ev_frame)
                    logger.info("[%s] 📸 Event saved (with bbox) → %s", self.name, ev_path)

                    if res is not None and has_any_detection(res):
                        person_dir = ev_dir / "person"
                        person_dir.mkdir(parents=True, exist_ok=True)
                        save_person_image_and_yolo(
                            frame, res, person_dir, ts, cfs,
                        )

                # ── Push trigger to PTZ queue ──
                # region2 events: alert + webhook only, NO PTZ trigger
                if event_fired:
                    now = time.time()
                    if now - last_trigger_time >= self._cooldown:
                        last_trigger_time = now

                        if trigger_source == "region2":
                            logger.info(
                                "[%s] 🌙 Region2 alert — webhook only (no PTZ trigger)",
                                self.name,
                            )
                        else:
                            trigger = TriggerEvent(
                                preset_id=self._preset_id,
                                preset_name=self._preset_name,
                                fixed_camera_url=self._rtsp_url,
                                fixed_camera_id=self._cam_id,
                                persons_count=1,
                            )
                            self._queue.put(trigger)
                            logger.info(
                                "[%s] ⚠️ TRIGGER → PTZ preset %d (%s)",
                                self.name, self._preset_id, self._preset_name,
                            )

                        # ── Webhook POST (full frame + bbox) ──
                        if self._webhook_dispatcher is not None and self._webhook_enabled:
                            from src.backend.core.webhook import FENCE_INTRUSION_ALARM_CODE
                            # Draw bbox on full frame copy
                            webhook_frame = frame.copy()
                            if bbox is not None:
                                x1, y1 = int(bbox[0]), int(bbox[1])
                                x2, y2 = int(bbox[2]), int(bbox[3])
                                cv2.rectangle(webhook_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                cv2.putText(
                                    webhook_frame, "INTRUSION",
                                    (x1, max(y1 - 8, 15)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
                                )
                            self._webhook_dispatcher.enqueue(
                                webhook_frame, self._device_name, FENCE_INTRUSION_ALARM_CODE
                            )
                            logger.info(
                                "[%s] 📡 Webhook queued (full+bbox): device=%s",
                                self.name, self._device_name,
                            )

                time.sleep(self._poll_interval)

        except Exception as e:
            logger.error("[%s] Error: %s", self.name, e)
        finally:
            cap.release()
            logger.info("[%s] Monitor stopped.", self.name)

    def _publish_detections(self, res, frame_h: int, frame_w: int) -> None:
        """Publish latest person bboxes to shared_detections for overlay."""
        try:
            # Import shared state from backend
            import sys
            backend_mod = sys.modules.get("src.backend.api.rtsp_api")
            if backend_mod is None:
                # Try alternate import path
                backend_mod = sys.modules.get("rtsp_api")
            if backend_mod is None:
                return

            detections: list[list[float]] = []
            if res is not None and hasattr(res, "boxes") and res.boxes is not None:
                boxes = res.boxes
                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item()) if boxes.cls is not None else -1
                    if cls_id != 0:  # Only person class
                        continue
                    x1, y1, x2, y2 = boxes.xyxy[i].tolist()
                    conf = float(boxes.conf[i].item()) if boxes.conf is not None else 0.0
                    detections.append([x1, y1, x2, y2, conf, float(cls_id)])

            with backend_mod.shared_detections_lock:
                backend_mod.shared_detections[self._cam_id] = detections
                backend_mod.shared_det_resolution[self._cam_id] = (frame_w, frame_h)
        except Exception:
            pass  # Non-critical — overlay is best-effort

    def stop(self) -> None:
        self._running = False
        # Clear shared detections for this camera
        try:
            import sys
            backend_mod = sys.modules.get("src.backend.api.rtsp_api") or sys.modules.get("rtsp_api")
            if backend_mod is not None:
                with backend_mod.shared_detections_lock:
                    backend_mod.shared_detections.pop(self._cam_id, None)
        except Exception:
            pass
