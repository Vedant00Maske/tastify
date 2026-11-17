from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest

from app.domains.users.events import TrackSignals, aggregate_events
from app.domains.users.profile import (
    AUTO_TARGET_RANGE,
    DISCOVERY_TARGETS,
    DeclaredPreferences,
    ExplorationMode,
    TasteProfile,
    TasteProfileConfig,
    build_taste_profile,
    profile_query,
)

CONFIG = TasteProfileConfig()
ROCK, ELECTRONIC = np.eye(4)[0], np.eye(4)[1]


def signals(events: Sequence[tuple[str, str, float, float | None]]) -> TrackSignals[Any]:
    keys, types, ages, positions = zip(*events, strict=True) if events else ((), (), (), ())
    return aggregate_events(
        list(keys),
        list(types),
        list(ages),
        list(positions),
        weights=CONFIG.feedback,
        long_decay=CONFIG.long_decay,
        short_decay=CONFIG.short_decay,
    )


TRACKS = {
    "rock1": ("radiohead", ROCK, {"alternative rock": 0.9}),
    "rock2": ("radiohead", ROCK, {"alternative rock": 0.8, "rock": 0.3}),
    "rock3": ("arctic", ROCK, {"indie rock": 0.9}),
    "edm1": ("daft", ELECTRONIC, {"electronic": 0.9}),
    "pop1": ("popstar", np.eye(4)[2], {"pop": 0.9}),
    "pop2": ("popstar", np.eye(4)[2], {"pop": 0.9}),
}


def build(
    events: Sequence[tuple[str, str, float, float | None]],
    preferences: DeclaredPreferences[str] | None = None,
    declared: np.ndarray[Any, Any] | None = None,
) -> TasteProfile[str, str]:
    s = signals(events)
    keys = list(s.keys)
    return build_taste_profile(
        s,
        track_artists=[TRACKS[k][0] for k in keys],
        track_embeddings=np.array([TRACKS[k][1] for k in keys]) if keys else None,
        track_genres=[TRACKS[k][2] for k in keys],
        config=CONFIG,
        preferences=preferences,
        declared_artist_embeddings=declared,
    )


LONG_TERM_ROCK = [
    (t, "play", 30.0 + i, None) for i in range(20) for t in ("rock1", "rock2", "rock3")
]


def test_long_term_taste_survives_a_burst_of_recent_listening() -> None:
    burst = [("edm1", "play", 0.5, None)] * 6
    profile = build([*LONG_TERM_ROCK, *burst])
    assert profile.long_term_embedding is not None
    assert profile.short_term_embedding is not None
    # Recent listening moves the short-term profile, not the long-term one.
    assert float(profile.long_term_embedding @ ROCK) > 0.9
    assert float(profile.short_term_embedding @ ELECTRONIC) > 0.9
    assert next(iter(profile.genre_affinity)) == "alternative rock"
    # Recent tracks are content seeds too (here the burst is already strong enough to be a seed).
    assert "edm1" in (*profile.seed_tracks, *profile.recent_tracks)


def test_profile_query_blends_long_and_short_term() -> None:
    query = profile_query(ROCK, ELECTRONIC, 0.3)
    assert query is not None
    assert float(query @ ROCK) > float(query @ ELECTRONIC) > 0
    assert profile_query(None, ELECTRONIC, 0.3) is ELECTRONIC
    assert profile_query(ROCK, None, 0.3) is ROCK
    assert profile_query(None, None, 0.3) is None


def test_artist_affinity_seeds_and_known_artists() -> None:
    profile = build(LONG_TERM_ROCK)
    assert list(profile.artist_affinity) == ["radiohead", "arctic"]
    assert profile.artist_affinity["radiohead"] == 1.0
    assert set(profile.seed_tracks) == {"rock1", "rock2", "rock3"}
    assert profile.known_artists == {"radiohead", "arctic"}
    assert profile.history_size == 3
    assert profile.heard_tracks == {"rock1", "rock2", "rock3"}


