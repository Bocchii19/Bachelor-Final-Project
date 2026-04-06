"""
PTZ Camera Controller — ONVIF + RTSP integration.

Communicates with PTZ cameras via ONVIF protocol for movement control
and RTSP for frame capture. Supports both IP cameras and USB cameras.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class PTZController:
    """
    PTZ camera controller using ONVIF for pan/tilt/zoom
    and RTSP for video stream capture.
    """

    _instance: Optional["PTZController"] = None

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        rtsp_url: Optional[str] = None,
    ):
        self._host = host or settings.PTZ_HOST
        self._port = port or settings.PTZ_PORT
        self._user = user or settings.PTZ_USER
        self._password = password or settings.PTZ_PASSWORD
        self._rtsp_url = rtsp_url or settings.PTZ_RTSP_URL

        self._onvif_camera = None
        self._ptz_service = None
        self._media_service = None
        self._profile_token: Optional[str] = None
        self._cap: Optional[cv2.VideoCapture] = None

        # GStreamer native pipeline state
        self._gst_pipeline = None
        self._appsink = None
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_width: int = 960
        self._frame_height: int = 540
        self._frame_lock = __import__('threading').Lock()

    @classmethod
    def get_instance(cls) -> "PTZController":
        """Singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_onvif(self) -> None:
        """Initialize ONVIF connection if not already done."""
        if self._onvif_camera is not None:
            return

        try:
            from onvif import ONVIFCamera

            self._onvif_camera = ONVIFCamera(
                self._host,
                self._port,
                self._user,
                self._password,
            )

            # Get services
            self._media_service = self._onvif_camera.create_media_service()
            self._ptz_service = self._onvif_camera.create_ptz_service()

            # Get first profile token
            profiles = self._media_service.GetProfiles()
            if profiles:
                self._profile_token = profiles[0].token
                logger.info(
                    "ONVIF connected to %s:%s, profile=%s",
                    self._host,
                    self._port,
                    self._profile_token,
                )
            else:
                logger.warning("No media profiles found on camera")

        except Exception as e:
            logger.error("ONVIF connection failed: %s", e)
            raise

    def _on_new_sample(self, appsink):
        """Callback when a new frame arrives from appsink (same as GUI.py)."""
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst

        try:
            sample = appsink.emit('pull-sample')
            if sample:
                buf = sample.get_buffer()
                caps = sample.get_caps()
                structure = caps.get_structure(0)
                width = structure.get_value('width')
                height = structure.get_value('height')

                success, map_info = buf.map(Gst.MapFlags.READ)
                if success:
                    frame_data = np.frombuffer(map_info.data, dtype=np.uint8)
                    frame_rgb = frame_data.reshape((height, width, 3)).copy()
                    buf.unmap(map_info)

                    # Convert RGB -> BGR for OpenCV (pipeline outputs RGB like GUI.py)
                    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

                    with self._frame_lock:
                        self._latest_frame = frame_bgr
        except Exception as e:
            logger.error("Error in on_new_sample: %s", e)

        return Gst.FlowReturn.OK

    def _ensure_rtsp(self) -> None:
        """Initialize RTSP capture using native GStreamer pipeline for H.265.
        Uses the same approach as GUI.py: Gst.parse_launch + appsink + callback.
        """
        if self._gst_pipeline is not None:
            return  # Already running

        if not self._rtsp_url:
            raise RuntimeError("No RTSP URL configured")

        import gi
        gi.require_version('Gst', '1.0')
        gi.require_version('GLib', '2.0')
        from gi.repository import Gst, GLib

        if not Gst.is_initialized():
            Gst.init(None)

        # Build pipeline string — GPU accelerated H.265 decoding with NVDEC
        pipeline_str = (
            f"rtspsrc location={self._rtsp_url} latency=0 ! "
            "rtph265depay ! "
            "h265parse ! "
            "nvh265dec ! "
            "cudadownload ! "
            "videoconvert ! "
            "videoscale ! "
            "video/x-raw,width=960,height=540,format=RGB ! "
            "appsink name=appsink emit-signals=true max-buffers=1 drop=true sync=false"
        )

        logger.info("Starting native GStreamer pipeline for: %s", self._rtsp_url)
        try:
            self._gst_pipeline = Gst.parse_launch(pipeline_str)

            # Connect appsink callback — same as GUI.py
            self._appsink = self._gst_pipeline.get_by_name('appsink')
            if self._appsink:
                self._appsink.connect('new-sample', self._on_new_sample)
            else:
                raise RuntimeError("Could not find appsink in pipeline")

            # Setup bus for error handling
            bus = self._gst_pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message::error", self._on_gst_error)

            # Start GLib MainLoop in a background thread for signal delivery
            if not hasattr(self, '_glib_loop') or self._glib_loop is None:
                self._glib_loop = GLib.MainLoop()
                import threading
                self._glib_thread = threading.Thread(
                    target=self._glib_loop.run, daemon=True
                )
                self._glib_thread.start()

            # Start pipeline
            ret = self._gst_pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                self._gst_pipeline = None
                raise RuntimeError("Failed to start GStreamer pipeline")

            logger.info("GStreamer pipeline started successfully")
        except Exception as e:
            logger.error("GStreamer pipeline creation failed: %s", e)
            self._gst_pipeline = None
            raise

    def _on_gst_error(self, bus, msg):
        """Handle GStreamer bus error messages."""
        err, debug = msg.parse_error()
        logger.error("GStreamer bus error: %s | %s", err.message, debug)

    def _kill_gst(self) -> None:
        """Stop the GStreamer pipeline if running."""
        if self._gst_pipeline is not None:
            try:
                import gi
                gi.require_version('Gst', '1.0')
                from gi.repository import Gst
                self._gst_pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
            self._gst_pipeline = None
            self._appsink = None

        # Stop GLib MainLoop
        if hasattr(self, '_glib_loop') and self._glib_loop is not None:
            self._glib_loop.quit()
            self._glib_loop = None

    def capture_frame(self) -> np.ndarray:
        """Return the latest frame from the GStreamer callback buffer."""
        self._ensure_rtsp()

        # Wait briefly for the first frame if pipeline just started
        import time
        for _ in range(50):  # Wait up to 5 seconds (50 × 0.1s)
            with self._frame_lock:
                if self._latest_frame is not None:
                    return self._latest_frame.copy()
            time.sleep(0.1)

        raise RuntimeError("No frame available from GStreamer pipeline (timeout)")

    def move_to_preset(self, preset_token: str) -> None:
        """Move camera to a named preset position."""
        self._ensure_onvif()
        assert self._ptz_service is not None
        assert self._profile_token is not None

        try:
            self._ptz_service.GotoPreset({
                "ProfileToken": self._profile_token,
                "PresetToken": preset_token,
            })
            logger.info("Moving to preset: %s", preset_token)
        except Exception as e:
            logger.error("Move to preset failed: %s", e)
            raise

    def continuous_move(
        self,
        pan_speed: float = 0.0,
        tilt_speed: float = 0.0,
        zoom_speed: float = 0.0,
    ) -> None:
        """Start continuous PTZ movement.

        Args:
            pan_speed: -1.0 (left) to 1.0 (right)
            tilt_speed: -1.0 (down) to 1.0 (up)
            zoom_speed: -1.0 (wide) to 1.0 (tele)
        """
        self._ensure_onvif()
        assert self._ptz_service is not None
        assert self._profile_token is not None

        try:
            request = self._ptz_service.create_type('ContinuousMove')
            request.ProfileToken = self._profile_token
            request.Velocity = {
                "PanTilt": {"x": pan_speed, "y": tilt_speed},
                "Zoom": {"x": zoom_speed},
            }
            self._ptz_service.ContinuousMove(request)
            logger.info(
                "ContinuousMove: pan=%.2f tilt=%.2f zoom=%.2f",
                pan_speed, tilt_speed, zoom_speed,
            )
        except Exception as e:
            logger.error("ContinuousMove failed: %s", e)
            raise

    def stop_move(self, pan_tilt: bool = True, zoom: bool = True) -> None:
        """Stop all PTZ movement."""
        self._ensure_onvif()
        assert self._ptz_service is not None
        assert self._profile_token is not None

        try:
            self._ptz_service.Stop({
                "ProfileToken": self._profile_token,
                "PanTilt": pan_tilt,
                "Zoom": zoom,
            })
            logger.info("PTZ Stop")
        except Exception as e:
            logger.error("PTZ Stop failed: %s", e)
            raise

    def get_presets(self) -> List[Dict[str, Any]]:
        """Get list of user-created presets (filtered, max 8)."""
        self._ensure_onvif()
        assert self._ptz_service is not None
        assert self._profile_token is not None

        try:
            presets = self._ptz_service.GetPresets({"ProfileToken": self._profile_token})
            import re
            result = []
            for p in presets:
                name = getattr(p, "Name", None) or ""
                token = str(p.token)
                # Skip default/empty presets — only keep user-named ones
                if not name or re.match(r'^(preset\s*\d+|Preset\s*\d+|\d+)$', name.strip()):
                    continue
                result.append({"token": token, "name": name})
                if len(result) >= 8:
                    break
            return result
        except Exception as e:
            logger.error("Get presets failed: %s", e)
            return []

    def get_status(self) -> Dict[str, float]:
        """Get current PTZ position."""
        self._ensure_onvif()
        assert self._ptz_service is not None
        assert self._profile_token is not None

        try:
            status = self._ptz_service.GetStatus({"ProfileToken": self._profile_token})
            pos = status.Position
            return {
                "pan": float(pos.PanTilt.x) if pos and pos.PanTilt else 0.0,
                "tilt": float(pos.PanTilt.y) if pos and pos.PanTilt else 0.0,
                "zoom": float(pos.Zoom.x) if pos and pos.Zoom else 1.0,
            }
        except Exception as e:
            logger.warning("Get status failed: %s", e)
            return {"pan": 0.0, "tilt": 0.0, "zoom": 1.0}

    def execute_scan_plan(
        self,
        plan: dict,
        callback: Callable[[np.ndarray, str], None],
    ) -> None:
        """
        Execute a scan plan: iterate through zones and sweeps,
        capturing frames and calling the callback for each.

        Args:
            plan: ScanPlan dict with zones, sweeps, dwell_seconds, move_seconds
            callback: Function(frame, zone_id) called for each captured frame
        """
        zones = plan.get("zones", [])
        sweeps = plan.get("sweeps", 1)
        dwell_seconds = plan.get("dwell_seconds", 3.0)
        move_seconds = plan.get("move_seconds", 1.5)

        # Estimate frames per dwell (at ~2 FPS processing rate)
        frames_per_dwell = max(1, int(dwell_seconds * 2))

        logger.info(
            "Executing scan plan: %d zones × %d sweeps, "
            "%d frames/dwell (dwell=%.1fs, move=%.1fs)",
            len(zones),
            sweeps,
            frames_per_dwell,
            dwell_seconds,
            move_seconds,
        )

        for sweep_idx in range(sweeps):
            logger.info("=== Sweep %d/%d ===", sweep_idx + 1, sweeps)

            for zone in zones:
                zone_id = zone.get("id", "unknown")
                preset = str(zone.get("preset", "1"))

                logger.info("Moving to zone %s (preset %s)…", zone_id, preset)

                try:
                    self.move_to_preset(preset)
                except Exception as e:
                    logger.error("Failed to move to zone %s: %s", zone_id, e)
                    continue

                # Wait for camera to settle
                time.sleep(move_seconds)

                # Capture frames during dwell period
                for frame_idx in range(frames_per_dwell):
                    try:
                        frame = self.capture_frame()
                        callback(frame, zone_id)
                    except Exception as e:
                        logger.error(
                            "Frame capture failed (zone=%s, frame=%d): %s",
                            zone_id,
                            frame_idx,
                            e,
                        )

                    # Small delay between frames
                    time.sleep(dwell_seconds / frames_per_dwell)

        logger.info("Scan plan execution complete")

    def release(self) -> None:
        """Release resources."""
        self._kill_gst()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._onvif_camera = None
        self._ptz_service = None
        logger.info("PTZ controller released")


