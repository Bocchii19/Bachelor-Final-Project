#!/usr/bin/env python3
"""
RTSP backend + AI Detection API for UI.

Endpoints:
- POST /api/streams/show
- POST /api/streams/stop/{camera_id}
- GET  /api/streams/{camera_id}/mjpeg
- POST /api/ai/start
- POST /api/ai/stop
- GET  /api/ai/status
- WS   /ws/events
- GET  /api/events/{event_id}/image

Run:
  uvicorn src.backend.api.rtsp_api:app --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Optional
from urllib.parse import unquote, urlparse
import sys

import cv2
import numpy as np
import yaml
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

ai_logger = logging.getLogger("ai_manager")

GST_LATENCY = 300
GST_MAX_BUFFERS = 3
OPEN_VALIDATE_SECONDS = 4.0
OPEN_VALIDATE_READS = 25

ROOT_DIR = Path(__file__).resolve().parents[3]
# mtrpc_client.py lives alongside this file in src/backend/
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
from mtrpc_client import MTRPCClient  # type: ignore

# ── Fence detection imports ──
# Add Hiep/src parent to path so we can import src.backend.modules.fence.*
_HIEP_DIR = str(ROOT_DIR / "Hiep")
if _HIEP_DIR not in sys.path:
    sys.path.insert(0, _HIEP_DIR)

from event_bridge import event_bridge  # type: ignore


def _build_gstreamer_pipeline(rtsp_url: str) -> str:
    return (
        f'rtspsrc location="{rtsp_url}" protocols=tcp latency={GST_LATENCY} '
        "tcp-timeout=20000000 do-rtsp-keep-alive=true ! "
        "application/x-rtp,media=video,encoding-name=H264 ! "
        "rtph264depay ! h264parse config-interval=-1 ! "
        "nvv4l2decoder disable-dpb=true ! "
        "nvvidconv interpolation-method=1 ! "
        "video/x-raw,format=BGRx ! "
        "videoconvert n-threads=2 ! video/x-raw,format=BGR ! "
        f"queue max-size-buffers={GST_MAX_BUFFERS} leaky=downstream ! "
        f"appsink max-buffers={GST_MAX_BUFFERS} drop=true sync=false"
    )


def _validate_capture(cap: cv2.VideoCapture) -> bool:
    deadline = time.time() + OPEN_VALIDATE_SECONDS
    attempts = 0
    while time.time() < deadline and attempts < OPEN_VALIDATE_READS:
        ok, frame = cap.read()
        attempts += 1
        if ok and frame is not None and frame.size > 0:
            return True
        time.sleep(0.05)
    return False


def _open_capture(rtsp_url: str) -> cv2.VideoCapture:
    pipeline = _build_gstreamer_pipeline(rtsp_url)
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if cap.isOpened() and _validate_capture(cap):
        return cap
    cap.release()
    cap = cv2.VideoCapture(rtsp_url)
    if cap.isOpened() and _validate_capture(cap):
        return cap
    cap.release()
    raise RuntimeError("Cannot open RTSP stream")


def _safe_public_base_url(request: Request) -> str:
    base = str(request.base_url).rstrip("/")
    parsed = urlparse(base)
    if parsed.hostname in {"0.0.0.0", "::"}:
        fallback = "127.0.0.1"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{fallback}{port}"
    return base


class StreamReader:
    def __init__(self, camera_id: str, rtsp_url: str):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.cap: Optional[cv2.VideoCapture] = None
        self.latest_frame = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.cap = _open_capture(self.rtsp_url)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        assert self.cap is not None
        failed_reads = 0
        while not self.stop_event.is_set():
            ok, frame = self.cap.read()
            if not ok or frame is None:
                failed_reads += 1
                # Recover from stuck/closed stream by reopening capture.
                if failed_reads >= 30:
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    try:
                        self.cap = _open_capture(self.rtsp_url)
                        failed_reads = 0
                    except Exception:
                        time.sleep(0.25)
                time.sleep(0.1)
                continue
            failed_reads = 0
            with self.lock:
                self.latest_frame = frame
        self.cap.release()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.5)
        if self.cap is not None:
            self.cap.release()

    def get_jpeg(
        self,
        overlay_manager: 'OverlayManager | None' = None,
        stream_mgr: 'StreamManager | None' = None,
    ) -> Optional[bytes]:
        with self.lock:
            frame = None if self.latest_frame is None else self.latest_frame.copy()
        if frame is None:
            return None

        # Draw overlay if enabled
        if overlay_manager is not None:
            frame = overlay_manager.draw_overlay(self.camera_id, frame, stream_mgr=stream_mgr)

        # Resize to 720p max to reduce memory and bandwidth
        h, w = frame.shape[:2]
        MAX_H = 720
        if h > MAX_H:
            scale = MAX_H / h
            frame = cv2.resize(frame, (int(w * scale), MAX_H))
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        if not ok:
            return None
        return encoded.tobytes()


class ShowRequest(BaseModel):
    cameraId: str
    rtspUrl: str


class PtzRequest(BaseModel):
    cameraId: str
    rtspUrl: str
    direction: str
    ptzPort: int = 80


class PtzZoomRequest(BaseModel):
    cameraId: str
    rtspUrl: str
    action: str
    ptzPort: int = 80


class PtzPresetRequest(BaseModel):
    cameraId: str
    rtspUrl: str
    preset: int = 255
    ptzPort: int = 80


class PtzHomeRequest(BaseModel):
    cameraId: str
    rtspUrl: str
    ptzPort: int = 80
    preset: int = 255
    password: str | None = None


class PolygonPoint(BaseModel):
    x: int
    y: int


class TreoRaoConfigRequest(BaseModel):
    cameraId: str
    cameraName: str | None = None
    configKey: str = "treo-rao"
    polygon: list[PolygonPoint]
    width: int = 1920
    height: int = 1080
    rtspUrl: str = ""


class StreamManager:
    def __init__(self):
        self.readers: dict[str, StreamReader] = {}
        self.lock = threading.Lock()

    def start(self, camera_id: str, rtsp_url: str) -> None:
        with self.lock:
            old = self.readers.get(camera_id)
            if old is not None:
                old.stop()
            reader = StreamReader(camera_id, rtsp_url)
            reader.start()
            self.readers[camera_id] = reader

    def stop(self, camera_id: str) -> None:
        with self.lock:
            reader = self.readers.pop(camera_id, None)
        if reader is not None:
            reader.stop()

    def get(self, camera_id: str) -> Optional[StreamReader]:
        with self.lock:
            return self.readers.get(camera_id)

    def shutdown(self) -> None:
        with self.lock:
            keys = list(self.readers.keys())
        for k in keys:
            self.stop(k)


def _parse_rtsp_auth(rtsp_url: str) -> tuple[str, str, str]:
    parsed = urlparse(rtsp_url)
    host = parsed.hostname or ""
    username = unquote(parsed.username or "admin")
    password = unquote(parsed.password or "")
    return host, username, password


# ── Overlay Manager ────────────────────────────────────────────────────────

# Shared latest detection bboxes from IntrusionMonitor threads.
# key = camera_id, value = list of [x1, y1, x2, y2, conf, cls_id]
shared_detections: dict[str, list[list[float]]] = {}
# Resolution at which detections were made (for bbox scaling to display stream)
shared_det_resolution: dict[str, tuple[int, int]] = {}  # cam_id -> (width, height)
shared_detections_lock = threading.Lock()


def _extract_ip_from_rtsp(url: str) -> str | None:
    """Extract IP from RTSP URL."""
    import re
    m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", url or "")
    return m.group(1) if m else None


class OverlayManager:
    """
    Manages per-camera overlay rendering state.

    Each camera has independent toggle for:
      - show_region: draw region1/region2 + fence_line from polygon.yaml
      - show_bbox:   draw YOLO detection bboxes (from shared_detections)
    """

    # Color palette (BGR)
    CLR_REGION1 = (255, 255, 0)     # Cyan
    CLR_REGION2 = (0, 255, 0)       # Green
    CLR_FENCE   = (0, 0, 255)       # Red
    CLR_BBOX    = (0, 200, 255)     # Orange-ish
    CLR_LEGEND_BG = (30, 30, 30)

    def __init__(self) -> None:
        self._states: dict[str, dict[str, bool]] = {}  # cam_id -> {show_region, show_bbox}
        self._lock = threading.Lock()
        # Cached polygon data loaded from polygon.yaml
        self._polygon_data: dict | None = None
        self._polygon_loaded = False

    def reload_polygon(self) -> int:
        """Clear polygon cache and reload from disk."""
        self._polygon_loaded = False
        self._polygon_data = None
        data = self._load_polygon_yaml()
        cams = data.get("cameras", {})
        n = len(cams) if isinstance(cams, dict) else 0
        logging.getLogger(__name__).info("OverlayManager: reloaded polygon.yaml (%d cameras)", n)
        return n

    def _default_state(self) -> dict[str, bool]:
        return {"show_region": False, "show_bbox": False}

    def get_state(self, camera_id: str) -> dict[str, bool]:
        with self._lock:
            return dict(self._states.get(camera_id, self._default_state()))

    def set_state(
        self, camera_id: str, show_region: bool | None = None, show_bbox: bool | None = None
    ) -> dict[str, bool]:
        with self._lock:
            state = self._states.setdefault(camera_id, self._default_state())
            if show_region is not None:
                state["show_region"] = show_region
            if show_bbox is not None:
                state["show_bbox"] = show_bbox
            return dict(state)

    def _load_polygon_yaml(self) -> dict:
        """Load polygon.yaml (lazy, cached)."""
        if self._polygon_loaded:
            return self._polygon_data or {}
        # Load from src/backend/config/polygon.yaml (single source of truth)
        paths = [
            ROOT_DIR / "src" / "config" / "polygon.yaml",
        ]
        for p in paths:
            if p.exists():
                try:
                    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                    self._polygon_data = data
                    self._polygon_loaded = True
                    return data
                except Exception:
                    continue
        self._polygon_loaded = True
        self._polygon_data = {}
        return {}

    def _get_camera_polygon_data(
        self, camera_id: str, rtsp_url: str = ""
    ) -> tuple[
        list[list[float]] | None,  # region1
        list[list[float]] | None,  # region2
        list[list[float]] | None,  # fence_line
        tuple[int, int],           # resolution
    ]:
        """Get polygon data for a camera (by camera_id or by IP match)."""
        data = self._load_polygon_yaml()
        cams = data.get("cameras", {})
        if not isinstance(cams, dict):
            return None, None, None, (1920, 1080)

        # Try direct match by camera_id
        node = cams.get(camera_id)

        # Fallback: match by IP in RTSP URL
        if node is None and rtsp_url:
            target_ip = _extract_ip_from_rtsp(rtsp_url)
            if target_ip:
                for _cid, n in cams.items():
                    if isinstance(n, dict):
                        ip = _extract_ip_from_rtsp(str(n.get("rtsp_url", "")))
                        if ip == target_ip:
                            node = n
                            break

        if not isinstance(node, dict):
            return None, None, None, (1920, 1080)

        # Resolution
        res = node.get("resolution", {})
        rw = int(res.get("width", 1920)) if isinstance(res, dict) else 1920
        rh = int(res.get("height", 1080)) if isinstance(res, dict) else 1080

        # Regions
        regions = node.get("regions", {})
        r1 = r2 = None
        if isinstance(regions, dict):
            r1_raw = regions.get("region1")
            r2_raw = regions.get("region2")
            if isinstance(r1_raw, list):
                r1 = self._parse_pts(r1_raw)
            if isinstance(r2_raw, list):
                r2 = self._parse_pts(r2_raw)

        # Fence line
        fl = None
        fl_raw = node.get("line")
        if isinstance(fl_raw, list):
            fl = self._parse_pts(fl_raw)

        return r1, r2, fl, (rw, rh)

    @staticmethod
    def _parse_pts(seq: list) -> list[list[float]] | None:
        pts: list[list[float]] = []
        for p in seq:
            if isinstance(p, list) and len(p) == 2:
                try:
                    pts.append([float(p[0]), float(p[1])])
                except (TypeError, ValueError):
                    continue
        return pts if len(pts) >= 2 else None

    def draw_overlay(self, camera_id: str, frame: np.ndarray, stream_mgr: 'StreamManager | None' = None) -> np.ndarray:
        """Draw overlays on frame based on camera state."""
        with self._lock:
            state = self._states.get(camera_id)
        if state is None:
            return frame
        show_region = state.get("show_region", False)
        show_bbox = state.get("show_bbox", False)
        if not show_region and not show_bbox:
            return frame

        out = frame.copy()
        ih, iw = out.shape[:2]

        # ── Draw regions & fence line ──
        if show_region:
            # Look up camera RTSP url from StreamManager for IP matching
            rtsp_url = ""
            if stream_mgr is not None:
                reader = stream_mgr.get(camera_id)
                if reader is not None:
                    rtsp_url = reader.rtsp_url

            r1, r2, fl, (rw, rh) = self._get_camera_polygon_data(camera_id, rtsp_url)
            sx = float(iw) / float(rw) if rw > 0 else 1.0
            sy = float(ih) / float(rh) if rh > 0 else 1.0

            def scale_pts(pts: list[list[float]]) -> np.ndarray:
                return np.array(
                    [[int(p[0] * sx), int(p[1] * sy)] for p in pts],
                    dtype=np.int32,
                )

            # ── MASK: darken inside region1 (like YOLO sees) ──
            if r1 is not None and len(r1) >= 3:
                r1_scaled = scale_pts(r1)
                mask = np.zeros((ih, iw), dtype=np.uint8)
                cv2.fillPoly(mask, [r1_scaled.reshape(-1, 1, 2)], 255)
                # Black out masked area 100% (inside region1 = what YOLO ignores)
                out[mask > 0] = 0
                # Draw region1 outline
                cv2.polylines(out, [r1_scaled.reshape(-1, 1, 2)], True, self.CLR_REGION1, 2, cv2.LINE_AA)

            # ── Region2 outline (semi-transparent fill) ──
            if r2 is not None and len(r2) >= 3:
                r2_scaled = scale_pts(r2)
                overlay = out.copy()
                cnt = r2_scaled.reshape(-1, 1, 2)
                cv2.fillPoly(overlay, [cnt], self.CLR_REGION2)
                cv2.addWeighted(overlay, 0.15, out, 0.85, 0, out)
                cv2.polylines(out, [cnt], True, self.CLR_REGION2, 2, cv2.LINE_AA)

            # ── Fence line ──
            if fl is not None and len(fl) >= 2:
                pts_arr = scale_pts(fl)
                cv2.polylines(out, [pts_arr], False, self.CLR_FENCE, 3, cv2.LINE_AA)
                for pt in pts_arr:
                    cv2.circle(out, tuple(pt), 4, self.CLR_FENCE, -1)




        # ── Draw detection bboxes ──
        if show_bbox:
            with shared_detections_lock:
                bboxes = list(shared_detections.get(camera_id, []))
                det_res = shared_det_resolution.get(camera_id)
                # Also try matching by RTSP IP
                if not bboxes and stream_mgr is not None:
                    reader = stream_mgr.get(camera_id)
                    if reader is not None:
                        cam_ip = _extract_ip_from_rtsp(reader.rtsp_url)
                        if cam_ip:
                            for key, val in shared_detections.items():
                                if val:
                                    other = stream_mgr.get(key)
                                    if other is not None and _extract_ip_from_rtsp(other.rtsp_url) == cam_ip:
                                        bboxes = list(val)
                                        det_res = shared_det_resolution.get(key)
                                        break

            # Scale factor: detection resolution → display resolution
            bsx = bsy = 1.0
            if det_res is not None:
                det_w, det_h = det_res
                if det_w > 0 and det_h > 0:
                    bsx = float(iw) / float(det_w)
                    bsy = float(ih) / float(det_h)

            for det in bboxes:
                if len(det) >= 4:
                    x1 = int(det[0] * bsx)
                    y1 = int(det[1] * bsy)
                    x2 = int(det[2] * bsx)
                    y2 = int(det[3] * bsy)
                    conf = det[4] if len(det) > 4 else 0.0
                    cv2.rectangle(out, (x1, y1), (x2, y2), self.CLR_BBOX, 2, cv2.LINE_AA)
                    label = f"person {conf:.0%}" if conf > 0 else "person"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                    cv2.rectangle(out, (x1, y1 - th - 6), (x1 + tw + 4, y1), self.CLR_BBOX, -1)
                    cv2.putText(out, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

        return out


# File to persist HOME preset states across restarts
HOME_STATES_FILE = Path(__file__).resolve().parent / "ptz_home.json"
SET_HOME_PASSWORD = "hanet123"


def _load_home_states_from_file() -> dict[str, dict[str, int | bool]]:
    """Load persisted HOME states from ptz_home.json."""
    if not HOME_STATES_FILE.exists():
        return {}
    try:
        data = json.loads(HOME_STATES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_home_states_to_file(states: dict[str, dict[str, int | bool]]) -> None:
    """Persist HOME states to ptz_home.json."""
    try:
        HOME_STATES_FILE.write_text(
            json.dumps(states, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


class PtzManager:
    def __init__(self):
        self.clients: dict[str, MTRPCClient] = {}
        self.client_last_active: dict[str, float] = {}
        self.home_states: dict[str, dict[str, int | bool]] = _load_home_states_from_file()
        self.lock = threading.Lock()
        self.session_ttl_seconds = 20.0

    @staticmethod
    def _default_home_state() -> dict[str, int | bool]:
        return {
            "home_set": False,
            "pan": 0,
            "tilt": 0,
            "zoom": 0,
            "home_pan": 0,
            "home_tilt": 0,
            "home_zoom": 0,
        }

    def _state_for(self, camera_id: str) -> dict[str, int | bool]:
        state = self.home_states.get(camera_id)
        if state is None:
            state = self._default_home_state()
            self.home_states[camera_id] = state
        return state

    def _state_payload(self, camera_id: str) -> dict[str, int | bool]:
        with self.lock:
            state = dict(self._state_for(camera_id))
        return state

    def _connect(
        self,
        camera_id: str,
        rtsp_url: str,
        ptz_port: int,
        force_reconnect: bool = False,
    ) -> MTRPCClient:
        host, username, password = _parse_rtsp_auth(rtsp_url)
        if not host:
            raise RuntimeError("Invalid RTSP URL: missing host")
        with self.lock:
            existing = self.clients.get(camera_id)
            should_refresh = False
            if existing is not None and not force_reconnect:
                last_active = self.client_last_active.get(camera_id, 0.0)
                if time.monotonic() - last_active > self.session_ttl_seconds:
                    should_refresh = True
            if existing is not None and not force_reconnect and not should_refresh:
                return existing
            if existing is not None and force_reconnect:
                try:
                    existing.logout()
                except Exception:
                    pass
                self.clients.pop(camera_id, None)
            elif existing is not None and should_refresh:
                try:
                    existing.logout()
                except Exception:
                    pass
                self.clients.pop(camera_id, None)
            client = MTRPCClient(host=host, port=ptz_port)
            if not client.connect(username=username, password=password):
                raise RuntimeError(f"PTZ login failed for {camera_id}@{host}:{ptz_port}")
            self.clients[camera_id] = client
            self.client_last_active[camera_id] = time.monotonic()
            return client

    def refresh_session(self, camera_id: str, rtsp_url: str, ptz_port: int = 80) -> bool:
        try:
            self._connect(camera_id, rtsp_url, ptz_port, force_reconnect=True)
            return True
        except Exception:
            return False

    def _send_ptz_with_retry(
        self,
        camera_id: str,
        rtsp_url: str,
        ptz_port: int,
        *,
        cmd: str,
        operate: str,
        step: int,
        preset: int = 0,
        zoom: int = 0,
        preset_name: str = "",
    ) -> bool:
        client = self._connect(camera_id, rtsp_url, ptz_port)
        ok = self._send_ptz(
            client,
            cmd=cmd,
            operate=operate,
            step=step,
            preset=preset,
            zoom=zoom,
            preset_name=preset_name,
        )
        if ok:
            with self.lock:
                self.client_last_active[camera_id] = time.monotonic()
            return True

        # Session may have expired; reconnect and retry once.
        client = self._connect(camera_id, rtsp_url, ptz_port, force_reconnect=True)
        retried = self._send_ptz(
            client,
            cmd=cmd,
            operate=operate,
            step=step,
            preset=preset,
            zoom=zoom,
            preset_name=preset_name,
        )
        if retried:
            with self.lock:
                self.client_last_active[camera_id] = time.monotonic()
        return retried

    def _run_ptz_pulse(
        self,
        camera_id: str,
        rtsp_url: str,
        ptz_port: int,
        *,
        cmd: str,
        start_step: int,
        stop_step: int,
        zoom: int = 0,
        hold_s: float = 0.18,
    ) -> bool:
        ok_start = self._send_ptz_with_retry(
            camera_id,
            rtsp_url,
            ptz_port,
            cmd=cmd,
            operate="kOperateStart",
            step=start_step,
            zoom=zoom,
        )
        time.sleep(hold_s)
        ok_stop = self._send_ptz_with_retry(
            camera_id,
            rtsp_url,
            ptz_port,
            cmd=cmd,
            operate="kOperateStop",
            step=stop_step,
            zoom=zoom,
        )
        return ok_start and ok_stop

    @staticmethod
    def _send_ptz(
        client: MTRPCClient,
        cmd: str,
        operate: str,
        step: int,
        preset: int = 0,
        zoom: int = 0,
        preset_name: str = "",
    ) -> bool:
        data = {
            "cmd": cmd,
            "operate": operate,
            "channel": 0,
            "step": step,
            "preset": preset,
            "zoom": zoom,
            "patrol": 0,
            "position_3d": {"x": 0, "y": 0, "width": 0, "height": 0},
            "auto_scan": 0,
            "mode_path": 0,
            "preset_name": preset_name,
        }
        result = client._send_request("Control.DoPtz", {"data": data, "session_id": client.session_id})
        return result is not None

    def move_pulse(self, camera_id: str, rtsp_url: str, direction: str, ptz_port: int) -> bool:
        if direction == "home":
            return self.goto_home_preset(camera_id, rtsp_url, ptz_port, preset=255)

        cmd_map = {
            "up": "kCmdUp",
            "down": "kCmdDown",
            "left": "kCmdLeft",
            "right": "kCmdRight",
        }
        cmd = cmd_map.get(direction)
        if cmd is None:
            raise RuntimeError(f"Unsupported PTZ direction: {direction}")
        ok_pulse = self._run_ptz_pulse(
            camera_id,
            rtsp_url,
            ptz_port,
            cmd=cmd,
            start_step=5,
            stop_step=8,
            zoom=0,
            hold_s=0.18,
        )
        if ok_pulse:
            with self.lock:
                state = self._state_for(camera_id)
                if direction == "up":
                    state["tilt"] = int(state["tilt"]) + 1
                elif direction == "down":
                    state["tilt"] = int(state["tilt"]) - 1
                elif direction == "left":
                    state["pan"] = int(state["pan"]) - 1
                elif direction == "right":
                    state["pan"] = int(state["pan"]) + 1
        return ok_pulse

    def zoom_pulse(self, camera_id: str, rtsp_url: str, action: str, ptz_port: int) -> bool:
        cmd = "kCmdZoomTele" if action == "in" else "kCmdZoomWide" if action == "out" else None
        if cmd is None:
            raise RuntimeError(f"Unsupported zoom action: {action}")
        ok_pulse = self._run_ptz_pulse(
            camera_id,
            rtsp_url,
            ptz_port,
            cmd=cmd,
            start_step=8,
            stop_step=8,
            zoom=1,
            hold_s=0.2,
        )
        if ok_pulse:
            with self.lock:
                state = self._state_for(camera_id)
                state["zoom"] = int(state["zoom"]) + (1 if action == "in" else -1)
        return ok_pulse

    def goto_preset(self, camera_id: str, rtsp_url: str, preset: int, ptz_port: int) -> bool:
        ok = self._send_ptz_with_retry(
            camera_id,
            rtsp_url,
            ptz_port,
            cmd="kCmdGotoPreset",
            operate="kOperateStart",
            step=0,
            preset=max(0, int(preset)),
            zoom=0,
        )
        if ok and int(preset) == 255:
            with self.lock:
                state = self._state_for(camera_id)
                state["pan"] = 0
                state["tilt"] = 0
                state["zoom"] = 0
        return ok

    def set_home_preset(self, camera_id: str, rtsp_url: str, ptz_port: int, preset: int = 255) -> bool:
        ok = self._send_ptz_with_retry(
            camera_id,
            rtsp_url,
            ptz_port,
            cmd="kCmdSetPreset",
            operate="kOperateStart",
            step=0,
            preset=max(0, int(preset)),
            zoom=0,
            preset_name="HOME",
        )
        if ok:
            with self.lock:
                state = self._state_for(camera_id)
                state["home_set"] = True
                # Match GUI.py behavior: after Set HOME, step display resets to 0.
                state["pan"] = 0
                state["tilt"] = 0
                state["zoom"] = 0
                state["home_pan"] = 0
                state["home_tilt"] = 0
                state["home_zoom"] = 0
                # Persist HOME state to file so it survives service restarts
                _save_home_states_to_file(self.home_states)
        return ok

    def goto_home_preset(self, camera_id: str, rtsp_url: str, ptz_port: int, preset: int = 255) -> bool:
        with self.lock:
            state = self._state_for(camera_id)
            if not bool(state["home_set"]):
                return False
        ok = self._send_ptz_with_retry(
            camera_id,
            rtsp_url,
            ptz_port,
            cmd="kCmdGotoPreset",
            operate="kOperateStart",
            step=0,
            preset=max(0, int(preset)),
            zoom=0,
            preset_name="",
        )
        if ok:
            with self.lock:
                state = self._state_for(camera_id)
                state["pan"] = 0
                state["tilt"] = 0
                state["zoom"] = 0
        return ok

    def get_home_state(self, camera_id: str) -> dict[str, int | bool]:
        return self._state_payload(camera_id)


# ── AI Manager ──────────────────────────────────────────────────────────────

class AIManager:
    """Manages fence detection threads, PTZ patrol, and webhook dispatch."""

    def __init__(self) -> None:
        self._monitors: list = []  # IntrusionMonitor threads
        self._tracker = None  # PatrolTracker
        self._tracker_thread: threading.Thread | None = None
        self._ptz = None  # PTZController
        self._ptz_stream = None  # PTZStreamReader
        self._face = None  # FaceCapture
        self._webhook_dispatcher = None  # AsyncWebhookDispatcher
        self._yolo = None
        self._trigger_queue: Queue | None = None
        self._ptz_queue: Queue | None = None
        self._running = False
        self._ptz_det_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._running_cores: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def running_cores(self) -> list[str]:
        return list(self._running_cores)

    def start_fence(self, no_ptz: bool = False) -> dict:
        """Start fence detection monitors for all configured cameras."""
        with self._lock:
            if self._running:
                return {"ok": False, "message": "AI already running"}

            try:
                return self._start_fence_impl(no_ptz=no_ptz)
            except Exception as e:
                ai_logger.error("Failed to start fence: %s", e, exc_info=True)
                self._running = False
                return {"ok": False, "message": str(e)}

    def _start_fence_impl(self, no_ptz: bool) -> dict:
        from src.backend.core.config import RESULTS_DIR
        from src.backend.core.ai.yolo import resolve_model_path, path_for_ultralytics_load
        from src.backend.modules.fence.config import load_patrol_config
        from src.backend.modules.fence.geometry import build_cam_roi_refs
        from src.backend.modules.fence.monitor import IntrusionMonitor
        from src.backend.core.webhook import AsyncWebhookDispatcher, FENCE_INTRUSION_ALARM_CODE

        ai_logger.info(
            "╔══════════════════════════════════════╗\n"
            "║  FENCE DETECTION — STARTING          ║\n"
            "║  PTZ patrol: %-24s ║\n"
            "╚══════════════════════════════════════╝",
            "ENABLED" if not no_ptz else "DISABLED",
        )

        # Load config
        config = load_patrol_config(None)
        presets = config.get("presets", [])
        valid_presets = [
            p for p in presets
            if p.get("fixed_camera_url") and p.get("enabled", True) is not False
        ]
        ai_logger.info("Presets: %d total, %d valid (have URL + enabled)", len(presets), len(valid_presets))

        if not valid_presets:
            return {"ok": False, "message": "No presets with camera URLs configured"}

        # Load YOLO model
        if self._yolo is None:
            ai_logger.info("Loading YOLO model...")
            # Check for hardcoded model_path in system.yaml
            model_cfg = config.get("model", {})
            cfg_model_path = model_cfg.get("model_path", "")
            if cfg_model_path:
                from src.backend.core.config import PROJECT_ROOT
                user_path = Path(cfg_model_path)
                if not user_path.is_absolute():
                    user_path = PROJECT_ROOT / user_path
                model_path = resolve_model_path(user_path)
            else:
                model_path = resolve_model_path(None)
            load_path = path_for_ultralytics_load(model_path)
            from ultralytics import YOLO
            self._yolo = YOLO(str(load_path))
            ai_logger.info("YOLO model loaded: %s", load_path)

        # Detection config
        det_cfg = config.get("detection", {})
        conf = det_cfg.get("confidence_threshold", 0.5)
        device = det_cfg.get("device", "0")
        imgsz = det_cfg.get("imgsz", 640)

        # ROI data
        cameras = config.get("_cameras", {})
        rtsp_list = [(cam_id, url) for cam_id, url in cameras.items()]
        polygon_yaml = config.get("_polygon_yaml", Path("config/polygon.yaml"))
        configs_yaml = config.get("_configs_yaml", Path("src/backend/api/configs.yaml"))
        roi_by_cam = build_cam_roi_refs(rtsp_list, polygon_yaml, configs_yaml)

        results_dir = config.get("_results_dir", RESULTS_DIR)
        patrol_cfg = config.get("patrol", {})
        cooldown = patrol_cfg.get("cooldown", 10.0)

        # ── Webhook dispatcher ──
        self._webhook_dispatcher = AsyncWebhookDispatcher()
        ai_logger.info("Webhook dispatcher started")

        # Shared trigger queue → EventBridge
        self._trigger_queue = Queue()
        event_bridge.set_trigger_queue(self._trigger_queue)

        # ── PTZ setup (if enabled) ──
        ptz_enabled = False
        if not no_ptz:
            try:
                from src.backend.modules.fence.ptz_control import PTZController
                from src.backend.modules.fence.tracker import PatrolTracker, PTZStreamReader, IntrusionEvent

                ptz_cfg = config.get("ptz_camera", {})
                ai_logger.info("[PTZ] Step 1: Connecting PTZ %s:%s...",
                               ptz_cfg.get("ip"), ptz_cfg.get("port"))
                self._ptz = PTZController(
                    host=ptz_cfg.get("ip", "127.0.0.1"),
                    port=ptz_cfg.get("port", 80),
                    username=ptz_cfg.get("username", "admin"),
                    password=ptz_cfg.get("password", ""),
                )

                if self._ptz.connect():
                    ai_logger.info("[PTZ] Step 1 OK: PTZ connected")

                    # ── Auto-home on startup ──
                    ai_logger.info("[PTZ] 🏠 Về Home position (preset 255) khi khởi động...")
                    try:
                        self._ptz.goto_preset(255)
                        ai_logger.info("[PTZ] 🏠 Home OK")
                    except Exception as _he:
                        ai_logger.warning("[PTZ] Về Home thất bại: %s", _he)

                    # PTZ stream
                    ai_logger.info("[PTZ] Step 2: Opening PTZ stream...")
                    ptz_rtsp = ptz_cfg.get("rtsp_url", "")
                    self._ptz_stream = PTZStreamReader(ptz_rtsp)
                    if ptz_rtsp:
                        self._ptz_stream.open()
                    ai_logger.info("[PTZ] Step 2 OK: Stream opened")

                    # Face capture (optional — InsightFace may not be installed)
                    ai_logger.info("[PTZ] Step 3: FaceCapture init (optional)...")
                    try:
                        from src.backend.modules.fence.face_capture import FaceCapture
                        face_cfg = config.get("face_recognition", {})
                        self._face = FaceCapture(
                            save_dir=face_cfg.get("save_dir", "results/captures"),
                            min_face_size=face_cfg.get("min_face_size", 50),
                        )
                        if not self._face.initialize():
                            ai_logger.warning("[PTZ] InsightFace failed — face capture disabled")
                            self._face = None
                    except Exception as fc_err:
                        ai_logger.warning("[PTZ] FaceCapture error: %s — disabled", fc_err)
                        self._face = None

                    # PTZ trigger queue (EventBridge will forward triggers)
                    self._ptz_queue = Queue()
                    event_bridge.set_ptz_queue(self._ptz_queue)

                    # Intrusion event callback
                    def on_intrusion(event: IntrusionEvent) -> None:
                        ai_logger.info(
                            "[INTRUSION] Preset %d (%s): %d person(s), %d face(s), %.0fms",
                            event.preset_id, event.preset_name,
                            event.total_persons, len(event.face_captures),
                            event.duration_ms,
                        )

                    # Patrol tracker
                    ai_logger.info("[PTZ] Step 4: Creating PatrolTracker...")
                    zoom_cfg = config.get("zoom_track", {})
                    ptz_cfg = config.get("ptz_camera", {})
                    self._tracker = PatrolTracker(
                        ptz=self._ptz,
                        model=self._yolo,
                        stream=self._ptz_stream,
                        face=self._face,  # Can be None if InsightFace unavailable
                        trigger_queue=self._ptz_queue,
                        presets=valid_presets,
                        target_bbox_ratio=zoom_cfg.get("target_bbox_ratio", 0.6),
                        max_zoom_steps=zoom_cfg.get("max_zoom_steps", 25),
                        zoom_step=zoom_cfg.get("zoom_step", 8),
                        zoom_duration=zoom_cfg.get("zoom_duration", 0.5),
                        center_tolerance=zoom_cfg.get("center_tolerance", 0.12),
                        disable_tracking=zoom_cfg.get("disable_tracking", False),
                        conf=conf,
                        device=device,
                        imgsz=imgsz,
                        on_intrusion=on_intrusion,
                        webhook_dispatcher=self._webhook_dispatcher,
                        ptz_device_name=ptz_cfg.get("device_name", ""),
                    )

                    # Run tracker in background thread
                    self._tracker_thread = threading.Thread(
                        target=self._tracker.run,
                        daemon=True,
                        name="PatrolTracker",
                    )
                    self._tracker_thread.start()
                    ptz_enabled = True
                    ai_logger.info("[PTZ] Step 4 OK: PatrolTracker running")
                else:
                    ai_logger.warning("[PTZ] Connection failed — running without PTZ")
            except Exception as e:
                ai_logger.error("[PTZ] Setup failed: %s — running without PTZ", e, exc_info=True)

        event_bridge.start()

        # ── Start monitors ──
        self._monitors = []
        region2_schedule = config.get("region2_schedule")
        for preset in valid_presets:
            cam_id = preset.get("fixed_camera_id", "")
            roi = roi_by_cam.get(cam_id)

            monitor = IntrusionMonitor(
                preset=preset,
                model=self._yolo,
                trigger_queue=self._trigger_queue,
                roi=roi,
                cooldown=cooldown,
                conf=conf,
                device=device,
                imgsz=imgsz,
                results_dir=results_dir,
                webhook_dispatcher=self._webhook_dispatcher,
                region2_schedule=region2_schedule,
            )
            self._monitors.append(monitor)
            monitor.start()
            ai_logger.info(
                "Monitor started: Preset %d (%s) → %s",
                preset["id"], preset.get("name", ""), cam_id,
            )

        self._running = True
        self._running_cores = ["fenceClimb"]

        # ── PTZ continuous detection (overlay only) ──
        if ptz_enabled:
            ptz_rtsp = ptz_cfg.get("rtsp_url", "")
            if ptz_rtsp:
                self._ptz_det_thread = threading.Thread(
                    target=self._ptz_detect_loop,
                    args=(ptz_rtsp, conf, device, imgsz),
                    daemon=True,
                    name="PTZ-Detect",
                )
                self._ptz_det_thread.start()
                ai_logger.info("PTZ continuous detection started")

        return {
            "ok": True,
            "message": f"Fence detection started on {len(self._monitors)} camera(s)"
                       + (" + PTZ patrol" if ptz_enabled else " (no PTZ)"),
            "monitors": len(self._monitors),
            "ptz": ptz_enabled,
            "running": self._running_cores,
        }

    def stop_fence(self) -> dict:
        """Stop all fence detection monitors, PTZ tracker, and webhook."""
        with self._lock:
            if not self._running:
                return {"ok": False, "message": "AI not running"}

            # Stop monitors
            for m in self._monitors:
                m.stop()
            self._monitors.clear()

            # Stop PTZ tracker
            if self._tracker is not None:
                self._tracker.stop()
                if self._tracker_thread and self._tracker_thread.is_alive():
                    self._tracker_thread.join(timeout=3.0)
                self._tracker = None
                self._tracker_thread = None

            # Release PTZ resources
            if self._ptz_stream is not None:
                self._ptz_stream.release()
                self._ptz_stream = None
            if self._ptz is not None:
                self._ptz.disconnect()
                self._ptz = None
            self._face = None

            # Stop webhook dispatcher
            if self._webhook_dispatcher is not None:
                self._webhook_dispatcher.stop(timeout=3.0)
                self._webhook_dispatcher = None

            # Stop event bridge
            event_bridge.set_ptz_queue(None)
            event_bridge.stop()

            self._running = False
            self._running_cores.clear()

            ai_logger.info("Fence detection stopped (monitors + PTZ + webhook)")
            return {"ok": True, "message": "Fence detection stopped"}

    def _ptz_detect_loop(
        self, ptz_rtsp: str, conf: float, device: str, imgsz: int
    ) -> None:
        """Continuously run YOLO on PTZ stream frames from UI StreamReader."""
        cam_id = "ptz"
        ai_logger.info("[PTZ-Detect] Starting — will reuse UI stream for '%s'", cam_id)
        detect_count = 0

        try:
            while self._running:
                # Grab latest frame from the UI StreamReader (no extra RTSP open)
                reader = manager.get(cam_id)
                if reader is None:
                    # Auto-start PTZ stream if not already showing on UI
                    ai_logger.info("[PTZ-Detect] PTZ stream not open, starting reader...")
                    try:
                        manager.start(cam_id, ptz_rtsp)
                    except Exception as e:
                        ai_logger.error("[PTZ-Detect] Cannot start stream: %s", e)
                        time.sleep(5.0)
                        continue
                    time.sleep(2.0)
                    continue

                with reader.lock:
                    frame = reader.latest_frame

                if frame is None:
                    time.sleep(0.2)
                    continue

                frame = frame.copy()
                ih, iw = frame.shape[:2]

                # Run YOLO — catch errors so thread survives
                try:
                    results = self._yolo(
                        frame,
                        conf=conf,
                        device=device,
                        imgsz=imgsz,
                        verbose=False,
                    )
                    res = results[0] if results else None
                except Exception as e:
                    ai_logger.warning("[PTZ-Detect] YOLO error (skipping frame): %s", e)
                    time.sleep(1.0)
                    continue

                # Publish bboxes to shared_detections for overlay
                detections: list[list[float]] = []
                if res is not None and hasattr(res, "boxes") and res.boxes is not None:
                    for i in range(len(res.boxes)):
                        cls_id = int(res.boxes.cls[i].item())
                        if cls_id != 0:
                            continue
                        x1, y1, x2, y2 = res.boxes.xyxy[i].tolist()
                        c = float(res.boxes.conf[i].item())
                        detections.append([x1, y1, x2, y2, c, float(cls_id)])

                with shared_detections_lock:
                    shared_detections[cam_id] = detections
                    shared_det_resolution[cam_id] = (iw, ih)

                detect_count += 1
                if detect_count == 1:
                    ai_logger.info("[PTZ-Detect] ✅ First detection published! %d persons", len(detections))
                elif detect_count % 200 == 0:
                    ai_logger.info("[PTZ-Detect] %d frames processed", detect_count)

                time.sleep(0.1)  # ~10 FPS detect

        except Exception as e:
            ai_logger.error("[PTZ-Detect] Fatal error: %s", e, exc_info=True)
        finally:
            with shared_detections_lock:
                shared_detections.pop(cam_id, None)
                shared_det_resolution.pop(cam_id, None)
            ai_logger.info("[PTZ-Detect] Stopped (processed %d frames)", detect_count)

    def status(self) -> dict:
        tracker_info = None
        if self._tracker is not None:
            tracker_info = {
                "state": self._tracker.state.value if hasattr(self._tracker, 'state') else "unknown",
                "is_running": self._tracker.is_running if hasattr(self._tracker, 'is_running') else False,
                "manual_override": self._tracker.is_manual_override if hasattr(self._tracker, 'is_manual_override') else False,
            }
        return {
            "running": self._running,
            "cores": self._running_cores,
            "monitors": len(self._monitors),
            "ws_clients": event_bridge.client_count,
            "tracker": tracker_info,
            "tracker_thread_alive": (
                self._tracker_thread is not None
                and self._tracker_thread.is_alive()
            ),
            "trigger_queue_size": self._trigger_queue.qsize() if self._trigger_queue else 0,
        }


# ── App setup ──────────────────────────────────────────────────────────────

app = FastAPI(title="UI RTSP Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = StreamManager()
ptz_manager = PtzManager()
ai_manager = AIManager()
overlay_manager = OverlayManager()
CONFIGS_FILE = Path(__file__).resolve().parent / "configs.yaml"
CONFIG_SECTION_MAP = {
    "treo-rao": "Treo_rao",
    "lan-chiem": "Lan_chiem_via_he",
    "do-xe": "Do_xe_trai_phep",
    "do-rac": "Do_rac_trai_phep",
}


def _image_size_meta(camera_cfg: dict) -> dict[str, int]:
    raw = camera_cfg.get("image_size")
    if isinstance(raw, dict):
        try:
            w = int(raw.get("width", 1920))
            h = int(raw.get("height", 1080))
            if w > 0 and h > 0:
                return {"width": w, "height": h}
        except (TypeError, ValueError):
            pass
    # YAML cũ không có image_size: polygon theo 640×360
    return {"width": 640, "height": 360}


def _load_polygon_configs() -> dict[str, dict[str, object]]:
    configs: dict[str, dict[str, object]] = {
        section: {"cameras": {}}
        for section in CONFIG_SECTION_MAP.values()
    }
    if not CONFIGS_FILE.exists():
        return configs

    try:
        raw = yaml.safe_load(CONFIGS_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return configs
    if not isinstance(raw, dict):
        return configs

    for section in CONFIG_SECTION_MAP.values():
        section_raw = raw.get(section, {})
        cameras: dict[str, dict[str, object]] = {}

        if isinstance(section_raw, dict) and isinstance(section_raw.get("cameras"), dict):
            for camera_key, camera_cfg in section_raw["cameras"].items():
                if not isinstance(camera_cfg, dict):
                    continue
                polygon_raw = camera_cfg.get("polygon", [])
                polygon: list[list[int]] = []
                if isinstance(polygon_raw, list):
                    for point in polygon_raw:
                        if isinstance(point, list) and len(point) == 2:
                            try:
                                polygon.append([int(point[0]), int(point[1])])
                            except Exception:
                                continue
                camera_name = str(camera_cfg.get("camera_id", camera_key))
                cameras[str(camera_key)] = {
                    "camera_id": camera_name,
                    "rtsp_url": str(camera_cfg.get("rtsp_url", "") or ""),
                    "image_size": _image_size_meta(camera_cfg),
                    "polygon": polygon,
                    "updated_at": str(camera_cfg.get("updated_at", "")),
                }
        elif isinstance(section_raw, dict):
            # Backward compatibility: migrate previous single-camera format.
            legacy_camera = str(section_raw.get("camera_id", "")).strip()
            legacy_polygon = section_raw.get("polygon", [])
            if legacy_camera and isinstance(legacy_polygon, list):
                polygon: list[list[int]] = []
                for point in legacy_polygon:
                    if isinstance(point, list) and len(point) == 2:
                        try:
                            polygon.append([int(point[0]), int(point[1])])
                        except Exception:
                            continue
                cameras[legacy_camera] = {
                    "camera_id": legacy_camera,
                    "rtsp_url": str(
                        (section_raw if isinstance(section_raw, dict) else {}).get(
                            "rtsp_url",
                            "",
                        )
                        or ""
                    ),
                    "image_size": _image_size_meta(section_raw if isinstance(section_raw, dict) else {}),
                    "polygon": polygon,
                    "updated_at": str(section_raw.get("updated_at", "")),
                }

        configs[section] = {"cameras": cameras}
    return configs


def _write_polygon_configs(configs: dict[str, dict[str, object]]) -> None:
    payload: dict[str, object] = {}
    for section in CONFIG_SECTION_MAP.values():
        section_cfg = configs.get(section, {})
        cameras = section_cfg.get("cameras", {}) if isinstance(section_cfg, dict) else {}
        payload[section] = {"cameras": cameras if isinstance(cameras, dict) else {}}

    CONFIGS_FILE.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


@app.post("/api/streams/show")
def show_stream(payload: ShowRequest, request: Request):
    try:
        # Use display_url (sub-stream) if configured, for lower bandwidth UI display
        from src.backend.core.config import load_display_urls_from_settings
        display_urls = load_display_urls_from_settings()
        stream_url = display_urls.get(payload.cameraId, payload.rtspUrl)
        ai_logger.info("Stream %s: using %s", payload.cameraId,
                       "display_url (sub)" if stream_url != payload.rtspUrl else "rtsp_url (main)")
        manager.start(payload.cameraId, stream_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    # UX fix: when user presses Show again on PTZ tab, proactively refresh PTZ session
    # so controls continue to work without requiring browser refresh.
    is_likely_ptz = payload.cameraId.lower() == "ptz" or payload.cameraId in ptz_manager.clients
    if is_likely_ptz:
        ptz_manager.refresh_session(payload.cameraId, payload.rtspUrl, 80)

    base = _safe_public_base_url(request)
    return {
        "cameraId": payload.cameraId,
        "streamUrl": f"{base}/api/streams/{payload.cameraId}/mjpeg",
        "startedAt": datetime.utcnow().isoformat() + "Z",
        "mode": "rtsp",
    }


@app.post("/api/streams/stop/{camera_id}")
def stop_stream(camera_id: str):
    manager.stop(camera_id)
    return {"ok": True}


@app.post("/api/ptz/move")
def ptz_move(payload: PtzRequest):
    try:
        # Pause patrol tracker during manual control
        if ai_manager._tracker is not None:
            ai_manager._tracker.pause_for_manual()
        ok = ptz_manager.move_pulse(payload.cameraId, payload.rtspUrl, payload.direction, payload.ptzPort)
        if not ok:
            raise RuntimeError("PTZ move request failed")
        return {"ok": True, "homeState": ptz_manager.get_home_state(payload.cameraId)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/ptz/zoom")
def ptz_zoom(payload: PtzZoomRequest):
    try:
        if ai_manager._tracker is not None:
            ai_manager._tracker.pause_for_manual()
        ok = ptz_manager.zoom_pulse(payload.cameraId, payload.rtspUrl, payload.action, payload.ptzPort)
        if not ok:
            raise RuntimeError("PTZ zoom request failed")
        return {"ok": True, "homeState": ptz_manager.get_home_state(payload.cameraId)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/ptz/preset")
def ptz_preset(payload: PtzPresetRequest):
    try:
        if ai_manager._tracker is not None:
            ai_manager._tracker.pause_for_manual()
        ok = ptz_manager.goto_preset(payload.cameraId, payload.rtspUrl, payload.preset, payload.ptzPort)
        if not ok:
            raise RuntimeError("PTZ preset request failed")
        return {"ok": True, "homeState": ptz_manager.get_home_state(payload.cameraId)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/ptz/set_home")
def ptz_set_home(payload: PtzHomeRequest):
    # Password required to set HOME preset
    if not payload.password or payload.password != SET_HOME_PASSWORD:
        raise HTTPException(status_code=403, detail="Sai mat khau. Vui long nhap dung mat khau de SET HOME.")
    try:
        ok = ptz_manager.set_home_preset(
            payload.cameraId,
            payload.rtspUrl,
            payload.ptzPort,
            preset=payload.preset,
        )
        if not ok:
            raise RuntimeError("PTZ set home request failed")
        return {"ok": True, "homeState": ptz_manager.get_home_state(payload.cameraId)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/ptz/goto_home")
def ptz_goto_home(payload: PtzHomeRequest):
    try:
        ok = ptz_manager.goto_home_preset(
            payload.cameraId,
            payload.rtspUrl,
            payload.ptzPort,
            preset=payload.preset,
        )
        if not ok:
            raise RuntimeError("PTZ goto home request failed")
        return {"ok": True, "homeState": ptz_manager.get_home_state(payload.cameraId)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/ptz/home/status")
def ptz_home_status(payload: PtzHomeRequest):
    try:
        return {"ok": True, "homeState": ptz_manager.get_home_state(payload.cameraId)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _normalize_polygon_to_ref(
    polygon: list[PolygonPoint], src_w: int, src_h: int, ref_w: int, ref_h: int
) -> list[list[int]]:
    """Scale polygon from client reference size to ref_w×ref_h (storage size)."""
    sx = ref_w / float(src_w)
    sy = ref_h / float(src_h)
    out: list[list[int]] = []
    for p in polygon:
        x = int(round(p.x * sx))
        y = int(round(p.y * sy))
        x = max(0, min(ref_w, x))
        y = max(0, min(ref_h, y))
        out.append([x, y])
    return out


@app.post("/api/configs/polygon")
def save_polygon_config(payload: TreoRaoConfigRequest):
    ref_w, ref_h = 1920, 1080
    # Chấp nhận 1920×1080 (UI mới) hoặc 640×360 (UI cũ / bundle cũ); luôn lưu 1920×1080.
    allowed = {
        (1920, 1080): (1920, 1080),
        (640, 360): (640, 360),
    }
    src_size = allowed.get((payload.width, payload.height))
    if src_size is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported reference size {payload.width}x{payload.height}; "
            f"use {ref_w}x{ref_h} or 640x360",
        )
    src_w, src_h = src_size
    normalized = _normalize_polygon_to_ref(payload.polygon, src_w, src_h, ref_w, ref_h)
    if len(normalized) < 3:
        raise HTTPException(status_code=400, detail="Polygon must contain at least 3 points")
    for x, y in normalized:
        if x < 0 or x > ref_w or y < 0 or y > ref_h:
            raise HTTPException(
                status_code=400,
                detail=f"Polygon points must be within {ref_w}x{ref_h}",
            )
    section_name = CONFIG_SECTION_MAP.get(payload.configKey)
    if section_name is None:
        raise HTTPException(status_code=400, detail=f"Unsupported config key: {payload.configKey}")

    camera_name = (payload.cameraName or "").strip()
    camera_config_id = camera_name if camera_name else payload.cameraId

    all_configs = _load_polygon_configs()
    section_configs = all_configs.setdefault(section_name, {"cameras": {}})
    cameras = section_configs.get("cameras")
    if not isinstance(cameras, dict):
        cameras = {}
        section_configs["cameras"] = cameras

    cameras[camera_config_id] = {
        "camera_id": camera_config_id,
        "rtsp_url": (payload.rtspUrl or "").strip(),
        "image_size": {"width": ref_w, "height": ref_h},
        "polygon": normalized,
        "updated_at": f"{datetime.utcnow().isoformat()}Z",
    }
    _write_polygon_configs(all_configs)

    return {"ok": True, "path": str(CONFIGS_FILE), "section": section_name}


@app.get("/api/streams/{camera_id}/mjpeg")
def mjpeg(camera_id: str):
    reader = manager.get(camera_id)
    if reader is None:
        raise HTTPException(status_code=404, detail="Stream not active")

    def frame_generator():
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        while True:
            live_reader = manager.get(camera_id)
            if live_reader is None:
                break
            jpeg = live_reader.get_jpeg(overlay_manager=overlay_manager, stream_mgr=manager)
            if jpeg is None:
                time.sleep(0.05)
                continue
            yield boundary + jpeg + b"\r\n"
            time.sleep(0.1)  # ~10 FPS to avoid OOM on Jetson

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ── Overlay Endpoints ──────────────────────────────────────────────────────

class OverlayToggleRequest(BaseModel):
    cameraId: str
    showRegion: bool | None = None
    showBbox: bool | None = None


@app.post("/api/overlay/toggle")
def overlay_toggle(payload: OverlayToggleRequest):
    state = overlay_manager.set_state(
        payload.cameraId,
        show_region=payload.showRegion,
        show_bbox=payload.showBbox,
    )
    return {"ok": True, **state}


@app.get("/api/overlay/status/{camera_id}")
def overlay_status(camera_id: str):
    return overlay_manager.get_state(camera_id)


@app.post("/api/overlay/reload")
def overlay_reload():
    """Reload polygon.yaml from disk (after editing regions)."""
    n = overlay_manager.reload_polygon()
    return {"ok": True, "message": f"Reloaded polygon.yaml ({n} cameras)"}


# ── Region2 Polygon Drawing API ────────────────────────────────────────────

@app.get("/api/polygon/{camera_id}/snapshot")
def polygon_snapshot(camera_id: str):
    """Return a JPEG snapshot of the camera for polygon drawing background."""
    reader = manager.get(camera_id)
    if reader is None:
        raise HTTPException(status_code=404, detail="Stream not active — open camera first")
    with reader.lock:
        frame = None if reader.latest_frame is None else reader.latest_frame.copy()
    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available yet")
    # Full-res snapshot (no resize)
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise HTTPException(status_code=500, detail="JPEG encode failed")
    return Response(content=encoded.tobytes(), media_type="image/jpeg")


@app.get("/api/polygon/{camera_id}/region2")
def polygon_get_region2(camera_id: str):
    """Get existing region2 polygon for a camera."""
    data = overlay_manager._load_polygon_yaml()
    cams = data.get("cameras", {})
    node = cams.get(camera_id, {})
    if not isinstance(node, dict):
        return {"points": [], "resolution": {"width": 1920, "height": 1080}}
    regions = node.get("regions", {})
    r2_raw = regions.get("region2", [])
    pts = []
    if isinstance(r2_raw, list):
        for p in r2_raw:
            if isinstance(p, list) and len(p) == 2:
                pts.append([int(p[0]), int(p[1])])
    res = node.get("resolution", {})
    return {
        "points": pts,
        "resolution": {
            "width": int(res.get("width", 1920)) if isinstance(res, dict) else 1920,
            "height": int(res.get("height", 1080)) if isinstance(res, dict) else 1080,
        },
    }


class Region2SaveRequest(BaseModel):
    points: list[list[int]]  # [[x, y], ...]
    resolution: dict | None = None  # {"width": int, "height": int} — resolution ảnh khi vẽ polygon


@app.post("/api/polygon/{camera_id}/region2")
def polygon_save_region2(camera_id: str, payload: Region2SaveRequest):
    """Save region2 polygon for a camera to polygon.yaml.
    
    Lưu kèm resolution để đảm bảo polygon có thể scale đúng khi frame size thay đổi.
    """
    if len(payload.points) < 3:
        raise HTTPException(status_code=400, detail="Region2 needs at least 3 points")

    polygon_path = Path(__file__).resolve().parents[1] / "config" / "polygon.yaml"
    if not polygon_path.exists():
        raise HTTPException(status_code=404, detail="polygon.yaml not found")

    data = yaml.safe_load(polygon_path.read_text(encoding="utf-8")) or {}
    cameras = data.setdefault("cameras", {})
    cam = cameras.setdefault(camera_id, {})
    regions = cam.setdefault("regions", {})
    regions["region2"] = [[p[0], p[1]] for p in payload.points]
    cam["updated_at"] = datetime.utcnow().isoformat()

    # Cập nhật resolution nếu frontend gửi kèm (để đảm bảo scale đúng)
    if payload.resolution and isinstance(payload.resolution, dict):
        ref_w = int(payload.resolution.get("width", 0) or 0)
        ref_h = int(payload.resolution.get("height", 0) or 0)
        if ref_w > 0 and ref_h > 0:
            # Chỉ cập nhật resolution nếu chưa có hoặc khác với giá trị đang lưu
            existing_res = cam.get("resolution", {})
            existing_w = int(existing_res.get("width", 0)) if isinstance(existing_res, dict) else 0
            existing_h = int(existing_res.get("height", 0)) if isinstance(existing_res, dict) else 0
            if existing_w != ref_w or existing_h != ref_h:
                cam["resolution"] = {"width": ref_w, "height": ref_h}
                logging.getLogger(__name__).info(
                    "polygon_save_region2: updated resolution for %s → %dx%d",
                    camera_id, ref_w, ref_h,
                )
    else:
        # Fallback: lấy resolution từ frame stream đang chạy
        reader = manager.get(camera_id)
        if reader is not None:
            with reader.lock:
                frame = reader.latest_frame
            if frame is not None:
                fh, fw = frame.shape[:2]
                existing_res = cam.get("resolution", {})
                existing_w = int(existing_res.get("width", 0)) if isinstance(existing_res, dict) else 0
                existing_h = int(existing_res.get("height", 0)) if isinstance(existing_res, dict) else 0
                if existing_w != fw or existing_h != fh:
                    cam["resolution"] = {"width": fw, "height": fh}
                    logging.getLogger(__name__).info(
                        "polygon_save_region2: auto-detected resolution for %s → %dx%d",
                        camera_id, fw, fh,
                    )

    polygon_path.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Auto-reload overlay
    overlay_manager.reload_polygon()

    return {
        "ok": True,
        "message": f"Region2 saved for {camera_id} ({len(payload.points)} points)",
        "points": len(payload.points),
    }



# ── AI Feature Schedule API (per-feature time ranges) ──────────────────────

CONFIGS_YAML = _BACKEND_DIR / "configs.yaml"

AI_FEATURES = {
    "Treo_rao":          "Trèo rào",
    "Lan_chiem_via_he":  "Lấn chiếm via hè",
    "Do_xe_trai_phep":   "Đổ xe trái phép",
    "Do_rac_trai_phep":  "Đổ rác trái phép",
}

DEFAULT_SCHEDULE = "09:00 - 21:00"


def _load_configs() -> dict:
    if CONFIGS_YAML.exists():
        return yaml.safe_load(CONFIGS_YAML.read_text(encoding="utf-8")) or {}
    return {}


def _save_configs(data: dict):
    CONFIGS_YAML.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


@app.get("/api/ai-features/schedules")
def ai_features_schedules_get():
    """Get all AI feature schedules."""
    data = _load_configs()
    result = {}
    for key in AI_FEATURES:
        node = data.get(key, {})
        result[key] = {
            "label": AI_FEATURES[key],
            "schedule": node.get("schedule", DEFAULT_SCHEDULE),
        }
    return result


class FeatureScheduleRequest(BaseModel):
    schedule: str  # "HH:MM - HH:MM"


@app.post("/api/ai-features/{feature_key}/schedule")
def ai_feature_schedule_save(feature_key: str, payload: FeatureScheduleRequest):
    """Save schedule for a specific AI feature."""
    if feature_key not in AI_FEATURES:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature_key}")

    import re
    if not re.match(r"^\d{2}:\d{2}\s*-\s*\d{2}:\d{2}$", payload.schedule):
        raise HTTPException(status_code=400, detail="Invalid format. Use HH:MM - HH:MM")

    data = _load_configs()
    node = data.setdefault(feature_key, {})
    node["schedule"] = payload.schedule

    _save_configs(data)

    # ── Sync Treo_rao schedule → system.yaml (region2_schedule) ──
    if feature_key == "Treo_rao":
        import re as _re
        parts = _re.split(r"\s*-\s*", payload.schedule)
        if len(parts) == 2:
            system_yaml = ROOT_DIR / "src" / "config" / "system.yaml"
            if system_yaml.exists():
                text = system_yaml.read_text(encoding="utf-8")
                # Replace just the region2_schedule block (keep comments above)
                new_block = (
                    'region2_schedule:\n'
                    '  enabled: true\n'
                    '  time_ranges:\n'
                    f'    - start: "{parts[0]}"        # Bắt đầu ON region2\n'
                    f'      end: "{parts[1]}"          # Kết thúc\n'
                )
                text = _re.sub(
                    r'region2_schedule:\s*\n(?:  .+\n)*',
                    new_block,
                    text,
                )
                system_yaml.write_text(text, encoding="utf-8")
                print(f"[rtsp_api] Synced region2_schedule → system.yaml: {payload.schedule}")

    label = AI_FEATURES[feature_key]
    return {
        "ok": True,
        "message": f"{label}: {payload.schedule}",
    }


# ── AI Detection Endpoints ─────────────────────────────────────────────────

class AIStartRequest(BaseModel):
    cores: list[str] = ["fenceClimb"]
    noPtz: bool = False


@app.post("/api/ai/start")
def ai_start(payload: AIStartRequest):
    if "fenceClimb" not in payload.cores:
        raise HTTPException(status_code=400, detail="Only fenceClimb core is supported")
    result = ai_manager.start_fence(no_ptz=payload.noPtz)
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.post("/api/ai/stop")
def ai_stop():
    result = ai_manager.stop_fence()
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.get("/api/ai/status")
def ai_status():
    return ai_manager.status()


@app.get("/api/ai/debug/detections")
def ai_debug_detections():
    """Debug endpoint: show what's in shared_detections."""
    with shared_detections_lock:
        det_keys = list(shared_detections.keys())
        det_counts = {k: len(v) for k, v in shared_detections.items()}
        det_res = dict(shared_det_resolution)
    stream_keys = list(manager.readers.keys())
    return {
        "shared_detections_keys": det_keys,
        "detection_counts": det_counts,
        "detection_resolutions": det_res,
        "active_streams": stream_keys,
        "ptz_det_thread_alive": (
            ai_manager._ptz_det_thread is not None
            and ai_manager._ptz_det_thread.is_alive()
        ),
    }

