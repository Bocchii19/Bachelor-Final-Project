"""
PTZ Control Adapter — MTRPC protocol.

Wrapper quanh mtrpc_client để điều khiển camera PTZ:
- connect/disconnect
- goto_preset / set_preset
- move_direction (pan/tilt)
- zoom_in / zoom_out / zoom_wide_max
- stop / autofocus
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Import MTRPC Client — sử dụng bản trong ptz_patrol/src/ (bản gốc)
# Fallback: thử từ src.backend
_MTRPC_AVAILABLE = False
_MTRPCClient = None
_RelayMTRPCClient = None
_create_client = None

try:
    # Prefer ptz_patrol's mtrpc_client (có RelayMTRPCClient đầy đủ)
    _ptz_patrol_src = str(Path(__file__).resolve().parents[4] / "ptz_patrol" / "src")
    if _ptz_patrol_src not in sys.path:
        sys.path.insert(0, _ptz_patrol_src)
    from mtrpc_client import MTRPCClient as _MTRPCClient
    from mtrpc_client import RelayMTRPCClient as _RelayMTRPCClient
    from mtrpc_client import create_client as _create_client
    _MTRPC_AVAILABLE = True
    logger.debug("MTRPC client loaded from ptz_patrol/src/")
except ImportError:
    try:
        # Fallback: src/backend/mtrpc_client.py (UBQN project)
        # ptz_control.py → fence/ → modules/ → src/ → PROJECT_ROOT
        _project_root = str(Path(__file__).resolve().parents[4])
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from src.backend.api.mtrpc_client import MTRPCClient as _MTRPCClient
        from src.backend.api.mtrpc_client import RelayMTRPCClient as _RelayMTRPCClient
        from src.backend.api.mtrpc_client import create_client as _create_client
        _MTRPC_AVAILABLE = True
        logger.debug("MTRPC client loaded from src.backend")
    except ImportError:
        logger.warning(
            "mtrpc_client not found. PTZ control will not work."
        )


# ── Constants ──
STEP_MIN = 1
STEP_MAX = 8


class PTZController:
    """
    PTZ camera controller via MTRPC protocol.

    Simplified interface cho patrol module:
    - connect / disconnect
    - goto_preset
    - move_direction (pan/tilt with duration)
    - zoom_in / zoom_out
    - stop / autofocus
    """

    def __init__(
        self,
        host: str,
        port: int = 80,
        username: str = "admin",
        password: str = "",
        mode: str = "direct",
        relay_host: str = "",
        relay_port: int = 8765,
        relay_token: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mode = mode
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.relay_token = relay_token

        self._client = None
        self._connected = False

    # ── Connection ──

    def connect(self) -> bool:
        """Connect to PTZ camera via MTRPC."""
        if not _MTRPC_AVAILABLE or _MTRPCClient is None:
            logger.error("MTRPC client not available.")
            return False

        try:
            if self.mode == "relay" and _create_client is not None:
                self._client = _create_client(
                    mode="relay",
                    relay_host=self.relay_host,
                    relay_port=self.relay_port,
                    relay_token=self.relay_token,
                )
            else:
                if _create_client is not None:
                    self._client = _create_client(
                        mode="direct",
                        host=self.host,
                        port=self.port,
                    )
                else:
                    self._client = _MTRPCClient(self.host, self.port)

            success = self._client.connect(self.username, self.password)
            self._connected = bool(success)
            if self._connected:
                logger.info("✓ PTZ connected: %s:%d", self.host, self.port)
            else:
                logger.error("✗ PTZ login failed")
            return self._connected

        except Exception as e:
            logger.error("PTZ connect error: %s", e)
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from PTZ camera."""
        if self._client:
            try:
                self._client.logout()
            except Exception:
                pass
            self._connected = False
            logger.info("PTZ disconnected.")

    # ── PTZ Command ──

    def _send_ptz(self, data: dict) -> dict | None:
        """Send PTZ command with auto re-login on session expired."""
        if not self._connected or self._client is None:
            if not self.connect():
                return None

        result = self._client._send_request("Control.DoPtz", {
            "data": data,
            "session_id": self._client.session_id,
        })

        if result is not None:
            return result

        # Try re-login
        logger.warning("PTZ command failed, re-login...")
        try:
            if self._client.connect(self.username, self.password):
                return self._client._send_request("Control.DoPtz", {
                    "data": data,
                    "session_id": self._client.session_id,
                })
        except Exception as e:
            logger.error("Re-login failed: %s", e)

        self._connected = False
        return None

    # ── Preset ──

    def goto_preset(self, preset_id: int = 255) -> bool:
        """Go to saved preset position."""
        if not self._connected:
            return False
        result = self._send_ptz({
            "cmd": "kCmdGotoPreset",
            "operate": "kOperateStart",
            "channel": 0,
            "step": 0,
            "preset": preset_id,
            "zoom": 0,
            "patrol": 0,
            "position_3d": {"x": 0, "y": 0, "width": 0, "height": 0},
            "auto_scan": 0,
            "mode_path": 0,
            "preset_name": "",
        })
        if result is not None:
            logger.info("[PRESET] Goto preset %d OK", preset_id)
            return True
        logger.error("[PRESET] Goto preset %d failed", preset_id)
        return False

    def set_preset(self, preset_id: int, name: str = "") -> bool:
        """Save current PTZ position as preset."""
        if not self._connected:
            return False
        result = self._send_ptz({
            "cmd": "kCmdSetPreset",
            "operate": "kOperateStart",
            "channel": 0,
            "step": 0,
            "preset": preset_id,
            "zoom": 0,
            "patrol": 0,
            "position_3d": {"x": 0, "y": 0, "width": 0, "height": 0},
            "auto_scan": 0,
            "mode_path": 0,
            "preset_name": name,
        })
        ok = result is not None
        if ok:
            logger.info("[PRESET] Set preset %d ('%s') OK", preset_id, name)
        return ok

    def clear_preset(self, preset_id: int) -> bool:
        """Clear (delete) a saved preset from the camera."""
        if not self._connected:
            return False
        result = self._send_ptz({
            "cmd": "kCmdClearPreset",
            "operate": "kOperateStart",
            "channel": 0,
            "step": 0,
            "preset": preset_id,
            "zoom": 0,
            "patrol": 0,
            "position_3d": {"x": 0, "y": 0, "width": 0, "height": 0},
            "auto_scan": 0,
            "mode_path": 0,
            "preset_name": "",
        })
        ok = result is not None
        if ok:
            logger.info("[PRESET] Cleared preset %d", preset_id)
        return ok

    # ── Movement ──

    def move_direction(
        self,
        cmd: str,
        step: int = 5,
        duration: float = 0.0,
    ) -> bool:
        """
        Move PTZ in a direction.

        Args:
            cmd: kCmdUp/Down/Left/Right/ZoomTele/ZoomWide
            step: speed [1-8]
            duration: seconds to move. 0 = start only.
        """
        if not self._connected:
            return False

        step = max(STEP_MIN, min(STEP_MAX, step))
        data = {
            "cmd": cmd,
            "operate": "kOperateStart",
            "channel": 0,
            "step": step,
            "preset": 0,
            "zoom": 1 if "Zoom" in cmd else 0,
            "patrol": 0,
            "position_3d": {"x": 0, "y": 0, "width": 0, "height": 0},
            "auto_scan": 0,
            "mode_path": 0,
            "preset_name": "",
        }
        self._send_ptz(data)

        if duration > 0:
            time.sleep(duration)
            data["operate"] = "kOperateStop"
            self._send_ptz(data)

        return True

    def stop(self) -> bool:
        """Stop all PTZ movement."""
        if not self._connected:
            return False
        self._send_ptz({
            "cmd": "kCmdUp",
            "operate": "kOperateStop",
            "channel": 0,
            "step": 0,
            "preset": 0,
            "zoom": 0,
            "patrol": 0,
            "position_3d": {"x": 0, "y": 0, "width": 0, "height": 0},
            "auto_scan": 0,
            "mode_path": 0,
            "preset_name": "",
        })
        return True

    def autofocus(self) -> bool:
        """Trigger autofocus."""
        if not self._connected:
            return False
        result = self._send_ptz({
            "cmd": "kCmdAutoFocus",
            "operate": "kOperateStart",
            "channel": 0,
            "step": 0,
            "preset": 0,
            "zoom": 0,
            "patrol": 0,
            "position_3d": {"x": 0, "y": 0, "width": 0, "height": 0},
            "auto_scan": 0,
            "mode_path": 0,
            "preset_name": "",
        })
        return result is not None

    def zoom_in(self, step: int = 3, duration: float = 0.5) -> bool:
        return self.move_direction("kCmdZoomTele", step=step, duration=duration)

    def zoom_out(self, step: int = 3, duration: float = 0.5) -> bool:
        return self.move_direction("kCmdZoomWide", step=step, duration=duration)

    def zoom_wide_max(self, duration: float = 2.0) -> bool:
        """Zoom out to widest angle."""
        return self.move_direction("kCmdZoomWide", step=STEP_MAX, duration=duration)

    @property
    def is_connected(self) -> bool:
        return self._connected
