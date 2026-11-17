"""Content-based candidates: content neighbours of the user's strongest tracks.

The seeds are the profile's `seed_tracks` (strongest long-term) and `recent_tracks` (strongest
short-term). A candidate's score is its best similarity to any seed, and the seed it came from is
kept, so the explanation can name it ("Similar to <track> you play often").
"""

from collections.abc import Hashable, Sequence
from typing import TypeVar

from app.domains.recommendations.candidate_generation.base import CandidateList, Source

K = TypeVar("K", bound=Hashable)


def content_candidates(
    seed_neighbours: Sequence[tuple[K, Sequence[tuple[K, float]]]],
    *,
    exclude: frozenset[K] | set[K],
    limit: int,
    model_version: str | None,
) -> tuple[CandidateList[K], dict[K, K]]:
    """`seed_neighbours`: (seed, its neighbours best first). Returns the list and, per item, the
    seed it is most similar to. Ties keep the first occurrence (seed order, then rank)."""
    if not seed_neighbours:
        return CandidateList.skipped(Source.CONTENT, "no seed tracks"), {}
    best: dict[K, float] = {}
    best_seed: dict[K, K] = {}
    seeds = {seed for seed, _ in seed_neighbours}
    for seed, neighbours in seed_neighbours:
        for item, similarity in neighbours:
            if item in exclude or item in seeds:
                continue
            if item not in best or similarity > best[item]:
                best[item] = similarity
                best_seed[item] = seed
    # Python's sort is stable, so equal scores keep first-occurrence order.
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:limit]
    return (
        CandidateList.build(Source.CONTENT, ranked, model_version),
        {item: best_seed[item] for item, _ in ranked},
    )
