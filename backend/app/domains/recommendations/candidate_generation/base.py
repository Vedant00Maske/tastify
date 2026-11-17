"""Candidate lists, the shared currency of the candidate generators (ADR-016).

Each generator returns a `CandidateList` for one source: items best first, each with the score
the source retrieved it by. Generators never see each other's output; the merger combines them
without discarding which sources found an item, its rank there or the model version used.

A generator that fails or cannot run (no model, no profile) returns a list with a non-OK status
instead of raising, so one broken source never takes the others down.
"""

import logging
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)

logger = logging.getLogger(__name__)


class Source(StrEnum):
    CONTENT = "content_based"  # content neighbours of the user's strongest tracks
    COLLABORATIVE_ITEM = "collaborative_item"  # item-item co-listening neighbours of the history
    COLLABORATIVE_MF = "collaborative_mf"  # implicit-feedback matrix factorization (ALS)
    PROFILE = "listening_profile"  # nearest tracks to the user's taste-profile embedding
    EXPLORATION = "exploration"  # popular tracks of similar artists the user does not know
    POPULARITY = "popularity"  # popular tracks in the user's genres, then overall


# Merge order: earlier sources win ties in the merged order. The order is part of the
# deterministic contract (same input, same merged list), not a quality ranking.
SOURCE_ORDER: tuple[Source, ...] = (
    Source.COLLABORATIVE_ITEM,
    Source.COLLABORATIVE_MF,
    Source.PROFILE,
    Source.CONTENT,
    Source.EXPLORATION,
    Source.POPULARITY,
)

# Sources derived from the content model, whose genre signal is MusicBrainz tags (CC BY-NC-SA).
CONTENT_DERIVED_SOURCES = frozenset({Source.CONTENT, Source.PROFILE, Source.EXPLORATION})


class SourceStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"  # ran, found nothing
    SKIPPED = "skipped"  # not applicable (no model, no history)
    FAILED = "failed"  # raised; isolated and logged


@dataclass(frozen=True)
class CandidateList(Generic[K]):
    source: Source
    items: tuple[K, ...]
    scores: tuple[float, ...]
    model_version: str | None = None
    status: SourceStatus = SourceStatus.OK
    detail: str | None = None

    def __post_init__(self) -> None:
        if len(self.items) != len(self.scores):
            raise ValueError("items and scores must have the same length")

    def __len__(self) -> int:
        return len(self.items)

    @classmethod
    def build(
        cls,
        source: Source,
        ranked: Sequence[tuple[K, float]],
        model_version: str | None,
        limit: int | None = None,
    ) -> "CandidateList[K]":
        chosen = ranked if limit is None else ranked[:limit]
        return cls(
            source,
            tuple(item for item, _ in chosen),
            tuple(float(score) for _, score in chosen),
            model_version,
            SourceStatus.OK if chosen else SourceStatus.EMPTY,
        )

    @classmethod
    def skipped(cls, source: Source, reason: str) -> "CandidateList[K]":
        return cls(source, (), (), None, SourceStatus.SKIPPED, reason)

    @classmethod
    def failed(cls, source: Source, error: BaseException) -> "CandidateList[K]":
        return cls(source, (), (), None, SourceStatus.FAILED, f"{type(error).__name__}: {error}")


@dataclass(frozen=True, slots=True)
class SourceCandidate(Generic[K]):
    """Where one source placed a merged candidate."""

    item: K
    source: Source
    retrieval_score: float
    rank: int  # 1-based within the source
    model_version: str | None


def run_isolated(source: Source, generate: Callable[[], CandidateList[K]]) -> CandidateList[K]:
    """Run a generator; an exception becomes a FAILED list instead of propagating."""
    try:
        return generate()
    except Exception as error:  # isolation is the point: any failure stays in its source
        logger.warning("candidate source %s failed: %s", source.value, error, exc_info=True)
        return CandidateList.failed(source, error)


def take_unseen(
    ranked: Sequence[tuple[K, float]], exclude: frozenset[K] | set[K], limit: int
) -> list[tuple[K, float]]:
    """The first `limit` entries whose item is not excluded, keeping the first of duplicates."""
    out: list[tuple[K, float]] = []
    seen: set[K] = set()
    for item, score in ranked:
        if item in exclude or item in seen:
            continue
        seen.add(item)
        out.append((item, score))
        if len(out) == limit:
            break
    return out
