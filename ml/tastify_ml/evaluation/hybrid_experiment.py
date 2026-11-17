"""The Milestone 3 offline experiment (docs/reports/hybrid-benchmark.md, ADR-016).

Timeline (the data ends at the last complete day E; periods of `period_days`, default 3):

    ...history... | ranker-train [E-9d, E-6d) | validation [E-6d, E-3d) | test [E-3d, E)

Each period is predicted from interactions before its start only: signals, popularity and the
collaborative models are retrained per period.

1. CF benchmark (validation): user-user and item-item k-NN, ALS grid, BPR. Selects the ALS and
   item-item configurations used by the hybrid.
2. Candidates and features for ranker-train and validation users (hybrid_engine).
3. Weighted hybrid: Platt calibration on ranker-train; weights by coordinate ascent on validation.
4. LambdaRank: trained on ranker-train, early-stopped on validation.
   Pre-declared rule: the API serves the ranker with the higher validation NDCG@10; it is then
   retrained on ranker-train + validation (same number of rounds) before the test.
5. Diversity: MMR lambda = the most diverse setting whose validation NDCG@10 is within
   `max_ndcg_loss` of lambda = 1 (pre-declared rule); exploration modes measured; the default mode
   is "auto" unless "balanced" scores higher on validation.
6. Test, once: every model on all eligible users, with segments and paired differences.
   Primary metric (pre-declared): NDCG@10 against the Milestone 2 content-profile model.
7. Rolling one-day windows across the test period, cold start, profile stability, exploration
   calibration and reproducibility checks.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from threadpoolctl import threadpool_limits

from app.domains.recommendations.candidate_generation import SOURCE_ORDER, Source
from app.domains.recommendations.diversity import POLICIES, DiversityPolicy, compose
from app.domains.recommendations.features import COMMERCIAL_FEATURES, FEATURE_NAMES
from app.domains.recommendations.hybrid_ranking import (
    COMPONENT_FEATURES,
    WeightedHybridRanker,
)
from app.domains.recommendations.ranking import DEFAULT_MAX_PER_ARTIST, blended_score
from app.domains.users.events import aggregate_events
from app.domains.users.profile import (
    DISCOVERY_TARGETS,
    ExplorationMode,
    TasteProfile,
    build_taste_profile,
)
from tastify_ml.evaluation import metrics, segments
from tastify_ml.evaluation.experiment import (
    data_end,
    genre_affinity_matrix,
    song_keys,
)
from tastify_ml.evaluation.hybrid_engine import (
    CandidateEngine,
    HybridConfig,
    ItemFacts,
    PeriodModels,
    UserCandidates,
    train_period_models,
)
from tastify_ml.evaluation.recommenders import (
    ContentRecommender,
    RandomRecommender,
    RankedListRecommender,
    Recommender,
    popularity_ranking,
)
from tastify_ml.evaluation.runner import MetricContext, ModelResult, evaluate, evaluate_lists
from tastify_ml.evaluation.split import EvaluationTask, build_task, temporal_split
from tastify_ml.recommendation.catalogue_data import CatalogueData
from tastify_ml.recommendation.collaborative import (
    ALSConfig,
    ItemItemConfig,
    train_als,
    train_bpr,
    train_item_item,
    train_user_knn,
)
from tastify_ml.recommendation.content_assets import ContentAssets
from tastify_ml.recommendation.ltr import (
    LambdaRankConfig,
    RankingData,
    TrainedRanker,
    fit_platt,
    train_lambdarank,
)
from tastify_ml.recommendation.popularity import PopularityConfig

logger = logging.getLogger(__name__)

DAY = pd.Timedelta(days=1)
IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]

MODES: tuple[str, ...] = ("familiar", "balanced", "explorer", "auto")
# Ranked lists without MMR: the artist cap and one version per song, as every Milestone 2 list.
RANKED = DiversityPolicy("ranked", mmr_lambda=1.0, max_per_artist=DEFAULT_MAX_PER_ARTIST)
CC0_SOURCES = (Source.COLLABORATIVE_ITEM, Source.COLLABORATIVE_MF, Source.POPULARITY)
# Cold start with declared taste only: similarity to the declared profile, blended with popularity.
COLD_START_POPULARITY_WEIGHT = 0.3


def default_als_grid() -> tuple[ALSConfig, ...]:
    return tuple(
        ALSConfig(factors=128, alpha=alpha, regularization=regularization)
        for alpha in (1.0, 5.0, 20.0)
        for regularization in (0.01, 0.1, 1.0)
    )


def default_item_grid() -> tuple[ItemItemConfig, ...]:
    # At most 100 neighbours per track: the served table holds tracks x neighbours rows, and on
    # validation 200 neighbours scored within 0.5% of 50.
    return tuple(
        ItemItemConfig(neighbours=k, weighting=w) for w in ("bm25", "cosine") for k in (50, 100)
    )


@dataclass(frozen=True)
class HybridExperimentConfig:
    period_days: int = 3
    rolling_windows: int = 3
    min_history: int = 5
    ltr_min_history: int = 1
    ltr_users: int = 6000
    tuning_users: int = 5000
    test_users: int | None = None
    rolling_users: int | None = 8000
    low_history_users: int | None = None
    onboarding_users: int = 5000
    stability_users: int = 5000
    ks: tuple[int, ...] = (10, 20)
    als_grid: tuple[ALSConfig, ...] = field(default_factory=default_als_grid)
    als_factor_grid: tuple[int, ...] = (64, 256)
    item_grid: tuple[ItemItemConfig, ...] = field(default_factory=default_item_grid)
    user_knn_neighbours: tuple[int, ...] = (50, 100)
    bpr_factors: int = 128
    weight_grid: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)
    weight_rounds: int = 2
    lambdas: tuple[float, ...] = (1.0, 0.95, 0.9, 0.85, 0.8, 0.7, 0.6, 0.5)
    max_ndcg_loss: float = 0.05
    ltr_grid: tuple[LambdaRankConfig, ...] = (
        LambdaRankConfig(num_leaves=31),
        LambdaRankConfig(num_leaves=63, min_data_in_leaf=200),
        # Smaller, slower trees: rankers must transfer to a later period with more history.
        LambdaRankConfig(num_leaves=15, learning_rate=0.03, min_data_in_leaf=500),
    )
    # Milestone 2 popularity blend of the content baselines (ADR-015).
    m2_betas: tuple[tuple[str, float], ...] = (("seed", 0.3), ("profile", 0.3))
    seed: int = 42
    popularity: PopularityConfig = field(default_factory=PopularityConfig)
    hybrid: HybridConfig = field(default_factory=HybridConfig)

    def params(self) -> dict[str, Any]:
        out = asdict(self)
        out["hybrid"] = self.hybrid.params()
        return out


@dataclass
class Period:
    name: str
    cutoff: pd.Timestamp
    end: pd.Timestamp
    models: PeriodModels
    task: EvaluationTask
    context: MetricContext

    @property
    def window(self) -> dict[str, str]:
        return {"cutoff": str(self.cutoff), "end": str(self.end)}


_DISCOUNTS = 1.0 / np.log2(np.arange(2, 102, dtype=np.float64))


def fast_ndcg(
    candidates: Sequence[UserCandidates], scores: Sequence[FloatArray], k: int = 10
) -> float:
    """NDCG@k of each user's top-k candidates by score (no artist cap): for tuning loops."""
    total = 0.0
    for uc, score in zip(candidates, scores, strict=True):
        if len(score) == 0 or uc.n_targets == 0:
            continue
        top = np.argsort(-score, kind="stable")[:k] if len(score) <= k else None
        if top is None:
            part = np.argpartition(-score, k)[:k]
            top = part[np.argsort(-score[part], kind="stable")]
        dcg = float((uc.labels[top] * _DISCOUNTS[: len(top)]).sum())
        total += dcg / float(_DISCOUNTS[: min(uc.n_targets, k)].sum())
    return total / max(len(candidates), 1)


