import numpy as np
import pandas as pd
import pytest

from tastify_ml.evaluation.experiment import data_end
from tastify_ml.evaluation.split import build_task, temporal_split
from tests.recommendation_fixtures import T0, listens

ITEMS = pd.Series({"a": 0, "b": 1, "c": 2, "d": 3, "e": 4})


def history(user: str, tracks: str, day: float = 1.0) -> list[tuple[str, str, float]]:
    return [(user, t, day + i * 0.01) for i, t in enumerate(tracks)]


def test_temporal_split_never_leaks_across_the_cutoff() -> None:
    data = listens([("u", "a", 1), ("u", "b", 2), ("u", "c", 2.5), ("u", "d", 3)])
    cutoff = T0 + pd.Timedelta(days=2)

    split = temporal_split(data, cutoff, T0 + pd.Timedelta(days=3))

    assert split.train["track_id"].tolist() == ["a"]
    assert split.test["track_id"].tolist() == ["b", "c"]  # the end is exclusive
    assert (split.train["listened_at"] < cutoff).all()
    assert (split.test["listened_at"] >= cutoff).all()
    with pytest.raises(ValueError, match="before"):
        temporal_split(data, cutoff, cutoff)


def test_build_task_keeps_eligible_users_and_new_items_only() -> None:
    data = listens(
        [
            *history("eligible", "abcd"),
            ("eligible", "b", 1.5),  # b is played most -> the seed
            ("eligible", "a", 5),  # already heard: not relevant
            ("eligible", "e", 5),  # new: relevant
            *history("short", "ab"),  # too little history
            ("short", "e", 5),
            *history("idle", "abcd"),  # nothing new after the cutoff
            ("idle", "a", 5),
            ("unknown", "zzz", 5),  # track outside the catalogue
        ]
    )
    split = temporal_split(data, T0 + pd.Timedelta(days=4), T0 + pd.Timedelta(days=6))

    task = build_task(split, ITEMS, n_items=5, min_history=3)

    assert task.users.tolist() == ["eligible"]
    assert sorted(task.history[0].tolist()) == [0, 1, 2, 3]
    assert task.history[0][0] == 1  # most recent first
    assert task.relevant[0].tolist() == [4]
    assert task.seeds.tolist() == [1]


def test_seed_ties_prefer_the_most_recent_track() -> None:
    data = listens([*history("u", "abc"), ("u", "d", 5)])
    split = temporal_split(data, T0 + pd.Timedelta(days=4), T0 + pd.Timedelta(days=6))
    task = build_task(split, ITEMS, n_items=5, min_history=1)
    assert task.seeds.tolist() == [2]


def test_user_sampling_is_reproducible() -> None:
    rows = []
    for user in range(20):
        rows += [*history(f"u{user:02d}", "ab"), (f"u{user:02d}", "c", 5)]
    split = temporal_split(listens(rows), T0 + pd.Timedelta(days=4), T0 + pd.Timedelta(days=6))

    first = build_task(split, ITEMS, 5, min_history=2, max_users=5, seed=1)
    again = build_task(split, ITEMS, 5, min_history=2, max_users=5, seed=1)

    assert len(first) == 5
    assert first.users.tolist() == again.users.tolist()
    assert np.array_equal(first.seeds, again.seeds)


def test_data_end_is_the_last_complete_day() -> None:
    data = listens([("u", "a", 0.5), ("u", "a", 3.0001)])
    assert data_end(data) == T0 + pd.Timedelta(days=3)
