"""Milestone 3 personalization pipeline (docs/ML_PIPELINE.md, ADR-016).

    baseline -> evaluate -> publish -> benchmark -> report

- baseline:  snapshot the Milestone 2 models' artifacts, configurations and results into
             ml/data/models/baselines/m2/ (they stay the baseline; nothing is replaced);
- evaluate:  the hybrid experiment (models/hybrid/evaluation.json) and the trained rankers
             (models/hybrid/rankers.json);
- publish:   train the collaborative models on the full window and publish the `collaborative`
             and `hybrid` model versions (the Milestone 2 versions stay active);
- benchmark: exact vs HNSW retrieval of collaborative factors for folded-in users;
- report:    docs/reports/hybrid-benchmark.md, with live API examples.
"""

import asyncio
import hashlib
import json
import logging
import shutil
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.core.database import SessionFactory
from app.domains.recommendations.diversity import POLICIES
from app.domains.recommendations.features import FEATURE_NAMES
from app.domains.recommendations.models import TrackCollaborativeFactors
from app.domains.recommendations.repository import RecommendationRepository
from app.domains.users.events import FeedbackWeights
from app.domains.users.profile import TasteProfileConfig
from soniqueo_ml.config import get_ml_settings
from soniqueo_ml.evaluation.experiment import data_end, load_interactions
from soniqueo_ml.evaluation.hybrid_engine import HybridConfig
from soniqueo_ml.evaluation.hybrid_experiment import (
    COLD_START_POPULARITY_WEIGHT,
    HybridExperimentConfig,
    run_hybrid_experiment,
)
from soniqueo_ml.recommendation.catalogue_data import load_catalogue
from soniqueo_ml.recommendation.collaborative import (
    ALSConfig,
    ItemItemConfig,
    train_als,
    train_item_item,
)
from soniqueo_ml.recommendation.content import ContentConfig
from soniqueo_ml.recommendation.content_assets import load_content_assets
from soniqueo_ml.recommendation.lineage import lineage
from soniqueo_ml.recommendation.publish import VersionSpec, publish_collaborative, publish_hybrid
from soniqueo_ml.recommendation.signals import compute_signals

logger = logging.getLogger(__name__)

STAGES = ("baseline", "evaluate", "publish", "benchmark", "report")


class Paths:
    def __init__(self) -> None:
        settings = get_ml_settings()
        self.interactions = settings.processed_dir / "interactions.parquet"
        self.models = settings.data_dir / "models"
        self.baseline = self.models / "baselines" / "m2"
        self.hybrid = self.models / "hybrid"
        self.evaluation = self.hybrid / "evaluation.json"
        self.rankers = self.hybrid / "rankers.json"
        self.published = self.hybrid / "published.json"
        self.retrieval = self.hybrid / "retrieval.json"
        self.report = settings.reports_dir / "hybrid-benchmark.md"
        self.m2_report = settings.reports_dir / "model-benchmark.md"


def read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def active_versions() -> dict[str, dict[str, Any]]:
    async with SessionFactory() as session:
        repository = RecommendationRepository(session)
        out = {}
        for model_type in ("popularity", "content", "collaborative", "hybrid"):
            version = await repository.active_version(model_type)
            if version is not None:
                out[model_type] = {
                    "version": version.version,
                    "params": version.params,
                    "training_data": version.training_data,
                }
        return out


# --- baseline --------------------------------------------------------------------------------


async def stage_baseline() -> None:
    """Copy the Milestone 2 results and the active content model's artifacts, with checksums.
    Idempotent: an existing snapshot is left untouched."""
    paths = Paths()
    manifest_path = paths.baseline / "manifest.json"
    if manifest_path.exists():
        logger.info("Milestone 2 baseline already saved in %s", paths.baseline)
        return
    versions = await active_versions()
    paths.baseline.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    sources = [paths.models / n for n in ("evaluation.json", "published.json", "retrieval.json")]
    sources.append(paths.m2_report)
    content = versions.get("content", {}).get("version")
    if content and (paths.models / content).exists():
        target = paths.baseline / content
        shutil.copytree(paths.models / content, target, dirs_exist_ok=True)
        files.update({f"{content}/{f.name}": sha256(f) for f in target.iterdir()})
    for source in sources:
        if source.exists():
            shutil.copy2(source, paths.baseline / source.name)
            files[source.name] = sha256(source)
    write_json(
        manifest_path,
        {
            "saved_at": datetime.now(UTC).isoformat(),
            "active_versions": {k: v["version"] for k, v in versions.items()},
            "model_params": {k: v["params"] for k, v in versions.items()},
            "files": files,
        },
    )
    logger.info("Milestone 2 baseline saved to %s (%d files)", paths.baseline, len(files))


