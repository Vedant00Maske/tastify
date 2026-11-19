import uuid
from collections import Counter

import pytest

from app.domains.recommendations.context import (
    build_context_profile,
    build_session,
    context_fit,
    daypart,
    session_fit,
)
from app.domains.recommendations.experiments import (
    VariantOutcome,
    assign,
    compare,
    parse_variants,
    two_proportion_p_value,
    wilson,
)
from app.domains.recommendations.prompts import genre_vocabulary, parse

VOCABULARY = genre_vocabulary(
    ["indie rock", "electronic", "metal", "rock", "classic rock", "hip hop", "jazz", "dream pop"]
)


def read(prompt: str) -> dict[str, object]:
    parsed = parse(prompt, VOCABULARY, 2026)
    return {k: v for k, v in vars(parsed).items() if v not in ([], (None, None), None)}


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Indie rock with electronic influence", {"genres": ["indie rock", "electronic"]}),
        (
            "chill 90s hip-hop, no metal",
            {
                "genres": ["hip hop"],
                "excluded_genres": ["metal"],
                "danceability": (None, 0.5),
                "years": (1990, 1999),
            },
        ),
        ("classic rock hits", {"genres": ["classic rock"], "popularity": "popular"}),
        (
            "something like Radiohead but more upbeat",
            {"artist_phrases": ["radiohead"], "tempo": (120.0, None)},
        ),
        (
            "fast dream pop around 128 bpm, not too popular, new artists",
            {
                "genres": ["dream pop"],
                "tempo": (120.0, 136.0),
                "popularity": "lesser_known",
                "exploration": 0.8,
            },
        ),
        (
            "jazz before 1970 without miles davis",
            {
                "genres": ["jazz"],
                "excluded_artist_phrases": ["miles davis"],
                "years": (None, 1969),
            },
        ),
        (
            "rainy day study session",
            {"moods": ["rainy-afternoon", "deep-focus"], "ignored": ["day", "session"]},
        ),
    ],
)
def test_prompts_are_read_into_structured_intent(prompt: str, expected: dict[str, object]) -> None:
    assert read(prompt) == expected


def test_unanchored_prompts_are_recognised() -> None:
    parsed = parse("something chill please", VOCABULARY, 2026)
    assert not parsed.anchored
    assert parsed.danceability == (None, 0.5)


def test_experiment_assignment_is_stable_and_weighted() -> None:
    variants = parse_variants(
        [{"name": "control", "weight": 3}, {"name": "treatment", "weight": 1, "params": {"w": 1}}]
    )
    user = uuid.uuid4()
    assert assign("exp", variants, user) == assign("exp", variants, user)
    counts = Counter(assign("exp", variants, uuid.uuid4()).variant for _ in range(4000))
    assert 0.7 < counts["control"] / 4000 < 0.8
    with pytest.raises(ValueError, match="two variants"):
        parse_variants([{"name": "only"}])


def test_statistics() -> None:
    low, high = wilson(50, 1000)
    assert low < 0.05 < high
    assert wilson(0, 0) == (0.0, 0.0)
    p = two_proportion_p_value(80, 1000, 50, 1000)
    assert p is not None
    assert p < 0.01
    small = compare(VariantOutcome("a", 10, 10, 100, 5, 0), VariantOutcome("b", 10, 10, 100, 9, 0))
    assert small["verdict"] == "not enough data"
    big = compare(
        VariantOutcome("a", 500, 900, 5000, 250, 10), VariantOutcome("b", 500, 900, 5000, 330, 10)
    )
    assert big["verdict"] == "b better than a"


def test_session_fit_favours_what_is_playing_now() -> None:
    overall = {"rock": 0.5, "jazz": 0.5}
    session = build_session([{"jazz": 1.0}, {"jazz": 1.0}, {"jazz": 0.8, "rock": 0.2}])
    assert session_fit(session, overall, {"jazz": 1.0}) > 0
    assert session_fit(session, overall, {"rock": 1.0}) < 0
    one = build_session([{"jazz": 1.0}])
    assert session_fit(one, overall, {"jazz": 1.0}) == 0.0  # not enough session evidence


def test_daypart_fit_needs_evidence() -> None:
    profile = build_context_profile(
        [("evening", {"rock": 1.0})] * 30 + [("morning", {"jazz": 1.0})] * 30
    )
    assert daypart(20) == "evening"
    assert context_fit(profile, "evening", {"rock": 1.0}) > 0
    assert context_fit(profile, "night", {"rock": 1.0}) == 0.0
