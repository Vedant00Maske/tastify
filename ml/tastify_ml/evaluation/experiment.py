"""The Milestone 2 offline experiment (docs/reports/model-benchmark.md).

Protocol:
1. The data window ends at the last complete day. The final `test_days` are the test period and
   the `validation_days` before them the validation period. Each period is predicted from all
   earlier interactions only.
2. Hyperparameters (content feature weights and the popularity blend beta) are chosen on the
   validation period. The test period is used once, to report results.
3. Popularity is recomputed from each training period. Content embeddings use catalogue metadata
   only (no interactions), so they can be shared by both periods.
"""

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
import scipy.sparse as sp

from app.domains.recommendations.ranking import GENRE_PRIOR_VOTES, LEVEL_WEIGHTS, song_key
from tastify_ml.evaluation import metrics
from tastify_ml.evaluation.recommenders import (
    ContentRecommender,
    GenrePopularityRecommender,
    RandomRecommender,
    RankedListRecommender,
    Recommender,
    SimilarArtistRecommender,
    popularity_ranking,
    trending_ranking,
)
from tastify_ml.evaluation.runner import MetricContext, ModelResult, evaluate
from tastify_ml.evaluation.split import EvaluationTask, build_task, temporal_split
from tastify_ml.recommendation.catalogue_data import CatalogueData
from tastify_ml.recommendation.content import (
    ContentConfig,
    ContentModel,
    artist_embeddings,
    fit_content_model,
)
from tastify_ml.recommendation.popularity import PopularityConfig, compute_popularity

logger = logging.getLogger(__name__)

DAY = pd.Timedelta(days=1)
Mode = Literal["seed", "profile", "artist"]

# Feature-weight variants compared on validation; "default" is ContentConfig().
CONTENT_VARIANTS: Mapping[str, ContentConfig] = {
    "default": ContentConfig(),
    "light-metadata": ContentConfig(categorical_weight=0.2, numeric_weight=0.2),
    "heavy-metadata": ContentConfig(categorical_weight=0.5, numeric_weight=0.5),
    "no-audio": ContentConfig(numeric_weight=0.0),
    "genres-only": ContentConfig(categorical_weight=0.0, numeric_weight=0.0),
    "raw-tags": ContentConfig(genre_prior_votes=0.0),
}


@dataclass(frozen=True)
class ExperimentConfig:
    validation_days: int = 3
    test_days: int = 3
    min_history: int = 5
    ks: tuple[int, ...] = (10, 20)
    # Users sampled for the tuning grid; the test period uses every eligible user.
    tuning_users: int = 5000
    test_users: int | None = None
    betas: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
    fidelity_queries: int = 1000
    seed: int = 42
    popularity: PopularityConfig = field(default_factory=PopularityConfig)

    def params(self) -> dict[str, Any]:
        return asdict(self)


