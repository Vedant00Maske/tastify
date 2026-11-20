"""Ranking rules shared by the API and the offline evaluation (ADR-015).

`soniqueo_ml.evaluation` calls these same functions, so the offline metrics in
docs/reports/model-benchmark.md measure exactly what the API serves.
"""

import re
from collections import Counter
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from app.domains.catalogue.normalization import matching_key

K = TypeVar("K", bound=Hashable)

# How strongly a genre tag counts depending on where it was attached (track_genres.level, or the
# artist's own genres). Recording tags describe the track itself; artist tags are only a prior.
LEVEL_WEIGHTS: Mapping[str, float] = {"recording": 1.0, "album": 0.8, "artist": 0.6}

# Genre tags are user votes. A tag's weight is its votes / (all votes at that level + PRIOR), so a
# single vote counts for 1/3 rather than 100%, while a broad consensus is barely changed.
GENRE_PRIOR_VOTES = 2.0

# Nearest neighbours fetched from the vector index before re-ranking.
CANDIDATE_POOL = 200
DEFAULT_MAX_PER_ARTIST = 2

# Artist recommendations: the most similar artists, and each one's most popular tracks.
SIMILAR_ARTISTS_POOL = 30
TRACKS_PER_SIMILAR_ARTIST = 2

# Genre recommendations: a track belongs to a genre when its strongest level-weighted tag for that
# genre reaches MIN_GENRE_AFFINITY. Ranking mixes popularity with how central the genre is: it is
# `rerank` with similarity = affinity and beta = GENRE_POPULARITY_WEIGHT.
# 0.25 means the genre carries a real share of the track's (smoothed) votes, so a popular track with
# a stray tag is not listed under that genre.
MIN_GENRE_AFFINITY = 0.25
GENRE_POPULARITY_WEIGHT = 0.7


def blended_score(similarity: float, popularity: float, beta: float) -> float:
    """Content similarity with a popularity prior. beta=0 is pure similarity."""
    return (1.0 - beta) * similarity + beta * popularity


def genre_score(affinity: float, popularity: float) -> float:
    return blended_score(affinity, popularity, GENRE_POPULARITY_WEIGHT)


def smoothed_tag_weight(
    votes: float, total_votes: float, prior: float = GENRE_PRIOR_VOTES
) -> float:
    """Share of the votes, shrunk towards zero when there are few votes."""
    return votes / (total_votes + prior)


# Trailing "(radio edit)", "[Live]", " - Remastered 2011" and similar version notes.
_VERSION_SUFFIX = re.compile(r"\s*(?:[(\[][^()\[\]]*[)\]]|\s-\s.*)\s*$")


def song_key(artist: Hashable, title: str) -> str:
    """Identifies a song across its versions (edits, remasters, live takes) for one artist.

    The catalogue keeps versions as separate recordings (ADR-014); recommendation lists show only
    the best-ranked version of each song.
    """
    base = title
    while True:
        stripped = _VERSION_SUFFIX.sub("", base)
        if stripped == base or not stripped.strip():
            break
        base = stripped
    return f"{artist}|{matching_key(base)}"


def genre_affinity(level_weights: Iterable[tuple[str, float]]) -> float:
    """Strongest level-weighted tag weight among (level, weight) pairs for one genre."""
    return max((LEVEL_WEIGHTS[level] * weight for level, weight in level_weights), default=0.0)


@dataclass(frozen=True, slots=True)
class Candidate(Generic[K]):
    item: K
    similarity: float
    popularity: float
    artist: Hashable
    # Candidates with the same key are the same song (see song_key); only the best one is kept.
    dedup_key: str | None = None


@dataclass(frozen=True, slots=True)
class Ranked(Generic[K]):
    candidate: Candidate[K]
    score: float

    @property
    def item(self) -> K:
        return self.candidate.item


def rerank(
    candidates: Iterable[Candidate[K]],
    *,
    beta: float,
    limit: int,
    max_per_artist: int | None = DEFAULT_MAX_PER_ARTIST,
    exclude_dedup_keys: Iterable[str] = (),
) -> list[Ranked[K]]:
    """Blend, sort, then apply the artist cap and duplicate removal.

    Ties keep the input order (Python's sort is stable), so results are deterministic.
    """
    scored = sorted(
        (Ranked(c, blended_score(c.similarity, c.popularity, beta)) for c in candidates),
        key=lambda ranked: -ranked.score,
    )
    seen_keys = set(exclude_dedup_keys)
    per_artist: Counter[Hashable] = Counter()
    selected: list[Ranked[K]] = []
    for ranked in scored:
        if len(selected) == limit:
            break
        candidate = ranked.candidate
        if candidate.dedup_key is not None and candidate.dedup_key in seen_keys:
            continue
        if max_per_artist is not None and per_artist[candidate.artist] >= max_per_artist:
            continue
        if candidate.dedup_key is not None:
            seen_keys.add(candidate.dedup_key)
        per_artist[candidate.artist] += 1
        selected.append(ranked)
    return selected