class CameraManager:
    """
    Manages multiple PTZController instances, keyed by camera UUID string.
    Each camera gets its own GStreamer pipeline and optional ONVIF connection.
    """

    _cameras: Dict[str, PTZController] = {}
    _lock = __import__("threading").Lock()

    @classmethod
    def add_camera(
        cls,
        camera_id: str,
        rtsp_url: str,
        onvif_host: Optional[str] = None,
        onvif_port: Optional[int] = None,
        onvif_user: Optional[str] = None,
        onvif_password: Optional[str] = None,
    ) -> PTZController:
        """Create and register a PTZController for the given camera."""
        with cls._lock:
            if camera_id in cls._cameras:
                return cls._cameras[camera_id]

            ctrl = PTZController(
                host=onvif_host or "",
                port=onvif_port or 80,
                user=onvif_user or "",
                password=onvif_password or "",
                rtsp_url=rtsp_url,
            )
            cls._cameras[camera_id] = ctrl
            logger.info("CameraManager: added camera %s (rtsp=%s)", camera_id, rtsp_url)
            return ctrl

    @classmethod
    def get_camera(cls, camera_id: str) -> Optional[PTZController]:
        """Return the PTZController for *camera_id*, or None."""
        return cls._cameras.get(camera_id)

    @classmethod
    def remove_camera(cls, camera_id: str) -> None:
        """Stop and remove a camera controller."""
        with cls._lock:
            ctrl = cls._cameras.pop(camera_id, None)
            if ctrl is not None:
                ctrl.release()
                logger.info("CameraManager: removed camera %s", camera_id)

    @classmethod
    def list_camera_ids(cls) -> List[str]:
        """Return list of registered camera IDs."""
        return list(cls._cameras.keys())

    @classmethod
    def remove_all(cls) -> None:
        """Stop and remove every camera."""
        with cls._lock:
            for cid in list(cls._cameras):
                ctrl = cls._cameras.pop(cid, None)
                if ctrl:
                    ctrl.release()
            logger.info("CameraManager: removed all cameras")