def load_interactions(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    return frame.assign(
        user_key=frame["user_key"].astype("category"), track_id=frame["track_id"].astype("category")
    )


def data_end(interactions: pd.DataFrame) -> pd.Timestamp:
    """End of the last complete day (exclusive): later stragglers are ignored."""
    return pd.Timestamp(interactions["listened_at"].max()).floor("D")


def song_keys(catalogue: CatalogueData) -> list[str]:
    """ranking.song_key of every item, as the API computes it for de-duplication."""
    tracks = catalogue.tracks
    return [
        song_key(artist, str(title))
        for artist, title in zip(tracks["artist_id"], tracks["title"], strict=True)
    ]


def genre_affinity_matrix(catalogue: CatalogueData) -> tuple[sp.csr_matrix, list[str]]:
    """(n_items, n_genres): strongest level-weighted, smoothed tag weight, as served by
    GET /recommendations/genre/{genre} (ranking.genre_affinity)."""
    genres = catalogue.tag_weights(GENRE_PRIOR_VOTES)
    values = genres["weight"].to_numpy() * genres["level"].map(LEVEL_WEIGHTS).to_numpy()
    strongest = (
        genres.assign(value=values).groupby(["item", "genre"], observed=True)["value"].max()
    ).reset_index()
    codes, names = pd.factorize(strongest["genre"])
    matrix = sp.csr_matrix(
        (strongest["value"].to_numpy(), (strongest["item"].to_numpy(), codes)),
        shape=(catalogue.n_items, len(names)),
    )
    return matrix, [str(n) for n in names]


@dataclass
class Period:
    """One train/predict period: the task and the training-period popularity."""

    name: str
    task: EvaluationTask
    popularity: pd.DataFrame
    train_users: int
    window: dict[str, str]

    @property
    def listeners(self) -> npt.NDArray[np.int64]:
        return self.popularity["listeners"].to_numpy(dtype=np.int64)

    @property
    def score(self) -> npt.NDArray[np.float64]:
        return self.popularity["score"].to_numpy(dtype=np.float64)


def make_period(
    name: str,
    interactions: pd.DataFrame,
    catalogue: CatalogueData,
    cutoff: pd.Timestamp,
    end: pd.Timestamp,
    config: ExperimentConfig,
    max_users: int | None,
) -> Period:
    split = temporal_split(interactions, cutoff, end)
    item_of = pd.Series(np.arange(catalogue.n_items), index=catalogue.track_ids)
    task = build_task(
        split,
        item_of,
        catalogue.n_items,
        min_history=config.min_history,
        max_users=max_users,
        seed=config.seed,
    )
    popularity = compute_popularity(split.train, catalogue.track_ids, cutoff, config.popularity)
    window = {
        "train_start": str(split.start),
        "cutoff": str(cutoff),
        "end": str(end),
    }
    logger.info(
        "%s period: %d users, train %s -> %s -> %s", name, len(task), split.start, cutoff, end
    )
    return Period(name, task, popularity, int(split.train["user_key"].nunique()), window)


class Experiment:
    def __init__(
        self,
        catalogue: CatalogueData,
        interactions: pd.DataFrame,
        config: ExperimentConfig | None = None,
    ) -> None:
        self.catalogue = catalogue
        self.config = config or ExperimentConfig()
        self.artist_codes = catalogue.artist_codes().astype(np.int64)
        self.dedup_keys = song_keys(catalogue)
        self.affinity, _ = genre_affinity_matrix(catalogue)
        end = data_end(interactions)
        test_start = end - self.config.test_days * DAY
        validation_start = test_start - self.config.validation_days * DAY
        self.validation = make_period(
            "validation",
            interactions,
            catalogue,
            validation_start,
            test_start,
            self.config,
            self.config.tuning_users,
        )
        self.test = make_period(
            "test", interactions, catalogue, test_start, end, self.config, self.config.test_users
        )
        self._models: dict[str, ContentModel] = {}

    def content_model(self, variant: str) -> ContentModel:
        if variant not in self._models:
            self._models[variant] = fit_content_model(self.catalogue, CONTENT_VARIANTS[variant])
        return self._models[variant]

    def recommender(self, mode: Mode, variant: str, beta: float, period: Period) -> Recommender:
        model = self.content_model(variant)
        name = f"content-{mode}"
        if mode == "artist":
            artists, _ = artist_embeddings(model.embeddings, self.artist_codes, period.listeners)
            return SimilarArtistRecommender(
                artists, self.artist_codes, period.score, self.dedup_keys, beta=beta, name=name
            )
        return ContentRecommender(
            name, model.embeddings, period.score, self.artist_codes, self.dedup_keys, beta, mode
        )

    # --- tuning ------------------------------------------------------------------------------

    def tune(self) -> dict[str, Any]:
        """Grid search on the validation period, by NDCG@10.

        The variant is chosen for the seed mode (it serves /similar); the blend for the profile and
        artist modes is then tuned on that variant."""
        grid: list[dict[str, Any]] = []

        def score(mode: Mode, variant: str, beta: float) -> float:
            result = evaluate(
                self.recommender(mode, variant, beta, self.validation),
                self.validation.task,
                None,
                ks=(10,),
            )
            value = result.metrics["ndcg@10"]
            grid.append({"mode": mode, "variant": variant, "beta": beta, "ndcg@10": value})
            return value

        best: dict[Mode, tuple[float, str, float]] = {}
        for variant in CONTENT_VARIANTS:
            for beta in self.config.betas:
                value = score("seed", variant, beta)
                if value > best.get("seed", (-1.0, "", 0.0))[0]:
                    best["seed"] = (value, variant, beta)
        variant = best["seed"][1]
        for mode in ("profile", "artist"):
            for beta in self.config.betas:
                value = score(mode, variant, beta)
                if value > best.get(mode, (-1.0, "", 0.0))[0]:
                    best[mode] = (value, variant, beta)
        logger.info("Selected variant %s, betas %s", variant, {m: b[2] for m, b in best.items()})
        return {
            "variant": variant,
            "content_config": CONTENT_VARIANTS[variant].params(),
            "beta": {mode: b[2] for mode, b in best.items()},
            "validation_ndcg@10": {mode: b[0] for mode, b in best.items()},
            "grid": grid,
        }

    # --- test --------------------------------------------------------------------------------

    def metric_context(self, variant: str, period: Period) -> MetricContext:
        return MetricContext(
            embeddings=self.content_model(variant).embeddings,
            artist_codes=self.artist_codes,
            information=metrics.self_information(period.listeners, period.train_users),
        )

    def baselines(self, period: Period) -> list[Recommender]:
        listeners = period.listeners
        trending = period.popularity["trending_score"].to_numpy(dtype=np.float64)
        ranking = popularity_ranking(listeners)
        return [
            RandomRecommender(self.catalogue.n_items, seed=self.config.seed),
            RankedListRecommender("popularity", ranking),
            RankedListRecommender("trending", trending_ranking(trending, listeners)),
            GenrePopularityRecommender(self.affinity, period.score, self.artist_codes, ranking),
        ]

    def run_test(self, selection: Mapping[str, Any]) -> dict[str, Any]:
        period, variant, betas = self.test, selection["variant"], selection["beta"]
        context = self.metric_context(variant, period)
        models: list[Recommender] = [
            *self.baselines(period),
            *(
                self.recommender(mode, variant, betas[mode], period)
                for mode in ("seed", "profile", "artist")
            ),
        ]
        results = [evaluate(model, period.task, context, self.config.ks) for model in models]
        ablations: list[ModelResult] = []
        pure = evaluate(
            self.recommender("seed", variant, 0.0, period), period.task, context, self.config.ks
        )
        pure.name = "content-seed (beta=0)"
        ablations.append(pure)
        for other in CONTENT_VARIANTS:
            if other == variant:
                continue
            result = evaluate(
                self.recommender("seed", other, betas["seed"], period),
                period.task,
                context,
                self.config.ks,
            )
            result.name = f"content-seed [{other}]"
            ablations.append(result)
        trending_reliable = int(period.popularity["trending_score"].notna().sum())
        return {
            "window": period.window,
            "users": len(period.task),
            "train_users": period.train_users,
            "mean_relevant": float(np.mean([len(r) for r in period.task.relevant])),
            "trending_reliable_tracks": trending_reliable,
            "results": [r.to_dict() for r in results],
            "ablations": [r.to_dict() for r in ablations],
        }

    # --- compression fidelity ----------------------------------------------------------------

    def fidelity(self, variant: str, k: int = 10) -> dict[str, float]:
        """How well the 128-d embedding preserves the neighbours of the uncompressed features."""
        model = self.content_model(variant)
        rng = np.random.default_rng(self.config.seed)
        queries = rng.choice(self.catalogue.n_items, self.config.fidelity_queries, replace=False)
        exact = np.asarray((model.features[queries] @ model.features.T).todense())
        approx = model.embeddings[queries] @ model.embeddings.T
        exact[np.arange(len(queries)), queries] = -np.inf
        approx[np.arange(len(queries)), queries] = -np.inf
        exact_top = np.argpartition(-exact, k, axis=1)[:, :k]
        approx_top = np.argpartition(-approx, k, axis=1)[:, :k]
        overlap = [
            len(np.intersect1d(a, b)) / k for a, b in zip(exact_top, approx_top, strict=True)
        ]
        return {
            "explained_variance": model.explained_variance,
            f"neighbour_recall@{k}": float(np.mean(overlap)),
            "queries": len(queries),
            **{f"dimensions_{name}": float(v) for name, v in model.block_dimensions.items()},
        }


def run_experiment(
    catalogue: CatalogueData,
    interactions: pd.DataFrame,
    config: ExperimentConfig | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    experiment = Experiment(catalogue, interactions, config)
    selection = experiment.tune()
    test = experiment.run_test(selection)
    fidelity = experiment.fidelity(selection["variant"])
    return {
        "config": experiment.config.params(),
        "catalogue_items": catalogue.n_items,
        "interactions": len(interactions),
        "validation": {
            "window": experiment.validation.window,
            "users": len(experiment.validation.task),
        },
        "selection": selection,
        "test": test,
        "fidelity": fidelity,
        "seconds": round(time.perf_counter() - started, 1),
    }


def selected_content_config(evaluation: Mapping[str, Any] | None) -> ContentConfig:
    if not evaluation:
        return ContentConfig()
    return replace(ContentConfig(), **evaluation["selection"]["content_config"])


def selected_betas(evaluation: Mapping[str, Any] | None) -> dict[str, float]:
    default = {"seed": 0.3, "profile": 0.3, "artist": 0.3}
    if not evaluation:
        return default
    return {**default, **evaluation["selection"]["beta"]}


def summarize(results: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[list[str]]:
    """Rows of formatted metric values, for reports and logs."""
    return [
        [str(r["name"]), *(f"{r['metrics'].get(key, float('nan')):.4f}" for key in keys)]
        for r in results
    ]
