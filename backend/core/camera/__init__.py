"""
Camera package — RTSP streaming and PTZ control.

Re-exports from submodules for convenience:
    from src.backend.core.camera import open_capture
    from src.backend.core.camera.stream import build_gstreamer_pipeline
"""

from src.backend.core.camera.stream import *  # noqa: F401,F403
