"""Async SQLAlchemy engine, session factory and the declarative base for all ORM models."""

import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import Engine, MetaData, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core import metrics
from app.core.config import get_settings

# Deterministic constraint names keep Alembic autogenerate output stable and reviewable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _engine_options() -> dict[str, Any]:
    settings = get_settings()
    return {
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        # Connections are recycled before typical proxy/firewall idle timeouts drop them.
        "pool_recycle": 1800,
        "connect_args": {
            "server_settings": {
                "application_name": f"tastify-{settings.environment}",
                # A runaway query is cancelled by PostgreSQL instead of holding a connection.
                "statement_timeout": str(settings.db_statement_timeout_ms),
            }
        },
    }


def _time_statements(target: Engine) -> None:
    """Database query latency (spec §15) per operation (SELECT, INSERT, ...)."""

    @event.listens_for(target, "before_cursor_execute")
    def _start(conn: Any, _cursor: Any, _stmt: str, _params: Any, _ctx: Any, _many: bool) -> None:
        # Statements on one connection run one at a time; a failed one is simply overwritten.
        conn.info["query_started"] = time.perf_counter()

    @event.listens_for(target, "after_cursor_execute")
    def _stop(
        conn: Any, _cursor: Any, statement: str, _params: Any, _ctx: Any, _many: bool
    ) -> None:
        started = conn.info.pop("query_started", None)
        if started is None:
            return
        operation = statement.lstrip().split(" ", 1)[0].upper()[:10] or "OTHER"
        if operation not in _OPERATIONS:
            operation = "OTHER"
        metrics.DB_QUERY_LATENCY.labels(operation).observe(time.perf_counter() - started)


_OPERATIONS = {"SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "BEGIN", "COMMIT", "ROLLBACK"}

engine = create_async_engine(get_settings().database_url, **_engine_options())
_time_statements(engine.sync_engine)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that is closed when the request finishes."""
    async with SessionFactory() as session:
        yield session
