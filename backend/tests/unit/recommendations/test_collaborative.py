import numpy as np
import pytest

from app.domains.recommendations.candidate_generation.collaborative_candidates import (
    bm25_row,
    fold_in,
    item_neighbour_scores,
)


def test_fold_in_solves_the_als_normal_equations() -> None:
    rng = np.random.default_rng(0)
    all_items = rng.normal(size=(50, 4))
    gram = all_items.T @ all_items
    rows = [3, 7, 11]
    confidence = np.array([2.0, 5.0, 0.5])
    regularization = 0.1
    x = fold_in(all_items[rows], confidence, gram, regularization)
    # Dense reference: minimize sum_i c_i (p_i - x.y_i)^2 + reg |x|^2 over every item, with
    # c = 1 and p = 0 for items the user never touched.
    c = np.ones(50)
    p = np.zeros(50)
    c[rows], p[rows] = confidence, 1.0
    a = all_items.T @ (c[:, None] * all_items) + regularization * np.eye(4)
    b = all_items.T @ (c * p)
    assert x == pytest.approx(np.linalg.solve(a, b))


def test_bm25_row_saturates_and_length_normalizes() -> None:
    idf = np.array([1.0, 2.0])
    weights = bm25_row(np.array([1.0, 3.0]), idf, average_length=4.0, k1=100.0, b=0.8)
    # Row length 4 equals the average, so the length norm is 1.
    assert weights == pytest.approx([101 / 101 * 1.0, 3 * 101 / 103 * 2.0])
    longer = bm25_row(np.array([1.0, 3.0]), idf, average_length=2.0, k1=100.0, b=0.8)
    assert np.all(longer < weights)


def test_item_neighbour_scores_sum_weighted_similarities() -> None:
    scores = item_neighbour_scores(
        {"a": 2.0, "b": 1.0},
        [("a", "x", 0.5), ("b", "x", 0.25), ("b", "y", 1.0), ("zzz", "y", 9.0)],
    )
    assert scores == pytest.approx({"x": 1.25, "y": 1.0})
