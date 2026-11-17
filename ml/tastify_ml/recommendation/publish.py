"""Publishes trained models to the serving tables (one transaction per call).

A version is written as `retired`, filled with its serving rows, then activated while the
previously active version of the same type is retired and its serving rows deleted. Readers
therefore see either the old or the new version, and the vector indexes only hold active rows.
Publishing the same version string again replaces it (idempotent re-runs).
"""

import hashlib
import io
import json
import logging
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.recommendations.models import (
    SERVING_TABLES,
    ArtistEmbedding,
    ModelArtifact,
    ModelVersion,
    TrackCollaborativeFactors,
    TrackEmbedding,
    TrackPopularity,
)

logger = logging.getLogger(__name__)

BATCH = 2000


def version_string(model_type: str, trained_at: datetime, fingerprint: Mapping[str, Any]) -> str:
    """`<type>-<YYYYMMDD>-<hash of params and training data>`: equal inputs give equal versions."""
    digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, default=str).encode())
    return f"{model_type}-{trained_at:%Y%m%d}-{digest.hexdigest()[:8]}"


@dataclass(frozen=True)
class VersionSpec:
    model_type: str
    params: dict[str, Any]
    training_data: dict[str, Any]
    metrics: dict[str, Any]
    trained_at: datetime

    @property
    def version(self) -> str:
        return version_string(
            self.model_type,
            self.trained_at,
            {"params": self.params, "training_data": self.training_data},
        )


def _vector(values: npt.NDArray[np.float32]) -> list[float]:
    return [float(v) for v in values]


async def _insert_batches(session: AsyncSession, table: Any, rows: Iterable[dict[str, Any]]) -> int:
    batch: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        batch.append(row)
        if len(batch) == BATCH:
            await session.execute(insert(table), batch)
            total, batch = total + len(batch), []
    if batch:
        await session.execute(insert(table), batch)
        total += len(batch)
    return total


async def _create_version(session: AsyncSession, spec: VersionSpec) -> ModelVersion:
    await session.execute(delete(ModelVersion).where(ModelVersion.version == spec.version))
    version = ModelVersion(
        model_type=spec.model_type,
        version=spec.version,
        status="retired",
        params=spec.params,
        training_data=spec.training_data,
        metrics=spec.metrics,
        trained_at=spec.trained_at,
    )
    session.add(version)
    await session.flush()
    return version


async def _activate(session: AsyncSession, version: ModelVersion) -> list[str]:
    """Retire the current active version of this type, delete its rows, activate `version`."""
    previous = (
        await session.scalars(
            select(ModelVersion).where(
                ModelVersion.model_type == version.model_type,
                ModelVersion.status == "active",
                ModelVersion.id != version.id,
            )
        )
    ).all()
    retired_ids = [p.id for p in previous]
    if retired_ids:
        await session.execute(
            update(ModelVersion).where(ModelVersion.id.in_(retired_ids)).values(status="retired")
        )
    await session.execute(
        update(ModelVersion)
        .where(ModelVersion.id == version.id)
        .values(status="active", activated_at=datetime.now(UTC))
    )
    # Retired versions keep their registry row (params, metrics) but not their serving rows.
    stale = select(ModelVersion.id).where(
        ModelVersion.model_type == version.model_type, ModelVersion.status == "retired"
    )
    for table in SERVING_TABLES:
        await session.execute(delete(table).where(table.model_version_id.in_(stale)))
    return [p.version for p in previous]


async def publish_popularity(
    session: AsyncSession, spec: VersionSpec, popularity: pd.DataFrame
) -> dict[str, Any]:
    started = time.perf_counter()
    version = await _create_version(session, spec)
    trending = popularity["trending_score"].to_numpy(dtype=np.float64)
    rows = (
        {
            "model_version_id": version.id,
            "track_id": uuid.UUID(track_id),
            "listeners": int(listeners),
            "plays": int(plays),
            "score": float(score),
            "recent_listeners": int(recent),
            "trending_score": None if np.isnan(trend) else float(trend),
        }
        for track_id, listeners, plays, score, recent, trend in zip(
            popularity["track_id"],
            popularity["listeners"],
            popularity["plays"],
            popularity["score"],
            popularity["recent_listeners"],
            trending,
            strict=True,
        )
    )
    written = await _insert_batches(session, TrackPopularity, rows)
    retired = await _activate(session, version)
    await session.commit()
    return {
        "version": spec.version,
        "rows": written,
        "retired": retired,
        "seconds": round(time.perf_counter() - started, 1),
    }


