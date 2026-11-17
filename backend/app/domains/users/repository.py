"""Data access for users, interaction events, preferences and taste profiles."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import Artist, Genre, Track
from app.domains.users.models import (
    User,
    UserArtistPreference,
    UserGenrePreference,
    UserInteraction,
    UserPreference,
    UserTasteProfile,
)

# Events read to build a profile: the most recent ones (older ones have decayed the most).
MAX_PROFILE_EVENTS = 10_000


@dataclass(frozen=True)
class EventRows:
    """A user's events, oldest first (parallel lists, as aggregate_events takes them)."""

    track_ids: list[uuid.UUID]
    event_types: list[str]
    occurred_at: list[datetime]
    positions_ms: list[int | None]

    def __len__(self) -> int:
        return len(self.track_ids)


@dataclass(frozen=True)
class DeclaredRows:
    preference: UserPreference | None
    artists: list[tuple[uuid.UUID, str, str]]  # (artist_id, name, preference)
    genres: list[tuple[uuid.UUID, str, str]]  # (genre_id, name, preference)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- users -------------------------------------------------------------------------------

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        user = await self.session.get(User, user_id)
        return user if user is not None and user.status == "active" else None

    # --- events ------------------------------------------------------------------------------

    async def existing_tracks(self, track_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
        if not track_ids:
            return set()
        rows = await self.session.scalars(select(Track.id).where(Track.id.in_(set(track_ids))))
        return set(rows)

    async def insert_events(self, rows: Sequence[dict[str, Any]]) -> int:
        """Insert events; rows whose (user, client_event_id) already exists are skipped.
        Returns how many were inserted."""
        if not rows:
            return 0
        statement = (
            insert(UserInteraction)
            .values(list(rows))
            .on_conflict_do_nothing(constraint="uq_user_interactions_client_event")
            .returning(UserInteraction.id)
        )
        inserted = (await self.session.scalars(statement)).all()
        return len(inserted)

    async def events(self, user_id: uuid.UUID, limit: int = MAX_PROFILE_EVENTS) -> EventRows:
        recent = (
            select(UserInteraction)
            .where(UserInteraction.user_id == user_id)
            .order_by(
                UserInteraction.occurred_at.desc(),
                UserInteraction.received_at.desc(),
                UserInteraction.id.desc(),
            )
            .limit(limit)
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(
                    recent.c.track_id,
                    recent.c.event_type,
                    recent.c.occurred_at,
                    recent.c.position_ms,
                ).order_by(recent.c.occurred_at, recent.c.received_at, recent.c.id)
            )
        ).all()
        return EventRows(
            [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows]
        )

    async def event_count(self, user_id: uuid.UUID) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(UserInteraction)
            .where(UserInteraction.user_id == user_id)
        )
        return int(count or 0)

    async def last_received(self, user_id: uuid.UUID) -> datetime | None:
        return await self.session.scalar(
            select(func.max(UserInteraction.received_at)).where(UserInteraction.user_id == user_id)
        )

    async def history(
        self,
        user_id: uuid.UUID,
        limit: int,
        before: datetime | None,
        event_types: Sequence[str] = (),
    ) -> list[UserInteraction]:
        statement = select(UserInteraction).where(UserInteraction.user_id == user_id)
        if event_types:
            statement = statement.where(UserInteraction.event_type.in_(list(event_types)))
        if before is not None:
            statement = statement.where(UserInteraction.occurred_at < before)
        rows = await self.session.scalars(
            statement.order_by(UserInteraction.occurred_at.desc(), UserInteraction.id.desc()).limit(
                limit
            )
        )
        return list(rows)

    # --- preferences -------------------------------------------------------------------------

    async def declared(self, user_id: uuid.UUID) -> DeclaredRows:
        preference = await self.session.get(UserPreference, user_id)
        artists = await self.session.execute(
            select(UserArtistPreference.artist_id, Artist.name, UserArtistPreference.preference)
            .join(Artist, Artist.id == UserArtistPreference.artist_id)
            .where(UserArtistPreference.user_id == user_id)
            .order_by(UserArtistPreference.created_at, Artist.name)
        )
        genres = await self.session.execute(
            select(UserGenrePreference.genre_id, Genre.name, UserGenrePreference.preference)
            .join(Genre, Genre.id == UserGenrePreference.genre_id)
            .where(UserGenrePreference.user_id == user_id)
            .order_by(UserGenrePreference.created_at, Genre.name)
        )
        return DeclaredRows(
            preference,
            [(a, n, p) for a, n, p in artists],
            [(g, n, p) for g, n, p in genres],
        )

    async def replace_preferences(
        self,
        user_id: uuid.UUID,
        *,
        exploration_mode: str | None,
        personalization_enabled: bool,
        preferred_moods: Sequence[str],
        artists: Sequence[tuple[uuid.UUID, str]],
        genres: Sequence[tuple[uuid.UUID, str]],
    ) -> None:
        await self.session.execute(
            insert(UserPreference)
            .values(
                user_id=user_id,
                exploration_mode=exploration_mode,
                personalization_enabled=personalization_enabled,
                preferred_moods=list(preferred_moods),
            )
            .on_conflict_do_update(
                index_elements=[UserPreference.user_id],
                set_={
                    "exploration_mode": exploration_mode,
                    "personalization_enabled": personalization_enabled,
                    "preferred_moods": list(preferred_moods),
                    "updated_at": func.now(),
                },
            )
        )
        await self.session.execute(
            delete(UserArtistPreference).where(UserArtistPreference.user_id == user_id)
        )
        await self.session.execute(
            delete(UserGenrePreference).where(UserGenrePreference.user_id == user_id)
        )
        if artists:
            await self.session.execute(
                insert(UserArtistPreference),
                [{"user_id": user_id, "artist_id": a, "preference": p} for a, p in artists],
            )
        if genres:
            await self.session.execute(
                insert(UserGenrePreference),
                [{"user_id": user_id, "genre_id": g, "preference": p} for g, p in genres],
            )

    async def existing_artists(self, artist_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
        if not artist_ids:
            return set()
        return set(await self.session.scalars(select(Artist.id).where(Artist.id.in_(artist_ids))))

    async def genres_by_name(self, names: Sequence[str]) -> dict[str, Genre]:
        """Case-insensitive lookup; keys are the lower-cased requested names."""
        if not names:
            return {}
        wanted = {n.lower() for n in names}
        rows = await self.session.scalars(select(Genre).where(func.lower(Genre.name).in_(wanted)))
        return {g.name.lower(): g for g in rows}

    # --- profiles and catalogue facts ----------------------------------------------------------

    async def profile(self, user_id: uuid.UUID) -> UserTasteProfile | None:
        return await self.session.get(UserTasteProfile, user_id)

    async def upsert_profile(self, values: dict[str, Any]) -> None:
        updates = {k: v for k, v in values.items() if k != "user_id"}
        await self.session.execute(
            insert(UserTasteProfile)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[UserTasteProfile.user_id],
                set_={**updates, "updated_at": func.now()},
            )
        )

    async def track_facts(
        self, track_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
        """track_id -> (artist_id, title)."""
        if not track_ids:
            return {}
        rows = await self.session.execute(
            select(Track.id, Track.artist_id, Track.title).where(Track.id.in_(set(track_ids)))
        )
        return {t: (a, title) for t, a, title in rows}

    async def artist_names(self, artist_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not artist_ids:
            return {}
        rows = await self.session.execute(
            select(Artist.id, Artist.name).where(Artist.id.in_(set(artist_ids)))
        )
        return {row[0]: row[1] for row in rows}
