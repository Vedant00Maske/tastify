import pytest

from app.domains.recommendations.ranking import (
    GENRE_POPULARITY_WEIGHT,
    LEVEL_WEIGHTS,
    Candidate,
    blended_score,
    genre_affinity,
    genre_score,
    rerank,
    smoothed_tag_weight,
    song_key,
)


def candidate(
    item: str, similarity: float, popularity: float = 0.0, artist: str = "", key: str | None = None
) -> Candidate[str]:
    return Candidate(item, similarity, popularity, artist or item, key)


def test_blended_score_interpolates_similarity_and_popularity() -> None:
    assert blended_score(0.8, 0.2, 0.0) == pytest.approx(0.8)
    assert blended_score(0.8, 0.2, 1.0) == pytest.approx(0.2)
    assert blended_score(0.8, 0.2, 0.25) == pytest.approx(0.65)


def test_genre_score_is_a_blend_with_the_genre_weight() -> None:
    assert genre_score(0.5, 0.9) == pytest.approx(blended_score(0.5, 0.9, GENRE_POPULARITY_WEIGHT))


def test_genre_affinity_takes_the_strongest_level_weighted_tag() -> None:
    affinity = genre_affinity([("recording", 0.2), ("album", 0.5), ("artist", 0.9)])
    assert affinity == pytest.approx(max(0.2, 0.5 * LEVEL_WEIGHTS["album"], 0.9 * 0.6))
    assert genre_affinity([]) == 0.0


def test_rerank_orders_by_blended_score() -> None:
    ranked = rerank(
        [candidate("a", 0.9, 0.0), candidate("b", 0.8, 1.0), candidate("c", 0.5, 0.0)],
        beta=0.5,
        limit=3,
    )
    assert [r.item for r in ranked] == ["b", "a", "c"]
    assert ranked[0].score == pytest.approx(0.9)


def test_rerank_caps_tracks_per_artist_and_backfills() -> None:
    ranked = rerank(
        [
            candidate("a1", 0.9, artist="A"),
            candidate("a2", 0.8, artist="A"),
            candidate("a3", 0.7, artist="A"),
            candidate("b1", 0.6, artist="B"),
        ],
        beta=0.0,
        limit=3,
        max_per_artist=2,
    )
    assert [r.item for r in ranked] == ["a1", "a2", "b1"]


def test_rerank_without_cap_keeps_every_artist_track() -> None:
    items = [candidate(f"a{i}", 1 - i / 10, artist="A") for i in range(4)]
    assert len(rerank(items, beta=0.0, limit=4, max_per_artist=None)) == 4


def test_rerank_removes_duplicates_and_excluded_keys() -> None:
    ranked = rerank(
        [
            candidate("seed-copy", 0.99, key="artist|song"),
            candidate("x", 0.9, key="artist|other"),
            candidate("x-dup", 0.85, key="artist|other"),
            candidate("y", 0.5),
        ],
        beta=0.0,
        limit=5,
        exclude_dedup_keys=["artist|song"],
    )
    assert [r.item for r in ranked] == ["x", "y"]


def test_rerank_is_stable_for_ties_and_respects_limit() -> None:
    ranked = rerank([candidate(name, 0.5) for name in "dcba"], beta=0.0, limit=2)
    assert [r.item for r in ranked] == ["d", "c"]
    assert rerank([], beta=0.3, limit=5) == []


def test_smoothed_tag_weight_shrinks_thin_evidence() -> None:
    assert smoothed_tag_weight(1, 1) == pytest.approx(1 / 3)
    assert smoothed_tag_weight(20, 20) == pytest.approx(20 / 22)
    assert smoothed_tag_weight(3, 4, prior=0) == pytest.approx(0.75)


@pytest.mark.parametrize(
    "title",
    [
        "Music Sounds Better With You",
        "Music Sounds Better With You (radio edit)",
        "Music Sounds Better With You [Remastered] (Live)",
        "Music Sounds Better With You - Remastered 2011",
        "MUSIC SOUNDS BETTER WITH YOU",
    ],
)
def test_song_key_groups_versions_of_a_song(title: str) -> None:
    assert song_key("artist-1", title) == song_key("artist-1", "Music Sounds Better With You")


def test_song_key_keeps_different_songs_and_artists_apart() -> None:
    assert song_key("a", "Creep") != song_key("b", "Creep")
    assert song_key("a", "Creep") != song_key("a", "Karma Police")
    # A title that is only a parenthetical is kept rather than emptied.
    assert song_key("a", "(Untitled)") == "a|untitled"
