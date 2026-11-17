import math

import numpy as np
import pytest

from app.domains.recommendations.candidate_generation import (
    SOURCE_ORDER,
    CandidateFilter,
    CandidateList,
    Source,
    SourceStatus,
    merge_candidates,
    run_isolated,
)
from app.domains.recommendations.candidate_generation.base import take_unseen
from app.domains.recommendations.candidate_generation.collaborative_candidates import (
    collaborative_candidates,
)
from app.domains.recommendations.candidate_generation.content_candidates import (
    content_candidates,
)
from app.domains.recommendations.candidate_generation.exploration_candidates import (
    exploration_candidates,
)
from app.domains.recommendations.candidate_generation.history_candidates import (
    history_candidates,
)
from app.domains.recommendations.candidate_generation.popularity_candidates import (
    popularity_candidates,
)


def ranked(source: Source, *pairs: tuple[str, float]) -> CandidateList[str]:
    return CandidateList.build(source, list(pairs), f"{source.value}-v1")


def test_merge_keeps_every_source_and_its_rank() -> None:
    merged = merge_candidates(
        [
            ranked(Source.POPULARITY, ("a", 0.9), ("b", 0.8)),
            ranked(Source.COLLABORATIVE_ITEM, ("b", 3.0), ("c", 2.0)),
        ]
    )
    assert merged.items == ("b", "a", "c")
    b = {c.source: c for c in merged.attribution(0)}
    assert set(b) == {Source.COLLABORATIVE_ITEM, Source.POPULARITY}
    assert b[Source.COLLABORATIVE_ITEM].rank == 1
    assert b[Source.POPULARITY].rank == 2
    assert b[Source.POPULARITY].retrieval_score == 0.8
    assert b[Source.POPULARITY].model_version == "popularity-v1"
    assert merged.found_by(Source.POPULARITY).tolist() == [True, True, False]
    column = merged.column(Source.POPULARITY)
    assert math.isinf(merged.ranks[2, column])
    assert math.isnan(merged.scores[2, column])


def test_merge_is_deterministic_regardless_of_list_order() -> None:
    lists = [
        ranked(Source.CONTENT, ("x", 0.5), ("y", 0.4)),
        ranked(Source.PROFILE, ("y", 0.9), ("z", 0.8)),
        ranked(Source.EXPLORATION, ("w", 0.7)),
    ]
    first, second = merge_candidates(lists), merge_candidates(list(reversed(lists)))
    assert first.items == second.items
    np.testing.assert_array_equal(first.ranks, second.ranks)
    # Rank 1 entries first, ties broken by SOURCE_ORDER (profile before content before exploration).
    assert first.items == ("y", "x", "w", "z")


def test_merge_ignores_failed_lists_but_reports_them() -> None:
    failed: CandidateList[str] = CandidateList.failed(Source.COLLABORATIVE_MF, RuntimeError("boom"))
    merged = merge_candidates([failed, ranked(Source.POPULARITY, ("a", 1.0))])
    assert merged.items == ("a",)
    report = merged.report(Source.COLLABORATIVE_MF)
    assert report is not None
    assert report.status is SourceStatus.FAILED
    assert "boom" in (report.detail or "")
    with pytest.raises(ValueError, match="two candidate lists"):
        merge_candidates([ranked(Source.POPULARITY), ranked(Source.POPULARITY)])


def test_duplicates_inside_a_list_keep_the_first_rank() -> None:
    merged = merge_candidates([ranked(Source.CONTENT, ("a", 0.9), ("a", 0.1), ("b", 0.5))])
    assert merged.items == ("a", "b")
    assert merged.ranks[0, merged.column(Source.CONTENT)] == 1


def test_run_isolated_turns_exceptions_into_failed_lists() -> None:
    def broken() -> CandidateList[str]:
        raise ValueError("no model")

    result = run_isolated(Source.CONTENT, broken)
    assert result.status is SourceStatus.FAILED
    assert len(result) == 0
    assert run_isolated(Source.CONTENT, lambda: ranked(Source.CONTENT, ("a", 1.0))).items == ("a",)


