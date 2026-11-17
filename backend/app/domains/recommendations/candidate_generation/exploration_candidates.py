"""Exploration candidates: tracks by artists the user does not know yet, chosen for being close
to the user's taste (artist embeddings nearest to the profile) and listened to by others (each
new artist's most popular tracks). Deterministic: no random sampling, so a given profile and model
always yield the same candidates.
"""

from collections.abc import Hashable, Mapping, Sequence
from typing import TypeVar

from app.domains.recommendations.candidate_generation.base import CandidateList, Source

K = TypeVar("K", bound=Hashable)
A = TypeVar("A", bound=Hashable)


def exploration_candidates(
    similar_artists: Sequence[tuple[A, float]] | None,
    top_tracks: Mapping[A, Sequence[K]],
    *,
    known_artists: frozenset[A] | set[A],
    avoided_artists: frozenset[A] | set[A],
    exclude: frozenset[K] | set[K],
    tracks_per_artist: int,
    limit: int,
    model_version: str | None,
) -> tuple[CandidateList[K], dict[K, A]]:
    """`similar_artists`: artists nearest to the profile, best first (None without a profile).
    Returns the list and, per track, its artist (for the explanation)."""
    if similar_artists is None:
        return CandidateList.skipped(Source.EXPLORATION, "no taste-profile embedding"), {}
    ranked: list[tuple[K, float]] = []
    artist_of: dict[K, A] = {}
    for artist, similarity in similar_artists:
        if artist in known_artists or artist in avoided_artists:
            continue
        taken = 0
        for track in top_tracks.get(artist, ()):
            if taken == tracks_per_artist or len(ranked) == limit:
                break
            if track in exclude or track in artist_of:
                continue
            ranked.append((track, similarity))
            artist_of[track] = artist
            taken += 1
        if len(ranked) == limit:
            break
    return CandidateList.build(Source.EXPLORATION, ranked, model_version), artist_of
