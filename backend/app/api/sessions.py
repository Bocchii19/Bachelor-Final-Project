"""Sessions API — CRUD, start scan, scan plan, coverage."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.schemas.session import (
    CoverageResult,
    ScanPlan,
    SessionCreate,
    SessionRead,
    SessionUpdate,
)

router = APIRouter()


@router.get("/", response_model=List[SessionRead])
async def list_sessions(
    class_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List sessions, optionally filter by class and status."""
    stmt = select(Session)
    if class_id:
        stmt = stmt.where(Session.class_id == class_id)
    if status_filter:
        stmt = stmt.where(Session.status == status_filter)
    stmt = stmt.order_by(Session.session_date.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Create a new session (buổi học)."""
    session = Session(**body.model_dump())
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


@router.get("/{session_id}", response_model=SessionRead)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/{session_id}", response_model=SessionRead)
async def update_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(session, key, value)

    await db.flush()
    await db.refresh(session)
    return session


@router.post("/{session_id}/start-scan", response_model=SessionRead)
async def start_scan(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """
    Start PTZ scan for a session.
    1. Compute scan plan based on enrolled_count
    2. Dispatch Celery task to orchestrate the scan
    3. Update session status to 'scanning'
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "scanning":
        raise HTTPException(status_code=409, detail="Session is already scanning")
    if session.status == "done":
        raise HTTPException(status_code=409, detail="Session scan already completed")

    # Compute scan plan
    from app.agent.scan_planner import compute_scan_plan
    plan = compute_scan_plan(session.enrolled_count, {})
    session.scan_plan = plan.model_dump()
    session.status = "scanning"
    await db.flush()

    # Dispatch Celery task
    from app.tasks.scan_session import run_attendance_session
    run_attendance_session.delay(str(session_id))

    await db.refresh(session)
    return session


@router.get("/{session_id}/scan-plan", response_model=ScanPlan)
async def get_scan_plan(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get the computed scan plan for a session."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.scan_plan:
        raise HTTPException(status_code=404, detail="No scan plan computed yet")
    return ScanPlan(**session.scan_plan)


@router.get("/{session_id}/coverage", response_model=CoverageResult)
async def get_coverage(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get current coverage (% of students recognized) for a session."""
    from app.agent.coverage_checker import check_coverage
    return await check_coverage(session_id, db)
