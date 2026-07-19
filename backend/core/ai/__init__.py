"""
AI package — YOLO model and detection utilities.

Re-exports from submodules for convenience:
    from src.backend.core.ai import resolve_model_path
    from src.backend.core.ai.detection import has_any_detection
"""

from src.backend.core.ai.yolo import *  # noqa: F401,F403
from src.backend.core.ai.detection import *  # noqa: F401,F403
