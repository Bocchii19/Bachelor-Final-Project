"""ORM Model — students."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_code: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )  # "65A001"
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id"), nullable=True
    )
    enrolled_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    class_ = relationship("Class", back_populates="students", lazy="selectin")
    face_embeddings = relationship(
        "FaceEmbedding", back_populates="student", cascade="all, delete-orphan", lazy="selectin"
    )
    attendance_records = relationship(
        "AttendanceRecord", back_populates="student", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Student {self.student_code} name={self.full_name}>"
