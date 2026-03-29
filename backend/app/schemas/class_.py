"""Pydantic Schemas — Class."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ClassBase(BaseModel):
    name: str = Field(..., max_length=100)  # "CNTT-K65A"
    subject: str = Field(..., max_length=100)  # "Nhập môn CNTT"
    room: Optional[str] = Field(None, max_length=50)
    capacity: int = Field(default=40, ge=1)


class ClassCreate(ClassBase):
    teacher_id: Optional[uuid.UUID] = None


class ClassUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    subject: Optional[str] = Field(None, max_length=100)
    room: Optional[str] = Field(None, max_length=50)
    capacity: Optional[int] = Field(None, ge=1)
    teacher_id: Optional[uuid.UUID] = None


class ClassRead(ClassBase):
    id: uuid.UUID
    teacher_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}
