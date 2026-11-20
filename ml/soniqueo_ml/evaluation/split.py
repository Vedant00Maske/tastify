"""Time-aware train/test splits and the per-user evaluation task built from them.

Everything a model may learn from (histories, popularity) comes from interactions strictly before
the cutoff; relevance comes only from the window after it. `temporal_split` asserts this.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class TemporalSplit:
    train: pd.DataFrame
    test: pd.DataFrame
    cutoff: pd.Timestamp
    end: pd.Timestamp

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(self.train["listened_at"].min())


def temporal_split(
    interactions: pd.DataFrame, cutoff: pd.Timestamp, end: pd.Timestamp
) -> TemporalSplit:
    """train = [first listen, cutoff), test = [cutoff, end)."""
    if not cutoff < end:
        raise ValueError(f"cutoff {cutoff} must be before end {end}")
    times = interactions["listened_at"]
    train = interactions[times < cutoff]
    test = interactions[(times >= cutoff) & (times < end)]
    # Guard against future leakage explicitly (asserts can be disabled with -O).
    if (not train.empty and train["listened_at"].max() >= cutoff) or (
        not test.empty and test["listened_at"].min() < cutoff
    ):
        raise RuntimeError("temporal split leaked interactions across the cutoff")
    return TemporalSplit(train=train, test=test, cutoff=cutoff, end=end)


@dataclass
class EvaluationTask:
    """Users to evaluate, with what is known about them at the cutoff and what they did next."""

    users: npt.NDArray[np.object_]
    # Distinct training items per user and their play counts (most recent first).
    history: list[IntArray]
    history_plays: list[IntArray]
    # Items heard after the cutoff that were not in the user's history: the targets.
    relevant: list[IntArray]
    # The user's most played training item (ties: most recent): the "favourite track".
    seeds: IntArray
    n_items: int

    def __len__(self) -> int:
        return len(self.users)


def _with_items(frame: pd.DataFrame, item_of: pd.Series) -> pd.DataFrame:
    items = frame["track_id"].map(item_of)
    known = items.notna().to_numpy()
    return pd.DataFrame(
        {
            "user_key": frame["user_key"].to_numpy()[known],
            "item": items.to_numpy()[known].astype(np.int64),
            "listened_at": frame["listened_at"].to_numpy()[known],
        }
    )


def build_task(
    split: TemporalSplit,
    item_of: pd.Series,
    n_items: int,
    *,
    min_history: int = 5,
    max_users: int | None = None,
    seed: int = 42,
    max_history: int | None = None,
) -> EvaluationTask:
    """Users with at least `min_history` distinct training items and at least one new test item.

    `max_history` (optional) keeps only users with at most that many items (low-history segment).

    `item_of` maps track_id to item index; interactions on other tracks are ignored.
    `max_users` draws a reproducible random sample of eligible users.
    """
    train = _with_items(split.train, item_of)
    test = _with_items(split.test, item_of)

    stats = (
        train.groupby(["user_key", "item"], observed=True)["listened_at"]
        .agg(["size", "max"])
        .rename(columns={"size": "plays", "max": "last"})
        .reset_index()
    )
    history_size = stats.groupby("user_key", observed=True).size()

    test_pairs = test[["user_key", "item"]].drop_duplicates()
    known_pairs = test_pairs.merge(
        stats[["user_key", "item"]], on=["user_key", "item"], how="left", indicator=True
    )
    new_pairs = known_pairs[known_pairs["_merge"] == "left_only"][["user_key", "item"]]
    relevant_size = new_pairs.groupby("user_key", observed=True).size()

    sized = history_size[history_size >= min_history]
    if max_history is not None:
        sized = sized[sized <= max_history]
    eligible = sized.index.intersection(relevant_size.index)
    users = np.sort(eligible.to_numpy(dtype=object))
    if max_users is not None and len(users) > max_users:
        users = np.sort(np.random.default_rng(seed).choice(users, max_users, replace=False))
    chosen = pd.Index(users)

    stats = stats[stats["user_key"].isin(chosen)].sort_values(
        ["user_key", "last", "item"], ascending=[True, False, True]
    )
    new_pairs = new_pairs[new_pairs["user_key"].isin(chosen)].sort_values(["user_key", "item"])

    history: list[IntArray] = []
    history_plays: list[IntArray] = []
    seeds = np.empty(len(users), dtype=np.int64)
    for position, (_, group) in enumerate(stats.groupby("user_key", observed=True, sort=True)):
        items = group["item"].to_numpy(dtype=np.int64)
        plays = group["plays"].to_numpy(dtype=np.int64)
        history.append(items)
        history_plays.append(plays)
        # Rows are most recent first, so argmax picks the most recent among the most played.
        seeds[position] = items[int(np.argmax(plays))]
    relevant = [
        group["item"].to_numpy(dtype=np.int64)
        for _, group in new_pairs.groupby("user_key", observed=True, sort=True)
    ]
    return EvaluationTask(
        users=users,
        history=history,
        history_plays=history_plays,
        relevant=relevant,
        seeds=seeds,
        n_items=n_items,
    )
