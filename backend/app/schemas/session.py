"""Pydantic Schemas — Session & Scan Plan."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ZoneConfig(BaseModel):
    id: str  # "zone_A"
    preset: int  # preset token / number
    pan: float = 0.0
    tilt: float = 0.0


class ScanPlan(BaseModel):
    zones: List[ZoneConfig]
    sweeps: int
    dwell_seconds: float
    move_seconds: float
    total_seconds: float
    coverage_threshold: float


class CoverageResult(BaseModel):
    session_id: uuid.UUID
    recognized_count: int
    enrolled_count: int
    coverage_pct: float  # 0.0 – 100.0
    target_pct: float
    is_sufficient: bool
    missing_zones: List[str] = Field(default_factory=list)


class SessionBase(BaseModel):
    class_id: uuid.UUID
    session_date: date
    start_time: time
    end_time: time
    enrolled_count: int = Field(ge=1)


class SessionCreate(SessionBase):
    pass


class SessionUpdate(BaseModel):
    session_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    enrolled_count: Optional[int] = Field(None, ge=1)
    status: Optional[str] = None


class SessionRead(SessionBase):
    id: uuid.UUID
    scan_plan: Optional[Dict[str, Any]] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
