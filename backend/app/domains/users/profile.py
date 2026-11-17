"""User taste profiles (spec §8.4, ADR-016).

A profile summarizes a user's interactions as of a reference time:

- long-term taste:  embedding, genre and artist affinities from all positive signals, with a slow
                    decay (half-life of months), so a burst of recent listening cannot erase them;
- short-term taste: an embedding of the last weeks with a fast decay (half-life of days);
- negative taste:   disliked tracks; artists with several disliked tracks (or one, with no
                    positive signal); artists the user repeatedly skips early (only after several
                    early skips across several tracks, with no positive signal; spec §8.5 warns
                    that most skips are not dislikes);
- exploration:      how much of the user's listening spreads across artists, used as the default
                    share of new artists when the user has not chosen an exploration mode;
- declared taste:   preferred and excluded artists and genres the user set explicitly. They are
                    applied on top of the learned profile and always win over it.

`build_taste_profile` is a pure function of the event signals, the catalogue facts of those
tracks, the declared preferences and the configuration, so a profile is reproducible: the API
and the offline evaluation call it with the same inputs and get the same profile.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Generic, TypeVar

import numpy as np
import numpy.typing as npt

from app.domains.users.events import Decay, FeedbackWeights, TrackSignals

T = TypeVar("T", bound=Hashable)
A = TypeVar("A", bound=Hashable)

FloatArray = npt.NDArray[np.float64]

PROFILE_SCHEMA = "taste-profile-v1"


class ExplorationMode(StrEnum):
    """Initial playlist composition targets: share of tracks by artists new to the user."""

    FAMILIAR = "familiar"
    BALANCED = "balanced"
    EXPLORER = "explorer"


DISCOVERY_TARGETS: Mapping[ExplorationMode, float] = {
    ExplorationMode.FAMILIAR: 0.2,
    ExplorationMode.BALANCED: 0.5,
    ExplorationMode.EXPLORER: 0.8,
}
# Bounds of the behaviour-derived target used when the user has not chosen a mode.
AUTO_TARGET_RANGE = (0.2, 0.8)


@dataclass(frozen=True)
class TasteProfileConfig:
    feedback: FeedbackWeights = field(default_factory=FeedbackWeights)
    long_half_life_days: float = 180.0
    short_half_life_days: float = 3.0
    short_window_days: float = 14.0
    # Share of the short-term embedding in the listening-profile query.
    short_term_weight: float = 0.3
    # Content-similarity seeds: the strongest long-term tracks, plus the strongest recent ones.
    seed_tracks: int = 5
    recent_seed_tracks: int = 3
    max_genres: int = 30
    max_artists: int = 50
    # An artist becomes a (soft) negative after this many early skips across this many tracks,
    # with no positive signal for the artist.
    negative_artist_min_skips: int = 3
    negative_artist_min_tracks: int = 2
    # ... or after this many disliked tracks (one is enough when the artist has no positive signal).
    negative_artist_min_dislikes: int = 2
    # Smoothing of the exploration preference towards `exploration_prior`.
    exploration_prior_tracks: float = 5.0
    exploration_prior: float = 0.5
    # Weight of each declared favourite artist in the long-term embedding (one played track ~0.7).
    declared_artist_weight: float = 1.0

    @property
    def long_decay(self) -> Decay:
        return Decay(self.long_half_life_days)

    @property
    def short_decay(self) -> Decay:
        return Decay(self.short_half_life_days, self.short_window_days)

    def params(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def version(self) -> str:
        digest = hashlib.sha256(json.dumps(self.params(), sort_keys=True).encode()).hexdigest()
        return f"{PROFILE_SCHEMA}-{digest[:8]}"


@dataclass(frozen=True)
class DeclaredPreferences(Generic[A]):
    preferred_artists: tuple[A, ...] = ()
    preferred_genres: tuple[str, ...] = ()
    excluded_artists: tuple[A, ...] = ()
    excluded_genres: tuple[str, ...] = ()
    exploration_mode: ExplorationMode | None = None


@dataclass(frozen=True)
class TasteProfile(Generic[T, A]):
    long_term_embedding: FloatArray | None
    short_term_embedding: FloatArray | None
    # Normalized to a maximum of 1, strongest first, at most max_genres / max_artists entries.
    genre_affinity: dict[str, float]
    artist_affinity: dict[A, float]
    negative_artists: dict[A, float]
    excluded_artists: frozenset[A]
    excluded_genres: frozenset[str]
    disliked_tracks: frozenset[T]
    # Every track the user interacted with in any way.
    heard_tracks: frozenset[T]
    # Artists of positively played tracks plus declared favourites: "familiar" artists.
    known_artists: frozenset[A]
    seed_tracks: tuple[T, ...]
    recent_tracks: tuple[T, ...]
    listening_stats: dict[str, float]
    exploration_preference: float
    # Distinct tracks with a positive signal.
    history_size: int
    profile_version: str
    exploration_mode: ExplorationMode | None = None

    @property
    def is_empty(self) -> bool:
        return self.history_size == 0 and self.long_term_embedding is None

    def discovery_target(self, mode: ExplorationMode | None = None) -> float:
        """Target share of new-artist tracks: the requested mode, else the user's chosen mode,
        else the behaviour-derived exploration preference (bounded)."""
        chosen = mode or self.exploration_mode
        if chosen is not None:
            return DISCOVERY_TARGETS[chosen]
        low, high = AUTO_TARGET_RANGE
        return float(np.clip(self.exploration_preference, low, high))


def _normalized(vector: FloatArray) -> FloatArray | None:
    norm = float(np.linalg.norm(vector))
    return None if norm == 0.0 else np.asarray(vector / norm, dtype=np.float64)


def profile_query(
    long_term: FloatArray | None, short_term: FloatArray | None, short_term_weight: float
) -> FloatArray | None:
    """The listening-profile query vector: long-term taste nudged towards recent listening."""
    if long_term is None:
        return short_term
    if short_term is None:
        return long_term
    return _normalized((1.0 - short_term_weight) * long_term + short_term_weight * short_term)


def _top(values: Mapping[Any, float], limit: int) -> dict[Any, float]:
    """Normalize to a maximum of 1 and keep the strongest `limit` (ties by insertion order)."""
    positive = [(k, v) for k, v in values.items() if v > 0]
    if not positive:
        return {}
    top = max(v for _, v in positive)
    ranked = sorted(positive, key=lambda kv: -kv[1])[:limit]
    return {k: round(v / top, 6) for k, v in ranked}


def _ranked_tracks(
    keys: Sequence[T], weights: FloatArray, ages: FloatArray, eligible: npt.NDArray[np.bool_]
) -> list[T]:
    """Tracks with a positive weight, strongest first; ties: most recent, then input order."""
    rows = np.flatnonzero(eligible & (weights > 0))
    order = rows[np.lexsort((rows, ages[rows], -weights[rows]))]
    return [keys[i] for i in order]


def build_taste_profile(
    signals: TrackSignals[T],
    *,
    track_artists: Sequence[A],
    track_embeddings: npt.NDArray[np.floating[Any]] | None,
    track_genres: Sequence[Mapping[str, float]] | None,
    config: TasteProfileConfig,
    preferences: DeclaredPreferences[A] | None = None,
    declared_artist_embeddings: npt.NDArray[np.floating[Any]] | None = None,
) -> TasteProfile[T, A]:
    """Build a profile from one user's per-track signals.

    `track_artists`, `track_embeddings` (rows L2-normalized, all-zero when a track has no
    content) and `track_genres` are aligned with `signals.keys`. `declared_artist_embeddings`
    holds the content embeddings of the declared favourite artists that have one.
    """
    declared = preferences or DeclaredPreferences()
    keys: list[T] = list(signals.keys)
    n = len(keys)
    if len(track_artists) != n:
        raise ValueError("track_artists must be aligned with the signals")
    preference = signals.preference
    recent = signals.recent_preference
    positive = preference > 0
    excluded_artists = frozenset(declared.excluded_artists)
    excluded_genres = frozenset(declared.excluded_genres)

    has_content = np.zeros(n, dtype=np.bool_)
    long_term: FloatArray | None = None
    short_term: FloatArray | None = None
    if track_embeddings is not None and n:
        embeddings = np.asarray(track_embeddings, dtype=np.float64)
        has_content = np.linalg.norm(embeddings, axis=1) > 0
        long_sum = preference @ embeddings
        if declared_artist_embeddings is not None and len(declared_artist_embeddings):
            long_sum = long_sum + config.declared_artist_weight * np.asarray(
                declared_artist_embeddings, dtype=np.float64
            ).sum(axis=0)
        long_term = _normalized(long_sum)
        short_term = _normalized(recent @ embeddings)
    elif declared_artist_embeddings is not None and len(declared_artist_embeddings):
        long_term = _normalized(
            np.asarray(declared_artist_embeddings, dtype=np.float64).sum(axis=0)
        )

    artist_weight: defaultdict[A, float] = defaultdict(float)
    artist_negative: defaultdict[A, float] = defaultdict(float)
    artist_skips: defaultdict[A, int] = defaultdict(int)
    artist_skipped_tracks: defaultdict[A, int] = defaultdict(int)
    artist_disliked: defaultdict[A, int] = defaultdict(int)
    for row, artist in enumerate(track_artists):
        artist_weight[artist] += float(preference[row])
        artist_negative[artist] += float(signals.negative[row])
        skips = int(signals.early_skips[row])
        artist_skips[artist] += skips
        artist_skipped_tracks[artist] += int(skips > 0)
        artist_disliked[artist] += int(signals.disliked[row])

    affinity = {a: w for a, w in artist_weight.items() if a not in excluded_artists}
    artist_affinity = _top(affinity, config.max_artists)
    for artist in declared.preferred_artists:
        if artist not in excluded_artists:
            artist_affinity[artist] = 1.0

    negative: dict[A, float] = {}
    for artist, value in artist_negative.items():
        # Cautious: one disliked track of an artist the user otherwise plays is not enough.
        disliked_artist = artist_disliked[artist] >= config.negative_artist_min_dislikes or (
            artist_disliked[artist] > 0 and artist_weight[artist] == 0.0
        )
        skipped_artist = (
            artist_skips[artist] >= config.negative_artist_min_skips
            and artist_skipped_tracks[artist] >= config.negative_artist_min_tracks
            and artist_weight[artist] == 0.0
        )
        if (disliked_artist or skipped_artist) and artist not in declared.preferred_artists:
            negative[artist] = value
    negative_artists = _top(negative, config.max_artists)

    genre_weight: defaultdict[str, float] = defaultdict(float)
    if track_genres is not None:
        for row in np.flatnonzero(positive).tolist():
            for genre, value in track_genres[row].items():
                genre_weight[genre] += float(preference[row]) * value
    genre_affinity = _top(
        {g: w for g, w in genre_weight.items() if g not in excluded_genres}, config.max_genres
    )
    for genre in declared.preferred_genres:
        if genre not in excluded_genres:
            genre_affinity[genre] = 1.0

    ages = signals.last_age_days
    eligible = has_content if track_embeddings is not None else np.ones(n, dtype=np.bool_)
    seeds = _ranked_tracks(keys, preference, ages, eligible)[: config.seed_tracks]
    recent_ranked = [t for t in _ranked_tracks(keys, recent, ages, eligible) if t not in seeds]

    distinct_tracks = int(positive.sum())
    positive_artists = {track_artists[i] for i in np.flatnonzero(positive).tolist()}
    plays = int(signals.plays.sum())
    played_tracks = int((signals.plays > 0).sum())
    stats = {
        "tracks": float(n),
        "positive_tracks": float(distinct_tracks),
        "positive_artists": float(len(positive_artists)),
        "playbacks": float(plays),
        "repeat_share": round(1.0 - played_tracks / plays, 6) if plays else 0.0,
        "liked": float(signals.liked.sum()),
        "saved": float(signals.saved.sum()),
        "disliked": float(signals.disliked.sum()),
        "early_skips": float(signals.early_skips.sum()),
        "recent_tracks": float((recent > 0).sum()),
    }
    exploration = (
        len(positive_artists) + config.exploration_prior * config.exploration_prior_tracks
    ) / (distinct_tracks + config.exploration_prior_tracks)
    known = {a for a in positive_artists if a not in excluded_artists}
    known.update(a for a in declared.preferred_artists if a not in excluded_artists)
    return TasteProfile(
        long_term_embedding=long_term,
        short_term_embedding=short_term,
        genre_affinity=genre_affinity,
        artist_affinity=artist_affinity,
        negative_artists=negative_artists,
        excluded_artists=excluded_artists,
        excluded_genres=excluded_genres,
        disliked_tracks=frozenset(keys[i] for i in np.flatnonzero(signals.disliked).tolist()),
        heard_tracks=frozenset(keys),
        known_artists=frozenset(known),
        seed_tracks=tuple(seeds),
        recent_tracks=tuple(recent_ranked[: config.recent_seed_tracks]),
        listening_stats=stats,
        exploration_preference=round(float(exploration), 6),
        history_size=distinct_tracks,
        profile_version=config.version,
        exploration_mode=declared.exploration_mode,
    )
