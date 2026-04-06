"""ORM Model — cameras."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rtsp_url: Mapped[str] = mapped_column(Text(), nullable=False)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="fixed"
    )  # "ptz" | "fixed"

    # ONVIF settings (for PTZ cameras)
    onvif_host: Mapped[str | None] = mapped_column(String(100), nullable=True)
    onvif_port: Mapped[int | None] = mapped_column(Integer(), nullable=True, default=80)
    onvif_user: Mapped[str | None] = mapped_column(String(100), nullable=True)
    onvif_password: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def __repr__(self) -> str:
        return f"<Camera {self.name} type={self.type} active={self.is_active}>"
