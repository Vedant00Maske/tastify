"""Entity resolution: decide whether an incoming source track is a track already in the catalogue.

Policy (docs/DATA_SOURCES.md, ADR-014):

- A shared ISRC links the tracks, unless durations disagree by more than 10 s or the artists do
  not match. ISRCs are sometimes reused or mis-assigned, so those cases go to review.
- Without an ISRC, the cleaned title AND the artist must match exactly and the durations must agree
  within 3 s to link. Partial agreement goes to review. A title match alone never links.
- If several catalogue tracks qualify for linking, none is linked: the case is ambiguous and goes to
  review.

Everything here is pure (no I/O), so the policy is fully unit-tested.
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Generic, TypeVar

from app.domains.catalogue.normalization import clean_title, matching_key

ISRC_DURATION_TOLERANCE_MS = 10_000
METADATA_DURATION_TOLERANCE_MS = 3_000
FUZZY_SIMILARITY = 0.9
MIN_ARTIST_SIMILARITY_FOR_ISRC = 0.5

K = TypeVar("K", bound=Hashable)


class MatchDecision(StrEnum):
    LINK = "link"
    REVIEW = "review"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class TrackEvidence:
    """What any source tells us about a track, reduced to the fields used for matching."""

    title: str
    artists: tuple[str, ...]
    duration_ms: int | None = None
    isrcs: frozenset[str] = field(default_factory=frozenset)
    album: str | None = None


@dataclass(frozen=True)
class MatchResult:
    decision: MatchDecision
    confidence: float
    method: str
    signals: dict[str, float | int | bool | None]


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def artist_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    """Best pairwise similarity between the credited artists of two tracks."""
    left_keys = [matching_key(name) for name in left if name.strip()]
    right_keys = [matching_key(name) for name in right if name.strip()]
    return max((_similarity(a, b) for a in left_keys for b in right_keys), default=0.0)


def compare(incoming: TrackEvidence, existing: TrackEvidence) -> MatchResult:
    title_sim = _similarity(
        matching_key(clean_title(incoming.title)), matching_key(clean_title(existing.title))
    )
    artist_sim = artist_similarity(incoming.artists, existing.artists)
    duration_delta = (
        abs(incoming.duration_ms - existing.duration_ms)
        if incoming.duration_ms is not None and existing.duration_ms is not None
        else None
    )
    album_match = (
        incoming.album is not None
        and existing.album is not None
        and matching_key(incoming.album) == matching_key(existing.album)
    )
    shared_isrc = bool(incoming.isrcs & existing.isrcs)
    signals: dict[str, float | int | bool | None] = {
        "shared_isrc": shared_isrc,
        "title_similarity": round(title_sim, 3),
        "artist_similarity": round(artist_sim, 3),
        "duration_delta_ms": duration_delta,
        "album_match": album_match,
    }

    if shared_isrc:
        if (
            duration_delta is not None and duration_delta > ISRC_DURATION_TOLERANCE_MS
        ) or artist_sim < MIN_ARTIST_SIMILARITY_FOR_ISRC:
            return MatchResult(MatchDecision.REVIEW, 0.6, "isrc", signals)
        return MatchResult(MatchDecision.LINK, 0.99, "isrc", signals)

    if title_sim == 1.0 and artist_sim == 1.0:
        if duration_delta is None:
            return MatchResult(MatchDecision.REVIEW, 0.7, "metadata", signals)
        if duration_delta <= METADATA_DURATION_TOLERANCE_MS:
            confidence = 0.95 if album_match else 0.9
            return MatchResult(MatchDecision.LINK, confidence, "metadata", signals)
        return MatchResult(MatchDecision.NO_MATCH, 0.3, "metadata", signals)

    if (
        title_sim >= FUZZY_SIMILARITY
        and artist_sim >= FUZZY_SIMILARITY
        and duration_delta is not None
        and duration_delta <= METADATA_DURATION_TOLERANCE_MS
    ):
        return MatchResult(MatchDecision.REVIEW, 0.75, "metadata", signals)

    return MatchResult(MatchDecision.NO_MATCH, 0.0, "metadata", signals)


@dataclass(frozen=True)
class Resolution(Generic[K]):
    decision: MatchDecision
    linked: K | None
    """The catalogue track to link to, when decision is LINK."""
    review: list[tuple[K, MatchResult]]
    """Candidates that need human verification, when decision is REVIEW."""
    match: MatchResult | None = None


def resolve(
    incoming: TrackEvidence, candidates: Sequence[tuple[K, TrackEvidence]]
) -> Resolution[K]:
    """Apply the policy to every candidate and decide the outcome for the incoming track."""
    results = [(key, compare(incoming, evidence)) for key, evidence in candidates]
    links = [(key, result) for key, result in results if result.decision is MatchDecision.LINK]
    if len(links) == 1:
        key, result = links[0]
        return Resolution(MatchDecision.LINK, key, [], result)
    if len(links) > 1:
        ambiguous = [(key, _as_review(result)) for key, result in links]
        return Resolution(MatchDecision.REVIEW, None, ambiguous)
    reviews = [(key, result) for key, result in results if result.decision is MatchDecision.REVIEW]
    if reviews:
        return Resolution(MatchDecision.REVIEW, None, reviews)
    return Resolution(MatchDecision.NO_MATCH, None, [])


def _as_review(result: MatchResult) -> MatchResult:
    signals = {**result.signals, "ambiguous": True}
    return MatchResult(MatchDecision.REVIEW, min(result.confidence, 0.8), result.method, signals)
