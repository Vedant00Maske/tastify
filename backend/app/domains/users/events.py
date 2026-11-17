"""Interaction events and how they become preference signals (spec §8.5, ADR-016).

Events are immutable facts ("played", "skipped at 0:12", "liked"). This module turns a list of
events into one signal row per track, as of a reference time:

- positive: decayed sum of playback events (play, complete, replay, playlist_add), plus a bonus
  while the track is liked or saved;
- recent:   the same with a short half-life and a window, for the short-term profile;
- negative: decayed early skips, plus a penalty while the track is disliked.

Likes, dislikes and saves are states: the latest event wins (`like` then `unlike` leaves the track
neutral), so repeating a like does not count twice. A skip is only negative when it is early: users
skip for many reasons, and a late skip says little about taste (spec §8.5).

The same function serves the API (one user's events) and the offline evaluation (all research
users at once, with integer (user, item) keys), so both build identical profiles.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Generic, TypeVar

import numpy as np
import numpy.typing as npt

K = TypeVar("K")

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]


class EventType(StrEnum):
    PLAY = "play"  # a counted listen: at least 30 s or half the track (ListenBrainz semantics)
    COMPLETE = "complete"  # played to the end
    REPLAY = "replay"  # played again on purpose
    SKIP = "skip"  # skipped; position_ms says when
    LIKE = "like"
    UNLIKE = "unlike"
    DISLIKE = "dislike"
    UNDISLIKE = "undislike"
    SAVE = "save"
    UNSAVE = "unsave"
    PLAYLIST_ADD = "playlist_add"


EVENT_TYPES = tuple(e.value for e in EventType)
PLAYBACK_EVENTS = (EventType.PLAY, EventType.COMPLETE, EventType.REPLAY)

# State changes: event -> ((state, value), ...). Liking clears a dislike and vice versa.
STATE_CHANGES: dict[EventType, tuple[tuple[str, bool], ...]] = {
    EventType.LIKE: (("liked", True), ("disliked", False)),
    EventType.UNLIKE: (("liked", False),),
    EventType.DISLIKE: (("disliked", True), ("liked", False)),
    EventType.UNDISLIKE: (("disliked", False),),
    EventType.SAVE: (("saved", True),),
    EventType.UNSAVE: (("saved", False),),
}
STATES = ("liked", "disliked", "saved")


@dataclass(frozen=True)
class FeedbackWeights:
    """Initial interpretation of events (spec §8.5). Configurable; to be tuned with real users."""

    play: float = 1.0
    complete: float = 1.25
    replay: float = 1.5
    playlist_add: float = 3.0
    # Added to `positive` while the track is liked / saved.
    like: float = 3.0
    save: float = 3.0
    # Added to `negative` (magnitudes): per early skip, and while the track is disliked.
    early_skip: float = 0.5
    dislike: float = 4.0
    # A skip before this position is "very early" and counts as negative.
    early_skip_ms: int = 30_000

    def implicit_weight(self, event_type: str) -> float:
        return {
            EventType.PLAY: self.play,
            EventType.COMPLETE: self.complete,
            EventType.REPLAY: self.replay,
            EventType.PLAYLIST_ADD: self.playlist_add,
        }.get(EventType(event_type), 0.0)

    def params(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Decay:
    """Exponential time decay: an event `half_life_days` old counts half. Events older than
    `window_days` (when set) do not count at all."""

    half_life_days: float
    window_days: float | None = None

    def factor(self, age_days: FloatArray) -> FloatArray:
        age = np.maximum(age_days, 0.0)
        factor = np.power(0.5, age / self.half_life_days)
        if self.window_days is not None:
            factor = np.where(age <= self.window_days, factor, 0.0)
        return np.asarray(factor, dtype=np.float64)


@dataclass(frozen=True)
class TrackSignals(Generic[K]):
    """One row per distinct key (a track, or offline a (user, track) pair), sorted by key."""

    keys: npt.NDArray[Any]
    positive: FloatArray
    recent: FloatArray
    negative: FloatArray
    plays: IntArray
    early_skips: IntArray
    liked: BoolArray
    saved: BoolArray
    disliked: BoolArray
    # Age in days of the key's most recent event of any type.
    last_age_days: FloatArray

    def __len__(self) -> int:
        return len(self.keys)

    @property
    def preference(self) -> FloatArray:
        """Net long-term preference on a log scale: log(1 + positive) - log(1 + negative), >= 0.

        The log keeps one obsessively replayed track from dominating a profile."""
        return np.asarray(
            np.maximum(np.log1p(self.positive) - np.log1p(self.negative), 0.0), dtype=np.float64
        )

    @property
    def recent_preference(self) -> FloatArray:
        return np.asarray(np.log1p(self.recent) * ~self.disliked, dtype=np.float64)

    def take(self, index: npt.NDArray[np.int64] | slice) -> "TrackSignals[K]":
        return TrackSignals(
            keys=self.keys[index],
            positive=self.positive[index],
            recent=self.recent[index],
            negative=self.negative[index],
            plays=self.plays[index],
            early_skips=self.early_skips[index],
            liked=self.liked[index],
            saved=self.saved[index],
            disliked=self.disliked[index],
            last_age_days=self.last_age_days[index],
        )


def _latest_state(
    inverse: IntArray, order_age: FloatArray, n_keys: int, mask: BoolArray, values: BoolArray
) -> tuple[BoolArray, FloatArray]:
    """Per key: the value of the most recent event in `mask` (False if none) and its age."""
    state = np.zeros(n_keys, dtype=np.bool_)
    age = np.full(n_keys, np.inf)
    rows = np.flatnonzero(mask)
    if len(rows) == 0:
        return state, age
    # Oldest first within each key; for equal ages the later event (higher row) wins.
    order = rows[np.lexsort((rows, -order_age[rows], inverse[rows]))]
    last = np.ones(len(order), dtype=np.bool_)
    last[:-1] = inverse[order][1:] != inverse[order][:-1]
    chosen = order[last]
    state[inverse[chosen]] = values[chosen]
    age[inverse[chosen]] = order_age[chosen]
    return state, age


def aggregate_events(
    keys: Sequence[K] | npt.NDArray[Any],
    event_types: Sequence[str] | npt.NDArray[Any],
    age_days: Sequence[float] | FloatArray,
    positions_ms: Sequence[float | None] | FloatArray | None,
    *,
    weights: FeedbackWeights,
    long_decay: Decay,
    short_decay: Decay,
) -> TrackSignals[K]:
    """Aggregate events (parallel arrays) into per-key signals. `age_days` is how long before the
    reference time each event happened; `positions_ms` is where playback was (skips), or None."""
    key_array = np.asarray(keys)
    types = np.asarray(event_types).astype(str)
    ages = np.asarray(age_days, dtype=np.float64)
    n_events = len(key_array)
    if not (len(types) == len(ages) == n_events):
        raise ValueError("keys, event_types and age_days must have the same length")
    unknown = set(np.unique(types)) - set(EVENT_TYPES)
    if unknown:
        raise ValueError(f"unknown event types: {sorted(unknown)}")
    positions = (
        np.full(n_events, np.nan)
        if positions_ms is None
        else np.array([np.nan if p is None else p for p in positions_ms], dtype=np.float64)
    )

    if n_events == 0:
        empty_f = np.zeros(0)
        empty_i = np.zeros(0, dtype=np.int64)
        empty_b = np.zeros(0, dtype=np.bool_)
        return TrackSignals(
            key_array,
            empty_f,
            empty_f,
            empty_f,
            empty_i,
            empty_i,
            empty_b,
            empty_b,
            empty_b,
            empty_f,
        )

    unique_keys, inverse = np.unique(key_array, return_inverse=True)
    inverse = inverse.astype(np.int64).reshape(-1)
    n_keys = len(unique_keys)
    long_factor = long_decay.factor(ages)
    short_factor = short_decay.factor(ages)

    implicit = np.zeros(n_events)
    for event_type in (*PLAYBACK_EVENTS, EventType.PLAYLIST_ADD):
        implicit[types == event_type.value] = weights.implicit_weight(event_type)
    early_skip = (types == EventType.SKIP.value) & (positions < weights.early_skip_ms)
    playback = np.isin(types, [e.value for e in PLAYBACK_EVENTS])

    positive: FloatArray = np.bincount(inverse, implicit * long_factor, n_keys).astype(np.float64)
    recent: FloatArray = np.bincount(inverse, implicit * short_factor, n_keys).astype(np.float64)
    negative: FloatArray = np.bincount(
        inverse, early_skip * weights.early_skip * long_factor, n_keys
    ).astype(np.float64)

    states: dict[str, tuple[BoolArray, FloatArray]] = {}
    for state in STATES:
        mask = np.zeros(n_events, dtype=np.bool_)
        values = np.zeros(n_events, dtype=np.bool_)
        for event_type, changes in STATE_CHANGES.items():
            for name, value in changes:
                if name == state:
                    hit = types == event_type.value
                    mask |= hit
                    values[hit] = value
        states[state] = _latest_state(inverse, ages, n_keys, mask, values)

    liked, liked_age = states["liked"]
    saved, saved_age = states["saved"]
    disliked, disliked_age = states["disliked"]
    for active, age, bonus in ((liked, liked_age, weights.like), (saved, saved_age, weights.save)):
        finite_age = np.where(active, age, 0.0)
        positive = positive + np.where(active, bonus * long_decay.factor(finite_age), 0.0)
        recent = recent + np.where(active, bonus * short_decay.factor(finite_age), 0.0)
    disliked_factor = long_decay.factor(np.where(disliked, disliked_age, 0.0))
    negative = negative + np.where(disliked, weights.dislike * disliked_factor, 0.0)

    last_age = np.full(n_keys, np.inf)
    np.minimum.at(last_age, inverse, ages)
    return TrackSignals(
        keys=unique_keys,
        positive=positive,
        recent=recent,
        negative=negative,
        plays=np.bincount(inverse, playback, n_keys).astype(np.int64),
        early_skips=np.bincount(inverse, early_skip, n_keys).astype(np.int64),
        liked=liked,
        saved=saved,
        disliked=disliked,
        last_age_days=last_age,
    )
