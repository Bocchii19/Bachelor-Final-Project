"""ORM Model — attendance_records (bảng trung tâm)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("student_id", "session_id", name="uq_student_session"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'present' | 'absent' | 'unknown'
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    zone_id: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "zone_A"
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    student = relationship("Student", back_populates="attendance_records", lazy="selectin")
    session = relationship("Session", back_populates="attendance_records", lazy="selectin")

    def __repr__(self) -> str:
        return f"<AttendanceRecord student={self.student_id} status={self.status}>"
