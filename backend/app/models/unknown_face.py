"""ORM Model — unknown_faces (queue for admin verification)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UnknownFace(Base):
    __tablename__ = "unknown_faces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    best_match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=True
    )
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_id: Mapped[str | None] = mapped_column(String(10), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | matched | stranger | false_positive
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    resolved_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=True
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    session = relationship("Session", back_populates="unknown_faces", lazy="selectin")
    best_match = relationship(
        "Student", foreign_keys=[best_match_id], lazy="selectin"
    )
    resolved_student = relationship(
        "Student", foreign_keys=[resolved_to], lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<UnknownFace session={self.session_id} status={self.status}>"
