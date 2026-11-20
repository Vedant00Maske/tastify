"""Collaborative models: the serving math must reproduce `implicit` exactly."""

import numpy as np
import pytest
import scipy.sparse as sp
from implicit.als import AlternatingLeastSquares
from implicit.nearest_neighbours import BM25Recommender, bm25_weight

from app.domains.recommendations.candidate_generation.collaborative_candidates import bm25_row
from soniqueo_ml.recommendation.collaborative import (
    ALSConfig,
    ItemItemConfig,
    bm25_idf,
    train_als,
    train_item_item,
    train_user_knn,
)


@pytest.fixture
def matrix() -> sp.csr_matrix:
    rng = np.random.default_rng(7)
    dense = rng.poisson(0.4, size=(60, 40)).astype(np.float64)
    dense[:, :10] += rng.poisson(1.5, size=(60, 10)) * (np.arange(60)[:, None] < 30)
    return sp.csr_matrix(dense)


def test_bm25_row_and_idf_match_implicit(matrix: sp.csr_matrix) -> None:
    weighted = bm25_weight(matrix, K1=100.0, B=0.8).tocsr()
    idf, average_length = bm25_idf(matrix)
    for user in (0, 13, 41):
        row = matrix[user]
        ours = bm25_row(row.data, idf[row.indices], average_length, 100.0, 0.8)
        assert ours == pytest.approx(weighted[user].data, rel=1e-6)


def test_fold_in_reproduces_implicit_recalculate_user(matrix: sp.csr_matrix) -> None:
    config = ALSConfig(factors=8, regularization=0.5, alpha=2.0, iterations=5)
    model = train_als(matrix, config)
    reference = AlternatingLeastSquares(
        factors=8, regularization=0.5, alpha=2.0, iterations=5, random_state=42
    )
    reference.item_factors = model.item_factors
    weighted = bm25_weight(matrix, K1=config.bm25_k1, B=config.bm25_b).tocsr().astype(np.float32)
    for user in (2, 30, 55):
        row = matrix[user]
        ours = model.user_vector(row.indices.astype(np.int64), row.data)
        expected = reference.recalculate_user(user, weighted[user])
        assert ours == pytest.approx(expected, rel=1e-3, abs=1e-4)


def test_als_training_is_reproducible(matrix: sp.csr_matrix) -> None:
    config = ALSConfig(factors=8, iterations=5)
    first, second = train_als(matrix, config), train_als(matrix, config)
    np.testing.assert_array_equal(first.item_factors, second.item_factors)
    assert first.gram == pytest.approx(
        first.item_factors.astype(np.float64).T @ first.item_factors.astype(np.float64)
    )


def test_item_item_scores_match_implicit_recommend(matrix: sp.csr_matrix) -> None:
    model = train_item_item(matrix, ItemItemConfig(neighbours=10, weighting="bm25"))
    assert model.similarity.diagonal().sum() == 0  # self-similarity removed
    reference = BM25Recommender(K=11)
    reference.fit(matrix.astype(np.float32), show_progress=False)
    users = np.array([1, 20, 44])
    ids, scores = reference.recommend(
        users, matrix[users].astype(np.float32), N=5, filter_already_liked_items=True
    )
    ours = model.scores(matrix[users]).toarray()
    for row, user in enumerate(users):
        values = ours[row].copy()
        values[matrix[user].indices] = -np.inf
        top = np.argsort(-values, kind="stable")[:5]
        assert values[top] == pytest.approx(scores[row], rel=1e-5)
        assert set(top.tolist()) == set(ids[row].tolist())


def test_user_knn_ignores_the_user_itself(matrix: sp.csr_matrix) -> None:
    model = train_user_knn(matrix, neighbours=5)
    scores = model.scores(np.array([0, 1]))
    assert scores.shape == (2, matrix.shape[1])
    lonely = sp.csr_matrix(([1.0], ([0], [0])), shape=(3, 4))
    assert train_user_knn(lonely, neighbours=1).scores(np.array([0])).sum() == 0.0
    with pytest.raises(ValueError, match="unknown item-item weighting"):
        train_item_item(matrix, ItemItemConfig(weighting="jaccard"))
