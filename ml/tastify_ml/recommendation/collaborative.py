"""Collaborative filtering on implicit feedback (ADR-016).

Input: the (users, items) matrix of `positive` signals (event-weighted, time-decayed listening),
not binary values. Models:

- ALS (implicit-feedback matrix factorization, Hu, Koren and Volinsky 2008) via `implicit`, on
  BM25-weighted confidences. Served: track factors, and user factors folded in at request time;
- item-item: `implicit`'s BM25 item-item k-nearest-neighbours. Served: each track's neighbours;
- user-user k-nearest-neighbours and BPR: benchmarks only. User-user needs every research
  user's history at serving time, which must never enter the application database.

Training is reproducible: fixed random state, and BLAS limited to one thread while `implicit`
parallelizes over users and items (its per-row solves do not depend on thread scheduling).
"""

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp
from implicit.als import AlternatingLeastSquares
from implicit.bpr import BayesianPersonalizedRanking
from implicit.nearest_neighbours import BM25Recommender, CosineRecommender, bm25_weight
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from app.domains.recommendations.candidate_generation.collaborative_candidates import (
    FoldInParameters,
    bm25_row,
    fold_in,
)

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class ALSConfig:
    factors: int = 128
    regularization: float = 0.1
    alpha: float = 5.0
    iterations: int = 15
    bm25_k1: float = 100.0
    bm25_b: float = 0.8
    random_state: int = 42

    def params(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ItemItemConfig:
    neighbours: int = 100
    weighting: str = "bm25"  # or "cosine"
    # implicit's BM25Recommender defaults: term frequency saturates quickly (K1), so a few heavy
    # listeners cannot dominate a pair's similarity.
    bm25_k1: float = 1.2
    bm25_b: float = 0.75

    def params(self) -> dict[str, Any]:
        return asdict(self)


def bm25_idf(matrix: sp.csr_matrix) -> tuple[FloatArray, float]:
    """Per-item idf and the average row length, exactly as implicit's bm25_weight computes them
    for a (users, items) matrix."""
    n_users = float(matrix.shape[0])
    document_frequency = np.bincount(matrix.indices, minlength=matrix.shape[1])
    idf = np.log(n_users) - np.log1p(document_frequency)
    average_length = float(np.asarray(matrix.sum(axis=1)).ravel().mean())
    return np.asarray(idf, dtype=np.float64), average_length


@dataclass
class ALSModel:
    config: ALSConfig
    item_factors: npt.NDArray[np.float32]
    idf: FloatArray
    average_length: float

    def __post_init__(self) -> None:
        y = self.item_factors.astype(np.float64)
        self.gram = y.T @ y

    @property
    def fold_in_parameters(self) -> FoldInParameters:
        return FoldInParameters(
            regularization=self.config.regularization,
            alpha=self.config.alpha,
            bm25_k1=self.config.bm25_k1,
            bm25_b=self.config.bm25_b,
            average_length=self.average_length,
        )

    def user_vector(self, items: IntArray, values: FloatArray) -> FloatArray:
        """Fold-in, the computation the API runs for a user (shared backend code)."""
        if len(items) == 0:
            return np.zeros(self.item_factors.shape[1])
        weights = bm25_row(
            np.asarray(values, dtype=np.float64),
            self.idf[items],
            self.average_length,
            self.config.bm25_k1,
            self.config.bm25_b,
        )
        return fold_in(
            self.item_factors[items],
            self.config.alpha * weights,
            self.gram,
            self.config.regularization,
        )


def train_als(matrix: sp.csr_matrix, config: ALSConfig) -> ALSModel:
    weighted = bm25_weight(matrix, K1=config.bm25_k1, B=config.bm25_b).tocsr()
    model = AlternatingLeastSquares(
        factors=config.factors,
        regularization=config.regularization,
        alpha=config.alpha,
        iterations=config.iterations,
        random_state=config.random_state,
    )
    with threadpool_limits(1, "blas"):
        model.fit(weighted.astype(np.float32), show_progress=False)
    idf, average_length = bm25_idf(matrix)
    return ALSModel(config, np.asarray(model.item_factors, dtype=np.float32), idf, average_length)


@dataclass
class ItemItemModel:
    config: ItemItemConfig
    # (items, items): row i holds the neighbours of item i and their similarity (self removed).
    similarity: sp.csr_matrix

    def scores(self, user_rows: sp.csr_matrix) -> sp.csr_matrix:
        """score(u, j) = sum_i value(u, i) * similarity(i, j), as implicit's recommend."""
        return sp.csr_matrix(user_rows @ self.similarity)


def train_item_item(matrix: sp.csr_matrix, config: ItemItemConfig) -> ItemItemModel:
    model: CosineRecommender | BM25Recommender
    if config.weighting == "bm25":
        model = BM25Recommender(K=config.neighbours + 1, K1=config.bm25_k1, B=config.bm25_b)
    elif config.weighting == "cosine":
        model = CosineRecommender(K=config.neighbours + 1)
    else:
        raise ValueError(f"unknown item-item weighting {config.weighting}")
    model.fit(matrix.astype(np.float32), show_progress=False)
    similarity = sp.csr_matrix(model.similarity, dtype=np.float64)
    similarity.setdiag(0.0)
    similarity.eliminate_zeros()
    return ItemItemModel(config, similarity)


@dataclass
class BPRModel:
    """Bayesian Personalized Ranking (benchmark only)."""

    user_factors: npt.NDArray[np.float32]
    item_factors: npt.NDArray[np.float32]


def train_bpr(
    matrix: sp.csr_matrix, factors: int = 128, iterations: int = 100, random_state: int = 42
) -> BPRModel:
    model = BayesianPersonalizedRanking(
        factors=factors, iterations=iterations, random_state=random_state
    )
    with threadpool_limits(1, "blas"):
        model.fit((matrix > 0).astype(np.float32), show_progress=False)
    return BPRModel(
        np.asarray(model.user_factors, dtype=np.float32),
        np.asarray(model.item_factors, dtype=np.float32),
    )


@dataclass
class UserKNNModel:
    """User-user cosine k-nearest-neighbours on BM25-weighted rows (benchmark only)."""

    rows: sp.csr_matrix  # L2-normalized BM25 rows of every training user
    values: sp.csr_matrix  # the raw matrix, to sum the neighbours' listening
    neighbours: int = 50

    def scores(self, positions: IntArray) -> FloatArray:
        query = self.rows[positions]
        similarity = np.asarray((query @ self.rows.T).todense())
        similarity[np.arange(len(positions)), positions] = 0.0
        k = min(self.neighbours, similarity.shape[1] - 1)
        top = np.argpartition(-similarity, k, axis=1)[:, :k]
        weights = np.zeros_like(similarity)
        rows = np.arange(len(positions))[:, None]
        weights[rows, top] = similarity[rows, top]
        return np.asarray((sp.csr_matrix(weights) @ self.values.astype(np.float64)).toarray())


def train_user_knn(matrix: sp.csr_matrix, neighbours: int = 50) -> UserKNNModel:
    weighted = bm25_weight(matrix, K1=100.0, B=0.8).tocsr()
    return UserKNNModel(sp.csr_matrix(normalize(weighted)), matrix.tocsr(), neighbours)