def test_filter_removes_and_counts_by_reason() -> None:
    merged = merge_candidates(
        [ranked(Source.PROFILE, *((t, 1.0 - i / 10) for i, t in enumerate("abcdef")))]
    )
    rules: CandidateFilter[str, str] = CandidateFilter(
        heard=frozenset({"a", "b"}),
        disliked=frozenset({"b"}),
        excluded_artists=frozenset({"artist-c"}),
        heard_song_keys=frozenset({"song-d"}),
    )
    kept, removed = rules.apply(
        merged,
        artists=[f"artist-{t}" for t in merged.items],
        song_keys=[f"song-{t}" for t in merged.items],
        eligible=[t != "e" for t in merged.items],
    )
    assert kept.items == ("f",)
    assert removed == {
        "ineligible": 1,
        "heard": 1,
        "disliked": 1,
        "excluded_artist": 1,
        "heard_song": 1,
    }
    with pytest.raises(ValueError, match="aligned"):
        rules.apply(merged, artists=[], song_keys=[])


def test_content_candidates_take_the_best_seed() -> None:
    result, seed_of = content_candidates(
        [("s1", [("a", 0.9), ("b", 0.5), ("s2", 0.99)]), ("s2", [("b", 0.8), ("h", 0.95)])],
        exclude={"h"},
        limit=10,
        model_version="content-v1",
    )
    assert result.items == ("a", "b")
    assert result.scores == (0.9, 0.8)
    assert seed_of == {"a": "s1", "b": "s2"}
    skipped, _ = content_candidates([], exclude=set(), limit=10, model_version=None)
    assert skipped.status is SourceStatus.SKIPPED


def test_collaborative_and_history_candidates_exclude_heard() -> None:
    result = collaborative_candidates(
        Source.COLLABORATIVE_MF,
        [("a", 2.0), ("h", 1.5), ("b", 1.0)],
        exclude={"h"},
        limit=10,
        model_version="cf-v1",
    )
    assert result.items == ("a", "b")
    with pytest.raises(ValueError, match="not a collaborative source"):
        collaborative_candidates(Source.CONTENT, [], exclude=set(), limit=1, model_version=None)
    assert history_candidates(None, exclude=set(), limit=5, model_version=None).status is (
        SourceStatus.SKIPPED
    )
    empty = history_candidates([("h", 1.0)], exclude={"h"}, limit=5, model_version=None)
    assert empty.status is SourceStatus.EMPTY


def test_popularity_candidates_interleave_genres_then_global() -> None:
    result = popularity_candidates(
        [[("r1", 0.9), ("r2", 0.8)], [("j1", 0.7)]],
        [("g1", 1.0), ("r1", 0.9)],
        exclude=set(),
        limit=10,
        model_version="popularity-v1",
    )
    assert result.items == ("r1", "j1", "r2", "g1")


def test_exploration_candidates_skip_known_and_avoided_artists() -> None:
    result, artist_of = exploration_candidates(
        [("known", 0.99), ("bad", 0.95), ("new1", 0.9), ("new2", 0.8)],
        {"new1": ["n1a", "n1b", "n1c"], "new2": ["heard", "n2a"], "known": ["k1"]},
        known_artists={"known"},
        avoided_artists={"bad"},
        exclude={"heard"},
        tracks_per_artist=2,
        limit=10,
        model_version="content-v1",
    )
    assert result.items == ("n1a", "n1b", "n2a")
    assert result.scores == (0.9, 0.9, 0.8)
    assert artist_of["n2a"] == "new2"
    skipped, _ = exploration_candidates(
        None,
        {},
        known_artists=set(),
        avoided_artists=set(),
        exclude=set(),
        tracks_per_artist=2,
        limit=10,
        model_version=None,
    )
    assert skipped.status is SourceStatus.SKIPPED


def test_take_unseen_respects_limit_and_order() -> None:
    assert take_unseen([("a", 3.0), ("b", 2.0), ("a", 1.0), ("c", 0.5)], {"b"}, 2) == [
        ("a", 3.0),
        ("c", 0.5),
    ]


def test_source_order_covers_every_source() -> None:
    assert set(SOURCE_ORDER) == set(Source)
