"""Removes candidates a user must not get, and counts why.

Rules, in order:
- ineligible:      not servable (e.g. outside the active models' catalogue);
- heard:           the user already interacted with the track (recommendations are new tracks);
- disliked:        explicitly disliked (also covered by `heard`, counted separately for clarity);
- excluded_artist: the user excluded the artist in their preferences;
- heard_song:      another version of a song the user already heard (ranking.song_key).

Soft negatives (artists the user tends to skip) are not filtered here: ranking demotes them.
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from app.domains.recommendations.candidate_generation.candidate_merger import CandidateSet

K = TypeVar("K", bound=Hashable)
A = TypeVar("A", bound=Hashable)

FILTER_REASONS = ("ineligible", "heard", "disliked", "excluded_artist", "heard_song")


@dataclass(frozen=True)
class CandidateFilter(Generic[K, A]):
    heard: frozenset[K] = field(default_factory=frozenset)
    disliked: frozenset[K] = field(default_factory=frozenset)
    excluded_artists: frozenset[A] = field(default_factory=frozenset)
    heard_song_keys: frozenset[str] = field(default_factory=frozenset)

    def apply(
        self,
        candidates: CandidateSet[K],
        *,
        artists: Sequence[A],
        song_keys: Sequence[str | None],
        eligible: Sequence[bool] | None = None,
    ) -> tuple[CandidateSet[K], dict[str, int]]:
        """`artists`, `song_keys` and `eligible` are aligned with `candidates.items`."""
        n = len(candidates)
        if (
            len(artists) != n
            or len(song_keys) != n
            or (eligible is not None and len(eligible) != n)
        ):
            raise ValueError("artists, song_keys and eligible must be aligned with the candidates")
        removed = dict.fromkeys(FILTER_REASONS, 0)
        keep: list[int] = []
        for row, item in enumerate(candidates.items):
            if eligible is not None and not eligible[row]:
                removed["ineligible"] += 1
            elif item in self.disliked:
                removed["disliked"] += 1
            elif item in self.heard:
                removed["heard"] += 1
            elif artists[row] in self.excluded_artists:
                removed["excluded_artist"] += 1
            elif song_keys[row] is not None and song_keys[row] in self.heard_song_keys:
                removed["heard_song"] += 1
            else:
                keep.append(row)
        return candidates.subset(keep), removed
