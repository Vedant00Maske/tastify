import math

import numpy as np
import pandas as pd
import pytest

from tastify_ml.recommendation.popularity import PopularityConfig, compute_popularity
from tests.recommendation_fixtures import T0, listens

TRACKS = np.array(["a", "b", "c"], dtype=object)


def test_counts_and_log_normalized_score() -> None:
    data = listens([("u1", "a", 1), ("u1", "a", 2), ("u2", "a", 2), ("u1", "b", 3)])

    frame = compute_popularity(data, TRACKS, T0 + pd.Timedelta(days=4))

    assert frame["track_id"].tolist() == ["a", "b", "c"]
    assert frame["listeners"].tolist() == [2, 1, 0]
    assert frame["plays"].tolist() == [3, 1, 0]
    assert frame["score"].tolist() == pytest.approx([1.0, math.log(2) / math.log(3), 0.0])


def test_interactions_at_or_after_as_of_are_ignored() -> None:
    data = listens([("u1", "a", 1), ("u2", "b", 5), ("u3", "b", 6)])
    frame = compute_popularity(data, TRACKS, T0 + pd.Timedelta(days=5))
    assert frame["listeners"].tolist() == [1, 0, 0]


def test_trending_only_where_reliable() -> None:
    config = PopularityConfig(
        recent_days=2, min_recent_listeners=3, min_history_days=4, smoothing=1
    )
    rows: list[tuple[str, str, float]] = [("early", "a", 1.0)]
    # Track "a": 3 recent listeners in days 7-9 vs 1 earlier user-day over the 6 days since the
    # first listen (day 1 to day 7).
    rows += [(f"r{i}", "a", 8.5) for i in range(3)]
    # Track "b": only 2 recent listeners: below the reliability threshold.
    rows += [(f"s{i}", "b", 8.5) for i in range(2)]
    frame = compute_popularity(listens(rows), TRACKS, T0 + pd.Timedelta(days=9), config)

    growth = (3 / 2 + 1) / (1 / 6 + 1)
    assert frame.loc[0, "growth"] == pytest.approx(growth)
    assert frame.loc[0, "trending_score"] == pytest.approx(math.log(growth))
    assert frame.loc[0, "recent_listeners"] == 3
    assert math.isnan(float(frame["trending_score"].iloc[1]))

    short = compute_popularity(
        listens(rows),
        TRACKS,
        T0 + pd.Timedelta(days=9),
        PopularityConfig(recent_days=2, min_recent_listeners=3, min_history_days=30),
    )
    assert short["trending_score"].isna().all()


def test_empty_history_gives_zero_popularity() -> None:
    frame = compute_popularity(listens([]), TRACKS, T0)
    assert frame["score"].tolist() == [0.0, 0.0, 0.0]
    assert frame["trending_score"].isna().all()