# --- evaluate --------------------------------------------------------------------------------


async def stage_evaluate(config: HybridExperimentConfig | None = None) -> None:
    paths = Paths()
    if not paths.interactions.exists():
        raise FileNotFoundError(
            f"{paths.interactions} is missing; run `python -m soniqueo_ml catalogue all` first"
        )
    versions = await active_versions()
    content_version = versions.get("content")
    if content_version is None:
        raise RuntimeError("No active content model; run `python -m soniqueo_ml recommend all`")
    async with SessionFactory() as session:
        catalogue = await load_catalogue(session)
    content_config = ContentConfig(**content_version["params"]["content_config"])
    content = await asyncio.to_thread(
        load_content_assets,
        catalogue,
        content_config,
        version=content_version["version"],
        models_dir=paths.models,
    )
    betas = content_version["params"].get("beta", {})
    config = config or HybridExperimentConfig(
        m2_betas=(
            ("seed", float(betas.get("seed", 0.3))),
            ("profile", float(betas.get("profile", 0.3))),
        )
    )
    interactions = await asyncio.to_thread(load_interactions, paths.interactions)
    results, experiment = await asyncio.to_thread(
        run_hybrid_experiment, catalogue, interactions, content, config
    )
    results["interactions_sha256"] = sha256(paths.interactions)
    results["depends_on"] = {k: v["version"] for k, v in versions.items() if k != "hybrid"}
    results["generated_at"] = datetime.now(UTC).isoformat()
    write_json(paths.evaluation, results)
    final = experiment.final
    write_json(
        paths.rankers,
        {
            "served": final["served"],
            "mmr_lambda": final["lambda"],
            "default_mode": final["default_mode"],
            "weighted": final["weighted"].params(),
            "lambdarank": final["lambdarank"].export().to_dict(),
            "lambdarank_importance": final["lambdarank"].importance(),
            "lambdarank_cc0": final["cc0"].export().to_dict(),
            "hybrid_config": experiment.hybrid.params(),
            "evaluation_sha256": sha256(paths.evaluation),
        },
    )
    for row in results["test"]["results"]:
        logger.info(
            "%-32s NDCG@10 %.4f  R@10 %.4f  coverage@10 %.3f",
            row["name"],
            row["metrics"]["ndcg@10"],
            row["metrics"]["recall@10"],
            row["metrics"]["coverage@10"],
        )
    logger.info("Hybrid evaluation written to %s (%.0f s)", paths.evaluation, results["seconds"])


# --- publish ---------------------------------------------------------------------------------

CANDIDATE_SETTINGS = (
    "source_limit",
    "content_neighbours",
    "exploration_artists",
    "tracks_per_artist",
    "exploration_limit",
    "popularity_limit",
    "popular_genres",
)


def hybrid_config_from(saved: dict[str, Any]) -> HybridConfig:
    profile = dict(saved["profile"])
    profile["feedback"] = FeedbackWeights(**profile["feedback"])
    return HybridConfig(
        profile=TasteProfileConfig(**profile),
        als=ALSConfig(**saved["als"]),
        item_item=ItemItemConfig(**saved["item_item"]),
        **{key: saved[key] for key in CANDIDATE_SETTINGS},
    )


def _test_rows(evaluation: dict[str, Any], prefix: tuple[str, ...]) -> dict[str, Any]:
    return {
        row["name"]: row["metrics"]
        for row in evaluation["test"]["results"]
        if row["name"].startswith(prefix)
    }


