"""
Unified config loader cho PTZ Patrol module.

Load config/patrol.yaml + merge thông tin từ:
- settings.yaml (camera RTSP URLs)
- polygon.yaml  (ROI regions)
- configs.yaml  (Treo_rao polygons)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.backend.core.config import (
    CONFIG_DIR,
    SRC_DIR,
    POLYGON_YAML,
    CONFIGS_YAML,
    RESULTS_DIR,
    RTSP_URLS,
    load_rtsp_urls_from_settings,
)

logger = logging.getLogger(__name__)

DEFAULT_FENCE_CONFIG = SRC_DIR / "config" / "system.yaml"


def load_yaml(path: Path) -> dict:
    """Load YAML file, return empty dict on failure."""
    if not path.exists():
        logger.warning("Config file not found: %s", path)
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
        return {}


def load_patrol_config(
    config_path: Path | None = None,
) -> dict[str, Any]:
    """
    Load fence config (bao gồm polygon areas + patrol + thresholds).

    Returns:
        Dict chứa tất cả config:
        - cameras: polygon areas, ROI regions, fence lines
        - ptz_camera: PTZ connection info
        - presets: mapping preset_id → fixed_camera_id
        - patrol: cooldown, dwell_time
        - detection: confidence, device, imgsz
        - zoom_track: zoom & center params
        - face_recognition: save_dir, min_face_size
        - _cameras: resolved RTSP URL dict {cam_id: url}
        - _fence_config: Path to system.yaml (cho polygon loading)
        - _configs_yaml: Path to configs.yaml
        - _results_dir: Path to results/
    """
    path = config_path or DEFAULT_FENCE_CONFIG
    cfg = load_yaml(path)
    logger.info("Loaded fence config: %s", path)

    # Resolve camera RTSP URLs từ system.yaml
    rtsp_list = load_rtsp_urls_from_settings()
    cameras = {cam_id: url for cam_id, url in rtsp_list}
    cfg["_cameras"] = cameras

    # Inject fixed_camera_url vào mỗi preset dựa trên fixed_camera_id
    for preset in cfg.get("presets", []):
        cam_id = preset.get("fixed_camera_id", "")
        if cam_id and cam_id in cameras:
            preset["fixed_camera_url"] = cameras[cam_id]
        elif not preset.get("fixed_camera_url"):
            logger.warning(
                "Preset %d (%s): no fixed_camera_url for cam_id=%s",
                preset.get("id", 0),
                preset.get("name", ""),
                cam_id,
            )

    # Metadata paths
    cfg["_polygon_yaml"] = POLYGON_YAML
    cfg["_configs_yaml"] = CONFIGS_YAML
    cfg["_results_dir"] = RESULTS_DIR

    return cfg
