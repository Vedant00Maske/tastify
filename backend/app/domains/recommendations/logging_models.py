"""Recommendation logs and experiments (Milestone 6; spec §6.2 RecommendationLog, ADR-019).

Every personalized response is logged: one `recommendation_requests` row (surface, strategy,
model versions, experiment variant, context) and one `recommendation_logs` row per recommended
track (spec §6.2: user, track, category, ranking score, model version, request id). Feedback
events can carry the request id, which is how experiments measure outcomes. Logs are personal
data: deleted with the user and pruned after `RECOMMENDATION_LOG_RETENTION_DAYS`.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.catalogue.models import created_at_column, uuid_pk

EXPERIMENT_STATUSES = ("draft", "running", "stopped")


class RecommendationRequest(Base):
    __tablename__ = "recommendation_requests"
    __table_args__ = (
        Index("ix_recommendation_requests_user_id_created_at", "user_id", "created_at"),
        Index("ix_recommendation_requests_experiment", "experiment_key", "variant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)  # the response's request_id
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(32))
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    experiment_key: Mapped[str | None] = mapped_column(String(64))
    variant: Mapped[str | None] = mapped_column(String(32))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    items: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()


class RecommendationLog(Base):
    __tablename__ = "recommendation_logs"
    __table_args__ = (
        Index("ix_recommendation_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_recommendation_logs_request_id", "request_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation_requests.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    recommendation_category: Mapped[str] = mapped_column(String(32))
    ranking_score: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at_column()


class Experiment(Base):
    """An online experiment: users are split deterministically between weighted variants, each
    with the parameters it changes (e.g. {"context_weight": 0.1})."""

    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'running', 'stopped')", name="status_valid"),
    )

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    surface: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    # [{"name": "control", "weight": 0.5, "params": {...}}, ...]
    variants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
