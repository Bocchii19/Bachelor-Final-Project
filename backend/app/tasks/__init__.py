"""
Celery Tasks — App configuration.

Configures Celery with Redis broker for async task processing.
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "cv_attendance",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.scan_session",
        "app.tasks.process_frame",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # important for GPU tasks
    task_time_limit=600,  # 10 min max per task
    task_soft_time_limit=540,  # soft limit at 9 min
)
