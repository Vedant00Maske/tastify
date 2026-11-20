"""Milestone 2 recommendation pipeline (docs/ML_PIPELINE.md).

    evaluate -> publish -> benchmark -> report

- evaluate:  time-aware offline evaluation and tuning (ml/data/models/evaluation.json), plus the
             research-only FMA experiment;
- publish:   train the popularity and content models on the full window with the selected
             hyperparameters and publish them to the serving tables;
- benchmark: exact vs HNSW retrieval over the published embeddings (retrieval.json);
- report:    docs/reports/model-benchmark.md from the results above and live API examples.
"""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.core.database import SessionFactory
from app.domains.recommendations.models import TrackEmbedding
from app.domains.recommendations.ranking import CANDIDATE_POOL, DEFAULT_MAX_PER_ARTIST
from app.domains.recommendations.repository import RecommendationRepository
from soniqueo_ml.config import get_ml_settings
from soniqueo_ml.evaluation.experiment import (
    ExperimentConfig,
    data_end,
    load_interactions,
    run_experiment,
    selected_betas,
    selected_content_config,
)
from soniqueo_ml.evaluation.fma_experiment import genre_labels, run_fma_experiment
from soniqueo_ml.evaluation.report import collect_examples, write_report
from soniqueo_ml.recommendation.catalogue_data import load_catalogue
from soniqueo_ml.recommendation.content import artist_embeddings, fit_content_model
from soniqueo_ml.recommendation.popularity import PopularityConfig, compute_popularity
from soniqueo_ml.recommendation.publish import VersionSpec, publish_content, publish_popularity
from soniqueo_ml.recommendation.retrieval_benchmark import run_retrieval_benchmark

logger = logging.getLogger(__name__)

STAGES = ("evaluate", "publish", "benchmark", "report")


class Paths:
    def __init__(self) -> None:
        settings = get_ml_settings()
        self.interactions = settings.processed_dir / "interactions.parquet"
        self.fma_archive = settings.raw_dir / "fma" / "fma_metadata.zip"
        self.models = settings.data_dir / "models"
        self.evaluation = self.models / "evaluation.json"
        self.published = self.models / "published.json"
        self.retrieval = self.models / "retrieval.json"
        self.report = settings.reports_dir / "model-benchmark.md"


