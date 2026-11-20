"""Scheduled housekeeping (Milestone 7): enforce retention and keep tables bounded.

Runs daily from Celery beat (`maintenance.prune`) and on demand (`python -m app.cli prune`).
Every step is an idempotent delete by age, safe to repeat or to run concurrently.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.integrations.models import ProviderTrackId
from app.domains.integrations.service import TRACK_ID_MAX_AGE
from app.domains.recommendations import logging_service
from app.domains.users.models import AccountToken, UserSession

logger = logging.getLogger(__name__)

# Revoked sessions are kept briefly (so a user's own "signed out" state is consistent), then
# dropped; expired ones go immediately.
REVOKED_SESSION_KEEP = timedelta(days=7)
# Used or expired e-mail tokens carry no value after a day.
SPENT_TOKEN_KEEP = timedelta(days=1)


@dataclass(frozen=True)
class PruneResult:
    sessions: int
    account_tokens: int
    recommendation_requests: int
    provider_track_ids: int


async def prune(session: AsyncSession, now: datetime | None = None) -> PruneResult:
    now = now or datetime.now(UTC)
    sessions = await session.execute(
        delete(UserSession).where(
            or_(
                UserSession.expires_at < now,
                UserSession.revoked_at < now - REVOKED_SESSION_KEEP,
            )
        )
    )
    tokens = await session.execute(
        delete(AccountToken).where(
            or_(
                AccountToken.expires_at < now - SPENT_TOKEN_KEEP,
                AccountToken.used_at < now - SPENT_TOKEN_KEEP,
            )
        )
    )
    track_ids = await session.execute(
        delete(ProviderTrackId).where(ProviderTrackId.fetched_at < now - TRACK_ID_MAX_AGE)
    )
    await session.commit()
    logs = await logging_service.prune(session, get_settings().recommendation_log_retention_days)
    result = PruneResult(
        sessions=int(sessions.rowcount or 0),  # type: ignore[attr-defined]
        account_tokens=int(tokens.rowcount or 0),  # type: ignore[attr-defined]
        recommendation_requests=logs,
        provider_track_ids=int(track_ids.rowcount or 0),  # type: ignore[attr-defined]
    )
    logger.info("maintenance prune %s", result)
    return result
