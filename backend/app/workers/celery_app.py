"""Celery application, using Redis as broker and result backend."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "tastify",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Retry-safe processing: a task is acknowledged only after it finishes, so work held by a
    # crashed worker is redelivered. Tasks must therefore be idempotent.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)
