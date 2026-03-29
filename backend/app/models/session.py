"""ORM Model — sessions (buổi học)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import Date, ForeignKey, Integer, String, Time, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("class_id", "session_date", name="uq_class_session_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False, index=True
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    enrolled_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scan_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled"
    )  # scheduled | scanning | done
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    class_ = relationship("Class", back_populates="sessions", lazy="selectin")
    attendance_records = relationship(
        "AttendanceRecord", back_populates="session", lazy="selectin"
    )
    unknown_faces = relationship(
        "UnknownFace", back_populates="session", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Session {self.session_date} status={self.status}>"
