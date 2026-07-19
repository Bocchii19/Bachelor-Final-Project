"""
Centralized configuration for the UBQN Intrusion Detection system.

All paths, RTSP URLs, GStreamer params, and model settings are defined here.
Overridable via environment variables and config/settings.yaml.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# src/backend/ directory (parent of core/) — holds all Python processing
SRC_DIR = Path(__file__).resolve().parents[1]

CONFIG_DIR = PROJECT_ROOT / "configs"       # legacy — still has polygon.yaml copy
SRC_CONFIG_DIR = SRC_DIR / "config"         # canonical config dir: system.yaml, polygon.yaml
MODELS_DIR = PROJECT_ROOT / "models"        # legacy placeholder
SRC_MODELS_DIR = SRC_DIR / "models"         # actual model location: src/backend/models/v4/, v5/
RESULTS_DIR = PROJECT_ROOT / "results"
API_DIR = SRC_DIR / "api"                    # FastAPI web layer (src/backend/api)
FRONTEND_DIR = SRC_DIR.parent / "frontend"   # React app (src/frontend)

CONFIGS_YAML = API_DIR / "configs.yaml"
POLYGON_YAML = SRC_CONFIG_DIR / "polygon.yaml"

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

MODEL_STEM = "best_UBQN_V5"  # default; overridden by system.yaml model.name

# ---------------------------------------------------------------------------
# GStreamer / RTSP defaults
# ---------------------------------------------------------------------------

GST_LATENCY = 300
GST_MAX_BUFFERS = 3
OPEN_VALIDATE_SECONDS = 5.0
OPEN_VALIDATE_READS = 30
ENABLE_UDP_FALLBACK = False
ENABLE_H265_FALLBACK = False

# ---------------------------------------------------------------------------
# Camera list (default)
# ---------------------------------------------------------------------------

RTSP_URLS: list[tuple[str, str]] = [
    ("cam1", "rtsp://admin:Hanet123@10.128.55.225:554/media/live/105"),
    ("cam2", "rtsp://admin:Hanet123@10.128.55.222:554/media/live/105"),
    ("cam3", "rtsp://admin:Hanet123@10.128.55.223:554/media/live/105"),
]

# ---------------------------------------------------------------------------
# Image extensions accepted
# ---------------------------------------------------------------------------

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

# Camera folder → polygon.yaml camera key mapping
CAM_FOLDER_TO_KEY = {
    "cam_1": "cam1",
    "cam_2": "cam2",
    "cam_3": "cam3",
}

CAM_FOLDERS = ["cam_1", "cam_2", "cam_3"]


# ---------------------------------------------------------------------------
# Optional: load overrides from settings.yaml
# ---------------------------------------------------------------------------

def _load_settings_yaml() -> dict:
    # Try src/config/system.yaml first (actual location), then configs/
    for settings_path in [SRC_DIR / "config" / "system.yaml", CONFIG_DIR / "system.yaml"]:
        if settings_path.exists():
            try:
                data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                continue
    return {}


def load_rtsp_urls_from_settings() -> list[tuple[str, str]]:
    """Load RTSP URLs from config/settings.yaml if available, else use defaults."""
    settings = _load_settings_yaml()
    cameras = settings.get("cameras")
    if not isinstance(cameras, list):
        return RTSP_URLS
    result: list[tuple[str, str]] = []
    for cam in cameras:
        if isinstance(cam, dict) and "id" in cam and "rtsp_url" in cam:
            result.append((str(cam["id"]), str(cam["rtsp_url"])))
    return result if result else RTSP_URLS


def load_display_urls_from_settings() -> dict[str, str]:
    """Load display_url (sub-stream) mapping for UI display.
    
    Returns dict: {cam_id: display_url}.
    Falls back to rtsp_url if display_url is not set.
    """
    settings = _load_settings_yaml()
    cameras = settings.get("cameras")
    if not isinstance(cameras, list):
        return {}
    result: dict[str, str] = {}
    for cam in cameras:
        if isinstance(cam, dict) and "id" in cam:
            cam_id = str(cam["id"])
            # Prefer display_url, fallback to rtsp_url
            display = cam.get("display_url", "") or cam.get("rtsp_url", "")
            if display:
                result[cam_id] = str(display)
    return result
