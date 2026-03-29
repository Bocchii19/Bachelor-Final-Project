"""Pydantic Schemas — Unknown Faces (admin verification queue)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class UnknownFaceRead(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    image_path: str
    best_match_id: Optional[uuid.UUID] = None
    best_match_name: Optional[str] = None
    best_match_code: Optional[str] = None
    best_score: Optional[float] = None
    zone_id: Optional[str] = None
    captured_at: datetime
    status: str
    cluster_id: Optional[uuid.UUID] = None
    cluster_size: int = 1  # how many faces in the same cluster
    resolved_by: Optional[uuid.UUID] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MatchRequest(BaseModel):
    """Admin matches an unknown face to a student."""
    student_id: uuid.UUID


class BulkResolveRequest(BaseModel):
    """Resolve all faces in a cluster at once."""
    cluster_id: uuid.UUID
    action: str = Field(..., pattern="^(matched|stranger|false_positive)$")
    student_id: Optional[uuid.UUID] = None  # required if action == 'matched'


class BulkResolveResult(BaseModel):
    resolved_count: int
    action: str
    cluster_id: uuid.UUID