def hybrid_list(
    uc: UserCandidates,
    scores: FloatArray,
    k: int,
    policy: DiversityPolicy,
    target: float | None,
    embeddings: npt.NDArray[np.float32],
) -> IntArray:
    picked = compose(
        scores,
        limit=k,
        policy=policy,
        artists=uc.artists.tolist(),
        song_keys=uc.song_keys,
        embeddings=embeddings[uc.items] if policy.mmr_lambda < 1.0 else None,
        discovery=uc.discovery,
        discovery_target=target,
    )
    out = np.full(k, -1, dtype=np.int64)
    out[: len(picked)] = uc.items[picked]
    return out


def mode_target(mode: str | None, uc: UserCandidates) -> float | None:
    if mode is None:
        return None
    if mode == "auto":
        return uc.discovery_target
    return DISCOVERY_TARGETS[ExplorationMode(mode)]


Scorer = Callable[[Sequence[UserCandidates]], list[FloatArray]]


def weighted_scorer(ranker: WeightedHybridRanker) -> Scorer:
    return lambda batch: [ranker.score(uc.features) for uc in batch]


def ltr_scorer(model: TrainedRanker) -> Scorer:
    def score(batch: Sequence[UserCandidates]) -> list[FloatArray]:
        if not batch:
            return []
        stacked = np.vstack([uc.features for uc in batch])
        values = model.predict(stacked)
        bounds = np.cumsum([0, *(len(uc) for uc in batch)])
        return [values[bounds[i] : bounds[i + 1]] for i in range(len(batch))]

    return score


def cc0_rows(uc: UserCandidates) -> npt.NDArray[np.bool_]:
    columns = [SOURCE_ORDER.index(s) for s in CC0_SOURCES]
    return np.asarray(np.isfinite(uc.ranks[:, columns]).any(axis=1))


@dataclass
class ListVariant:
    name: str
    scorer: str  # key into the scorers mapping
    policy: DiversityPolicy
    mode: str | None = None
    cc0: bool = False


class ScoreListRecommender:
    """A model that scores every item for a batch of users, post-processed like the hybrid
    lists (unheard items, top pool, artist cap and one version per song)."""

    def __init__(
        self,
        name: str,
        score: Callable[[list[str]], FloatArray],
        facts: ItemFacts,
        pool: int = 200,
        batch: int = 500,
    ) -> None:
        self.name, self._score, self.facts, self.pool, self.batch = name, score, facts, pool, batch

    def recommend(self, task: EvaluationTask, k: int) -> IntArray:
        out = np.full((len(task), k), -1, dtype=np.int64)
        users = list(task.users)
        for start in range(0, len(users), self.batch):
            scores = self._score(users[start : start + self.batch])
            for row, values in enumerate(scores):
                user = start + row
                values = values.astype(np.float64, copy=True)
                values[task.history[user]] = -np.inf
                pool = min(self.pool, len(values) - 1)
                top = np.argpartition(-values, pool)[:pool]
                top = top[np.argsort(-values[top], kind="stable")]
                top = top[np.isfinite(values[top])]
                picked = compose(
                    values[top],
                    limit=k,
                    policy=RANKED,
                    artists=self.facts.artist_codes[top].tolist(),
                    song_keys=[self.facts.song_keys[i] for i in top.tolist()],
                )
                out[user, : len(picked)] = top[picked]
        return out


