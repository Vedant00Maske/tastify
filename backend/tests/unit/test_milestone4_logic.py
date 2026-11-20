import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domains.auth import passwords
from app.domains.recommendations.moods import MOODS, MoodRecipe
from app.domains.recommendations.repository import TagMember
from app.domains.users.analytics import (
    EventRow,
    GenreShift,
    GenreStat,
    overview_text,
    week_start,
    weekly_trends,
)
from app.domains.users.profile import strongest_first


@pytest.mark.parametrize(
    ("password", "problem"),
    [
        ("short", "at least"),
        ("x" * 129, "at most"),
        (" padded password ", "spaces"),
        ("me@example.com", "e-mail"),
        ("a long enough pass", None),
    ],
)
def test_password_policy(password: str, problem: str | None) -> None:
    result = passwords.password_problem(password, "Me@Example.com")
    assert (result is None) if problem is None else (problem in (result or ""))


def test_passwords_are_argon2id_hashed_and_verified() -> None:
    hashed = passwords.hash_password("a long enough pass")
    assert hashed.startswith("$argon2id$")
    assert passwords.verify_password(hashed, "a long enough pass")
    assert not passwords.verify_password(hashed, "a different pass")
    assert not passwords.verify_password("not-a-hash", "anything at all")


def member(tempo: float | None, dance: float | None) -> TagMember:
    return TagMember(uuid.uuid4(), "synthwave", 0.9, 0.5, 10, tempo, dance)


def test_mood_recipes_bound_measured_features_only() -> None:
    recipe = MoodRecipe("x", "X", "", ("synthwave",), tempo=(90, 120), danceability=(0.4, None))
    assert recipe.fits(member(100, 0.5))
    assert not recipe.fits(member(140, 0.5))
    assert not recipe.fits(member(100, 0.2))
    assert recipe.fits(member(None, None))  # no audio features: genres alone decide


def test_every_mood_has_genres_and_a_unique_key() -> None:
    assert len(MOODS) == 8
    for key, recipe in MOODS.items():
        assert key == recipe.key
        assert recipe.genres


def test_weekly_trends_count_playbacks_tracks_and_first_artists() -> None:
    now = datetime(2026, 11, 17, 12, tzinfo=UTC)  # a Tuesday
    a, b = uuid.uuid4(), uuid.uuid4()
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    rows = [
        EventRow(t1, "play", now - timedelta(days=8), a),
        EventRow(t1, "play", now - timedelta(days=1), a),
        EventRow(t2, "complete", now - timedelta(hours=1), b),
        EventRow(t2, "like", now, b),
    ]
    trends = weekly_trends(rows, now)
    assert len(trends) == 12
    assert trends[-1].week_start == week_start(now)
    assert (trends[-1].playbacks, trends[-1].distinct_tracks, trends[-1].new_artists) == (2, 2, 1)
    assert (trends[-2].playbacks, trends[-2].new_artists) == (1, 1)


def test_overview_states_only_recorded_facts() -> None:
    assert overview_text([], [], []) is None
    text = overview_text(
        [GenreStat(genre="rock", score=1.0), GenreStat(genre="jazz", score=0.5)],
        [],
        [GenreShift(genre="dream pop", recent_share=0.3, earlier_share=0.1, change=0.2)],
    )
    assert text == (
        "Your listening centres on rock and jazz. Lately you are spending more time with dream pop."
    )


def test_affinities_are_strongest_first_with_deterministic_ties() -> None:
    # The key order PostgreSQL JSONB returns (shortest keys first) must not leak into rankings.
    stored = {"rock": 0.4, "metal": 1.0, "indie rock": 1.0, "rapcore": 0.01}
    assert list(strongest_first(stored)) == ["indie rock", "metal", "rock", "rapcore"]


@pytest.mark.parametrize(
    ("peer", "proxies", "trusted"),
    [
        ("127.0.0.1", ["127.0.0.1", "::1"], True),
        ("172.18.0.5", ["172.16.0.0/12"], True),
        ("203.0.113.9", ["172.16.0.0/12"], False),
        ("unknown", ["127.0.0.1"], False),
        ("10.0.0.1", ["not-an-address"], False),
    ],
)
def test_forwarded_for_is_trusted_only_from_configured_proxies(
    peer: str, proxies: list[str], trusted: bool
) -> None:
    from app.api.limits import trusted_peer as _trusted

    assert _trusted(peer, proxies) is trusted
