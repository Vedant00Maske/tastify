"""Listening context (Milestone 6; ADR-019, docs/reports/context-benchmark.md).

Two context signals were evaluated on unseen days of the research listens:

- **Session** (the user's listening in the previous hour): predicts the next listen's genres
  10.5% better than the overall profile, while the same hour one day earlier does worse. It is
  used by default (`DEFAULT_SESSION_WEIGHT`), with the validated shrinkage `SESSION_SHRINKAGE`.
- **Time of day** (dayparts of local time): no better than shuffled dayparts. It stays off by
  default (`DEFAULT_DAYPART_WEIGHT` = 0) and can only be switched on by an experiment.

In both cases a context distribution over genres (the session's, or the daypart's) is shrunk
toward the user's overall distribution, so little evidence says nothing new. A candidate's
*context fit* is the expected log-ratio of the context distribution to the overall one over the
track's genres: positive when its genres are what the user plays more of right now, negative
when less, zero without enough evidence. It nudges the ranking by a small weight; it never
decides it alone.

Pure functions only: the API applies them to a user's events, and the offline evaluation
(`tastify_ml.evaluation.context_experiment`) to research listens.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, tzinfo

DAYPARTS = ("night", "morning", "afternoon", "evening")
POSITIVE_EVENTS = frozenset({"play", "complete", "replay", "like", "save", "playlist_add"})
SHRINKAGE = 100.0  # pseudo-events pulling a daypart toward the overall (validated: K=100)
MIN_DAYPART_EVENTS = 15  # below this the daypart is not used at all
EPSILON = 1e-4
MAX_FIT = 1.0

SESSION_WINDOW_MINUTES = 60
SESSION_SHRINKAGE = 2.0  # validated: the session is trusted quickly
MIN_SESSION_EVENTS = 2
DEFAULT_SESSION_WEIGHT = 0.1  # ranking nudge; the online experiment measures its effect
DEFAULT_DAYPART_WEIGHT = 0.0  # no offline evidence for time of day


def daypart(hour: int) -> str:
    """night 0-5, morning 6-11, afternoon 12-17, evening 18-23 (local time)."""
    return DAYPARTS[(hour % 24) // 6]


def daypart_of(moment: datetime, zone: tzinfo) -> str:
    return daypart(moment.astimezone(zone).hour)


def normalized(weights: Mapping[str, float]) -> dict[str, float]:
    total = sum(v for v in weights.values() if v > 0)
    if total <= 0:
        return {}
    return {g: v / total for g, v in weights.items() if v > 0}


@dataclass
class ContextProfile:
    overall: dict[str, float] = field(default_factory=dict)
    dayparts: dict[str, dict[str, float]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def evidence(self, part: str) -> int:
        return self.counts.get(part, 0)


def build_context_profile(
    listens: Iterable[tuple[str, Mapping[str, float]]],
) -> ContextProfile:
    """`listens`: (daypart, the track's genre weights) for each positive event."""
    overall: dict[str, float] = defaultdict(float)
    per_part: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: dict[str, int] = defaultdict(int)
    for part, genres in listens:
        share = normalized(genres)
        if not share:
            continue
        counts[part] += 1
        for genre, value in share.items():
            overall[genre] += value
            per_part[part][genre] += value
    return ContextProfile(
        overall=normalized(overall),
        dayparts={part: dict(values) for part, values in per_part.items()},
        counts=dict(counts),
    )


def daypart_distribution(
    profile: ContextProfile, part: str, shrinkage: float = SHRINKAGE
) -> dict[str, float]:
    """The daypart's genre distribution, shrunk toward the overall one."""
    n = profile.evidence(part)
    raw = profile.dayparts.get(part, {})
    genres = set(profile.overall) | set(raw)
    return {
        g: (raw.get(g, 0.0) + shrinkage * profile.overall.get(g, 0.0)) / (n + shrinkage)
        for g in genres
    }


def context_fit(
    profile: ContextProfile,
    part: str,
    track_genres: Mapping[str, float],
    *,
    shrinkage: float = SHRINKAGE,
    min_events: int = MIN_DAYPART_EVENTS,
) -> float:
    """Expected log(p_daypart / p_overall) over the track's genres, clipped to ±MAX_FIT."""
    if profile.evidence(part) < min_events or not profile.overall:
        return 0.0
    share = normalized(track_genres)
    if not share:
        return 0.0
    in_part = daypart_distribution(profile, part, shrinkage)
    fit = sum(
        weight
        * math.log(
            (in_part.get(genre, 0.0) + EPSILON) / (profile.overall.get(genre, 0.0) + EPSILON)
        )
        for genre, weight in share.items()
    )
    return max(-MAX_FIT, min(MAX_FIT, fit))


def strongest_daypart_genre(profile: ContextProfile, part: str) -> str | None:
    """The genre most over-represented in this daypart (for explanations), if any."""
    if profile.evidence(part) < MIN_DAYPART_EVENTS:
        return None
    in_part = daypart_distribution(profile, part)
    best = max(
        in_part,
        key=lambda g: in_part[g] / (profile.overall.get(g, 0.0) + EPSILON),
        default=None,
    )
    return best


# --- session ----------------------------------------------------------------------------------


@dataclass
class SessionContext:
    """Genre totals of the user's positive listening in the previous hour."""

    genres: dict[str, float] = field(default_factory=dict)
    events: int = 0


def build_session(listens: Iterable[Mapping[str, float]]) -> SessionContext:
    totals: dict[str, float] = defaultdict(float)
    events = 0
    for genres in listens:
        share = normalized(genres)
        if not share:
            continue
        events += 1
        for genre, value in share.items():
            totals[genre] += value
    return SessionContext(genres=dict(totals), events=events)


def session_fit(
    session: SessionContext,
    overall: Mapping[str, float],
    track_genres: Mapping[str, float],
    *,
    shrinkage: float = SESSION_SHRINKAGE,
    min_events: int = MIN_SESSION_EVENTS,
) -> float:
    """Expected log(p_session / p_overall) over the track's genres, clipped to ±MAX_FIT; the
    session distribution is shrunk toward `overall` (the user's genre affinity, normalized)."""
    if session.events < min_events or not overall:
        return 0.0
    share = normalized(track_genres)
    if not share:
        return 0.0
    fit = 0.0
    for genre, weight in share.items():
        prior = overall.get(genre, 0.0)
        in_session = (session.genres.get(genre, 0.0) + shrinkage * prior) / (
            session.events + shrinkage
        )
        fit += weight * math.log((in_session + EPSILON) / (prior + EPSILON))
    return max(-MAX_FIT, min(MAX_FIT, fit))
