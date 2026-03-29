"""Pydantic Schemas — Attendance Records & Sheet Pivot."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AttendanceRecordRead(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    session_id: uuid.UUID
    status: str
    confidence: Optional[float] = None
    captured_at: Optional[datetime] = None
    zone_id: Optional[str] = None
    verified_by: Optional[uuid.UUID] = None
    verified_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AttendanceCell(BaseModel):
    """One cell in the pivot attendance sheet."""
    status: str  # 'present' | 'absent' | 'unknown'
    confidence: Optional[float] = None


class StudentRow(BaseModel):
    """One row in the attendance sheet: student info + per-session status."""
    student_id: uuid.UUID
    student_code: str
    full_name: str
    attendance: Dict[str, AttendanceCell]  # key = session_date ISO string
    present_count: int = 0
    total_sessions: int = 0
    attendance_rate: float = 0.0  # percentage 0–100


class SessionColumn(BaseModel):
    """Column metadata for the attendance sheet."""
    session_id: uuid.UUID
    session_date: date
    status: str  # session status: scheduled | scanning | done
    present_count: int = 0
    unknown_count: int = 0
    total_students: int = 0


class AttendanceSheetData(BaseModel):
    """Full attendance sheet data for frontend pivot rendering."""
    class_id: uuid.UUID
    class_name: str
    subject: str
    columns: List[SessionColumn]
    rows: List[StudentRow]


class AttendanceExportRequest(BaseModel):
    class_id: uuid.UUID
    date_from: Optional[date] = None
    date_to: Optional[date] = None
