import uuid
from typing import Any

import numpy as np
import pytest

from app.domains.users.events import (
    Decay,
    EventType,
    FeedbackWeights,
    TrackSignals,
    aggregate_events,
)

WEIGHTS = FeedbackWeights()
LONG = Decay(180.0)
SHORT = Decay(3.0, window_days=14.0)


def aggregate(
    keys: list[object],
    types: list[str],
    ages: list[float],
    positions: list[float | None] | None = None,
) -> TrackSignals[Any]:
    return aggregate_events(
        keys, types, ages, positions, weights=WEIGHTS, long_decay=LONG, short_decay=SHORT
    )


def test_decay_halves_at_the_half_life_and_stops_at_the_window() -> None:
    assert Decay(3.0).factor(np.array([0.0, 3.0, 6.0])) == pytest.approx([1.0, 0.5, 0.25])
    assert SHORT.factor(np.array([14.0, 14.5])) == pytest.approx([0.5 ** (14 / 3), 0.0])


def test_plays_accumulate_with_decay_per_track() -> None:
    signals = aggregate(["a", "a", "b"], ["play", "complete", "play"], [0.0, 180.0, 3.0])
    assert list(signals.keys) == ["a", "b"]
    assert signals.positive[0] == pytest.approx(1.0 + 1.25 * 0.5)
    assert signals.plays.tolist() == [2, 1]
    assert signals.recent[1] == pytest.approx(0.5)
    assert signals.last_age_days.tolist() == [0.0, 3.0]


def test_only_early_skips_are_negative() -> None:
    signals = aggregate(
        ["a", "a", "b"], ["skip", "skip", "skip"], [0.0, 0.0, 0.0], [5_000, None, 120_000]
    )
    assert signals.negative.tolist() == pytest.approx([0.5, 0.0])
    assert signals.early_skips.tolist() == [1, 0]
    assert signals.positive.tolist() == [0.0, 0.0]


def test_likes_are_states_where_the_latest_event_wins() -> None:
    signals = aggregate(
        ["a", "a", "b", "b", "c"],
        ["like", "unlike", "like", "like", "unlike"],
        [2.0, 1.0, 2.0, 1.0, 0.0],
    )
    assert signals.liked.tolist() == [False, True, False]
    # A repeated like counts once (state, not event), decayed from the latest like.
    assert signals.positive[1] == pytest.approx(WEIGHTS.like * LONG.factor(np.array([1.0]))[0])
    assert signals.positive[0] == 0.0


def test_dislike_clears_a_like_and_counts_as_strong_negative() -> None:
    signals = aggregate(["a", "a", "a"], ["play", "like", "dislike"], [3.0, 2.0, 1.0])
    assert not signals.liked[0]
    assert signals.disliked[0]
    assert signals.negative[0] == pytest.approx(WEIGHTS.dislike * LONG.factor(np.array([1.0]))[0])
    assert signals.preference[0] == 0.0
    assert signals.recent_preference[0] == 0.0


def test_save_adds_a_bonus_until_unsaved() -> None:
    saved = aggregate(["a", "a"], ["play", "save"], [0.0, 0.0])
    unsaved = aggregate(["a", "a", "a"], ["play", "save", "unsave"], [0.0, 0.0, 0.0])
    assert saved.positive[0] == pytest.approx(1.0 + WEIGHTS.save)
    assert unsaved.positive[0] == pytest.approx(1.0)


def test_simultaneous_state_events_follow_input_order() -> None:
    signals = aggregate(["a", "a"], ["like", "unlike"], [0.0, 0.0])
    assert not signals.liked[0]


def test_preference_is_log_net_signal() -> None:
    signals = aggregate(["a", "a", "a"], ["play", "play", "skip"], [0.0, 0.0, 0.0], [None, None, 0])
    assert signals.preference[0] == pytest.approx(np.log1p(2.0) - np.log1p(0.5))


def test_uuid_keys_and_empty_input() -> None:
    track = uuid.uuid4()
    signals = aggregate([track], ["play"], [0.0])
    assert signals.keys[0] == track
    assert len(aggregate([], [], [])) == 0


def test_unknown_event_types_and_misaligned_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown event types"):
        aggregate(["a"], ["clap"], [0.0])
    with pytest.raises(ValueError, match="same length"):
        aggregate(["a", "b"], ["play"], [0.0, 1.0])


def test_every_event_type_has_a_defined_effect() -> None:
    for event_type in EventType:
        signals = aggregate(["a"], [event_type.value], [0.0], [1_000])
        assert len(signals) == 1