async def stage_publish() -> None:
    paths = Paths()
    evaluation, rankers = read_json(paths.evaluation), read_json(paths.rankers)
    if evaluation is None or rankers is None:
        raise FileNotFoundError("Run `python -m soniqueo_ml personalize evaluate` first")
    versions = await active_versions()
    for required in ("content", "popularity"):
        if required not in versions:
            raise RuntimeError(f"No active {required} model; run `python -m soniqueo_ml recommend`")
    config = hybrid_config_from(rankers["hybrid_config"])
    async with SessionFactory() as session:
        catalogue = await load_catalogue(session)
    interactions = await asyncio.to_thread(load_interactions, paths.interactions)
    end = data_end(interactions)
    window = interactions[interactions["listened_at"] < end]
    item_of = pd.Series(np.arange(catalogue.n_items), index=catalogue.track_ids)
    signals = await asyncio.to_thread(compute_signals, window, item_of, end, config.profile)
    matrix = signals.matrix("positive")
    als = await asyncio.to_thread(train_als, matrix, config.als)
    item_item = await asyncio.to_thread(train_item_item, matrix, config.item_item)
    listened = np.bincount(matrix.indices, minlength=catalogue.n_items) > 0

    trained_at = datetime.now(UTC)
    start = pd.Timestamp(window["listened_at"].min())
    data = {
        "interactions_sha256": sha256(paths.interactions),
        "interactions": len(window),
        "users": len(signals),
        "window_start": str(start),
        "window_end": str(end),
        "window_days": round((end - start) / pd.Timedelta(days=1)),
        "catalogue_tracks": catalogue.n_items,
        "catalogue_sha256": hashlib.sha256("\n".join(catalogue.track_ids).encode()).hexdigest(),
        "matrix_nnz": int(matrix.nnz),
    }
    upstream = {k: versions[k]["version"] for k in ("content", "popularity")}
    cf_spec = VersionSpec(
        "collaborative",
        {
            "als": config.als.params(),
            "item_item": config.item_item.params(),
            "fold_in": als.fold_in_parameters.params(),
            "signal": "positive (event-weighted, time-decayed listening)",
            "profile_config_version": config.profile.version,
        },
        {**data, "lineage": lineage("collaborative")},
        {
            "evaluation_window": evaluation["test"]["window"],
            "test": _test_rows(evaluation, ("cf-",)),
            "cf_benchmark_selected": evaluation["cf_benchmark"]["selected"],
        },
        trained_at,
    )
    async with SessionFactory() as session:
        cf_result = await publish_collaborative(
            session,
            cf_spec,
            np.asarray(catalogue.track_ids, dtype=object),
            als.item_factors,
            als.idf,
            listened,
            als.gram,
            item_item.similarity,
        )
    upstream["collaborative"] = cf_spec.version
    for_you = replace(POLICIES["for_you"], mmr_lambda=float(rankers["mmr_lambda"]))
    hybrid_spec = VersionSpec(
        "hybrid",
        {
            "ranker": rankers["served"],
            "weighted": rankers["weighted"],
            "features": list(FEATURE_NAMES),
            "profile_config": config.profile.params(),
            "candidates": {key: getattr(config, key) for key in CANDIDATE_SETTINGS},
            "diversity": {
                "mmr_lambda": float(rankers["mmr_lambda"]),
                "default_mode": rankers["default_mode"],
                "for_you": for_you.params(),
            },
            "cold_start_popularity_weight": COLD_START_POPULARITY_WEIGHT,
            "depends_on": upstream,
        },
        {
            "evaluation_sha256": sha256(paths.evaluation),
            "timeline": evaluation["timeline"],
            "rankers_trained_on": [
                evaluation["timeline"]["ranker_train"],
                evaluation["timeline"]["validation"],
            ],
            "lineage": lineage("hybrid", upstream),
            "cc0_ranker_lineage": lineage("hybrid-cc0", upstream),
        },
        {
            "evaluation_window": evaluation["test"]["window"],
            "served_variant": evaluation["test"]["served_variant"],
            "test": _test_rows(evaluation, ("hybrid",)),
            "baseline_content_profile": _test_rows(evaluation, ("content-profile",)),
            "paired": evaluation["test"]["paired"],
            "validation_selected_lambda": evaluation["validation"]["selected_lambda"],
        },
        trained_at,
    )
    artifacts = {
        "ranker": json.dumps(rankers["lambdarank"]).encode(),
        "ranker_cc0": json.dumps(rankers["lambdarank_cc0"]).encode(),
    }
    async with SessionFactory() as session:
        hybrid_result = await publish_hybrid(session, hybrid_spec, artifacts)

    directory = paths.models / cf_spec.version
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "item_factors.npy", als.item_factors)
    (directory / "track_ids.txt").write_text("\n".join(catalogue.track_ids), encoding="utf-8")
    write_json(directory / "params.json", cf_spec.params)
    directory = paths.models / hybrid_spec.version
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "rankers.json", rankers)
    write_json(directory / "params.json", hybrid_spec.params)
    write_json(
        paths.published,
        {
            "collaborative": cf_result,
            "hybrid": hybrid_result,
            "training_data": data,
            "kept_active": upstream,
        },
    )
    logger.info("Published %s and %s", cf_result, hybrid_result)


