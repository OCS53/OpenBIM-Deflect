"""Celery 앱. 브로커·백엔드 URL은 환경 변수 `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`."""

from __future__ import annotations

import os

from celery import Celery

_broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    "openbim_deflect",
    broker=_broker,
    backend=_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=int(os.environ.get("CELERY_TASK_TIME_LIMIT_SEC", "3600")),
)

# 태스크 모듈 로드(등록)
import app.tasks.pipeline  # noqa: E402, F401
