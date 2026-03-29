"""
PTZ Presets — Room / zone preset management.

Presets define the camera positions for each zone in a room.
These are calibrated once during setup and stored for reuse.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default room configurations for common room sizes
DEFAULT_ROOM_CONFIGS: Dict[str, Dict[str, Any]] = {
    "small_room": {
        "description": "Small room (< 20 seats)",
        "zones": [
            {"id": "zone_A", "preset": "1", "pan": -45, "tilt": -10, "description": "Left side"},
            {"id": "zone_B", "preset": "2", "pan": 45, "tilt": -10, "description": "Right side"},
        ],
    },
    "medium_room": {
        "description": "Medium room (20-39 seats)",
        "zones": [
            {"id": "zone_A", "preset": "1", "pan": -60, "tilt": -5, "description": "Far left"},
            {"id": "zone_B", "preset": "2", "pan": -20, "tilt": -5, "description": "Center left"},
            {"id": "zone_C", "preset": "3", "pan": 20, "tilt": -5, "description": "Center right"},
            {"id": "zone_D", "preset": "4", "pan": 60, "tilt": -5, "description": "Far right"},
        ],
    },
    "large_room": {
        "description": "Large room (40+ seats)",
        "zones": [
            {"id": "zone_A", "preset": "1", "pan": -80, "tilt": 0, "description": "Far left front"},
            {"id": "zone_B", "preset": "2", "pan": -40, "tilt": 0, "description": "Left front"},
            {"id": "zone_C", "preset": "3", "pan": 0, "tilt": 0, "description": "Center front"},
            {"id": "zone_D", "preset": "4", "pan": 40, "tilt": 0, "description": "Right front"},
            {"id": "zone_E", "preset": "5", "pan": -40, "tilt": -15, "description": "Left back"},
            {"id": "zone_F", "preset": "6", "pan": 40, "tilt": -15, "description": "Right back"},
        ],
    },
}


def get_room_config(room_type: str = "medium_room") -> Dict[str, Any]:
    """Get default room configuration by type."""
    return DEFAULT_ROOM_CONFIGS.get(room_type, DEFAULT_ROOM_CONFIGS["medium_room"])


def get_zones_for_capacity(capacity: int) -> List[Dict[str, Any]]:
    """Select room configuration based on room capacity."""
    if capacity < 20:
        config = DEFAULT_ROOM_CONFIGS["small_room"]
    elif capacity < 40:
        config = DEFAULT_ROOM_CONFIGS["medium_room"]
    else:
        config = DEFAULT_ROOM_CONFIGS["large_room"]

    return config["zones"]


def select_zones(
    zones: List[Dict[str, Any]],
    count: int,
) -> List[Dict[str, Any]]:
    """Select a subset of zones for scanning (e.g., for re-scan of missing zones)."""
    if count >= len(zones):
        return zones

    # Distribute evenly
    step = len(zones) / count
    indices = [int(i * step) for i in range(count)]
    return [zones[i] for i in indices]