# --- benchmark -------------------------------------------------------------------------------


async def stage_benchmark(queries: int = 300, k: int = 10) -> None:
    """Exact vs HNSW (inner product) retrieval for user factors.

    Query vectors are sums of the factors of 20 random listened tracks: fold-in is a linear map
    of the user's track factors, so these land in the same region of the space as real users."""
    paths = Paths()
    async with SessionFactory() as session:
        repository = RecommendationRepository(session)
        version = await repository.active_version("collaborative")
        if version is None:
            raise RuntimeError("No active collaborative model; run `personalize publish` first")
        version_id, name = version.id, version.version
        rows = (
            await session.execute(
                select(TrackCollaborativeFactors.track_id, TrackCollaborativeFactors.factors)
                .where(TrackCollaborativeFactors.model_version_id == version_id)
                .order_by(TrackCollaborativeFactors.track_id)
            )
        ).all()
        await session.rollback()
    ids = [r[0] for r in rows]
    factors = np.array([np.asarray(r[1], dtype=np.float64) for r in rows])
    rng = np.random.default_rng(42)
    vectors = np.array(
        [factors[rng.choice(len(factors), 20, replace=False)].sum(axis=0) for _ in range(queries)]
    )
    truth = []
    started = time.perf_counter()
    for vector in vectors:
        scores = factors @ vector
        top = np.argpartition(-scores, k)[:k]
        truth.append((float(scores[top].min()), scores))
    numpy_ms = 1000 * (time.perf_counter() - started) / queries
    index_of = {track: i for i, track in enumerate(ids)}
    methods: list[dict[str, Any]] = [
        {"method": "numpy exact (in-memory)", "recall": 1.0, "p50_ms": round(numpy_ms, 2)}
    ]
    async with SessionFactory() as session:
        repository = RecommendationRepository(session)
        for ef in (20, 40, 100, 200, 400):
            recalls, seconds = [], []
            for vector, (kth, scores) in zip(vectors, truth, strict=True):
                started = time.perf_counter()
                found = await repository.nearest_by_inner_product(
                    version_id, vector.tolist(), k, ef
                )
                seconds.append(time.perf_counter() - started)
                await session.rollback()
                good = sum(1 for t, _ in found if scores[index_of[t]] >= kth - 1e-6)
                recalls.append(min(good, k) / k)
            methods.append(
                {
                    "method": f"pgvector HNSW (ef_search={ef})",
                    "recall": round(float(np.mean(recalls)), 4),
                    "p50_ms": round(1000 * float(np.percentile(seconds, 50)), 2),
                    "p95_ms": round(1000 * float(np.percentile(seconds, 95)), 2),
                }
            )
    results = {
        "model_version": name,
        "vectors": len(ids),
        "dimensions": int(factors.shape[1]),
        "queries": queries,
        "k": k,
        "methods": methods,
    }
    write_json(paths.retrieval, results)
    for method in methods:
        logger.info("%-34s recall@%d %.3f", method["method"], k, method["recall"])


# --- report ----------------------------------------------------------------------------------


async def stage_report() -> None:
    from soniqueo_ml.evaluation.hybrid_report import collect_hybrid_examples, write_hybrid_report

    paths = Paths()
    evaluation = read_json(paths.evaluation)
    if evaluation is None:
        raise FileNotFoundError("Run `python -m soniqueo_ml personalize evaluate` first")
    examples = await collect_hybrid_examples()
    write_hybrid_report(
        paths.report,
        evaluation=evaluation,
        rankers=read_json(paths.rankers),
        published=read_json(paths.published),
        retrieval=read_json(paths.retrieval),
        baseline=read_json(paths.baseline / "manifest.json"),
        examples=examples,
    )
    logger.info("Hybrid benchmark report written to %s", paths.report)
