import numpy as np
import pytest

from soniqueo_ml.evaluation import segments
from soniqueo_ml.evaluation.split import EvaluationTask


def task() -> EvaluationTask:
    return EvaluationTask(
        users=np.array(["a", "b", "c"], dtype=object),
        history=[np.arange(3), np.arange(12), np.arange(150)],
        history_plays=[np.ones(3, dtype=np.int64)] * 3,
        relevant=[np.array([5]), np.array([6, 7]), np.array([199])],
        seeds=np.zeros(3, dtype=np.int64),
        n_items=200,
    )


LISTS = np.array([[5, 1, -1], [7, 8, 9], [10, 11, 12]])


def test_history_buckets_cover_every_user() -> None:
    assert segments.history_buckets(task()).tolist() == ["1-4", "10-24", "100+"]


def test_segment_metrics_average_within_each_segment() -> None:
    labels = np.array(["x", "x", "y"], dtype=object)
    result = segments.segment_metrics(LISTS, task(), labels, k=3)
    assert result["x"]["users"] == 2
    assert result["x"]["hit_rate@3"] == 1.0
    assert result["y"]["recall@3"] == 0.0


def test_popularity_strata_and_stratified_recall() -> None:
    listeners = np.arange(200, 0, -1)
    strata = segments.popularity_strata(listeners)
    assert strata[0] == "head"
    assert strata[5] == "mid"
    assert strata[199] == "tail"
    result = segments.stratified_recall(LISTS, task(), strata, k=3)
    assert result["mid"]["recall@3"] == pytest.approx(2 / 3)  # items 5, 6, 7: 5 and 7 found
    assert result["tail"]["relevant"] == 1
    assert sum(r["share_of_recommendations"] for r in result.values()) == pytest.approx(1.0)


def test_discovery_metrics_count_new_artists() -> None:
    artist_codes = np.arange(200) // 10  # ten tracks per artist
    known = segments.known_artists(task(), artist_codes)
    assert known[0] == {0}
    result = segments.discovery_metrics(LISTS, task(), artist_codes, known, k=3)
    # User a: item 5 (artist 0, known) and 1 (known) -> 0 new; b: 7, 8, 9 known (artist 0) -> 0;
    # c: 10, 11, 12 (artist 1, known) -> 0.
    assert result["discovery_share@3"] == 0.0
    # Relevant new-artist tracks: user c's 199 (artist 19); not recommended.
    assert result["new_artist_relevant"] == pytest.approx(1 / 4)
    assert result["discovery_recall@3"] == 0.0


def test_paired_difference_compares_the_same_users() -> None:
    better = np.array([[5, -1, -1], [6, 7, -1], [199, -1, -1]])
    worse = np.full((3, 3), -1)
    result = segments.paired_difference(better, worse, task(), k=3)
    assert result["difference"] > 0
    assert result["a_wins"] == 1.0
    assert result["b_wins"] == 0.0