class HybridExperiment:
    def __init__(
        self,
        catalogue: CatalogueData,
        interactions: pd.DataFrame,
        content: ContentAssets,
        config: HybridExperimentConfig | None = None,
    ) -> None:
        self.catalogue = catalogue
        self.interactions = interactions
        self.content = content
        self.config = config or HybridExperimentConfig()
        affinity, names = genre_affinity_matrix(catalogue)
        self.genre_affinity, self.genre_names = affinity, names
        self.facts = ItemFacts(
            catalogue.artist_codes().astype(np.int64), song_keys(catalogue), affinity.tocsc(), names
        )
        self.item_of = pd.Series(np.arange(catalogue.n_items), index=catalogue.track_ids)
        days = self.config.period_days * DAY
        self.end = data_end(interactions)
        self.test_start = self.end - days
        self.validation_start = self.test_start - days
        self.ranker_start = self.validation_start - days
        self.hybrid = self.config.hybrid
        self._models: dict[tuple[pd.Timestamp, str], PeriodModels] = {}
        self.timings: dict[str, float] = {}

    # --- periods -----------------------------------------------------------------------------

    def models(self, name: str, cutoff: pd.Timestamp, hybrid: HybridConfig) -> PeriodModels:
        key = (cutoff, json.dumps([hybrid.als.params(), hybrid.item_item.params()], sort_keys=True))
        if key not in self._models:
            self._models[key] = train_period_models(
                name,
                self.interactions,
                self.catalogue,
                self.content,
                self.facts,
                cutoff,
                hybrid,
                self.config.popularity,
            )
        return self._models[key]

    def period(
        self,
        name: str,
        cutoff: pd.Timestamp,
        end: pd.Timestamp,
        hybrid: HybridConfig,
        *,
        min_history: int,
        max_users: int | None,
        max_history: int | None = None,
    ) -> Period:
        models = self.models(name, cutoff, hybrid)
        split = temporal_split(self.interactions, cutoff, end)
        task = build_task(
            split,
            self.item_of,
            self.catalogue.n_items,
            min_history=min_history,
            max_users=max_users,
            seed=self.config.seed,
            max_history=max_history,
        )
        context = MetricContext(
            embeddings=self.content.embeddings,
            artist_codes=self.facts.artist_codes,
            information=metrics.self_information(models.listeners, models.train_users),
        )
        logger.info("%s: %d users (%s -> %s)", name, len(task), cutoff, end)
        return Period(name, cutoff, end, models, task, context)

    def _timed(self, label: str, started: float) -> None:
        self.timings[label] = round(time.perf_counter() - started, 1)
        logger.info("%s done in %.0f s", label, self.timings[label])

    # --- standalone models -------------------------------------------------------------------

    def _positions(self, models: PeriodModels, users: Sequence[str]) -> IntArray:
        return np.array([models.signals.position[u] for u in users], dtype=np.int64)

    def als_recommender(self, period: Period, models: PeriodModels, name: str) -> Recommender:
        als, signals = models.als, models.signals

        def score(users: list[str]) -> FloatArray:
            vectors = []
            for position in self._positions(models, users):
                rows = signals.user_signals(int(position))
                vectors.append(als.user_vector(rows.keys.astype(np.int64), rows.positive))
            return np.vstack(vectors) @ als.item_factors.T.astype(np.float64)

        return ScoreListRecommender(name, score, self.facts)

    def item_recommender(self, models: PeriodModels, name: str) -> Recommender:
        matrix = models.signals.matrix("positive")

        def score(users: list[str]) -> FloatArray:
            rows = matrix[self._positions(models, users)]
            return np.asarray(models.item_item.scores(rows).toarray())

        return ScoreListRecommender(name, score, self.facts)

    def user_knn_scores(
        self, models: PeriodModels, neighbours: int
    ) -> Callable[[list[str]], FloatArray]:
        knn = train_user_knn(models.signals.matrix("positive"), neighbours)

        def score(users: list[str]) -> FloatArray:
            return knn.scores(self._positions(models, users))

        return score

    def m2_recommenders(self, period: Period) -> list[Recommender]:
        betas = dict(self.config.m2_betas)
        dedup = self.facts.song_keys
        score = period.models.score
        return [
            RandomRecommender(self.catalogue.n_items, seed=self.config.seed),
            RankedListRecommender("popularity", popularity_ranking(period.models.listeners)),
            ContentRecommender(
                "content-seed (M2)",
                self.content.embeddings,
                score,
                self.facts.artist_codes,
                dedup,
                betas["seed"],
                "seed",
            ),
            ContentRecommender(
                "content-profile (M2)",
                self.content.embeddings,
                score,
                self.facts.artist_codes,
                dedup,
                betas["profile"],
                "profile",
            ),
        ]

    # --- 1. collaborative filtering benchmark ------------------------------------------------

    def benchmark_cf(self) -> dict[str, Any]:
        started = time.perf_counter()
        config = self.config
        period = self.period(
            "validation",
            self.validation_start,
            self.test_start,
            self.hybrid,
            min_history=config.min_history,
            max_users=config.tuning_users,
        )
        models = period.models
        matrix = models.signals.matrix("positive")
        rows: list[dict[str, Any]] = []

        def run(name: str, family: str, params: dict[str, Any], recommender: Recommender) -> float:
            result = evaluate(recommender, period.task, None, ks=(10,))
            rows.append({"name": name, "family": family, "params": params, **result.to_dict()})
            logger.info("CF %-34s NDCG@10 %.4f", name, result.metrics["ndcg@10"])
            return result.metrics["ndcg@10"]

        best_als: tuple[float, ALSConfig] = (-1.0, config.als_grid[0])
        for als_config in config.als_grid:
            model = replace(models, als=train_als(matrix, als_config))
            name = f"als f{als_config.factors} a{als_config.alpha:g} r{als_config.regularization:g}"
            value = run(name, "als", als_config.params(), self.als_recommender(period, model, name))
            if value > best_als[0]:
                best_als = (value, als_config)
        for factors in config.als_factor_grid:
            als_config = replace(best_als[1], factors=factors)
            model = replace(models, als=train_als(matrix, als_config))
            name = f"als f{factors} a{als_config.alpha:g} r{als_config.regularization:g}"
            value = run(name, "als", als_config.params(), self.als_recommender(period, model, name))
            if value > best_als[0]:
                best_als = (value, als_config)

        best_item: tuple[float, ItemItemConfig] = (-1.0, config.item_grid[0])
        for item_config in config.item_grid:
            model = replace(models, item_item=train_item_item(matrix, item_config))
            name = f"item-item {item_config.weighting} k{item_config.neighbours}"
            value = run(name, "item-item", item_config.params(), self.item_recommender(model, name))
            if value > best_item[0]:
                best_item = (value, item_config)

        for neighbours in config.user_knn_neighbours:
            name = f"user-user k{neighbours}"
            run(
                name,
                "user-user",
                {"neighbours": neighbours},
                ScoreListRecommender(name, self.user_knn_scores(models, neighbours), self.facts),
            )
        bpr = train_bpr(matrix, factors=config.bpr_factors, random_state=config.seed)

        def bpr_scores(users: list[str]) -> FloatArray:
            factors = bpr.user_factors[self._positions(models, users)].astype(np.float64)
            return factors @ bpr.item_factors.T.astype(np.float64)

        run(
            f"bpr f{config.bpr_factors}",
            "bpr",
            {"factors": config.bpr_factors},
            ScoreListRecommender("bpr", bpr_scores, self.facts),
        )
        self._timed("cf_benchmark", started)
        return {
            "window": period.window,
            "users": len(period.task),
            "results": rows,
            "selected": {"als": best_als[1].params(), "item_item": best_item[1].params()},
        }

    # --- 2-4. rankers --------------------------------------------------------------------------

    def candidates(self, period: Period, hybrid: HybridConfig) -> list[UserCandidates]:
        engine = CandidateEngine(period.models, self.content, self.facts, hybrid)
        relevant = dict(zip(period.task.users, period.task.relevant, strict=True))
        return list(engine.generate(list(period.task.users), relevant))

    @staticmethod
    def candidate_recall(candidates: Sequence[UserCandidates]) -> dict[str, Any]:
        """Share of relevant items each source retrieved (after filtering), the union, and what
        the union loses without each source."""
        totals = np.array([uc.n_targets for uc in candidates], dtype=np.float64)
        out: dict[str, Any] = {
            "union": float(np.mean([uc.labels.sum() for uc in candidates] / totals))
        }
        found = {}
        for column, source in enumerate(SOURCE_ORDER):
            found[source] = [uc.labels & np.isfinite(uc.ranks[:, column]) for uc in candidates]
        sources = {}
        for column, source in enumerate(SOURCE_ORDER):
            alone = np.array([f.sum() for f in found[source]]) / totals
            others = [
                np.isfinite(uc.ranks[:, [c for c in range(len(SOURCE_ORDER)) if c != column]]).any(
                    axis=1
                )
                for uc in candidates
            ]
            without = (
                np.array([(uc.labels & o).sum() for uc, o in zip(candidates, others, strict=True)])
                / totals
            )
            sources[source.value] = {
                "recall": float(alone.mean()),
                "marginal_recall": float(out["union"] - without.mean()),
                "mean_candidates": float(
                    np.mean([np.isfinite(uc.ranks[:, column]).sum() for uc in candidates])
                ),
            }
        out["sources"] = sources
        out["mean_candidates"] = float(np.mean([len(uc) for uc in candidates]))
        return out

    def tune_weighted(
        self, train: Sequence[UserCandidates], valid: Sequence[UserCandidates]
    ) -> tuple[WeightedHybridRanker, dict[str, Any]]:
        stacked = np.vstack([uc.features for uc in train])
        labels = np.concatenate([uc.labels for uc in train])
        calibration = fit_platt(stacked, labels)
        components = list(COMPONENT_FEATURES)
        probe = WeightedHybridRanker(dict.fromkeys(components, 1.0), calibration)
        calibrated = [
            np.column_stack([probe.components(uc.features)[c] for c in components]) for uc in valid
        ]

        def score(weights: Mapping[str, float]) -> float:
            w = np.array([weights[c] for c in components])
            return fast_ndcg(valid, [c @ w for c in calibrated])

        weights = dict.fromkeys(components, 1.0)
        best = score(weights)
        search = [{"weights": dict(weights), "ndcg@10": best}]
        for _ in range(self.config.weight_rounds):
            for component in components:
                for value in self.config.weight_grid:
                    trial = {**weights, component: value}
                    if not any(trial.values()):
                        continue
                    result = score(trial)
                    search.append({"weights": dict(trial), "ndcg@10": result})
                    if result > best + 1e-9:
                        best, weights = result, trial
        top = max(weights.values())
        weights = {c: round(v / top, 4) for c, v in weights.items()}
        ranker = WeightedHybridRanker(weights, calibration)
        logger.info("Weighted hybrid: %s (validation candidate NDCG@10 %.4f)", weights, best)
        return ranker, {
            "weights": weights,
            "calibration": ranker.params()["calibration"],
            "candidate_ndcg@10": best,
            "evaluations": len(search),
        }

    def train_ltr(
        self,
        train: Sequence[UserCandidates],
        valid: Sequence[UserCandidates],
        columns: Sequence[str] = FEATURE_NAMES,
        rows: Callable[[UserCandidates], npt.NDArray[np.bool_]] | None = None,
    ) -> tuple[TrainedRanker, LambdaRankConfig, list[dict[str, Any]]]:
        def data(candidates: Sequence[UserCandidates]) -> RankingData:
            return RankingData.stack(
                [uc.features for uc in candidates],
                [uc.labels for uc in candidates],
                columns,
                None if rows is None else [rows(uc) for uc in candidates],
            )

        train_data, valid_data = data(train), data(valid)
        grid: list[dict[str, Any]] = []
        best: tuple[float, TrainedRanker | None, LambdaRankConfig] = (
            -1.0,
            None,
            self.config.ltr_grid[0],
        )
        for ltr_config in self.config.ltr_grid:
            model = train_lambdarank(train_data, columns, ltr_config, valid_data)
            score = model.validation_ndcg or 0.0
            grid.append(
                {
                    "params": ltr_config.params(),
                    "best_iteration": model.best_iteration,
                    "candidate_ndcg@10": score,
                }
            )
            if score > best[0]:
                best = (score, model, ltr_config)
        if best[1] is None:
            raise RuntimeError("no LambdaRank configuration was trained")
        return best[1], best[2], grid

    def retrain_ltr(
        self,
        candidates: Sequence[UserCandidates],
        columns: Sequence[str],
        ltr_config: LambdaRankConfig,
        rounds: int,
        rows: Callable[[UserCandidates], npt.NDArray[np.bool_]] | None = None,
    ) -> TrainedRanker:
        data = RankingData.stack(
            [uc.features for uc in candidates],
            [uc.labels for uc in candidates],
            columns,
            None if rows is None else [rows(uc) for uc in candidates],
        )
        return train_lambdarank(data, columns, ltr_config, rounds=rounds)

    # --- lists -------------------------------------------------------------------------------

    def lists(
        self,
        candidates: Sequence[UserCandidates],
        scorers: Mapping[str, Scorer],
        variants: Sequence[ListVariant],
        k: int,
        batch: int = 500,
    ) -> dict[str, IntArray]:
        out = {v.name: np.full((len(candidates), k), -1, dtype=np.int64) for v in variants}
        for start in range(0, len(candidates), batch):
            chunk = list(candidates[start : start + batch])
            needs_cc0 = any(v.cc0 for v in variants)
            cc0_chunk = [uc.subset(cc0_rows(uc)) for uc in chunk] if needs_cc0 else []
            scored: dict[tuple[str, bool], list[FloatArray]] = {}
            for variant in variants:
                key = (variant.scorer, variant.cc0)
                if key not in scored:
                    scored[key] = scorers[variant.scorer](cc0_chunk if variant.cc0 else chunk)
            for variant in variants:
                users = cc0_chunk if variant.cc0 else chunk
                for row, (uc, score) in enumerate(
                    zip(users, scored[(variant.scorer, variant.cc0)], strict=True)
                ):
                    out[variant.name][start + row] = hybrid_list(
                        uc,
                        score,
                        k,
                        variant.policy,
                        mode_target(variant.mode, uc),
                        self.content.embeddings,
                    )
        return out

    # --- the experiment ------------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        config = self.config
        results: dict[str, Any] = {
            "config": config.params(),
            "timeline": {
                "data_end": str(self.end),
                "ranker_train": [str(self.ranker_start), str(self.validation_start)],
                "validation": [str(self.validation_start), str(self.test_start)],
                "test": [str(self.test_start), str(self.end)],
            },
        }

        cf = self.benchmark_cf()
        results["cf_benchmark"] = cf
        hybrid = replace(
            self.hybrid,
            als=ALSConfig(**cf["selected"]["als"]),
            item_item=ItemItemConfig(**cf["selected"]["item_item"]),
        )
        self.hybrid = hybrid
        results["hybrid_config"] = hybrid.params()

        started = time.perf_counter()
        ranker_period = self.period(
            "ranker-train",
            self.ranker_start,
            self.validation_start,
            hybrid,
            min_history=config.ltr_min_history,
            max_users=config.ltr_users,
        )
        validation = self.period(
            "validation",
            self.validation_start,
            self.test_start,
            hybrid,
            min_history=config.min_history,
            max_users=config.tuning_users,
        )
        train_candidates = self.candidates(ranker_period, hybrid)
        valid_candidates = self.candidates(validation, hybrid)
        self._timed("candidates_tuning", started)
        results["candidates"] = {
            "ranker_train": {
                "users": len(train_candidates),
                **self.candidate_recall(train_candidates),
            },
            "validation": {
                "users": len(valid_candidates),
                **self.candidate_recall(valid_candidates),
            },
        }

        started = time.perf_counter()
        weighted, weighted_info = self.tune_weighted(train_candidates, valid_candidates)
        ltr, ltr_config, ltr_grid = self.train_ltr(train_candidates, valid_candidates)
        cc0, cc0_config, cc0_grid = self.train_ltr(
            train_candidates, valid_candidates, COMMERCIAL_FEATURES, cc0_rows
        )
        self._timed("rankers", started)

        # Validation lists decide the served ranker and the diversity settings.
        started = time.perf_counter()
        scorers: dict[str, Scorer] = {
            "weighted": weighted_scorer(weighted),
            "lambdarank": ltr_scorer(ltr),
            "cc0": ltr_scorer(cc0),
        }
        k = max(config.ks)
        context = validation.context
        validation_lists = self.lists(
            valid_candidates,
            scorers,
            [
                ListVariant("hybrid-weighted", "weighted", RANKED),
                ListVariant("hybrid-lambdarank", "lambdarank", RANKED),
                ListVariant("hybrid-lambdarank-cc0", "cc0", RANKED, cc0=True),
            ],
            k,
        )
        validation_results = {
            name: evaluate_lists(name, lists, validation.task, context, config.ks)
            for name, lists in validation_lists.items()
        }
        chosen = (
            "lambdarank"
            if validation_results["hybrid-lambdarank"].metrics["ndcg@10"]
            >= validation_results["hybrid-weighted"].metrics["ndcg@10"]
            else "weighted"
        )
        logger.info("Served ranker: %s", chosen)

        sweep = []
        for lam in config.lambdas:
            policy = DiversityPolicy("mmr", mmr_lambda=lam, max_per_artist=DEFAULT_MAX_PER_ARTIST)
            lists = self.lists(valid_candidates, scorers, [ListVariant("x", chosen, policy)], k)[
                "x"
            ]
            result = evaluate_lists(f"lambda={lam}", lists, validation.task, context, config.ks)
            sweep.append({"lambda": lam, **result.to_dict()})
        base = sweep[0]["metrics"]["ndcg@10"]
        eligible = [
            s for s in sweep if s["metrics"]["ndcg@10"] >= (1 - config.max_ndcg_loss) * base
        ]
        selected_lambda = min(s["lambda"] for s in eligible)

        # The artist cap is a product rule; measure what it costs (lambda = 1, no MMR).
        cap_sweep = []
        for cap in (1, 2, 3, 5, None):
            policy = DiversityPolicy("cap", mmr_lambda=1.0, max_per_artist=cap)
            lists = self.lists(valid_candidates, scorers, [ListVariant("x", chosen, policy)], k)[
                "x"
            ]
            result = evaluate_lists(f"cap={cap}", lists, validation.task, context, config.ks)
            cap_sweep.append({"max_per_artist": cap, **result.to_dict()})

        for_you = replace(POLICIES["for_you"], mmr_lambda=selected_lambda)
        mode_lists = self.lists(
            valid_candidates,
            scorers,
            [ListVariant(f"mode={m}", chosen, for_you, mode=m) for m in MODES],
            k,
        )
        known = [set(uc.known_artists) for uc in valid_candidates]
        mode_results = []
        for mode in MODES:
            lists = mode_lists[f"mode={mode}"]
            result = evaluate_lists(mode, lists, validation.task, context, config.ks)
            mode_results.append(
                {
                    "mode": mode,
                    **result.to_dict(),
                    **segments.discovery_metrics(
                        lists, validation.task, self.facts.artist_codes, known
                    ),
                }
            )
        ndcg_of = {m["mode"]: m["metrics"]["ndcg@10"] for m in mode_results}
        default_mode = "auto" if ndcg_of["auto"] >= ndcg_of["balanced"] else "balanced"
        self._timed("validation_lists", started)

        results["weighted"] = weighted_info
        results["lambdarank"] = {
            "grid": ltr_grid,
            "selected": ltr_config.params(),
            "best_iteration": ltr.best_iteration,
            "importance": ltr.importance(),
            "features": list(FEATURE_NAMES),
        }
        results["cc0"] = {
            "grid": cc0_grid,
            "selected": cc0_config.params(),
            "best_iteration": cc0.best_iteration,
            "features": list(COMMERCIAL_FEATURES),
            "sources": [s.value for s in CC0_SOURCES],
        }
        results["validation"] = {
            "window": validation.window,
            "users": len(validation.task),
            "results": [r.to_dict() for r in validation_results.values()],
            "served_ranker": chosen,
            "diversity_sweep": sweep,
            "artist_cap_sweep": cap_sweep,
            "selected_lambda": selected_lambda,
            "modes": mode_results,
            "default_mode": default_mode,
        }

        # Final rankers: retrained on ranker-train + validation with the selected settings.
        started = time.perf_counter()
        both = [*train_candidates, *valid_candidates]
        final_ltr = self.retrain_ltr(both, FEATURE_NAMES, ltr_config, ltr.best_iteration)
        final_cc0 = self.retrain_ltr(
            both, COMMERCIAL_FEATURES, cc0_config, cc0.best_iteration, cc0_rows
        )
        results["reproducibility"] = self.reproducibility(train_candidates[:1500], ltr_config)
        del train_candidates, valid_candidates, both
        self._timed("final_rankers", started)
        self.final = {
            "weighted": weighted,
            "lambdarank": final_ltr,
            "cc0": final_cc0,
            "served": chosen,
            "lambda": selected_lambda,
            "default_mode": default_mode,
        }

        results["test"] = self.run_test(hybrid, scorers_for_test(weighted, final_ltr, final_cc0))
        results["rolling"] = self.run_rolling(
            hybrid, scorers_for_test(weighted, final_ltr, final_cc0)
        )
        results["cold_start"] = self.run_cold_start(
            hybrid, scorers_for_test(weighted, final_ltr, final_cc0)
        )
        results["onboarding"] = self.run_onboarding()
        results["stability"] = self.run_stability(hybrid)
        results["timings"] = self.timings
        return results

    # --- 6. test -------------------------------------------------------------------------------

    def final_variants(self) -> list[ListVariant]:
        served, lam = self.final["served"], self.final["lambda"]
        for_you = replace(POLICIES["for_you"], mmr_lambda=lam)
        return [
            ListVariant("hybrid-weighted", "weighted", RANKED),
            ListVariant("hybrid-lambdarank", "lambdarank", RANKED),
            ListVariant(
                "hybrid-lambdarank (no artist cap)",
                "lambdarank",
                DiversityPolicy("uncapped", mmr_lambda=1.0, max_per_artist=None),
            ),
            ListVariant("hybrid-lambdarank-cc0", "cc0", RANKED, cc0=True),
            ListVariant(
                "hybrid+mmr", served, DiversityPolicy("mmr", mmr_lambda=lam, max_per_artist=2)
            ),
            *(ListVariant(f"hybrid+mmr [{m}]", served, for_you, mode=m) for m in MODES),
        ]

    def evaluate_hybrid(
        self, period: Period, scorers: Mapping[str, Scorer], variants: Sequence[ListVariant]
    ) -> tuple[dict[str, IntArray], dict[str, Any]]:
        """Stream the period's users through the engine and build every variant's lists."""
        engine = CandidateEngine(period.models, self.content, self.facts, self.hybrid)
        relevant = dict(zip(period.task.users, period.task.relevant, strict=True))
        k = max(self.config.ks)
        users = list(period.task.users)
        lists = {v.name: np.full((len(users), k), -1, dtype=np.int64) for v in variants}
        started = time.perf_counter()
        position = 0
        chunk: list[UserCandidates] = []
        for uc in engine.generate(users, relevant):
            chunk.append(uc)
            if len(chunk) == 500 or position + len(chunk) == len(users):
                built = self.lists(chunk, scorers, variants, k)
                for name, values in built.items():
                    lists[name][position : position + len(chunk)] = values
                position += len(chunk)
                chunk = []
        seconds = time.perf_counter() - started
        info = {
            "seconds": round(seconds, 1),
            "ms_per_user": round(1000 * seconds / max(len(users), 1), 2),
        }
        return lists, info

    def run_test(self, hybrid: HybridConfig, scorers: Mapping[str, Scorer]) -> dict[str, Any]:
        started = time.perf_counter()
        config = self.config
        period = self.period(
            "test",
            self.test_start,
            self.end,
            hybrid,
            min_history=config.min_history,
            max_users=config.test_users,
        )
        task, context, models = period.task, period.context, period.models
        all_lists: dict[str, IntArray] = {}
        results: list[ModelResult] = []
        for recommender in self.m2_recommenders(period):
            lists = recommender.recommend(task, max(config.ks))
            all_lists[recommender.name] = lists
            results.append(evaluate_lists(recommender.name, lists, task, context, config.ks))
        selected = self.hybrid
        cf_models: list[tuple[str, Recommender]] = [
            (
                f"cf-als (f{selected.als.factors})",
                self.als_recommender(period, models, "cf-als"),
            ),
            (
                f"cf-item-item ({selected.item_item.weighting})",
                self.item_recommender(models, "cf-item-item"),
            ),
        ]
        cf_models.append(
            (
                "cf-user-user",
                ScoreListRecommender(
                    "cf-user-user",
                    self.user_knn_scores(models, max(config.user_knn_neighbours)),
                    self.facts,
                ),
            )
        )
        for name, recommender in cf_models:
            lists = recommender.recommend(task, max(config.ks))
            all_lists[name] = lists
            results.append(evaluate_lists(name, lists, task, context, config.ks))
        variants = self.final_variants()
        hybrid_lists, info = self.evaluate_hybrid(period, scorers, variants)
        for variant in variants:
            lists = hybrid_lists[variant.name]
            all_lists[variant.name] = lists
            results.append(
                evaluate_lists(variant.name, lists, task, context, config.ks, info["seconds"])
            )

        known = segments.known_artists(task, self.facts.artist_codes)
        discovery = {
            name: segments.discovery_metrics(lists, task, self.facts.artist_codes, known)
            for name, lists in all_lists.items()
        }
        buckets = segments.history_buckets(task)
        genres = segments.dominant_genres(task, self.genre_affinity, self.genre_names)
        strata = segments.popularity_strata(models.listeners)
        focus = [
            "popularity",
            "content-profile (M2)",
            cf_models[0][0],
            cf_models[1][0],
            "hybrid-lambdarank",
            "hybrid-weighted",
            f"hybrid+mmr [{self.final['default_mode']}]",
        ]
        served = f"hybrid+mmr [{self.final['default_mode']}]"
        best_cf = max(
            (name for name, _ in cf_models),
            key=lambda n: next(r.metrics["ndcg@10"] for r in results if r.name == n),
        )
        paired = {
            f"{a} vs {b}": segments.paired_difference(all_lists[a], all_lists[b], task)
            for a, b in (
                ("hybrid-lambdarank", "content-profile (M2)"),
                ("hybrid-weighted", "content-profile (M2)"),
                (served, "content-profile (M2)"),
                ("hybrid-lambdarank", best_cf),
                (served, "hybrid-lambdarank"),
                ("hybrid-lambdarank-cc0", "hybrid-lambdarank"),
            )
        }
        self._timed("test", started)
        self.test_period = period
        self.test_lists = all_lists
        return {
            "window": period.window,
            "users": len(task),
            "train_users": models.train_users,
            "results": [r.to_dict() for r in results],
            "discovery": discovery,
            "hybrid_timing": info,
            "segments": {
                "history": {
                    n: segments.segment_metrics(all_lists[n], task, buckets) for n in focus
                },
                "genre": {n: segments.segment_metrics(all_lists[n], task, genres) for n in focus},
                "popularity": {
                    n: segments.stratified_recall(all_lists[n], task, strata) for n in focus
                },
            },
            "paired": paired,
            "served_variant": served,
            "best_cf": best_cf,
        }

    # --- 7. rolling windows, cold start, onboarding, stability ------------------------------

    def run_rolling(
        self, hybrid: HybridConfig, scorers: Mapping[str, Scorer]
    ) -> list[dict[str, Any]]:
        started = time.perf_counter()
        config = self.config
        served = f"hybrid+mmr [{self.final['default_mode']}]"
        windows = []
        for offset in range(config.rolling_windows):
            cutoff = self.test_start + offset * DAY
            period = self.period(
                f"rolling-{offset + 1}",
                cutoff,
                cutoff + DAY,
                hybrid,
                min_history=config.min_history,
                max_users=config.rolling_users,
            )
            variants = [
                v
                for v in self.final_variants()
                if v.name in ("hybrid-lambdarank", served, "hybrid-weighted")
            ]
            lists, _ = self.evaluate_hybrid(period, scorers, variants)
            baselines = self.m2_recommenders(period)[1:4:2]  # popularity, content-profile
            rows = [evaluate(r, period.task, period.context, (10,)) for r in baselines]
            rows.append(
                evaluate(
                    self.item_recommender(period.models, "cf-item-item"), period.task, None, (10,)
                )
            )
            rows.append(
                evaluate(
                    self.als_recommender(period, period.models, "cf-als"), period.task, None, (10,)
                )
            )
            rows.extend(
                evaluate_lists(name, values, period.task, period.context, (10,))
                for name, values in lists.items()
            )
            windows.append(
                {
                    "window": period.window,
                    "users": len(period.task),
                    "results": [r.to_dict() for r in rows],
                }
            )
        self._timed("rolling", started)
        return windows

    def run_cold_start(self, hybrid: HybridConfig, scorers: Mapping[str, Scorer]) -> dict[str, Any]:
        started = time.perf_counter()
        config = self.config
        period = self.period(
            "low-history",
            self.test_start,
            self.end,
            hybrid,
            min_history=1,
            max_users=config.low_history_users,
            max_history=config.min_history - 1,
        )
        served = f"hybrid+mmr [{self.final['default_mode']}]"
        variants = [v for v in self.final_variants() if v.name in ("hybrid-lambdarank", served)]
        lists, _ = self.evaluate_hybrid(period, scorers, variants)
        rows = [
            evaluate(r, period.task, period.context, (10,))
            for r in self.m2_recommenders(period)[1:4:2]
        ]
        rows.append(
            evaluate(self.item_recommender(period.models, "cf-item-item"), period.task, None, (10,))
        )
        rows.append(
            evaluate(
                self.als_recommender(period, period.models, "cf-als"), period.task, None, (10,)
            )
        )
        rows.extend(
            evaluate_lists(name, values, period.task, period.context, (10,))
            for name, values in lists.items()
        )
        self._timed("cold_start", started)
        return {
            "window": period.window,
            "users": len(period.task),
            "results": [r.to_dict() for r in rows],
        }

    def run_onboarding(self) -> dict[str, Any]:
        """Brand-new users: what onboarding answers are worth. Simulated on test users, who
        "declare" the top genres and artists of their training history and nothing else."""
        started = time.perf_counter()
        config = self.config
        period = self.test_period
        rng = np.random.default_rng(config.seed)
        n = min(config.onboarding_users, len(period.task))
        chosen = np.sort(rng.choice(len(period.task), n, replace=False))
        task = EvaluationTask(
            users=period.task.users[chosen],
            history=[np.zeros(0, dtype=np.int64) for _ in chosen],
            history_plays=[np.zeros(0, dtype=np.int64) for _ in chosen],
            relevant=[period.task.relevant[i] for i in chosen],
            seeds=period.task.seeds[chosen],
            n_items=period.task.n_items,
        )
        full_history = [period.task.history[i] for i in chosen]
        models = period.models
        k = max(config.ks)
        engine = CandidateEngine(models, self.content, self.facts, self.hybrid)
        lists = {
            "popularity": np.full((n, k), -1, dtype=np.int64),
            "declared genres": np.full((n, k), -1, dtype=np.int64),
            "declared genres + artists": np.full((n, k), -1, dtype=np.int64),
        }
        for row, user in enumerate(task.users):
            profile, _ = engine.profile(models.signals.position[user])
            heard = frozenset(full_history[row].tolist())
            genres = list(profile.genre_affinity)[:3]
            artists = list(profile.artist_affinity)[:3]
            popular = [i for i, _ in models.global_ranking]
            genre_lists = [models.genre_ranking(g, self.facts, 300) for g in genres]
            interleaved: list[int] = []
            for position in range(300):
                for ranking in genre_lists:
                    if position < len(ranking):
                        interleaved.append(ranking[position][0])
            interleaved.extend(popular)
            for name, order in (("popularity", popular), ("declared genres", interleaved)):
                lists[name][row] = self._capped(order, heard, k)
            vectors = models.artist_embeddings[np.array(artists, dtype=np.int64)]
            declared: TasteProfile[int, int] = build_taste_profile(
                aggregate_events(
                    [],
                    [],
                    [],
                    None,
                    weights=self.hybrid.profile.feedback,
                    long_decay=self.hybrid.profile.long_decay,
                    short_decay=self.hybrid.profile.short_decay,
                ),
                track_artists=[],
                track_embeddings=None,
                track_genres=None,
                config=self.hybrid.profile,
                declared_artist_embeddings=vectors,
            )
            if declared.long_term_embedding is None:
                lists["declared genres + artists"][row] = lists["declared genres"][row]
                continue
            sims = self.content.embeddings @ declared.long_term_embedding.astype(np.float32)
            pool = np.argpartition(-sims, 200)[:200]
            candidates = set(pool.tolist()) | set(interleaved[:100])
            ranked = sorted(
                candidates,
                key=lambda i: (
                    -blended_score(
                        float(sims[i]), float(models.score[i]), COLD_START_POPULARITY_WEIGHT
                    )
                ),
            )
            lists["declared genres + artists"][row] = self._capped(ranked, heard, k)
        rows = [
            evaluate_lists(name, values, task, period.context, (10,)).to_dict()
            for name, values in lists.items()
        ]
        self._timed("onboarding", started)
        return {"users": n, "declared_genres": 3, "declared_artists": 3, "results": rows}

    def _capped(self, ranking: Sequence[int], heard: frozenset[int], k: int) -> IntArray:
        pool = [i for i in ranking if i not in heard][:200]
        if not pool:
            return np.full(k, -1, dtype=np.int64)
        items = np.array(pool, dtype=np.int64)
        picked = compose(
            -np.arange(len(items), dtype=np.float64),
            limit=k,
            policy=RANKED,
            artists=self.facts.artist_codes[items].tolist(),
            song_keys=[self.facts.song_keys[i] for i in pool],
        )
        out = np.full(k, -1, dtype=np.int64)
        out[: len(picked)] = items[picked]
        return out

    def run_stability(self, hybrid: HybridConfig) -> dict[str, Any]:
        """Profiles of the same users three days apart: recent listening must not erase
        long-term taste. Also: does the exploration preference predict discovery?"""
        started = time.perf_counter()
        config = self.config
        before = self.models("validation", self.validation_start, hybrid)
        after = self.test_period.models
        task = self.test_period.task
        rng = np.random.default_rng(config.seed)
        users = [u for u in task.users if u in before.signals.position]
        users = sorted(rng.choice(users, min(config.stability_users, len(users)), replace=False))
        engine_before = CandidateEngine(before, self.content, self.facts, hybrid)
        engine_after = CandidateEngine(after, self.content, self.facts, hybrid)
        relevant = dict(zip(task.users, task.relevant, strict=True))
        long_cos, short_cos, cross_cos, genre_jaccard, artist_jaccard = [], [], [], [], []
        exploration, realized = [], []

        def jaccard(a: Sequence[Any], b: Sequence[Any]) -> float:
            sa, sb = set(a), set(b)
            return len(sa & sb) / len(sa | sb) if sa | sb else 1.0

        for user in users:
            p0, _ = engine_before.profile(before.signals.position[user])
            p1, _ = engine_after.profile(after.signals.position[user])
            if p0.long_term_embedding is not None and p1.long_term_embedding is not None:
                long_cos.append(float(p0.long_term_embedding @ p1.long_term_embedding))
            if p0.short_term_embedding is not None and p1.short_term_embedding is not None:
                short_cos.append(float(p0.short_term_embedding @ p1.short_term_embedding))
            if p0.long_term_embedding is not None and p1.short_term_embedding is not None:
                cross_cos.append(float(p0.long_term_embedding @ p1.short_term_embedding))
            genre_jaccard.append(
                jaccard(list(p0.genre_affinity)[:10], list(p1.genre_affinity)[:10])
            )
            artist_jaccard.append(
                jaccard(list(p0.artist_affinity)[:10], list(p1.artist_affinity)[:10])
            )
            targets = relevant[user]
            new = [a not in p1.known_artists for a in self.facts.artist_codes[targets]]
            exploration.append(p1.exploration_preference)
            realized.append(float(np.mean(new)))
        exploration_arr, realized_arr = np.array(exploration), np.array(realized)
        ranks = pd.Series(exploration_arr).rank().corr(pd.Series(realized_arr).rank())
        self._timed("stability", started)
        return {
            "users": len(users),
            "window": {"before": str(self.validation_start), "after": str(self.test_start)},
            "long_term_cosine": float(np.mean(long_cos)),
            "short_term_cosine": float(np.mean(short_cos)) if short_cos else None,
            "long_before_vs_short_after_cosine": float(np.mean(cross_cos)) if cross_cos else None,
            "top10_genre_jaccard": float(np.mean(genre_jaccard)),
            "top10_artist_jaccard": float(np.mean(artist_jaccard)),
            "exploration": {
                "mean_preference": float(exploration_arr.mean()),
                "mean_new_artist_share_of_future_tracks": float(realized_arr.mean()),
                "pearson": float(np.corrcoef(exploration_arr, realized_arr)[0, 1]),
                "spearman": float(ranks),
            },
        }

    # --- reproducibility -----------------------------------------------------------------------

    def reproducibility(
        self, candidates: Sequence[UserCandidates], ltr_config: LambdaRankConfig
    ) -> dict[str, Any]:
        """Train the ranker twice on the same data, and regenerate candidates for the same users:
        both must be identical."""
        hashes = []
        for _ in range(2):
            model = train_lambdarank(
                RankingData.stack([c.features for c in candidates], [c.labels for c in candidates]),
                FEATURE_NAMES,
                ltr_config,
                rounds=50,
            )
            dump = json.dumps(model.export().to_dict(), sort_keys=True)
            hashes.append(hashlib.sha256(dump.encode()).hexdigest())
        period_models = next(iter(self._models.values()))
        engine = CandidateEngine(period_models, self.content, self.facts, self.hybrid)
        users = list(period_models.signals.users[:200])
        first = [(c.items.tolist(), c.features.tobytes()) for c in engine.generate(users)]
        second = [(c.items.tolist(), c.features.tobytes()) for c in engine.generate(users)]
        return {
            "ranker_identical": hashes[0] == hashes[1],
            "ranker_sha256": hashes[0][:16],
            "candidates_identical": first == second,
            "candidate_users": len(users),
        }


def scorers_for_test(
    weighted: WeightedHybridRanker, ltr: TrainedRanker, cc0: TrainedRanker
) -> dict[str, Scorer]:
    return {
        "weighted": weighted_scorer(weighted),
        "lambdarank": ltr_scorer(ltr),
        "cc0": ltr_scorer(cc0),
    }


def run_hybrid_experiment(
    catalogue: CatalogueData,
    interactions: pd.DataFrame,
    content: ContentAssets,
    config: HybridExperimentConfig | None = None,
) -> tuple[dict[str, Any], HybridExperiment]:
    started = time.perf_counter()
    experiment = HybridExperiment(catalogue, interactions, content, config)
    # Per-user work is many small matrix operations: multi-threaded BLAS only adds overhead
    # (implicit and LightGBM keep their own OpenMP parallelism).
    with threadpool_limits(1, user_api="blas"):
        results = experiment.run()
    results["catalogue_items"] = catalogue.n_items
    results["interactions"] = len(interactions)
    results["content_version"] = content.version
    results["seconds"] = round(time.perf_counter() - started, 1)
    return results, experiment