def test_repeated_early_skips_across_tracks_make_a_cautious_negative() -> None:
    skips = [(t, "skip", 1.0, 3_000.0) for t in ("pop1", "pop2", "pop1")]
    profile = build([*LONG_TERM_ROCK, *skips])
    assert "popstar" in profile.negative_artists
    assert "popstar" not in profile.known_artists


def test_skips_of_a_single_track_or_late_skips_are_not_a_negative() -> None:
    one_track = [("pop1", "skip", 1.0, 3_000.0)] * 5
    late = [(t, "skip", 1.0, 200_000.0) for t in ("pop1", "pop2", "pop1")]
    assert build([*LONG_TERM_ROCK, *one_track]).negative_artists == {}
    assert build([*LONG_TERM_ROCK, *late]).negative_artists == {}


def test_a_disliked_track_makes_its_artist_negative_and_is_excluded() -> None:
    profile = build([*LONG_TERM_ROCK, ("pop1", "dislike", 1.0, None)])
    assert profile.disliked_tracks == {"pop1"}
    assert "popstar" in profile.negative_artists


def test_declared_preferences_override_the_learned_profile() -> None:
    declared = DeclaredPreferences(
        preferred_artists=("daft",),
        excluded_artists=("arctic",),
        preferred_genres=("electronic",),
        excluded_genres=("indie rock",),
        exploration_mode=ExplorationMode.EXPLORER,
    )
    profile = build(LONG_TERM_ROCK, preferences=declared)
    assert profile.artist_affinity["daft"] == 1.0
    assert "arctic" not in profile.artist_affinity
    assert "daft" in profile.known_artists
    assert "arctic" not in profile.known_artists
    assert profile.genre_affinity["electronic"] == 1.0
    assert "indie rock" not in profile.genre_affinity
    assert profile.excluded_artists == {"arctic"}
    assert profile.discovery_target() == DISCOVERY_TARGETS[ExplorationMode.EXPLORER]


def test_cold_start_profile_from_declared_artists_only() -> None:
    declared = DeclaredPreferences(preferred_artists=("daft",), preferred_genres=("electronic",))
    profile = build([], preferences=declared, declared=np.array([ELECTRONIC]))
    assert profile.history_size == 0
    assert profile.long_term_embedding is not None
    assert float(profile.long_term_embedding @ ELECTRONIC) == pytest.approx(1.0)
    assert profile.short_term_embedding is None
    assert not profile.is_empty


def test_discovery_target_modes_and_behaviour_default() -> None:
    profile = build(LONG_TERM_ROCK)
    for mode, target in DISCOVERY_TARGETS.items():
        assert profile.discovery_target(mode) == target
    low, high = AUTO_TARGET_RANGE
    assert low <= profile.discovery_target() <= high
    # 3 tracks by 2 artists, smoothed towards 0.5 with 5 pseudo-tracks.
    assert profile.exploration_preference == pytest.approx((2 + 2.5) / (3 + 5))


def test_profiles_are_reproducible_and_versioned() -> None:
    events = [*LONG_TERM_ROCK, ("edm1", "like", 0.2, None)]
    first, second = build(events), build(events)
    assert first.long_term_embedding is not None
    assert second.long_term_embedding is not None
    assert np.array_equal(first.long_term_embedding, second.long_term_embedding)
    assert first.genre_affinity == second.genre_affinity
    assert first.artist_affinity == second.artist_affinity
    assert first.seed_tracks == second.seed_tracks
    assert first.profile_version == CONFIG.version
    assert TasteProfileConfig(short_half_life_days=7.0).version != CONFIG.version


def test_empty_history_without_preferences_is_empty() -> None:
    profile = build([])
    assert profile.is_empty
    assert profile.genre_affinity == {}
    assert profile.seed_tracks == ()
