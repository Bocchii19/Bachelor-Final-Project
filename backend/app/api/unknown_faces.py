"""Unknown Faces API — Admin verification queue."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_admin
from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.models.student import Student
from app.models.unknown_face import UnknownFace
from app.models.user import User
from app.schemas.unknown_face import (
    BulkResolveRequest,
    BulkResolveResult,
    MatchRequest,
    UnknownFaceRead,
)

router = APIRouter()


@router.get("/", response_model=List[UnknownFaceRead])
async def list_unknown_faces(
    session_id: Optional[uuid.UUID] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    cluster_id: Optional[uuid.UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List unknown faces with optional filters."""
    stmt = select(UnknownFace)
    if session_id:
        stmt = stmt.where(UnknownFace.session_id == session_id)
    if status_filter:
        stmt = stmt.where(UnknownFace.status == status_filter)
    if cluster_id:
        stmt = stmt.where(UnknownFace.cluster_id == cluster_id)
    stmt = stmt.order_by(UnknownFace.captured_at.desc()).offset(skip).limit(limit)

    result = await db.execute(stmt)
    faces = result.scalars().all()

    # Enrich with best_match info and cluster_size
    enriched = []
    for face in faces:
        data = UnknownFaceRead.model_validate(face)

        # Best match student info
        if face.best_match_id:
            match_result = await db.execute(
                select(Student).where(Student.id == face.best_match_id)
            )
            match_student = match_result.scalar_one_or_none()
            if match_student:
                data.best_match_name = match_student.full_name
                data.best_match_code = match_student.student_code

        # Cluster size
        if face.cluster_id:
            count_result = await db.execute(
                select(func.count()).where(UnknownFace.cluster_id == face.cluster_id)
            )
            data.cluster_size = count_result.scalar() or 1

        enriched.append(data)

    return enriched


@router.patch("/{face_id}/match", response_model=UnknownFaceRead)
async def match_face_to_student(
    face_id: uuid.UUID,
    body: MatchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """
    Admin matches an unknown face to a specific student.
    Creates/updates attendance record for this student+session.
    """
    result = await db.execute(select(UnknownFace).where(UnknownFace.id == face_id))
    face = result.scalar_one_or_none()
    if not face:
        raise HTTPException(status_code=404, detail="Unknown face not found")

    # Verify student exists
    student_result = await db.execute(select(Student).where(Student.id == body.student_id))
    if not student_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Student not found")

    # Update unknown face
    face.status = "matched"
    face.resolved_by = user.id
    face.resolved_at = datetime.now(timezone.utc)
    face.resolved_to = body.student_id

    # Create/update attendance record
    existing_att = await db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.student_id == body.student_id,
            AttendanceRecord.session_id == face.session_id,
        )
    )
    att = existing_att.scalar_one_or_none()
    if att:
        att.status = "present"
        att.verified_by = user.id
        att.verified_at = datetime.now(timezone.utc)
    else:
        att = AttendanceRecord(
            student_id=body.student_id,
            session_id=face.session_id,
            status="present",
            confidence=face.best_score,
            captured_at=face.captured_at,
            zone_id=face.zone_id,
            verified_by=user.id,
            verified_at=datetime.now(timezone.utc),
        )
        db.add(att)

    await db.flush()
    await db.refresh(face)
    return face


@router.patch("/{face_id}/stranger")
async def mark_as_stranger(
    face_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Mark unknown face as a stranger (not a student)."""
    result = await db.execute(select(UnknownFace).where(UnknownFace.id == face_id))
    face = result.scalar_one_or_none()
    if not face:
        raise HTTPException(status_code=404, detail="Unknown face not found")

    face.status = "stranger"
    face.resolved_by = user.id
    face.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "ok", "face_id": str(face_id)}


@router.patch("/{face_id}/false-positive")
async def mark_as_false_positive(
    face_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Mark as false positive (detection error, not a real face)."""
    result = await db.execute(select(UnknownFace).where(UnknownFace.id == face_id))
    face = result.scalar_one_or_none()
    if not face:
        raise HTTPException(status_code=404, detail="Unknown face not found")

    face.status = "false_positive"
    face.resolved_by = user.id
    face.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "ok", "face_id": str(face_id)}


@router.post("/bulk-resolve", response_model=BulkResolveResult)
async def bulk_resolve_cluster(
    body: BulkResolveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """
    Resolve all faces in a cluster at once.
    If action='matched', all faces in the cluster are matched to the given student.
    """
    # Find all faces in the cluster
    result = await db.execute(
        select(UnknownFace).where(
            UnknownFace.cluster_id == body.cluster_id,
            UnknownFace.status == "pending",
        )
    )
    faces = result.scalars().all()

    if not faces:
        raise HTTPException(status_code=404, detail="No pending faces in this cluster")

    if body.action == "matched" and not body.student_id:
        raise HTTPException(status_code=400, detail="student_id required for 'matched' action")

    now = datetime.now(timezone.utc)
    resolved_count = 0

    for face in faces:
        face.status = body.action
        face.resolved_by = user.id
        face.resolved_at = now
        if body.action == "matched" and body.student_id:
            face.resolved_to = body.student_id

            # Create attendance record
            existing = await db.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.student_id == body.student_id,
                    AttendanceRecord.session_id == face.session_id,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(
                    AttendanceRecord(
                        student_id=body.student_id,
                        session_id=face.session_id,
                        status="present",
                        confidence=face.best_score,
                        captured_at=face.captured_at,
                        zone_id=face.zone_id,
                        verified_by=user.id,
                        verified_at=now,
                    )
                )
        resolved_count += 1

    await db.flush()

    return BulkResolveResult(
        resolved_count=resolved_count,
        action=body.action,
        cluster_id=body.cluster_id,
    )
