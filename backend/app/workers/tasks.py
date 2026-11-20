"""Background tasks. All are idempotent or at-least-once safe (`task_acks_late`): a task may run
again after a worker crash."""

import asyncio
import logging
import smtplib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any, TypeVar

from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import mail, metrics
from app.core.config import get_settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

T = TypeVar("T")


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check that the worker and broker are wired correctly."""
    return "pong"


@celery_app.task(
    name="mail.send",
    bind=True,
    ignore_result=True,
    # The mail server is down or refusing: retry with exponential backoff for about a day.
    autoretry_for=(smtplib.SMTPException, OSError),
    retry_backoff=30,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=30,
)
def send_email(self: Task[Any, None], message: dict[str, Any]) -> None:
    """Deliver one e-mail (queued by `CeleryMailer`). The message holds a single-use link, so it
    is never logged; only its kind is."""
    email = mail.Email(**message)
    try:
        mail.deliver(email)
    except (smtplib.SMTPException, OSError):
        retries = self.request.retries
        outcome = "failed" if retries >= (self.max_retries or 0) else "retry"
        metrics.EMAILS.labels(email.kind, outcome).inc()
        logger.warning("%s e-mail not delivered (attempt %d)", email.kind, retries + 1)
        raise
    metrics.EMAILS.labels(email.kind, "sent").inc()
    logger.info("%s e-mail delivered", email.kind)


def run_with_session(work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run async database work from a (threaded) worker: a private event loop and engine, since
    asyncpg connections cannot cross event loops."""

    async def main() -> T:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


@celery_app.task(name="maintenance.prune", ignore_result=True)
def prune() -> dict[str, int]:
    """Daily retention: expired sessions and e-mail links, old recommendation logs, stale
    provider ids (app.domains.maintenance)."""
    from app.domains import maintenance

    return asdict(run_with_session(maintenance.prune))


@celery_app.task(name="recommendations.precompute", ignore_result=True)
def precompute_recommendations(user_id: str, zone: str | None = None) -> list[str]:
    """Compute the user's home-page mixes for their new state into the response cache
    (app.domains.recommendations.precompute). Idempotent: already-cached mixes are skipped."""
    from redis.asyncio import Redis

    from app.domains.recommendations import precompute

    async def work(session: AsyncSession) -> list[str]:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            return await precompute.warm(session, redis, uuid.UUID(user_id), zone)
        finally:
            await redis.aclose()

    return run_with_session(work)
