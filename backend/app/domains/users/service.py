"""User, interaction, preference and taste-profile services (spec §6.6: UserProfileService,
InteractionService; ADR-016).

Profiles are rebuilt from the stored events whenever the events or declared preferences change
(so "profiles update when new interactions arrive"), and lazily when the models or the profile
configuration they were built with are no longer the active ones.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.repository import CatalogueRepository
from app.domains.recommendations.models import ModelVersion
from app.domains.recommendations.repository import RecommendationRepository
from app.domains.users.events import EventType, FeedbackWeights, TrackSignals, aggregate_events
from app.domains.users.models import User, UserTasteProfile
from app.domains.users.profile import (
    DeclaredPreferences,
    ExplorationMode,
    TasteProfile,
    TasteProfileConfig,
    build_taste_profile,
    strongest_first,
)
from app.domains.users.repository import DeclaredRows, EventRows, UserRepository
from app.domains.users.schemas import (
    ArtistAffinityOut,
    ArtistRef,
    FeedbackState,
    FeedbackStates,
    GenreAffinityOut,
    InteractionBatch,
    InteractionHistory,
    InteractionOut,
    InteractionsRecorded,
    PreferencesIn,
    PreferencesOut,
    TasteProfileOut,
)

logger = logging.getLogger(__name__)

# Genre affinity is computed from the user's strongest tracks only (bounded query cost).
MAX_GENRE_TRACKS = 500
# A stored profile older than this is rebuilt before use (its decays are measured from as_of).
PROFILE_MAX_AGE = timedelta(hours=24)


class UserError(Exception):
    """Base class for errors the API maps to HTTP responses."""


class UserNotFoundError(UserError):
    def __init__(self) -> None:
        super().__init__("User not found")


class InvalidReferenceError(UserError):
    """The request references tracks, artists or genres that do not exist (HTTP 422)."""

    def __init__(self, kind: str, values: Sequence[object]) -> None:
        self.kind = kind
        self.values = [str(v) for v in values]
        super().__init__(f"unknown {kind}: {', '.join(self.values[:20])}")


def profile_config(hybrid: ModelVersion | None) -> TasteProfileConfig:
    """The profile configuration the active hybrid model was trained with (defaults without)."""
    params: dict[str, Any] | None = None if hybrid is None else hybrid.params.get("profile_config")
    if not params:
        return TasteProfileConfig()
    return TasteProfileConfig(
        **{**params, "feedback": FeedbackWeights(**params.get("feedback", {}))}
    )


def signals_from_events(
    events: EventRows, as_of: datetime, config: TasteProfileConfig
) -> TrackSignals[uuid.UUID]:
    ages = [(as_of - t).total_seconds() / 86400.0 for t in events.occurred_at]
    keys = np.empty(len(events), dtype=object)
    keys[:] = events.track_ids
    return aggregate_events(
        keys,
        events.event_types,
        ages,
        events.positions_ms,
        weights=config.feedback,
        long_decay=config.long_decay,
        short_decay=config.short_decay,
    )


def declared_preferences(rows: DeclaredRows) -> DeclaredPreferences[uuid.UUID]:
    mode = rows.preference.exploration_mode if rows.preference else None
    return DeclaredPreferences(
        preferred_artists=tuple(a for a, _, p in rows.artists if p == "preferred"),
        excluded_artists=tuple(a for a, _, p in rows.artists if p == "excluded"),
        preferred_genres=tuple(n for _, n, p in rows.genres if p == "preferred"),
        excluded_genres=tuple(n for _, n, p in rows.genres if p == "excluded"),
        exploration_mode=ExplorationMode(mode) if mode else None,
    )


@dataclass
class ProfileContext:
    """Everything recommendation needs about a user, at one reference time."""

    user_id: uuid.UUID
    profile: TasteProfile[uuid.UUID, uuid.UUID]
    signals: TrackSignals[uuid.UUID]
    declared: DeclaredPreferences[uuid.UUID]
    personalization_enabled: bool
    config: TasteProfileConfig
    row: UserTasteProfile
    content_version: ModelVersion | None


def _vector(values: Any) -> np.ndarray[Any, np.dtype[np.float64]] | None:
    return None if values is None else np.asarray([float(v) for v in values], dtype=np.float64)


def profile_from_row(
    row: UserTasteProfile,
    signals: TrackSignals[uuid.UUID],
    declared: DeclaredPreferences[uuid.UUID],
) -> TasteProfile[uuid.UUID, uuid.UUID]:
    """The stored profile, completed with the request-time facts (heard and disliked tracks)."""
    keys = list(signals.keys)
    return TasteProfile(
        long_term_embedding=_vector(row.long_term_embedding),
        short_term_embedding=_vector(row.short_term_embedding),
        genre_affinity=strongest_first(row.genre_affinity),
        artist_affinity=strongest_first({uuid.UUID(k): v for k, v in row.artist_affinity.items()}),
        negative_artists=strongest_first(
            {uuid.UUID(k): v for k, v in row.negative_artists.items()}
        ),
        excluded_artists=frozenset(declared.excluded_artists),
        excluded_genres=frozenset(declared.excluded_genres),
        disliked_tracks=frozenset(keys[i] for i in np.flatnonzero(signals.disliked).tolist()),
        heard_tracks=frozenset(keys),
        known_artists=frozenset(uuid.UUID(a) for a in row.known_artists),
        seed_tracks=tuple(uuid.UUID(t) for t in row.seed_tracks),
        recent_tracks=tuple(uuid.UUID(t) for t in row.recent_tracks),
        listening_stats=dict(row.listening_stats),
        exploration_preference=row.exploration_preference,
        history_size=row.history_size,
        profile_version=row.profile_version,
        exploration_mode=declared.exploration_mode,
    )


class TasteProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.models = RecommendationRepository(session)

    async def require_user(self, user_id: uuid.UUID) -> User:
        user = await self.users.get_user(user_id)
        if user is None:
            raise UserNotFoundError()
        return user

    async def rebuild(self, user_id: uuid.UUID) -> ProfileContext:
        """Build the profile from all stored events and preferences, store it, return it."""
        content = await self.models.active_version("content")
        hybrid = await self.models.active_version("hybrid")
        config = profile_config(hybrid)
        as_of = datetime.now(UTC)
        events = await self.users.events(user_id)
        signals = signals_from_events(events, as_of, config)
        declared_rows = await self.users.declared(user_id)
        declared = declared_preferences(declared_rows)
        keys: list[uuid.UUID] = list(signals.keys)

        facts = await self.users.track_facts(keys)
        artists = [facts[k][0] for k in keys]
        embeddings = None
        declared_vectors = None
        if content is not None:
            vectors = await self.models.track_embeddings(content.id, keys)
            dimension = len(next(iter(vectors.values()))) if vectors else 0
            if dimension:
                embeddings = np.zeros((len(keys), dimension))
                for position, key in enumerate(keys):
                    if key in vectors:
                        embeddings[position] = vectors[key]
            preferred = await self.models.artist_embeddings(content.id, declared.preferred_artists)
            if preferred:
                declared_vectors = np.asarray(list(preferred.values()), dtype=np.float64)
        strongest = np.argsort(-signals.preference, kind="stable")[:MAX_GENRE_TRACKS]
        genre_tracks = [keys[i] for i in strongest.tolist() if signals.preference[i] > 0]
        profiles = await self.models.genre_profiles(genre_tracks)
        track_genres = [profiles.get(k, {}) for k in keys]

        profile = build_taste_profile(
            signals,
            track_artists=artists,
            track_embeddings=embeddings,
            track_genres=track_genres,
            config=config,
            preferences=declared,
            declared_artist_embeddings=declared_vectors,
        )
        values = {
            "user_id": user_id,
            "profile_version": profile.profile_version,
            "content_model_version_id": None if content is None else content.id,
            "long_term_embedding": _as_list(profile.long_term_embedding),
            "short_term_embedding": _as_list(profile.short_term_embedding),
            "genre_affinity": profile.genre_affinity,
            "artist_affinity": {str(k): v for k, v in profile.artist_affinity.items()},
            "negative_artists": {str(k): v for k, v in profile.negative_artists.items()},
            "known_artists": sorted(str(a) for a in profile.known_artists),
            "seed_tracks": [str(t) for t in profile.seed_tracks],
            "recent_tracks": [str(t) for t in profile.recent_tracks],
            "listening_stats": {**profile.listening_stats, "events": float(len(events))},
            "exploration_preference": profile.exploration_preference,
            "history_size": profile.history_size,
            "interaction_count": len(events),
            "last_event_at": events.occurred_at[-1] if len(events) else None,
            "as_of": as_of,
        }
        await self.users.upsert_profile(values)
        await self.session.flush()
        row = await self.users.profile(user_id)
        if row is None:  # pragma: no cover - the upsert above guarantees it
            raise RuntimeError("profile upsert failed")
        await self.session.refresh(row)
        enabled = (
            declared_rows.preference is None or declared_rows.preference.personalization_enabled
        )
        logger.info(
            "taste profile rebuilt user=%s version=%s events=%d tracks=%d",
            user_id,
            profile.profile_version,
            len(events),
            profile.history_size,
        )
        return ProfileContext(user_id, profile, signals, declared, enabled, config, row, content)

    async def current(self, user_id: uuid.UUID) -> ProfileContext:
        """The stored profile if it is still valid for the active models, else a rebuilt one."""
        await self.require_user(user_id)
        row = await self.users.profile(user_id)
        content = await self.models.active_version("content")
        hybrid = await self.models.active_version("hybrid")
        config = profile_config(hybrid)
        if row is not None:
            last = await self.users.last_received(user_id)
            stale = (
                row.profile_version != config.version
                or row.content_model_version_id != (None if content is None else content.id)
                or (last is not None and last > row.updated_at)
                or datetime.now(UTC) - row.as_of > PROFILE_MAX_AGE
            )
            if not stale:
                declared_rows = await self.users.declared(user_id)
                declared = declared_preferences(declared_rows)
                events = await self.users.events(user_id)
                signals = signals_from_events(events, row.as_of, config)
                enabled = (
                    declared_rows.preference is None
                    or declared_rows.preference.personalization_enabled
                )
                return ProfileContext(
                    user_id,
                    profile_from_row(row, signals, declared),
                    signals,
                    declared,
                    enabled,
                    config,
                    row,
                    content,
                )
        return await self.rebuild(user_id)

    async def describe(
        self, context: ProfileContext, include_embeddings: bool = False
    ) -> TasteProfileOut:
        row, profile = context.row, context.profile
        artist_ids = [*profile.artist_affinity, *profile.negative_artists]
        names = await self.users.artist_names(artist_ids)
        return TasteProfileOut(
            user_id=context.user_id,
            profile_version=row.profile_version,
            content_model_version=None
            if context.content_version is None
            else context.content_version.version,
            updated_at=row.updated_at,
            as_of=row.as_of,
            genre_affinity=[
                GenreAffinityOut(genre=g, score=s) for g, s in profile.genre_affinity.items()
            ],
            artist_affinity=[
                ArtistAffinityOut(artist_id=a, name=names.get(a, ""), score=s)
                for a, s in profile.artist_affinity.items()
            ],
            negative_artists=[
                ArtistAffinityOut(artist_id=a, name=names.get(a, ""), score=s)
                for a, s in profile.negative_artists.items()
            ],
            listening_frequency={k: float(v) for k, v in row.listening_stats.items()},
            exploration_preference=profile.exploration_preference,
            exploration_mode=profile.exploration_mode,
            discovery_target=profile.discovery_target(),
            history_size=profile.history_size,
            interaction_count=row.interaction_count,
            last_event_at=row.last_event_at,
            long_term_embedding=_as_list(profile.long_term_embedding)
            if include_embeddings
            else None,
            short_term_embedding=_as_list(profile.short_term_embedding)
            if include_embeddings
            else None,
        )


def _as_list(vector: np.ndarray[Any, Any] | None) -> list[float] | None:
    return None if vector is None else [float(v) for v in vector]


class UserService:
    """Users, their interaction events and their declared preferences."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.profiles = TasteProfileService(session)

    async def record_events(
        self, user_id: uuid.UUID, batch: InteractionBatch
    ) -> InteractionsRecorded:
        await self.profiles.require_user(user_id)
        track_ids = [e.track_id for e in batch.events]
        known = await self.users.existing_tracks(track_ids)
        unknown = sorted({str(t) for t in track_ids if t not in known})
        if unknown:
            raise InvalidReferenceError("tracks", unknown)
        now = datetime.now(UTC)
        # Duplicate client ids inside one batch: the first wins, like a retried batch.
        seen: set[str] = set()
        rows = []
        for event in batch.events:
            if event.client_event_id is not None:
                if event.client_event_id in seen:
                    continue
                seen.add(event.client_event_id)
            rows.append(
                {
                    "user_id": user_id,
                    "track_id": event.track_id,
                    "event_type": event.event_type.value,
                    "occurred_at": event.occurred_at or now,
                    "position_ms": event.position_ms,
                    "session_id": event.session_id,
                    "source": batch.source,
                    "client_event_id": event.client_event_id,
                }
            )
        inserted = await self.users.insert_events(rows)
        context = await self.profiles.rebuild(user_id)
        await self.session.commit()
        logger.info(
            "interactions recorded user=%s recorded=%d duplicates=%d",
            user_id,
            inserted,
            len(batch.events) - inserted,
        )
        return InteractionsRecorded(
            recorded=inserted,
            duplicates=len(batch.events) - inserted,
            profile=await self.profiles.describe(context),
        )

    async def history(
        self,
        user_id: uuid.UUID,
        limit: int,
        before: datetime | None,
        event_types: Sequence[EventType] | None = None,
    ) -> InteractionHistory:
        await self.profiles.require_user(user_id)
        rows = await self.users.history(
            user_id, limit + 1, before, [e.value for e in event_types or ()]
        )
        tracks = await CatalogueRepository(self.session).track_summaries(
            list({r.track_id for r in rows[:limit]})
        )
        items = [
            InteractionOut(
                id=r.id,
                track_id=r.track_id,
                event_type=EventType(r.event_type),
                occurred_at=r.occurred_at,
                received_at=r.received_at,
                position_ms=r.position_ms,
                session_id=r.session_id,
                source=r.source,
                track=tracks.get(r.track_id),
            )
            for r in rows[:limit]
        ]
        return InteractionHistory(
            items=items, next_before=items[-1].occurred_at if len(rows) > limit else None
        )

    async def feedback_states(
        self, user_id: uuid.UUID, track_ids: Sequence[uuid.UUID]
    ) -> FeedbackStates:
        """Like, dislike and save states of the given tracks, from the user's events."""
        wanted = set(track_ids)
        events = await self.users.events(user_id)
        rows = [i for i, t in enumerate(events.track_ids) if t in wanted]
        states: dict[uuid.UUID, FeedbackState] = {
            t: FeedbackState(liked=False, disliked=False, saved=False) for t in wanted
        }
        if rows:
            keys = np.empty(len(rows), dtype=object)
            keys[:] = [events.track_ids[i] for i in rows]
            signals: TrackSignals[uuid.UUID] = aggregate_events(
                keys,
                [events.event_types[i] for i in rows],
                np.zeros(len(rows)),
                [events.positions_ms[i] for i in rows],
                weights=FeedbackWeights(),
                long_decay=TasteProfileConfig().long_decay,
                short_decay=TasteProfileConfig().short_decay,
            )
            for row, track in enumerate(signals.keys):
                states[track] = FeedbackState(
                    liked=bool(signals.liked[row]),
                    disliked=bool(signals.disliked[row]),
                    saved=bool(signals.saved[row]),
                )
        return FeedbackStates(states=states)

    async def preferences(self, user_id: uuid.UUID) -> PreferencesOut:
        await self.profiles.require_user(user_id)
        rows = await self.users.declared(user_id)
        return PreferencesOut(
            exploration_mode=ExplorationMode(rows.preference.exploration_mode)
            if rows.preference and rows.preference.exploration_mode
            else None,
            personalization_enabled=rows.preference is None
            or rows.preference.personalization_enabled,
            preferred_artists=[
                ArtistRef(artist_id=a, name=n) for a, n, p in rows.artists if p == "preferred"
            ],
            excluded_artists=[
                ArtistRef(artist_id=a, name=n) for a, n, p in rows.artists if p == "excluded"
            ],
            preferred_genres=[n for _, n, p in rows.genres if p == "preferred"],
            excluded_genres=[n for _, n, p in rows.genres if p == "excluded"],
            preferred_moods=list(rows.preference.preferred_moods) if rows.preference else [],
            updated_at=rows.preference.updated_at if rows.preference else None,
        )

    async def update_preferences(self, user_id: uuid.UUID, update: PreferencesIn) -> PreferencesOut:
        await self.profiles.require_user(user_id)
        artist_ids = [*update.preferred_artists, *update.excluded_artists]
        known = await self.users.existing_artists(artist_ids)
        unknown = [str(a) for a in artist_ids if a not in known]
        if unknown:
            raise InvalidReferenceError("artists", unknown)
        # Local import: the moods module imports this one.
        from app.domains.recommendations.moods import MOODS

        unknown_moods = [m for m in update.preferred_moods if m not in MOODS]
        if unknown_moods:
            raise InvalidReferenceError("moods", unknown_moods)
        names = [*update.preferred_genres, *update.excluded_genres]
        genres = await self.users.genres_by_name(names)
        missing = [n for n in names if n.lower() not in genres]
        if missing:
            raise InvalidReferenceError("genres", missing)
        await self.users.replace_preferences(
            user_id,
            exploration_mode=None
            if update.exploration_mode is None
            else update.exploration_mode.value,
            personalization_enabled=update.personalization_enabled,
            preferred_moods=list(dict.fromkeys(update.preferred_moods)),
            artists=[
                *((a, "preferred") for a in dict.fromkeys(update.preferred_artists)),
                *((a, "excluded") for a in dict.fromkeys(update.excluded_artists)),
            ],
            genres=list(
                {
                    **{genres[n.lower()].id: "preferred" for n in update.preferred_genres},
                    **{genres[n.lower()].id: "excluded" for n in update.excluded_genres},
                }.items()
            ),
        )
        await self.profiles.rebuild(user_id)
        await self.session.commit()
        logger.info("preferences updated user=%s", user_id)
        return await self.preferences(user_id)
