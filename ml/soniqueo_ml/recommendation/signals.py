"""Per-user interaction signals for one training period (offline).

Research listens are aggregated with the backend's own `aggregate_events`, using integer keys
user * n_items + item, so every research user's signals are exactly what the API would compute
from the same events. ListenBrainz listens are all `play` events (a listen is submitted after at
least half the track or four minutes), so skips, likes and saves do not occur in this data.
"""

from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt
import pandas as pd
import scipy.sparse as sp

from app.domains.users.events import EventType, TrackSignals, aggregate_events
from app.domains.users.profile import TasteProfileConfig

DAY = pd.Timedelta(days=1)
IntArray = npt.NDArray[np.int64]


@dataclass
class UserSignals:
    """Signals of every user active before `as_of`, grouped by user (users sorted by key)."""

    users: npt.NDArray[np.object_]
    n_items: int
    as_of: pd.Timestamp
    # keys = user position * n_items + item, sorted, so each user's rows are contiguous.
    signals: TrackSignals[np.int64]
    offsets: IntArray

    def __post_init__(self) -> None:
        self.position = {user: i for i, user in enumerate(self.users)}

    def __len__(self) -> int:
        return len(self.users)

    def user_signals(self, position: int) -> TrackSignals[np.int64]:
        """One user's signals with item indices as keys."""
        start, stop = int(self.offsets[position]), int(self.offsets[position + 1])
        rows = self.signals.take(slice(start, stop))
        return replace(rows, keys=rows.keys - position * self.n_items)

    def matrix(self, values: str = "positive") -> sp.csr_matrix:
        """(users, items) sparse matrix of a signal column ("positive", "preference", ...)."""
        data = np.asarray(getattr(self.signals, values), dtype=np.float32)
        users = self.signals.keys // self.n_items
        items = self.signals.keys % self.n_items
        keep = data > 0
        return sp.csr_matrix(
            (data[keep], (users[keep], items[keep])), shape=(len(self.users), self.n_items)
        )


def compute_signals(
    interactions: pd.DataFrame, item_of: pd.Series, as_of: pd.Timestamp, config: TasteProfileConfig
) -> UserSignals:
    """Signals from listens strictly before `as_of`; listens of tracks outside `item_of` are
    ignored."""
    train = interactions[interactions["listened_at"] < as_of]
    items = train["track_id"].map(item_of)
    known = items.notna().to_numpy()
    user_keys = train["user_key"].to_numpy(dtype=object)[known]
    users = np.array(sorted(set(user_keys)), dtype=object)
    position = pd.Series(np.arange(len(users)), index=pd.Index(users))
    n_items = len(item_of)
    keys = position.loc[user_keys].to_numpy(dtype=np.int64) * n_items + items.to_numpy()[
        known
    ].astype(np.int64)
    ages = (as_of - train["listened_at"][known]).to_numpy() / np.timedelta64(1, "D")
    signals: TrackSignals[np.int64] = aggregate_events(
        keys,
        np.full(len(keys), EventType.PLAY.value),
        ages.astype(np.float64),
        None,
        weights=config.feedback,
        long_decay=config.long_decay,
        short_decay=config.short_decay,
    )
    offsets = np.searchsorted(signals.keys // n_items, np.arange(len(users) + 1)).astype(np.int64)
    return UserSignals(users, n_items, as_of, signals, offsets)
