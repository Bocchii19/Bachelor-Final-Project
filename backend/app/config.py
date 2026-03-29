"""
CV Attendance System — Application Settings.

Loads configuration from environment variables with sensible defaults.
Supports Jetson (ARM64 + TensorRT), PC (x86 + CUDA), and CPU-only deployments.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Central configuration loaded from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- App ----
    APP_NAME: str = "CV Attendance System"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    CORS_ORIGINS: str = '["http://localhost:3000","http://localhost:5173"]'

    @property
    def cors_origins_list(self) -> List[str]:
        try:
            return json.loads(self.CORS_ORIGINS)
        except (json.JSONDecodeError, TypeError):
            return ["http://localhost:3000"]

    # ---- Database ----
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/cv_attendance"

    @property
    def database_url_sync(self) -> str:
        """Sync URL for Alembic migrations."""
        return self.DATABASE_URL.replace("+asyncpg", "")

    # ---- Redis / Celery ----
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---- Camera PTZ ----
    PTZ_HOST: str = ""
    PTZ_PORT: int = 80
    PTZ_USER: str = "admin"
    PTZ_PASSWORD: str = ""
    PTZ_RTSP_URL: str = ""

    # ---- CV Models ----
    INSIGHTFACE_MODEL_PACK: str = "buffalo_l"
    LIVENESS_MODEL_PATH: str = "./models/anti_spoof_model.onnx"

    # ---- Thresholds ----
    CONFIDENCE_AUTO_PRESENT: float = 0.75
    CONFIDENCE_SUGGEST: float = 0.45
    COVERAGE_TARGET: float = 0.90

    # ---- ONNX Runtime ----
    ONNX_PROVIDERS: str = ""  # comma-separated, empty = auto-detect

    @property
    def onnx_providers_list(self) -> Optional[List[str]]:
        """Return explicit providers or None for auto-detection."""
        if self.ONNX_PROVIDERS:
            return [p.strip() for p in self.ONNX_PROVIDERS.split(",")]
        return None

    # ---- Storage ----
    MEDIA_ROOT: str = "./media"

    # ---- S3 (optional) ----
    S3_BUCKET: Optional[str] = None
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "ap-southeast-1"


@lru_cache
def get_settings() -> Settings:
    """Singleton settings instance."""
    settings = Settings()
    logger.info("Settings loaded: APP_NAME=%s, DEBUG=%s", settings.APP_NAME, settings.DEBUG)
    return settings
