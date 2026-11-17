"""Diversity-aware composition of the final list (spec §8.1 E, ADR-016).

Greedy selection from the best-ranked candidates. At each step the chosen candidate maximizes
Maximal Marginal Relevance,

    MMR(t) = lambda * relevance(t) - (1 - lambda) * max_{s selected} similarity(t, s),

(relevance min-max scaled within the pool, similarity = content cosine) among candidates that
respect the policy's constraints:

- hard:  one version per song, and the artist cap (a separate, larger cap for the seed artist of
         an artist radio);
- soft:  maximum share of one primary genre, maximum share of popularity-head tracks. Soft caps
         are relaxed only when no candidate satisfies them, so lists are not cut short;
- composition: with a discovery target (exploration mode), each step draws from whichever group
         (familiar artist / new artist) is furthest below its target share; if that group is
         empty, from the other.

Rules are category-specific (POLICIES): a "for you" mix caps every artist, an artist radio wants
several tracks of its artist, and the Milestone 2 endpoints keep their documented behaviour.
"""

import math
from collections import Counter
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import numpy.typing as npt

from app.domains.recommendations.hybrid_ranking import normalized_relevance

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class DiversityPolicy:
    category: str
    # 1.0 = rank by relevance only.
    mmr_lambda: float = 1.0
    max_per_artist: int | None = 2
    # Artist radio: share of the list reserved at most for the seed artist.
    seed_artist_share: float | None = None
    max_genre_share: float | None = None
    max_head_share: float | None = None
    # Apply the user's discovery target (exploration mode).
    discovery: bool = False
    # Only the best `pool` candidates by relevance are considered.
    pool: int = 150

    def __post_init__(self) -> None:
        if not 0.0 <= self.mmr_lambda <= 1.0:
            raise ValueError("mmr_lambda must be in [0, 1]")

    def params(self) -> dict[str, Any]:
        return asdict(self)

    def with_overrides(self, **overrides: Any) -> "DiversityPolicy":
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})


POLICIES: Mapping[str, DiversityPolicy] = {
    # Personalized mix: diverse, capped artists, the user's familiar/discovery balance.
    "for_you": DiversityPolicy("for_you", mmr_lambda=0.8, max_per_artist=2, discovery=True),
    # New artists only (discovery target 1.0), one track each.
    "discovery": DiversityPolicy("discovery", mmr_lambda=0.7, max_per_artist=1, discovery=True),
    # Artist radio: the seed artist may fill up to 40% of the list; other artists two tracks.
    "artist_radio": DiversityPolicy(
        "artist_radio", mmr_lambda=0.85, max_per_artist=2, seed_artist_share=0.4
    ),
    # Milestone 2 endpoints (documented; they keep using ranking.rerank).
    "similar_tracks": DiversityPolicy("similar_tracks", mmr_lambda=1.0, max_per_artist=2),
    "genre": DiversityPolicy("genre", mmr_lambda=1.0, max_per_artist=2),
}


def compose(
    relevance: FloatArray,
    *,
    limit: int,
    policy: DiversityPolicy,
    artists: Sequence[Hashable],
    song_keys: Sequence[str | None] | None = None,
    embeddings: npt.NDArray[np.floating[Any]] | None = None,
    discovery: BoolArray | None = None,
    discovery_target: float | None = None,
    primary_genres: Sequence[str | None] | None = None,
    head: BoolArray | None = None,
    seed_artist: Hashable | None = None,
) -> list[int]:
    """Indices (into the inputs) of the selected candidates, in list order."""
    n = len(relevance)
    if n == 0 or limit <= 0:
        return []
    order = np.argsort(-np.asarray(relevance, dtype=np.float64), kind="stable")[: policy.pool]
    rel = normalized_relevance(np.asarray(relevance, dtype=np.float64)[order])
    size = len(order)
    lam = policy.mmr_lambda

    vectors: npt.NDArray[np.float64] | None = None
    if embeddings is not None and lam < 1.0:
        vectors = np.asarray(embeddings, dtype=np.float64)[order]
    max_sim = np.zeros(size)

    artist_code = _codes([artists[i] for i in order])
    key_code = _codes([song_keys[i] for i in order]) if song_keys is not None else None
    genre_code = _codes([primary_genres[i] for i in order]) if primary_genres is not None else None
    pool_head = np.asarray(head, dtype=np.bool_)[order] if head is not None else None
    pool_discovery = (
        np.asarray(discovery, dtype=np.bool_)[order]
        if discovery is not None and policy.discovery and discovery_target is not None
        else None
    )

    seed_code: int | None = None
    if seed_artist is not None and policy.seed_artist_share is not None:
        matches = [artists[i] == seed_artist for i in order]
        seed_code = int(artist_code[matches.index(True)]) if any(matches) else None
    seed_cap = (
        math.ceil(policy.seed_artist_share * limit)
        if policy.seed_artist_share is not None
        else None
    )
    genre_cap = math.ceil(policy.max_genre_share * limit) if policy.max_genre_share else None
    head_cap = math.ceil(policy.max_head_share * limit) if policy.max_head_share else None

    # Hard: picked, artist at its cap, song already in the list. Soft: genre or head share full.
    hard_blocked = np.zeros(size, dtype=np.bool_)
    soft_blocked = np.zeros(size, dtype=np.bool_)
    per_artist: Counter[int] = Counter()
    per_genre: Counter[int] = Counter()
    head_count = 0
    selected: list[int] = []
    discovered = 0

    while len(selected) < limit:
        hard = ~hard_blocked
        if not hard.any():
            break
        soft = hard & ~soft_blocked
        eligible = soft if soft.any() else hard

        if pool_discovery is not None and discovery_target is not None:
            steps = len(selected) + 1
            want_new = discovery_target * steps - discovered
            want_known = (1.0 - discovery_target) * steps - (len(selected) - discovered)
            if want_new != want_known:
                group = pool_discovery if want_new > want_known else ~pool_discovery
                if (eligible & group).any():
                    eligible = eligible & group

        mmr = lam * rel - (1.0 - lam) * max_sim
        pick = int(np.argmax(np.where(eligible, mmr, -np.inf)))
        selected.append(pick)
        hard_blocked[pick] = True

        artist = int(artist_code[pick])
        per_artist[artist] += 1
        cap = seed_cap if seed_code is not None and artist == seed_code else policy.max_per_artist
        if cap is not None and per_artist[artist] >= cap:
            hard_blocked |= artist_code == artist
        if key_code is not None and key_code[pick] >= 0:
            hard_blocked |= key_code == key_code[pick]
        if genre_code is not None and genre_cap is not None and genre_code[pick] >= 0:
            genre = int(genre_code[pick])
            per_genre[genre] += 1
            if per_genre[genre] >= genre_cap:
                soft_blocked |= genre_code == genre
        if pool_head is not None and head_cap is not None and pool_head[pick]:
            head_count += 1
            if head_count >= head_cap:
                soft_blocked |= pool_head
        if pool_discovery is not None and pool_discovery[pick]:
            discovered += 1
        if vectors is not None:
            max_sim = np.maximum(max_sim, vectors @ vectors[pick])

    return [int(order[i]) for i in selected]


def _codes(values: Sequence[Hashable | None]) -> npt.NDArray[np.int64]:
    """Integer code per distinct value (first appearance order); None -> -1."""
    index: dict[Hashable, int] = {}
    return np.array(
        [-1 if v is None else index.setdefault(v, len(index)) for v in values], dtype=np.int64
    )
