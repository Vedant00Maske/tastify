"""Popularity baselines: overall listeners, and trending where the data supports it.

Only interactions before `as_of` are used, so evaluation can compute popularity from the training
period alone (no leakage from the period being predicted).
"""

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

DAY = pd.Timedelta(days=1)


@dataclass(frozen=True)
class PopularityConfig:
    # The trend compares the last `recent_days` with the days before them.
    recent_days: int = 3
    # A trend needs at least this many recent distinct listeners and this much earlier history;
    # below that, the ratio is noise and trending_score is left empty.
    min_recent_listeners: int = 20
    min_history_days: int = 7
    # Pseudo-count added to both daily rates (listeners per day) before taking their ratio.
    smoothing: float = 1.0

    def params(self) -> dict[str, Any]:
        return asdict(self)


def compute_popularity(
    interactions: pd.DataFrame,
    track_ids: np.ndarray,
    as_of: pd.Timestamp,
    config: PopularityConfig = PopularityConfig(),
) -> pd.DataFrame:
    """One row per entry of `track_ids` (in that order), from interactions before `as_of`.

    Columns: listeners, plays, score, recent_listeners, growth, trending_score.
    - score is log(1 + listeners) / log(1 + max listeners), in [0, 1];
    - growth is the ratio of average daily listeners (distinct user-days per day) in the recent
      window to the earlier window, smoothed; trending_score is log(growth), or NaN if unreliable.
    """
    data = interactions[interactions["listened_at"] < as_of]
    start = data["listened_at"].min() if len(data) else as_of
    recent_start = as_of - config.recent_days * DAY
    earlier_days = max((recent_start - start) / DAY, 0.0)

    grouped = data.groupby("track_id", observed=True)
    listeners = grouped["user_key"].nunique()
    plays = grouped.size()
    recent = data[data["listened_at"] >= recent_start]
    recent_listeners = recent.groupby("track_id", observed=True)["user_key"].nunique()

    user_days = data.assign(day=data["listened_at"].dt.floor("D"))[["track_id", "user_key", "day"]]
    user_days = user_days.drop_duplicates()
    is_recent = user_days["day"] >= recent_start
    recent_rate = (
        user_days[is_recent].groupby("track_id", observed=True).size() / config.recent_days
    )
    earlier_rate = user_days[~is_recent].groupby("track_id", observed=True).size() / max(
        earlier_days, 1.0
    )

    frame = pd.DataFrame(index=pd.Index(track_ids, name="track_id"))
    frame["listeners"] = listeners.reindex(frame.index, fill_value=0).astype(np.int64)
    frame["plays"] = plays.reindex(frame.index, fill_value=0).astype(np.int64)
    top = frame["listeners"].max()
    frame["score"] = np.log1p(frame["listeners"]) / np.log1p(top) if top > 0 else 0.0
    frame["recent_listeners"] = recent_listeners.reindex(frame.index, fill_value=0).astype(np.int64)
    smoothed_recent = recent_rate.reindex(frame.index, fill_value=0.0) + config.smoothing
    smoothed_earlier = earlier_rate.reindex(frame.index, fill_value=0.0) + config.smoothing
    frame["growth"] = smoothed_recent / smoothed_earlier
    reliable = (frame["recent_listeners"] >= config.min_recent_listeners) & (
        earlier_days >= config.min_history_days
    )
    frame["trending_score"] = np.where(reliable, np.log(frame["growth"]), np.nan)
    return frame.reset_index()
