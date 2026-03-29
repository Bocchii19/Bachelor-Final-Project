"""
CV Attendance System — FastAPI Application Entry Point.

Registers routers, CORS, and lifecycle events.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import close_db, init_db

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    # --- Startup ---
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logger.info("Starting %s …", settings.APP_NAME)
    await init_db()

    # Log ONNX Runtime providers
    try:
        from app.cv.runtime import get_available_providers
        providers = get_available_providers()
        logger.info("ONNX Runtime providers available: %s", providers)
    except Exception as exc:
        logger.warning("Could not detect ONNX providers: %s", exc)

    yield

    # --- Shutdown ---
    logger.info("Shutting down %s …", settings.APP_NAME)
    await close_db()


def create_app() -> FastAPI:
    """Application factory."""
    _app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="Hệ thống điểm danh tự động bằng Computer Vision với PTZ camera",
        lifespan=lifespan,
    )

    # --- CORS ---
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Static files (uploaded media) ---
    import os
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    _app.mount("/media", StaticFiles(directory=settings.MEDIA_ROOT), name="media")

    # --- Routers ---
    from app.api.auth import router as auth_router
    from app.api.classes import router as classes_router
    from app.api.students import router as students_router
    from app.api.sessions import router as sessions_router
    from app.api.attendance import router as attendance_router
    from app.api.unknown_faces import router as unknown_faces_router
    from app.api.ptz import router as ptz_router

    _app.include_router(auth_router, prefix="/auth", tags=["Auth"])
    _app.include_router(classes_router, prefix="/classes", tags=["Classes"])
    _app.include_router(students_router, prefix="/students", tags=["Students"])
    _app.include_router(sessions_router, prefix="/sessions", tags=["Sessions"])
    _app.include_router(attendance_router, prefix="/attendance", tags=["Attendance"])
    _app.include_router(unknown_faces_router, prefix="/unknown-faces", tags=["Unknown Faces"])
    _app.include_router(ptz_router, prefix="/ptz", tags=["PTZ Camera"])

    @_app.get("/health")
    async def health_check():
        return {"status": "healthy", "app": settings.APP_NAME}

    return _app


app = create_app()
