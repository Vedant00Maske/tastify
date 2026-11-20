"""Celery application, using Redis as broker and result backend.

Worker: `celery -A app.workers.celery_app:celery_app worker --pool threads --concurrency 4`
(tasks are I/O bound; threads also work on Windows and keep one metrics registry per process).
Schedule: `celery -A app.workers.celery_app:celery_app beat` (exactly one beat per deployment).
"""

import logging
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    beat_init,
    celeryd_init,
    task_failure,
    task_retry,
    task_success,
    worker_ready,
)

from app.core import metrics
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.observability import init_error_tracking

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
    # Results are not read back by the API; keep the backend small.
    result_expires=3600,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "daily-prune": {
            "task": "maintenance.prune",
            "schedule": crontab(hour=3, minute=30),
        },
    },
)

logger = logging.getLogger(__name__)


def _task_name(sender: Any) -> str:
    return str(getattr(sender, "name", None) or "unknown")


@task_success.connect
def _success(sender: Any = None, **_: Any) -> None:
    metrics.BACKGROUND_JOBS.labels(_task_name(sender), "success").inc()


@task_failure.connect
def _failure(sender: Any = None, **_: Any) -> None:
    metrics.BACKGROUND_JOBS.labels(_task_name(sender), "failure").inc()


@task_retry.connect
def _retry(sender: Any = None, **_: Any) -> None:
    metrics.BACKGROUND_JOBS.labels(_task_name(sender), "retry").inc()


@worker_ready.connect
def _serve_metrics(**_: Any) -> None:
    """Background job metrics (spec §15) for Prometheus, on WORKER_METRICS_PORT."""
    if not settings.metrics_enabled:
        return
    from prometheus_client import start_http_server

    if settings.backup_status_file:
        metrics.register_backup_status(settings.backup_status_file)
    try:
        start_http_server(settings.worker_metrics_port)
    except OSError:
        logger.warning("worker metrics port %d is in use", settings.worker_metrics_port)


@celeryd_init.connect
@beat_init.connect
def _init_process(**_: Any) -> None:
    """Logging and error tracking for worker and beat processes only (the API imports this
    module to queue tasks and has its own setup)."""
    configure_logging(settings.log_level, settings.log_format)
    init_error_tracking("worker")
