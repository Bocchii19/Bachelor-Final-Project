"""
Scan Planner Agent — Computes optimal PTZ scan plan based on class size.

Determines number of zones, sweep cycles, dwell time, and movement speed
to ensure adequate coverage within reasonable scan duration.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.config import get_settings
from app.ptz.presets import get_zones_for_capacity
from app.schemas.session import ScanPlan, ZoneConfig

logger = logging.getLogger(__name__)
settings = get_settings()

# Scan configuration tiers based on enrolled student count
SCAN_TIERS = {
    "small": {
        "max_enrolled": 19,
        "zones": 2,
        "sweeps": 1,
        "dwell_seconds": 3.0,
        "move_seconds": 1.0,
    },
    "medium": {
        "max_enrolled": 39,
        "zones": 4,
        "sweeps": 2,
        "dwell_seconds": 4.0,
        "move_seconds": 1.5,
    },
    "large": {
        "max_enrolled": float("inf"),
        "zones": 6,
        "sweeps": 3,
        "dwell_seconds": 5.0,
        "move_seconds": 2.0,
    },
}


def _select_tier(enrolled_count: int) -> dict:
    """Select scan tier based on enrolled count."""
    for tier_name, tier in SCAN_TIERS.items():
        if enrolled_count <= tier["max_enrolled"]:
            logger.info(
                "Selected scan tier '%s' for %d students", tier_name, enrolled_count
            )
            return tier
    return SCAN_TIERS["large"]


def compute_scan_plan(
    enrolled_count: int,
    room_config: Optional[Dict[str, Any]] = None,
) -> ScanPlan:
    """
    Compute an optimal scan plan based on class size.

    Args:
        enrolled_count: Number of enrolled students
        room_config: Optional custom room config with zone definitions.
                     If None, uses default config based on capacity.

    Returns:
        ScanPlan with zones, sweeps, timing, and coverage threshold.
    """
    tier = _select_tier(enrolled_count)

    # Get zone definitions
    if room_config and "zones" in room_config:
        raw_zones = room_config["zones"]
    else:
        raw_zones = get_zones_for_capacity(enrolled_count)

    # Limit zones to tier recommendation
    zones_to_use = raw_zones[: tier["zones"]]

    zones = [
        ZoneConfig(
            id=z.get("id", f"zone_{i}"),
            preset=int(z.get("preset", i + 1)),
            pan=float(z.get("pan", 0)),
            tilt=float(z.get("tilt", 0)),
        )
        for i, z in enumerate(zones_to_use)
    ]

    sweeps = tier["sweeps"]
    dwell = tier["dwell_seconds"]
    move = tier["move_seconds"]

    # Calculate total scan time
    per_zone_time = dwell + move
    total_seconds = len(zones) * per_zone_time * sweeps

    plan = ScanPlan(
        zones=zones,
        sweeps=sweeps,
        dwell_seconds=dwell,
        move_seconds=move,
        total_seconds=round(total_seconds, 1),
        coverage_threshold=settings.COVERAGE_TARGET,
    )

    logger.info(
        "Scan plan: %d zones × %d sweeps = %.0fs total, threshold=%.0f%%",
        len(zones),
        sweeps,
        total_seconds,
        settings.COVERAGE_TARGET * 100,
    )

    return plan