async def publish_content(
    session: AsyncSession,
    spec: VersionSpec,
    track_ids: npt.NDArray[np.object_],
    embeddings: npt.NDArray[np.float32],
    artist_ids: npt.NDArray[np.object_],
    artist_vectors: npt.NDArray[np.float32],
    artist_track_counts: npt.NDArray[np.int64],
) -> dict[str, Any]:
    """Writes track and artist embeddings. Rows without content (zero vectors) are skipped."""
    started = time.perf_counter()
    version = await _create_version(session, spec)
    has_track = np.linalg.norm(embeddings, axis=1) > 0
    tracks_written = await _insert_batches(
        session,
        TrackEmbedding,
        (
            {
                "model_version_id": version.id,
                "track_id": uuid.UUID(str(track_id)),
                "embedding": _vector(vector),
            }
            for track_id, vector, keep in zip(track_ids, embeddings, has_track, strict=True)
            if keep
        ),
    )
    has_artist = (artist_track_counts > 0) & (np.linalg.norm(artist_vectors, axis=1) > 0)
    artists_written = await _insert_batches(
        session,
        ArtistEmbedding,
        (
            {
                "model_version_id": version.id,
                "artist_id": uuid.UUID(str(artist_id)),
                "track_count": int(count),
                "embedding": _vector(vector),
            }
            for artist_id, vector, count, keep in zip(
                artist_ids, artist_vectors, artist_track_counts, has_artist, strict=True
            )
            if keep
        ),
    )
    retired = await _activate(session, version)
    await session.commit()
    return {
        "version": spec.version,
        "track_embeddings": tracks_written,
        "artist_embeddings": artists_written,
        "retired": retired,
        "seconds": round(time.perf_counter() - started, 1),
    }


# --- Milestone 3: collaborative and hybrid ---------------------------------------------------


async def _copy_rows(
    session: AsyncSession, table: str, columns: list[str], records: list[tuple[Any, ...]]
) -> int:
    """Bulk insert with PostgreSQL COPY (binary) through the session's asyncpg connection."""
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    driver = raw.driver_connection
    if driver is None:  # pragma: no cover - asyncpg always exposes its connection
        raise RuntimeError("no driver connection for COPY")
    await driver.copy_records_to_table(table, records=records, columns=columns)
    return len(records)


async def _add_artifact(
    session: AsyncSession, version: ModelVersion, name: str, media_type: str, content: bytes
) -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    await session.execute(
        insert(ModelArtifact).values(
            model_version_id=version.id,
            name=name,
            media_type=media_type,
            content=content,
            sha256=digest,
        )
    )
    return {"name": name, "bytes": len(content), "sha256": digest[:16]}


async def publish_collaborative(
    session: AsyncSession,
    spec: VersionSpec,
    track_ids: npt.NDArray[np.object_],
    item_factors: npt.NDArray[np.float32],
    idf: npt.NDArray[np.float64],
    listened: npt.NDArray[np.bool_],
    gram: npt.NDArray[np.float64],
    similarity: Any,
) -> dict[str, Any]:
    """ALS factors of listened tracks, item-item neighbour rows and the Gram matrix artifact."""
    started = time.perf_counter()
    version = await _create_version(session, spec)
    factors_written = await _insert_batches(
        session,
        TrackCollaborativeFactors,
        (
            {
                "model_version_id": version.id,
                "track_id": uuid.UUID(str(track_id)),
                "factors": _vector(vector),
                "idf": float(weight),
            }
            for track_id, vector, weight, keep in zip(
                track_ids, item_factors, idf, listened, strict=True
            )
            if keep
        ),
    )
    coo = similarity.tocoo()
    keep = coo.data > 0
    uuids = [uuid.UUID(str(t)) for t in track_ids]
    records = [
        (version.id, uuids[i], uuids[j], float(score))
        for i, j, score in zip(coo.row[keep], coo.col[keep], coo.data[keep], strict=True)
    ]
    neighbours = await _copy_rows(
        session,
        "track_neighbours",
        ["model_version_id", "track_id", "neighbour_id", "score"],
        records,
    )
    buffer = io.BytesIO()
    np.save(buffer, gram.astype(np.float64), allow_pickle=False)
    artifact = await _add_artifact(session, version, "gram", "application/x-npy", buffer.getvalue())
    retired = await _activate(session, version)
    await session.commit()
    return {
        "version": spec.version,
        "track_factors": factors_written,
        "neighbour_rows": neighbours,
        "artifacts": [artifact],
        "retired": retired,
        "seconds": round(time.perf_counter() - started, 1),
    }


async def publish_hybrid(
    session: AsyncSession, spec: VersionSpec, artifacts: dict[str, bytes]
) -> dict[str, Any]:
    """The hybrid version holds settings in `params` and rankers as JSON artifacts."""
    started = time.perf_counter()
    version = await _create_version(session, spec)
    written = [
        await _add_artifact(session, version, name, "application/json", content)
        for name, content in artifacts.items()
    ]
    retired = await _activate(session, version)
    await session.commit()
    return {
        "version": spec.version,
        "artifacts": written,
        "retired": retired,
        "seconds": round(time.perf_counter() - started, 1),
    }
