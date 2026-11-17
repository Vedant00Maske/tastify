"""Listening-profile candidates: nearest tracks to the user's taste-profile embedding.

This is the Milestone 2 "content-profile" model (its strongest offline result), with the query
now coming from the taste profile: long-term taste nudged towards recent listening
(`app.domains.users.profile.profile_query`).
"""

from collections.abc import Hashable, Sequence
from typing import TypeVar

from app.domains.recommendations.candidate_generation.base import (
    CandidateList,
    Source,
    take_unseen,
)

K = TypeVar("K", bound=Hashable)


def history_candidates(
    neighbours: Sequence[tuple[K, float]] | None,
    *,
    exclude: frozenset[K] | set[K],
    limit: int,
    model_version: str | None,
) -> CandidateList[K]:
    """`neighbours`: nearest tracks to the profile query, best first; None without a profile."""
    if neighbours is None:
        return CandidateList.skipped(Source.PROFILE, "no taste-profile embedding")
    return CandidateList.build(
        Source.PROFILE, take_unseen(neighbours, exclude, limit), model_version
    )
