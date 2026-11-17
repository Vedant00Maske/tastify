"""Exact vs approximate nearest-neighbour retrieval over the published track embeddings.

Ground truth is brute-force cosine similarity in numpy. pgvector is queried through the same
repository method the API uses: once with index scans disabled (exact sequential scan) and then
through the HNSW index at several `ef_search` values, measuring recall@K and latency.

Many tracks share an identical embedding (same artist, genres and decade), so the K-th nearest
neighbour is often tied with others. Recall is therefore tie-aware: a returned neighbour is correct
when it is at least as similar as the true K-th neighbour (the usual ANN-benchmark definition).
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.recommendations.repository import RecommendationRepository

EF_SEARCH_VALUES = (10, 20, 40, 100, 200, 400)


def _latency(samples: list[float]) -> dict[str, float]:
    values = np.array(samples) * 1000
    return {
        "p50_ms": round(float(np.percentile(values, 50)), 2),
        "p95_ms": round(float(np.percentile(values, 95)), 2),
        "mean_ms": round(float(values.mean()), 2),
    }


TIE_TOLERANCE = 1e-5


@dataclass(frozen=True)
class GroundTruth:
    """Per query: similarity of every vector to the query, and the true K-th best similarity."""

    similarities: npt.NDArray[np.float32]
    kth: float


def tie_aware_recall(
    found: list[list[str]], truth: list[GroundTruth], row_of: dict[str, int], k: int
) -> float:
    scores = []
    for ids, query in zip(found, truth, strict=True):
        good = sum(1 for i in ids if query.similarities[row_of[i]] >= query.kth - TIE_TOLERANCE)
        scores.append(min(good, k) / k)
    return float(np.mean(scores))


async def _pgvector_run(
    session: AsyncSession,
    version_id: uuid.UUID,
    queries: list[tuple[str, list[float]]],
    k: int,
    ef_search: int,
    exact: bool,
) -> tuple[list[list[str]], list[float]]:
    repository = RecommendationRepository(session)
    found: list[list[str]] = []
    seconds: list[float] = []
    for track_id, vector in queries:
        if exact:
            await session.execute(text("SET LOCAL enable_indexscan = off"))
        started = time.perf_counter()
        rows = await repository.nearest_tracks(version_id, vector, k + 1, ef_search)
        seconds.append(time.perf_counter() - started)
        found.append([str(t) for t, _ in rows if str(t) != track_id][:k])
        await session.rollback()
    return found, seconds


async def _uses_hnsw(session: AsyncSession, version_id: uuid.UUID, vector: list[float]) -> bool:
    literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
    plan = await session.execute(
        text(
            "EXPLAIN SELECT track_id FROM track_embeddings WHERE model_version_id = :v "
            "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 10"
        ),
        {"v": version_id, "q": literal},
    )
    uses = any("ix_track_embeddings_embedding_hnsw" in row[0] for row in plan)
    await session.rollback()
    return uses


async def run_retrieval_benchmark(
    session: AsyncSession,
    version_id: uuid.UUID,
    track_ids: npt.NDArray[np.object_],
    embeddings: npt.NDArray[np.float32],
    *,
    queries: int = 300,
    k: int = 10,
    seed: int = 42,
) -> dict[str, Any]:
    has_content = np.linalg.norm(embeddings, axis=1) > 0
    ids = np.asarray(track_ids)[has_content]
    vectors = embeddings[has_content]
    rng = np.random.default_rng(seed)
    chosen = rng.choice(len(ids), size=min(queries, len(ids)), replace=False)

    row_of = {str(track_id): row for row, track_id in enumerate(ids)}
    numpy_seconds: list[float] = []
    numpy_found: list[list[str]] = []
    truth: list[GroundTruth] = []
    for i in chosen:
        started = time.perf_counter()
        sims = vectors @ vectors[i]
        sims[i] = -np.inf
        top = np.argpartition(-sims, k)[:k]
        numpy_seconds.append(time.perf_counter() - started)
        numpy_found.append([str(t) for t in ids[top]])
        truth.append(GroundTruth(sims, float(sims[top].min())))
    distinct = len(np.unique(vectors, axis=0))

    sample = [(str(ids[i]), [float(v) for v in vectors[i]]) for i in chosen]
    # Warm the buffer cache so the first timed method is not penalized.
    await _pgvector_run(session, version_id, sample[:20], k, 100, exact=False)

    exact_found, exact_seconds = await _pgvector_run(
        session, version_id, sample, k, 100, exact=True
    )
    methods: list[dict[str, Any]] = [
        {
            "method": "numpy exact (in-memory)",
            "recall": round(tie_aware_recall(numpy_found, truth, row_of, k), 4),
            **_latency(numpy_seconds),
        },
        {
            "method": "pgvector exact (sequential scan)",
            "recall": round(tie_aware_recall(exact_found, truth, row_of, k), 4),
            **_latency(exact_seconds),
        },
    ]
    for ef in EF_SEARCH_VALUES:
        found, seconds = await _pgvector_run(session, version_id, sample, k, ef, exact=False)
        methods.append(
            {
                "method": f"pgvector HNSW ef_search={ef}",
                "ef_search": ef,
                "recall": round(tie_aware_recall(found, truth, row_of, k), 4),
                **_latency(seconds),
            }
        )
    return {
        "vectors": len(ids),
        "distinct_vectors": int(distinct),
        "dimensions": int(vectors.shape[1]),
        "queries": len(chosen),
        "k": k,
        "hnsw": {"m": 16, "ef_construction": 64, "operator": "vector_cosine_ops"},
        "plan_uses_hnsw_index": await _uses_hnsw(session, version_id, sample[0][1]),
        "methods": methods,
    }
