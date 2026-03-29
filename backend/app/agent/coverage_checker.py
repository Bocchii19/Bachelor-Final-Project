"""
Coverage Checker — Monitors attendance recognition progress.

Determines if enough students have been recognized to meet the
coverage threshold, and identifies zones that may need re-scanning.
"""

from __future__ import annotations

import logging
import uuid
from typing import List

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.attendance import AttendanceRecord
from app.models.session import Session
from app.models.unknown_face import UnknownFace
from app.schemas.session import CoverageResult

logger = logging.getLogger(__name__)
settings = get_settings()


async def check_coverage(
    session_id: uuid.UUID,
    db: AsyncSession,
) -> CoverageResult:
    """
    Check how many students have been recognized in this session.

    Returns:
        CoverageResult with recognized count, percentage, and missing zones.
    """
    # Get session info
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError(f"Session {session_id} not found")

    enrolled = session.enrolled_count
    target_pct = settings.COVERAGE_TARGET * 100

    # Count recognized students (status = 'present')
    count_result = await db.execute(
        select(func.count(AttendanceRecord.id.distinct())).where(
            and_(
                AttendanceRecord.session_id == session_id,
                AttendanceRecord.status == "present",
            )
        )
    )
    recognized_count = count_result.scalar() or 0

    coverage_pct = round(recognized_count * 100.0 / enrolled, 1) if enrolled > 0 else 0.0
    is_sufficient = coverage_pct >= target_pct

    # Determine missing zones (zones that have many unknowns or few recognitions)
    missing_zones: List[str] = []

    if not is_sufficient and session.scan_plan:
        zones = session.scan_plan.get("zones", [])

        for zone in zones:
            zone_id = zone.get("id", "")

            # Count recognized in this zone
            zone_recognized = await db.execute(
                select(func.count()).where(
                    and_(
                        AttendanceRecord.session_id == session_id,
                        AttendanceRecord.zone_id == zone_id,
                        AttendanceRecord.status == "present",
                    )
                )
            )
            zone_count = zone_recognized.scalar() or 0

            # Count unknowns in this zone
            zone_unknown = await db.execute(
                select(func.count()).where(
                    and_(
                        UnknownFace.session_id == session_id,
                        UnknownFace.zone_id == zone_id,
                        UnknownFace.status == "pending",
                    )
                )
            )
            unknown_count = zone_unknown.scalar() or 0

            # If zone has few recognitions or many unknowns, mark it for re-scan
            if zone_count < 2 or unknown_count > zone_count:
                missing_zones.append(zone_id)

    coverage = CoverageResult(
        session_id=session_id,
        recognized_count=recognized_count,
        enrolled_count=enrolled,
        coverage_pct=coverage_pct,
        target_pct=target_pct,
        is_sufficient=is_sufficient,
        missing_zones=missing_zones,
    )

    logger.info(
        "Coverage for session %s: %d/%d (%.1f%%) — %s",
        session_id,
        recognized_count,
        enrolled,
        coverage_pct,
        "SUFFICIENT" if is_sufficient else f"NEED RE-SCAN zones={missing_zones}",
    )

    return coverage
