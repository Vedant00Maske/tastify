"""Data source registration and ingestion job bookkeeping."""

import hashlib
import json
import logging
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import DataSource, IngestionError, IngestionJob, RawRecord

logger = logging.getLogger(__name__)

# Keep the error table useful for diagnosis without letting one bad batch flood it.
MAX_ERRORS_PER_CODE = 200


async def ensure_data_source(session: AsyncSession, **fields: Any) -> uuid.UUID:
    """Insert or refresh a data source (keyed by `key`) and return its id."""
    values = insert(DataSource).values(**fields)
    statement = values.on_conflict_do_update(
        index_elements=[DataSource.key],
        set_={name: values.excluded[name] for name in fields if name != "key"},
    ).returning(DataSource.id)
    source_id: uuid.UUID = (await session.execute(statement)).scalar_one()
    return source_id


async def source_id_for(session: AsyncSession, key: str) -> uuid.UUID:
    source_id = await session.scalar(select(DataSource.id).where(DataSource.key == key))
    if source_id is None:
        raise LookupError(f"data source {key!r} is not registered")
    return source_id


def payload_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def store_raw_record(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    entity_type: str,
    external_id: str,
    payload: dict[str, Any],
    job_id: uuid.UUID | None,
) -> None:
    statement = insert(RawRecord).values(
        source_id=source_id,
        entity_type=entity_type,
        external_id=external_id,
        payload=payload,
        payload_sha256=payload_sha256(payload),
        job_id=job_id,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["source_id", "entity_type", "external_id"],
            set_={
                "payload": statement.excluded.payload,
                "payload_sha256": statement.excluded.payload_sha256,
                "job_id": statement.excluded.job_id,
                "fetched_at": datetime.now(UTC),
            },
        )
    )


class JobRecorder:
    """Tracks one pipeline stage run: parameters, counters, and sampled errors.

    Use as an async context manager so a crash marks the job as failed instead of leaving it
    "running" forever.
    """

    def __init__(self, session: AsyncSession, job_id: uuid.UUID) -> None:
        self.session = session
        self.job_id = job_id
        self.stats: Counter[str] = Counter()
        self.error_counts: Counter[str] = Counter()
        self._pending_errors: list[dict[str, Any]] = []
        self.finished = False

    async def __aenter__(self) -> "JobRecorder":
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, _tb: object
    ) -> None:
        if exc is not None and not self.finished:
            await self.session.rollback()
            self._pending_errors = []
            await self.finish("failed", f"{type(exc).__name__}: {exc}"[:2000])

    @classmethod
    async def start(
        cls, session: AsyncSession, source_id: uuid.UUID, stage: str, parameters: dict[str, Any]
    ) -> "JobRecorder":
        job_id = (
            await session.execute(
                insert(IngestionJob)
                .values(source_id=source_id, stage=stage, parameters=parameters)
                .returning(IngestionJob.id)
            )
        ).scalar_one()
        await session.commit()
        return cls(session, job_id)

    def error(
        self,
        stage: str,
        error_code: str,
        record_ref: str | None,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.error_counts[error_code] += 1
        if self.error_counts[error_code] <= MAX_ERRORS_PER_CODE:
            self._pending_errors.append(
                {
                    "job_id": self.job_id,
                    "stage": stage,
                    "error_code": error_code,
                    "record_ref": record_ref,
                    "message": message[:2000],
                    "payload": payload,
                }
            )

    async def flush(self) -> None:
        if self._pending_errors:
            await self.session.execute(insert(IngestionError), self._pending_errors)
            self._pending_errors = []

    async def finish(self, status: str = "succeeded", error_message: str | None = None) -> None:
        self.finished = True
        await self.flush()
        stats = {**self.stats, "errors": dict(self.error_counts)}
        await self.session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == self.job_id)
            .values(
                status=status,
                stats=stats,
                error_message=error_message,
                finished_at=datetime.now(UTC),
            )
        )
        await self.session.commit()
        logger.info("Job %s finished (%s): %s", self.job_id, status, stats)
