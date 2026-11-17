"""Taste analytics for the "Your taste" page (Milestone 4).

Every number comes from the user's recorded events and their taste profile; anything that cannot
be computed reliably is left out (empty list or null) rather than estimated.

- overview:   a sentence built from the strongest genres and artists, and recent changes;
- trends:     weekly listening (playbacks, distinct tracks, first-time artists) for 12 weeks;
- evolution:  genres whose share of the last 14 days differs most from the time before (only with
              enough plays on both sides);
- discovery:  first-time artists and genres in the last 30 days, saved or liked tracks, the
              exploration preference and the familiar/discovery target.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import Artist, Track
from app.domains.recommendations.repository import RecommendationRepository
from app.domains.users.events import PLAYBACK_EVENTS, EventType
from app.domains.users.models import UserInteraction
from app.domains.users.profile import TasteProfile
from app.domains.users.service import TasteProfileService

TREND_WEEKS = 12
RECENT_DAYS = 14
DISCOVERY_DAYS = 30
MIN_EVOLUTION_PLAYS = 10
MIN_SHIFT = 0.02
PLAYBACK = frozenset(e.value for e in PLAYBACK_EVENTS)


class ArtistStat(BaseModel):
    artist_id: uuid.UUID
    name: str
    score: float
    playbacks: int


class GenreStat(BaseModel):
    genre: str
    score: float


class TrendPoint(BaseModel):
    week_start: datetime
    playbacks: int
    distinct_tracks: int
    new_artists: int


class GenreShift(BaseModel):
    genre: str
    recent_share: float
    earlier_share: float
    change: float


class DiscoveryStats(BaseModel):
    new_artists_30d: int
    new_genres_30d: int
    saved_tracks: int
    liked_tracks: int
    exploration_preference: float
    discovery_target: float


class TasteAnalyticsOut(BaseModel):
    overview: str | None
    events: int
    genres: list[GenreStat]
    artists: list[ArtistStat]
    trends: list[TrendPoint]
    emerging: list[GenreShift]
    fading: list[GenreShift]
    discovery: DiscoveryStats | None


@dataclass(frozen=True)
class EventRow:
    track_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    artist_id: uuid.UUID


@dataclass
class Week:
    playbacks: int = 0
    tracks: set[uuid.UUID] = field(default_factory=set)
    new_artists: int = 0


def week_start(moment: datetime) -> datetime:
    day = moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def weekly_trends(rows: Sequence[EventRow], now: datetime) -> list[TrendPoint]:
    weeks: defaultdict[datetime, Week] = defaultdict(Week)
    first_artist: dict[uuid.UUID, datetime] = {}
    for row in rows:
        first_artist.setdefault(row.artist_id, row.occurred_at)
        if row.event_type in PLAYBACK:
            week = weeks[week_start(row.occurred_at)]
            week.playbacks += 1
            week.tracks.add(row.track_id)
    for first in first_artist.values():
        weeks[week_start(first)].new_artists += 1
    start = week_start(now) - timedelta(weeks=TREND_WEEKS - 1)
    points = []
    for i in range(TREND_WEEKS):
        moment = start + timedelta(weeks=i)
        week = weeks.get(moment, Week())
        points.append(
            TrendPoint(
                week_start=moment,
                playbacks=week.playbacks,
                distinct_tracks=len(week.tracks),
                new_artists=week.new_artists,
            )
        )
    return points


def genre_shares(
    plays: Counter[uuid.UUID], profiles: dict[uuid.UUID, dict[str, float]]
) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for track_id, count in plays.items():
        for genre, weight in profiles.get(track_id, {}).items():
            totals[genre] += count * weight
    mass = sum(totals.values())
    return {g: v / mass for g, v in totals.items()} if mass else {}


def overview_text(
    genres: Sequence[GenreStat], artists: Sequence[ArtistStat], emerging: Sequence[GenreShift]
) -> str | None:
    if not genres and not artists:
        return None
    parts = []
    if genres:
        parts.append(f"Your listening centres on {_join([g.genre for g in genres[:3]])}")
    if artists:
        parts.append(f"with {_join([a.name for a in artists[:2]])} at its heart")
    text = ", ".join(parts) + "."
    if emerging:
        recent = _join([e.genre for e in emerging[:2]])
        text += f" Lately you are spending more time with {recent}."
    return text


class TasteAnalytics:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.profiles = TasteProfileService(session)
        self.models = RecommendationRepository(session)

    async def _rows(self, user_id: uuid.UUID) -> list[EventRow]:
        result = await self.session.execute(
            select(
                UserInteraction.track_id,
                UserInteraction.event_type,
                UserInteraction.occurred_at,
                Track.artist_id,
            )
            .join(Track, Track.id == UserInteraction.track_id)
            .where(UserInteraction.user_id == user_id)
            .order_by(UserInteraction.occurred_at, UserInteraction.id)
        )
        return [EventRow(r[0], r[1], r[2], r[3]) for r in result]

    async def summarize(self, user_id: uuid.UUID) -> TasteAnalyticsOut:
        context = await self.profiles.current(user_id)
        await self.session.commit()
        profile = context.profile
        rows = await self._rows(user_id)
        genres = [GenreStat(genre=g, score=s) for g, s in list(profile.genre_affinity.items())[:10]]
        if not rows:
            return TasteAnalyticsOut(
                overview=None,
                events=0,
                genres=genres,
                artists=[],
                trends=[],
                emerging=[],
                fading=[],
                discovery=None,
            )
        now = datetime.now(UTC)
        plays: Counter[uuid.UUID] = Counter(r.artist_id for r in rows if r.event_type in PLAYBACK)
        top = list(profile.artist_affinity.items())[:10]
        names = await self._artist_names([a for a, _ in top])
        artists = [
            ArtistStat(artist_id=a, name=names.get(a, ""), score=s, playbacks=plays.get(a, 0))
            for a, s in top
        ]
        emerging, fading = await self._evolution(rows, now)
        return TasteAnalyticsOut(
            overview=overview_text(genres, artists, emerging),
            events=len(rows),
            genres=genres,
            artists=artists,
            trends=weekly_trends(rows, now),
            emerging=emerging,
            fading=fading,
            discovery=await self._discovery(rows, now, profile),
        )

    async def _artist_names(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(Artist.id, Artist.name).where(Artist.id.in_(ids))
        )
        return {row[0]: row[1] for row in result}

    async def _evolution(
        self, rows: Sequence[EventRow], now: datetime
    ) -> tuple[list[GenreShift], list[GenreShift]]:
        split = now - timedelta(days=RECENT_DAYS)
        recent: Counter[uuid.UUID] = Counter()
        earlier: Counter[uuid.UUID] = Counter()
        for row in rows:
            if row.event_type in PLAYBACK:
                (recent if row.occurred_at >= split else earlier)[row.track_id] += 1
        if min(sum(recent.values()), sum(earlier.values())) < MIN_EVOLUTION_PLAYS:
            return [], []
        profiles = await self.models.genre_profiles(list({*recent, *earlier})[:1000])
        now_share, before_share = genre_shares(recent, profiles), genre_shares(earlier, profiles)
        shifts = [
            GenreShift(
                genre=g,
                recent_share=round(now_share.get(g, 0.0), 4),
                earlier_share=round(before_share.get(g, 0.0), 4),
                change=round(now_share.get(g, 0.0) - before_share.get(g, 0.0), 4),
            )
            for g in sorted({*now_share, *before_share})
        ]
        emerging = sorted((s for s in shifts if s.change >= MIN_SHIFT), key=lambda s: -s.change)
        fading = sorted((s for s in shifts if s.change <= -MIN_SHIFT), key=lambda s: s.change)
        return emerging[:5], fading[:5]

    async def _discovery(
        self, rows: Sequence[EventRow], now: datetime, profile: TasteProfile[Any, Any]
    ) -> DiscoveryStats:
        since = now - timedelta(days=DISCOVERY_DAYS)
        first_artist: dict[uuid.UUID, datetime] = {}
        first_track: dict[uuid.UUID, datetime] = {}
        saved: set[uuid.UUID] = set()
        liked: set[uuid.UUID] = set()
        for row in rows:
            first_artist.setdefault(row.artist_id, row.occurred_at)
            first_track.setdefault(row.track_id, row.occurred_at)
            if row.event_type == EventType.SAVE.value:
                saved.add(row.track_id)
            elif row.event_type == EventType.UNSAVE.value:
                saved.discard(row.track_id)
            elif row.event_type == EventType.LIKE.value:
                liked.add(row.track_id)
            elif row.event_type in (EventType.UNLIKE.value, EventType.DISLIKE.value):
                liked.discard(row.track_id)
        old_tracks = [t for t, first in first_track.items() if first < since][:1000]
        new_tracks = [t for t, first in first_track.items() if first >= since][:1000]
        profiles = await self.models.genre_profiles([*old_tracks, *new_tracks])
        old_genres = {g for t in old_tracks for g in profiles.get(t, {})}
        new_genres = {g for t in new_tracks for g in profiles.get(t, {})} - old_genres
        return DiscoveryStats(
            new_artists_30d=sum(1 for first in first_artist.values() if first >= since),
            new_genres_30d=len(new_genres),
            saved_tracks=len(saved),
            liked_tracks=len(liked),
            exploration_preference=profile.exploration_preference,
            discovery_target=profile.discovery_target(),
        )
