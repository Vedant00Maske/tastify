"""Recording what was recommended, and the experiment each response belonged to (ADR-019)."""

import logging
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.recommendations.experiments import (
    NEGATIVE_FEEDBACK,
    POSITIVE_FEEDBACK,
    Assignment,
    VariantOutcome,
    assign,
    compare,
    parse_variants,
)
from app.domains.recommendations.logging_models import (
    Experiment,
    RecommendationLog,
    RecommendationRequest,
)
from app.domains.recommendations.schemas import RecommendationResponse
from app.domains.users.models import UserInteraction

logger = logging.getLogger(__name__)

ATTRIBUTION_WINDOW = timedelta(days=7)
_EXPERIMENT_CACHE_SECONDS = 30.0
_experiments: dict[str, tuple[float, list[Experiment]]] = {}


class ExperimentNotFoundError(LookupError):
    pass


async def running_experiments(session: AsyncSession, surface: str) -> list[Experiment]:
    """Running experiments on a surface, cached briefly (they change rarely)."""
    cached = _experiments.get(surface)
    now = time.monotonic()
    if cached and now - cached[0] < _EXPERIMENT_CACHE_SECONDS:
        return cached[1]
    rows = list(
        (
            await session.scalars(
                select(Experiment)
                .where(Experiment.surface == surface, Experiment.status == "running")
                .order_by(Experiment.key)
            )
        ).all()
    )
    _experiments[surface] = (now, rows)
    return rows


def forget_experiments() -> None:
    _experiments.clear()


async def assignment_for(
    session: AsyncSession, surface: str, user_id: uuid.UUID | None
) -> Assignment | None:
    """The user's variant in the surface's running experiment (the first, by key), if any."""
    if user_id is None:
        return None
    experiments = await running_experiments(session, surface)
    if not experiments:
        return None
    experiment = experiments[0]
    return assign(experiment.key, parse_variants(experiment.variants), user_id)


async def record(
    session: AsyncSession,
    response: RecommendationResponse,
    *,
    user_id: uuid.UUID | None,
    category: str,
    assignment: Assignment | None = None,
    context: dict[str, Any] | None = None,
    latency_ms: int | None = None,
) -> None:
    """Log one response and its items (spec §6.2). Logging never breaks a response."""
    try:
        session.add(
            RecommendationRequest(
                id=response.request_id,
                user_id=user_id,
                category=category,
                strategy=response.strategy.value,
                model_versions=dict(response.model_versions),
                experiment_key=assignment.experiment if assignment else None,
                variant=assignment.variant if assignment else None,
                context=context or {},
                items=len(response.recommendations),
                latency_ms=latency_ms,
            )
        )
        await session.flush()
        if response.recommendations:
            await session.execute(
                insert(RecommendationLog),
                [
                    {
                        "request_id": response.request_id,
                        "user_id": user_id,
                        "track_id": item.track_id,
                        "position": position,
                        "recommendation_category": category,
                        "ranking_score": item.score,
                        "model_version": response.model_version[:128],
                    }
                    for position, item in enumerate(response.recommendations)
                ],
            )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("recommendation log failed request_id=%s", response.request_id)


async def prune(session: AsyncSession, retention_days: int) -> int:
    """Delete logs older than the retention period (items go with their request)."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(
        delete(RecommendationRequest).where(RecommendationRequest.created_at < cutoff)
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# --- experiments ------------------------------------------------------------------------------


async def save_experiment(
    session: AsyncSession,
    key: str,
    description: str,
    surface: str,
    variants: Sequence[dict[str, Any]],
) -> Experiment:
    parse_variants(variants)  # validate
    experiment = await session.get(Experiment, key)
    if experiment is None:
        experiment = Experiment(key=key, status="draft")
        session.add(experiment)
    experiment.description = description
    experiment.surface = surface
    experiment.variants = list(variants)
    await session.commit()
    forget_experiments()
    return experiment


async def set_status(session: AsyncSession, key: str, status: str) -> Experiment:
    experiment = await session.get(Experiment, key)
    if experiment is None:
        raise ExperimentNotFoundError(key)
    experiment.status = status
    now = datetime.now(UTC)
    if status == "running":
        experiment.started_at = experiment.started_at or now
    elif status == "stopped":
        experiment.stopped_at = now
    await session.commit()
    forget_experiments()
    return experiment


async def outcomes(session: AsyncSession, key: str) -> list[VariantOutcome]:
    """Per variant: users, responses, items shown, and attributed positive / negative feedback
    (on a shown track, within ATTRIBUTION_WINDOW of the response)."""
    requests = (
        select(
            RecommendationRequest.variant.label("variant"),
            func.count(func.distinct(RecommendationRequest.user_id)).label("users"),
            func.count().label("requests"),
            func.coalesce(func.sum(RecommendationRequest.items), 0).label("items"),
        )
        .where(RecommendationRequest.experiment_key == key)
        .group_by(RecommendationRequest.variant)
    )
    shown = {row.variant: row for row in (await session.execute(requests)).all() if row.variant}
    feedback = (
        select(
            RecommendationRequest.variant,
            UserInteraction.event_type,
            func.count(func.distinct(UserInteraction.id)),
        )
        .join(UserInteraction, UserInteraction.request_id == RecommendationRequest.id)
        .join(
            RecommendationLog,
            (RecommendationLog.request_id == RecommendationRequest.id)
            & (RecommendationLog.track_id == UserInteraction.track_id),
        )
        .where(
            RecommendationRequest.experiment_key == key,
            UserInteraction.user_id == RecommendationRequest.user_id,
            UserInteraction.occurred_at <= RecommendationRequest.created_at + ATTRIBUTION_WINDOW,
            UserInteraction.event_type.in_(POSITIVE_FEEDBACK + NEGATIVE_FEEDBACK),
        )
        .group_by(RecommendationRequest.variant, UserInteraction.event_type)
    )
    positive: dict[str, int] = {}
    negative: dict[str, int] = {}
    for variant, event_type, count in (await session.execute(feedback)).all():
        if variant is None:
            continue
        target = positive if event_type in POSITIVE_FEEDBACK else negative
        target[variant] = target.get(variant, 0) + int(count)
    return [
        VariantOutcome(
            name=name,
            users=int(row.users),
            requests=int(row.requests),
            items=int(row.items),
            positive=positive.get(name, 0),
            negative=negative.get(name, 0),
        )
        for name, row in sorted(shown.items())
    ]


async def report(session: AsyncSession, key: str) -> dict[str, Any]:
    experiment = await session.get(Experiment, key)
    if experiment is None:
        raise ExperimentNotFoundError(key)
    results = await outcomes(session, key)
    variants = parse_variants(experiment.variants)
    by_name = {r.name: r for r in results}
    control_name = variants[0].name
    comparisons = [
        compare(by_name[control_name], by_name[v.name])
        for v in variants[1:]
        if control_name in by_name and v.name in by_name
    ]
    return {
        "experiment": key,
        "status": experiment.status,
        "surface": experiment.surface,
        "variants": [
            {
                "name": r.name,
                "users": r.users,
                "requests": r.requests,
                "items": r.items,
                "positive": r.positive,
                "negative": r.negative,
                "positive_rate": r.positive_rate,
                "negative_rate": r.negative_rate,
            }
            for r in results
        ],
        "comparisons": comparisons,
    }
