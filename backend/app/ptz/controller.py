"""
PTZ Camera Controller — ONVIF + RTSP integration.

Communicates with PTZ cameras via ONVIF protocol for movement control
and RTSP for frame capture. Supports both IP cameras and USB cameras.
"""

from __future__ import annotations

import logging
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

    def _ensure_rtsp(self) -> None:
        """Initialize RTSP capture if not already done."""
        if self._cap is not None and self._cap.isOpened():
            return

        if not self._rtsp_url:
            raise RuntimeError("No RTSP URL configured")

        self._cap = cv2.VideoCapture(self._rtsp_url)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open RTSP stream: {self._rtsp_url}")

        # Set buffer size to 1 for low latency
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        logger.info("RTSP stream opened: %s", self._rtsp_url)

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

    def capture_frame(self) -> np.ndarray:
        """Capture a single frame from the RTSP stream."""
        self._ensure_rtsp()
        assert self._cap is not None

        # Flush buffer to get latest frame
        for _ in range(3):
            self._cap.grab()

        ret, frame = self._cap.read()
        if not ret or frame is None:
            raise RuntimeError("Failed to capture frame from RTSP stream")

        return frame

    def get_presets(self) -> List[Dict[str, Any]]:
        """Get list of configured presets."""
        self._ensure_onvif()
        assert self._ptz_service is not None
        assert self._profile_token is not None

        try:
            presets = self._ptz_service.GetPresets({"ProfileToken": self._profile_token})
            return [
                {
                    "token": str(p.token),
                    "name": getattr(p, "Name", f"Preset {p.token}"),
                }
                for p in presets
            ]
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
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._onvif_camera = None
        self._ptz_service = None
        logger.info("PTZ controller released")
