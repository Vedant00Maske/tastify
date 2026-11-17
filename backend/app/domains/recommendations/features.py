"""Ranking features of a (user, candidate track) pair, with their provenance (ADR-016).

Every feature records which signal produces it and the most restrictive usage restriction of the
data behind it, so a ranker can be retrained on commercially usable signals only (spec: keep
licensing separation). `restriction`:

- "non_commercial": derived from the content model, whose genre signal is MusicBrainz tags
  (CC BY-NC-SA);
- "none": ListenBrainz listens (CC0), or the user's own TASTIFY interactions.

`feature_matrix` builds the matrix from per-candidate arrays; the API and the offline evaluation
both call it, so a trained ranker sees identical features in both.

Score features also come as percentile ranks within the user's candidate set (`q_rank_*`). Raw
scores shift between training periods (collaborative scores grow with the amount of data, for
example), while their order within one user's candidates is stable, so the ranks let a ranker
trained on one period transfer to the next.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from app.domains.recommendations.candidate_generation.base import (
    CONTENT_DERIVED_SOURCES,
    SOURCE_ORDER,
)

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    description: str
    signal: str
    restriction: str


_CONTENT = ("content model", "non_commercial")
_CF = ("collaborative model (ListenBrainz listens)", "none")
_POPULARITY = ("popularity model (ListenBrainz listens)", "none")
_USER = ("the user's own interactions", "none")

FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("content_seed_max", "Best content similarity to a seed track", *_CONTENT),
    FeatureSpec("content_seed_mean", "Mean content similarity to the seed tracks", *_CONTENT),
    FeatureSpec("profile_sim", "Similarity to the taste-profile query", *_CONTENT),
    FeatureSpec("profile_long_sim", "Similarity to the long-term embedding", *_CONTENT),
    FeatureSpec("profile_short_sim", "Similarity to the short-term embedding", *_CONTENT),
    FeatureSpec("cf_item_score", "Item-item score / total history weight", *_CF),
    FeatureSpec("cf_mf_score", "ALS score (user factors . track factors)", *_CF),
    FeatureSpec("popularity", "log(1 + listeners) / log(1 + max listeners)", *_POPULARITY),
    FeatureSpec("novelty", "Self-information of the track / maximum", *_POPULARITY),
    FeatureSpec("artist_affinity", "The user's affinity for the track's artist", *_USER),
    FeatureSpec("artist_known", "1 if the user already plays the artist", *_USER),
    FeatureSpec("artist_negative", "The user's negative signal for the artist", *_USER),
    FeatureSpec("user_history_log", "log(1 + distinct positive tracks)", *_USER),
    FeatureSpec("user_exploration", "The user's exploration preference", *_USER),
    *(
        FeatureSpec(
            f"rr_{source.value}",
            f"1 / rank in the {source.value} candidates (0 if absent)",
            f"candidate source {source.value}",
            "non_commercial" if source in CONTENT_DERIVED_SOURCES else "none",
        )
        for source in SOURCE_ORDER
    ),
)
# Score features that also get a within-candidate-set percentile rank.
RANKED_FEATURES = (
    "content_seed_max",
    "content_seed_mean",
    "profile_sim",
    "profile_long_sim",
    "profile_short_sim",
    "cf_item_score",
    "cf_mf_score",
    "popularity",
    "novelty",
)
_BASE = {f.name: f for f in FEATURES}
FEATURES = (
    *FEATURES,
    *(
        FeatureSpec(
            f"q_rank_{name}",
            f"Percentile rank of {name} among the user's candidates (ties averaged)",
            _BASE[name].signal,
            _BASE[name].restriction,
        )
        for name in RANKED_FEATURES
    ),
)
FEATURE_NAMES: tuple[str, ...] = tuple(f.name for f in FEATURES)
FEATURE_INDEX = {name: i for i, name in enumerate(FEATURE_NAMES)}
COMMERCIAL_FEATURES: tuple[str, ...] = tuple(f.name for f in FEATURES if f.restriction == "none")


@dataclass(frozen=True)
class FeatureInputs:
    """Per-candidate arrays (length n). None means "signal unavailable" and becomes 0."""

    popularity: FloatArray
    novelty: FloatArray
    artist_affinity: FloatArray
    artist_known: FloatArray
    artist_negative: FloatArray
    # (n, len(SOURCE_ORDER)) 1-based ranks, inf where a source did not find the candidate.
    source_ranks: FloatArray
    history_size: int
    exploration: float
    # (n, number of seeds): similarity of each candidate to each content seed.
    seed_similarity: FloatArray | None = None
    profile_sim: FloatArray | None = None
    profile_long_sim: FloatArray | None = None
    profile_short_sim: FloatArray | None = None
    cf_item_score: FloatArray | None = None
    cf_mf_score: FloatArray | None = None


def _column(values: FloatArray | None, n: int) -> FloatArray:
    if values is None:
        return np.zeros(n)
    return np.nan_to_num(np.asarray(values, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)


def feature_matrix(inputs: FeatureInputs) -> npt.NDArray[np.float32]:
    """(n, len(FEATURES)) float32, columns in FEATURE_NAMES order, no NaN or inf."""
    n = len(inputs.popularity)
    seeds = inputs.seed_similarity
    if seeds is not None and seeds.size:
        seed_max = seeds.max(axis=1)
        seed_mean = seeds.mean(axis=1)
    else:
        seed_max = seed_mean = np.zeros(n)
    ranks = np.asarray(inputs.source_ranks, dtype=np.float64)
    with np.errstate(divide="ignore"):
        reciprocal = np.where(np.isfinite(ranks), 1.0 / ranks, 0.0)
    columns: Sequence[FloatArray] = (
        _column(seed_max, n),
        _column(seed_mean, n),
        _column(inputs.profile_sim, n),
        _column(inputs.profile_long_sim, n),
        _column(inputs.profile_short_sim, n),
        _column(inputs.cf_item_score, n),
        _column(inputs.cf_mf_score, n),
        _column(inputs.popularity, n),
        _column(inputs.novelty, n),
        _column(inputs.artist_affinity, n),
        _column(inputs.artist_known, n),
        _column(inputs.artist_negative, n),
        np.full(n, np.log1p(inputs.history_size)),
        np.full(n, inputs.exploration),
    )
    if n == 0:
        return np.zeros((0, len(FEATURES)), dtype=np.float32)
    base = np.column_stack([*columns, reciprocal])
    rank_columns = [percentile_ranks(base[:, FEATURE_INDEX[name]]) for name in RANKED_FEATURES]
    return np.asarray(np.column_stack([base, *rank_columns]), dtype=np.float32)


def percentile_ranks(values: FloatArray) -> FloatArray:
    """Rank of each value in [0, 1] (0 = smallest), ties sharing their average rank, so the
    result does not depend on the candidates' order."""
    n = len(values)
    if n < 2:
        return np.zeros(n)
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    average = (ends - counts + ends - 1) / 2.0
    return np.asarray(average[inverse.reshape(-1)] / (n - 1), dtype=np.float64)
