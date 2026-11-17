"""Popularity candidates: popular tracks in the user's strongest genres, then popular overall.

The fallback that always works: for a brand-new user it is the whole candidate set (cold start,
spec §8.3), and with declared favourite genres it is already personalized.
"""

from collections.abc import Hashable, Sequence
from typing import TypeVar

from app.domains.recommendations.candidate_generation.base import (
    CandidateList,
    Source,
    take_unseen,
)

K = TypeVar("K", bound=Hashable)


def popularity_candidates(
    genre_rankings: Sequence[Sequence[tuple[K, float]]],
    global_ranking: Sequence[tuple[K, float]],
    *,
    exclude: frozenset[K] | set[K],
    limit: int,
    model_version: str | None,
) -> CandidateList[K]:
    """Interleave the genre rankings (strongest genre first, round robin), then the global
    ranking. Scores are each ranking's own popularity score."""
    interleaved: list[tuple[K, float]] = []
    longest = max((len(r) for r in genre_rankings), default=0)
    for position in range(longest):
        for ranking in genre_rankings:
            if position < len(ranking):
                interleaved.append(ranking[position])
    interleaved.extend(global_ranking)
    return CandidateList.build(
        Source.POPULARITY, take_unseen(interleaved, exclude, limit), model_version
    )
