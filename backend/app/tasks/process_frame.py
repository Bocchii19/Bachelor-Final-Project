"""
Celery Task — Process a single frame asynchronously.

Can be used for real-time streaming mode where frames are dispatched
individually instead of via the scan plan executor.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

import numpy as np

from app.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.process_frame")
def process_frame_task(
    frame_bytes: bytes,
    session_id: str,
    zone_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> dict:
    """
    Process a single frame in a Celery worker.

    Args:
        frame_bytes: JPEG-encoded frame bytes
        session_id: UUID of the session
        zone_id: Optional zone identifier
        class_id: Optional class UUID for filtering embeddings

    Returns:
        Dict with processing results
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            _process_async(frame_bytes, session_id, zone_id, class_id)
        )
    finally:
        loop.close()


async def _process_async(
    frame_bytes: bytes,
    session_id_str: str,
    zone_id: Optional[str],
    class_id_str: Optional[str],
) -> dict:
    """Async implementation of frame processing."""
    import cv2

    from app.cv.pipeline import CVPipeline
    from app.database import async_session_factory

    # Decode frame
    frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
    frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)

    if frame is None:
        return {"error": "Could not decode frame"}

    session_id = uuid.UUID(session_id_str)
    class_id = uuid.UUID(class_id_str) if class_id_str else None

    pipeline = CVPipeline.get_instance()

    async with async_session_factory() as db:
        result = await pipeline.process_frame(
            frame=frame,
            session_id=session_id,
            db=db,
            zone_id=zone_id,
            class_id=class_id,
        )
        await db.commit()

    return {
        "total_faces": result.total_faces,
        "recognized": len(result.recognized),
        "unrecognized": len(result.unrecognized),
        "spoofs": len(result.spoofs),
    }
