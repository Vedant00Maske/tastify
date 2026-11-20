"""Collaborative candidates: what listeners with overlapping taste play.

Two models, both trained offline on listening data and published as item-level data only (no
research user's history or factors ever enters the application database, ADR-016):

- item-item: for every track, its nearest co-listened tracks with a similarity. A user's score
  for a track is the sum, over the user's history, of history weight x similarity (exactly what
  `implicit`'s ItemItemRecommender computes);
- matrix factorization (implicit ALS): track factors. A user's factors are solved from the
  user's own interactions at request time ("fold-in", the same least-squares step ALS uses to
  update users), so new SONIQUEO users get collaborative recommendations without retraining.

The confidence of an interaction is BM25-weighted, as in training: frequent listening to a
track counts with diminishing returns, long histories are length-normalized and tracks almost
everyone plays count less.
"""

from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, TypeVar

import numpy as np
import numpy.typing as npt

from app.domains.recommendations.candidate_generation.base import (
    CandidateList,
    Source,
    take_unseen,
)

K = TypeVar("K", bound=Hashable)

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class FoldInParameters:
    """What serving needs, besides the track factors, to solve a user's factors."""

    regularization: float
    alpha: float
    # BM25 confidence weighting (see bm25_row); idf is per track, from training.
    bm25_k1: float
    bm25_b: float
    average_length: float

    def params(self) -> dict[str, Any]:
        return asdict(self)


def bm25_row(
    values: FloatArray, idf: FloatArray, average_length: float, k1: float, b: float
) -> FloatArray:
    """BM25 weights of one user's interaction values, as implicit.nearest_neighbours.bm25_weight
    computes them for a row of the user x item matrix."""
    length_norm = (1.0 - b) + b * float(values.sum()) / average_length
    return np.asarray(values * (k1 + 1.0) / (k1 * length_norm + values) * idf, dtype=np.float64)


def fold_in(
    item_factors: npt.NDArray[np.floating[Any]],
    confidence: FloatArray,
    gram: FloatArray,
    regularization: float,
) -> FloatArray:
    """User factors x = (Y'Y + reg I + Y'(C - I)Y)^-1 Y'C 1 over the user's items.

    `item_factors` (n, f) are the factors of the user's tracks, `confidence` (n,) their
    confidence (alpha x weight, as implicit applies alpha), `gram` = Y'Y over all tracks.
    Identical to implicit's AlternatingLeastSquares.recalculate_user.
    """
    factors = gram.shape[0]
    y = np.asarray(item_factors, dtype=np.float64)
    c = np.asarray(confidence, dtype=np.float64)
    a = np.asarray(gram, dtype=np.float64) + regularization * np.eye(factors)
    a += (y * (c - 1.0)[:, None]).T @ y
    b = y.T @ np.where(c > 0, c, 0.0)
    return np.asarray(np.linalg.solve(a, b), dtype=np.float64)


def item_neighbour_scores(
    history_weights: Mapping[K, float], neighbours: Iterable[tuple[K, K, float]]
) -> dict[K, float]:
    """score(j) = sum over history items i of weight(i) x similarity(i, j), for neighbour rows
    (i, j, similarity(i, j)) of the user's history items."""
    scores: dict[K, float] = {}
    for item, neighbour, similarity in neighbours:
        weight = history_weights.get(item)
        if weight is None:
            continue
        scores[neighbour] = scores.get(neighbour, 0.0) + weight * similarity
    return scores


def collaborative_candidates(
    source: Source,
    scored: Sequence[tuple[K, float]],
    *,
    exclude: frozenset[K] | set[K],
    limit: int,
    model_version: str | None,
) -> CandidateList[K]:
    """`scored`: (item, collaborative score), best first."""
    if source not in (Source.COLLABORATIVE_ITEM, Source.COLLABORATIVE_MF):
        raise ValueError(f"{source} is not a collaborative source")
    return CandidateList.build(source, take_unseen(scored, exclude, limit), model_version)