def _read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _require_interactions(paths: Paths) -> None:
    if not paths.interactions.exists():
        raise FileNotFoundError(
            f"{paths.interactions} is missing; run `python -m soniqueo_ml catalogue all` first"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- evaluate --------------------------------------------------------------------------------


async def stage_evaluate(fma: bool = True) -> None:
    paths = Paths()
    _require_interactions(paths)
    async with SessionFactory() as session:
        catalogue = await load_catalogue(session)
        research = await load_catalogue(session, research_only=True) if fma else None
        labels = (
            await genre_labels(session, paths.fma_archive)
            if fma and paths.fma_archive.exists()
            else None
        )
    interactions = await asyncio.to_thread(load_interactions, paths.interactions)
    results = await asyncio.to_thread(run_experiment, catalogue, interactions, ExperimentConfig())
    results["interactions_sha256"] = _sha256(paths.interactions)
    if research is not None and labels is not None and len(labels):
        results["fma_experiment"] = await asyncio.to_thread(run_fma_experiment, research, labels)
    results["generated_at"] = datetime.now(UTC).isoformat()
    _write_json(paths.evaluation, results)
    for row in results["test"]["results"]:
        logger.info(
            "%-20s NDCG@10 %.4f  P@10 %.4f  R@10 %.4f  coverage@10 %.3f",
            row["name"],
            row["metrics"]["ndcg@10"],
            row["metrics"]["precision@10"],
            row["metrics"]["recall@10"],
            row["metrics"]["coverage@10"],
        )
    logger.info("Evaluation written to %s (%.0f s)", paths.evaluation, results["seconds"])


# --- publish ---------------------------------------------------------------------------------


def _test_metrics(evaluation: dict[str, Any] | None, names: tuple[str, ...]) -> dict[str, Any]:
    if not evaluation:
        return {}
    rows = {r["name"]: r["metrics"] for r in evaluation["test"]["results"]}
    return {
        "evaluation_window": evaluation["test"]["window"],
        "test": {name: rows[name] for name in names if name in rows},
        "validation_ndcg@10": evaluation["selection"].get("validation_ndcg@10", {}),
    }


async def stage_publish() -> None:
    paths = Paths()
    _require_interactions(paths)
    evaluation = _read_json(paths.evaluation)
    if evaluation is None:
        logger.warning("No evaluation.json: publishing with default hyperparameters")
    config = selected_content_config(evaluation)
    betas = selected_betas(evaluation)
    popularity_config = PopularityConfig()

    async with SessionFactory() as session:
        catalogue = await load_catalogue(session)
    interactions = await asyncio.to_thread(load_interactions, paths.interactions)
    end = data_end(interactions)
    window = interactions[interactions["listened_at"] < end]
    popularity = await asyncio.to_thread(
        compute_popularity, window, catalogue.track_ids, end, popularity_config
    )
    model = await asyncio.to_thread(fit_content_model, catalogue, config)
    codes = catalogue.artist_codes()
    # pd.factorize (artist_codes) numbers artists in order of first appearance, like pd.unique.
    artist_ids = np.asarray(pd.unique(catalogue.tracks["artist_id"]), dtype=object)
    artist_vectors, artist_counts = artist_embeddings(
        model.embeddings, codes, popularity["listeners"].to_numpy()
    )

    trained_at = datetime.now(UTC)
    start = pd.Timestamp(window["listened_at"].min())
    data = {
        "interactions_sha256": _sha256(paths.interactions),
        "interactions": len(window),
        "users": int(window["user_key"].nunique()),
        "window_start": str(start),
        "window_end": str(end),
        "window_days": round((end - start) / pd.Timedelta(days=1)),
        "catalogue_tracks": catalogue.n_items,
        "catalogue_sha256": hashlib.sha256("\n".join(catalogue.track_ids).encode()).hexdigest(),
    }
    popularity_spec = VersionSpec(
        "popularity",
        popularity_config.params(),
        data,
        _test_metrics(evaluation, ("popularity", "trending", "genre-popularity")),
        trained_at,
    )
    content_spec = VersionSpec(
        "content",
        {
            "content_config": config.params(),
            "beta": betas,
            "candidate_pool": CANDIDATE_POOL,
            "max_per_artist": DEFAULT_MAX_PER_ARTIST,
            "explained_variance": round(model.explained_variance, 4),
            "block_dimensions": model.block_dimensions,
        },
        data,
        _test_metrics(evaluation, ("content-seed", "content-profile", "content-artist")),
        trained_at,
    )
    async with SessionFactory() as session:
        popularity_result = await publish_popularity(session, popularity_spec, popularity)
        content_result = await publish_content(
            session,
            content_spec,
            model.track_ids,
            model.embeddings,
            artist_ids,
            artist_vectors,
            artist_counts.astype(np.int64),
        )
    artifacts = paths.models / content_spec.version
    artifacts.mkdir(parents=True, exist_ok=True)
    np.save(artifacts / "embeddings.npy", model.embeddings)
    (artifacts / "track_ids.txt").write_text("\n".join(model.track_ids), encoding="utf-8")
    _write_json(artifacts / "params.json", content_spec.params)
    _write_json(
        paths.published,
        {"popularity": popularity_result, "content": content_result, "training_data": data},
    )
    logger.info("Published %s and %s", popularity_result, content_result)


# --- benchmark -------------------------------------------------------------------------------


async def stage_benchmark() -> None:
    paths = Paths()
    async with SessionFactory() as session:
        content = await RecommendationRepository(session).active_version("content")
        if content is None:
            raise RuntimeError("No active content model; run `recommend publish` first")
        # Read these now: the benchmark rolls back between queries, which expires ORM objects.
        version_id, version = content.id, content.version
        rows = (
            await session.execute(
                select(TrackEmbedding.track_id, TrackEmbedding.embedding)
                .where(TrackEmbedding.model_version_id == version_id)
                .order_by(TrackEmbedding.track_id)
            )
        ).all()
        await session.rollback()
        track_ids = np.array([str(r[0]) for r in rows], dtype=object)
        embeddings = np.array([np.asarray(r[1], dtype=np.float32) for r in rows])
        results = await run_retrieval_benchmark(session, version_id, track_ids, embeddings)
    results["model_version"] = version
    _write_json(paths.retrieval, results)
    for method in results["methods"]:
        logger.info(
            "%-34s recall@10 %.3f  p50 %.2f ms  p95 %.2f ms",
            method["method"],
            method["recall"],
            method["p50_ms"],
            method["p95_ms"],
        )


# --- report ----------------------------------------------------------------------------------


async def stage_report() -> None:
    paths = Paths()
    evaluation = _read_json(paths.evaluation)
    if evaluation is None:
        raise FileNotFoundError("Run `recommend evaluate` first")
    async with SessionFactory() as session:
        examples = await collect_examples(session)
    write_report(
        paths.report,
        evaluation=evaluation,
        published=_read_json(paths.published),
        retrieval=_read_json(paths.retrieval),
        examples=examples,
    )
    logger.info("Model benchmark report written to %s", paths.report)
