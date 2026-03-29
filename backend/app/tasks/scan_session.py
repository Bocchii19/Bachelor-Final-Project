"""
Celery Task — Run full attendance session scan.

Orchestrates the entire scan lifecycle:
1. Load session → compute scan plan
2. Execute PTZ scan with CV pipeline callbacks
3. Check coverage → re-scan if needed
4. Cluster unknown faces
5. Mark session as done
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.tasks import celery_app

logger = logging.getLogger(__name__)

MAX_RESCAN_ATTEMPTS = 2


def _get_event_loop():
    """Get or create an event loop for async operations inside Celery."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


@celery_app.task(bind=True, name="tasks.run_attendance_session")
def run_attendance_session(self, session_id: str) -> dict:
    """
    Full attendance session workflow.

    This task runs synchronously in the Celery worker but uses
    async DB operations internally via an event loop.
    """
    loop = _get_event_loop()
    return loop.run_until_complete(_run_session_async(self, session_id))


async def _run_session_async(task, session_id_str: str) -> dict:
    """Async implementation of the attendance session scan."""
    from sqlalchemy import select

    from app.agent.coverage_checker import check_coverage
    from app.agent.scan_planner import compute_scan_plan
    from app.cv.clustering import cluster_unknown_faces
    from app.cv.pipeline import CVPipeline
    from app.database import async_session_factory
    from app.models.session import Session
    from app.ptz.controller import PTZController

    session_id = uuid.UUID(session_id_str)
    pipeline = CVPipeline.get_instance()

    async with async_session_factory() as db:
        # 1. Load session
        result = await db.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if not session:
            logger.error("Session %s not found", session_id)
            return {"error": "Session not found"}

        class_id = session.class_id
        enrolled_count = session.enrolled_count

        logger.info(
            "=== Starting attendance session %s (enrolled=%d) ===",
            session_id,
            enrolled_count,
        )

        # 2. Compute scan plan (if not already computed by API)
        if not session.scan_plan:
            plan = compute_scan_plan(enrolled_count, {})
            session.scan_plan = plan.model_dump()
            await db.flush()
        else:
            from app.schemas.session import ScanPlan
            plan = ScanPlan(**session.scan_plan)

        # 3. Execute PTZ scan
        ptz = PTZController.get_instance()

        # Frame processing callback (runs synchronously inside scan loop)
        frames_processed = 0

        def on_frame(frame, zone_id: str):
            """Called for each captured frame during scan."""
            nonlocal frames_processed

            try:
                # Run CV pipeline async from sync callback
                inner_loop = asyncio.new_event_loop()
                inner_loop.run_until_complete(
                    _process_single_frame(
                        pipeline, frame, session_id, class_id, zone_id
                    )
                )
                inner_loop.close()
                frames_processed += 1
            except Exception as e:
                logger.error("Frame processing error: %s", e)

            # Update task progress
            task.update_state(
                state="SCANNING",
                meta={"frames_processed": frames_processed, "zone": zone_id},
            )

        try:
            ptz.execute_scan_plan(session.scan_plan, on_frame)
        except Exception as e:
            logger.error("Scan execution failed: %s", e)

        logger.info("Initial scan complete: %d frames processed", frames_processed)

        # 4. Check coverage + re-scan if needed
        for attempt in range(MAX_RESCAN_ATTEMPTS):
            coverage = await check_coverage(session_id, db)

            if coverage.is_sufficient:
                logger.info(
                    "Coverage sufficient: %.1f%% (target=%.1f%%)",
                    coverage.coverage_pct,
                    coverage.target_pct,
                )
                break

            logger.info(
                "Coverage insufficient: %.1f%% (target=%.1f%%), "
                "re-scanning zones: %s (attempt %d/%d)",
                coverage.coverage_pct,
                coverage.target_pct,
                coverage.missing_zones,
                attempt + 1,
                MAX_RESCAN_ATTEMPTS,
            )

            # Build re-scan plan with only missing zones
            if coverage.missing_zones and session.scan_plan:
                rescan_zones = [
                    z
                    for z in session.scan_plan.get("zones", [])
                    if z.get("id") in coverage.missing_zones
                ]
                if rescan_zones:
                    rescan_plan = {
                        **session.scan_plan,
                        "zones": rescan_zones,
                        "sweeps": 1,
                    }
                    try:
                        ptz.execute_scan_plan(rescan_plan, on_frame)
                    except Exception as e:
                        logger.error("Re-scan failed: %s", e)

        # 5. Cluster unknown faces
        n_clusters = await cluster_unknown_faces(session_id, db)
        logger.info("Clustered unknown faces into %d groups", n_clusters)

        # 6. Final coverage
        final_coverage = await check_coverage(session_id, db)

        # 7. Mark session as done
        session.status = "done"
        await db.commit()

        logger.info(
            "=== Session %s COMPLETE: %d/%d recognized (%.1f%%), "
            "%d clusters, %d frames ===",
            session_id,
            final_coverage.recognized_count,
            final_coverage.enrolled_count,
            final_coverage.coverage_pct,
            n_clusters,
            frames_processed,
        )

        return {
            "session_id": str(session_id),
            "recognized": final_coverage.recognized_count,
            "enrolled": final_coverage.enrolled_count,
            "coverage_pct": final_coverage.coverage_pct,
            "clusters": n_clusters,
            "frames_processed": frames_processed,
            "status": "done",
        }


async def _process_single_frame(
    pipeline, frame, session_id, class_id, zone_id
):
    """Process a single frame using the CV pipeline."""
    from app.database import async_session_factory

    async with async_session_factory() as db:
        result = await pipeline.process_frame(
            frame=frame,
            session_id=session_id,
            db=db,
            zone_id=zone_id,
            class_id=class_id,
        )
        await db.commit()
        return result
