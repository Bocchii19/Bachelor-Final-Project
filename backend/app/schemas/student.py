"""Pydantic Schemas — Student."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class StudentBase(BaseModel):
    student_code: str = Field(..., max_length=20)  # "65A001"
    full_name: str = Field(..., max_length=100)
    email: Optional[str] = Field(None, max_length=100)


class StudentCreate(StudentBase):
    class_id: Optional[uuid.UUID] = None


class StudentUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=100)
    class_id: Optional[uuid.UUID] = None


class StudentRead(StudentBase):
    id: uuid.UUID
    class_id: Optional[uuid.UUID] = None
    enrolled_at: datetime

    model_config = {"from_attributes": True}


class ImportResult(BaseModel):
    """Result of importing students from Excel."""
    inserted: int = 0
    updated: int = 0
    errors: List[str] = Field(default_factory=list)
    total_rows: int = 0


class EnrollmentResult(BaseModel):
    """Result of face enrollment."""
    student_id: uuid.UUID
    embeddings_created: int
    images_saved: List[str]
    errors: List[str] = Field(default_factory=list)
