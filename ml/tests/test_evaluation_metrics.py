import math

import numpy as np
import pytest

from tastify_ml.evaluation import metrics


def test_accuracy_metrics_match_hand_computed_values() -> None:
    recommendations = np.array([[1, 2, 3, 4], [5, 6, 7, 8], [9, -1, -1, -1]])
    relevant = [np.array([2, 4, 10]), np.array([99]), np.array([9])]

    result = metrics.accuracy_metrics(recommendations, relevant, k=4)

    # User 0: hits at ranks 2 and 4 out of 3 relevant items.
    assert result["precision"][0] == pytest.approx(2 / 4)
    assert result["recall"][0] == pytest.approx(2 / 3)
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert result["ndcg"][0] == pytest.approx(dcg / idcg)
    assert result["map"][0] == pytest.approx((1 / 2 + 2 / 4) / 3)
    assert result["hit_rate"][0] == 1.0
    # User 1: no hits. User 2: a hit at rank 1 of a padded list.
    assert result["ndcg"][1] == 0.0
    assert result["hit_rate"][1] == 0.0
    assert result["ndcg"][2] == pytest.approx(1.0)
    assert result["precision"][2] == pytest.approx(1 / 4)


def test_accuracy_metrics_truncate_at_k_and_ignore_padding() -> None:
    result = metrics.accuracy_metrics(np.array([[-1, 3, 1]]), [np.array([1, -1])], k=2)
    assert result["hit_rate"][0] == 0.0


def test_accuracy_metrics_reject_users_without_relevant_items() -> None:
    with pytest.raises(ValueError, match="relevant"):
        metrics.accuracy_metrics(np.array([[1]]), [np.array([], dtype=np.int64)], k=1)


def test_coverage_counts_distinct_recommended_items() -> None:
    assert metrics.coverage(np.array([[0, 1], [1, 2], [-1, -1]]), 2, n_items=10) == 0.3


def test_intra_list_diversity_uses_pairwise_cosine() -> None:
    embeddings = np.array([[1, 0], [1, 0], [0, 1]], dtype=np.float32)
    diversity = metrics.intra_list_diversity(np.array([[0, 1], [0, 2], [0, -1]]), 2, embeddings)
    assert diversity.tolist() == pytest.approx([0.0, 1.0, 0.0])


def test_artist_diversity_and_novelty() -> None:
    artists = np.array([0, 0, 1])
    assert metrics.artist_diversity(np.array([[0, 1], [0, 2]]), 2, artists).tolist() == [0.5, 1.0]
    information = metrics.self_information(np.array([3, 0]), n_users=3)
    assert information.tolist() == pytest.approx([0.0, 2.0])
    assert metrics.novelty(np.array([[0, 1], [1, -1]]), 2, information).tolist() == [1.0, 2.0]


def test_mean_with_ci() -> None:
    mean, half_width = metrics.mean_with_ci(np.array([0.0, 1.0, 0.0, 1.0]))
    assert mean == 0.5
    assert half_width == pytest.approx(1.96 * np.std([0, 1, 0, 1], ddof=1) / 2)
    assert metrics.mean_with_ci(np.array([0.3])) == (0.3, 0.0)