# ── WebSocket Events ───────────────────────────────────────────────────────

@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()

    # Set event loop for bridge broadcasting
    loop = asyncio.get_event_loop()
    event_bridge.set_event_loop(loop)

    await event_bridge.register(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        event_bridge.unregister(websocket)


# ── Event Image Serving ────────────────────────────────────────────────────

EVENT_IMAGE_DIR = ROOT_DIR / "Hiep" / "results" / "event"


@app.get("/api/events/{camera_id}/latest")
def get_latest_event_image(camera_id: str):
    cam_dir = EVENT_IMAGE_DIR / camera_id
    if not cam_dir.exists():
        raise HTTPException(status_code=404, detail="No events for this camera")

    # Find the latest .jpg file
    images = sorted(cam_dir.glob("*.jpg"), reverse=True)
    if not images:
        raise HTTPException(status_code=404, detail="No event images found")

    return FileResponse(str(images[0]), media_type="image/jpeg")


# ── Auto-Start Configuration ───────────────────────────────────────────────

AUTOSTART_YAML = ROOT_DIR / "src" / "config" / "autostart.yaml"


def _load_autostart_config() -> dict:
    """Load autostart.yaml from disk."""
    if not AUTOSTART_YAML.exists():
        return {}
    try:
        return yaml.safe_load(AUTOSTART_YAML.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_autostart_config(data: dict) -> None:
    """Save autostart.yaml to disk."""
    AUTOSTART_YAML.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


class AutostartToggleRequest(BaseModel):
    core: str              # e.g. "fenceClimb"
    enabled: bool
    noPtz: bool | None = None
    delay: int | None = None


@app.get("/api/autostart")
def autostart_get():
    """Get current autostart configuration."""
    data = _load_autostart_config()
    cores = data.get("ai_cores", {})
    result = {}
    for key, cfg in cores.items():
        if isinstance(cfg, dict):
            result[key] = {
                "enabled": bool(cfg.get("enabled", False)),
                "no_ptz": bool(cfg.get("no_ptz", False)),
                "delay": int(cfg.get("delay", 10)),
            }
    return {"ai_cores": result}


@app.post("/api/autostart")
def autostart_save(payload: AutostartToggleRequest):
    """Toggle autostart for a specific AI core."""
    data = _load_autostart_config()
    cores = data.setdefault("ai_cores", {})
    core_cfg = cores.setdefault(payload.core, {})
    core_cfg["enabled"] = payload.enabled
    if payload.noPtz is not None:
        core_cfg["no_ptz"] = payload.noPtz
    if payload.delay is not None:
        core_cfg["delay"] = payload.delay
    _save_autostart_config(data)
    return {
        "ok": True,
        "message": f"Autostart {'ON' if payload.enabled else 'OFF'} for {payload.core}",
        "config": core_cfg,
    }


def _autostart_ai_cores() -> None:
    """Background thread: read autostart.yaml and start configured AI cores."""
    data = _load_autostart_config()
    cores = data.get("ai_cores", {})
    if not cores:
        ai_logger.info("[Autostart] No AI cores configured for auto-start")
        return

    for core_key, cfg in cores.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", False):
            ai_logger.info("[Autostart] %s: disabled — skipping", core_key)
            continue

        delay_sec = int(cfg.get("delay", 10))
        no_ptz = bool(cfg.get("no_ptz", False))

        ai_logger.info(
            "[Autostart] %s: enabled (delay=%ds, no_ptz=%s) — waiting...",
            core_key, delay_sec, no_ptz,
        )
        time.sleep(delay_sec)

        if core_key == "fenceClimb":
            if ai_manager.is_running:
                ai_logger.info("[Autostart] %s: AI already running — skipping", core_key)
                continue
            ai_logger.info("[Autostart] %s: Starting fence detection...", core_key)
            result = ai_manager.start_fence(no_ptz=no_ptz)
            if result.get("ok"):
                ai_logger.info(
                    "[Autostart] %s: ✅ Started — %s",
                    core_key, result.get("message", ""),
                )
            else:
                ai_logger.error(
                    "[Autostart] %s: ❌ Failed — %s",
                    core_key, result.get("message", ""),
                )
        else:
            ai_logger.warning("[Autostart] %s: unknown core — skipping", core_key)


@app.on_event("startup")
async def on_startup():
    # Set event loop for bridge
    loop = asyncio.get_event_loop()
    event_bridge.set_event_loop(loop)

    # Auto-start AI cores in background thread (non-blocking)
    autostart_thread = threading.Thread(
        target=_autostart_ai_cores,
        daemon=True,
        name="AI-Autostart",
    )
    autostart_thread.start()
    ai_logger.info("[Autostart] Background auto-start thread launched")


@app.on_event("shutdown")
def on_shutdown():
    manager.shutdown()
    ai_manager.stop_fence()
