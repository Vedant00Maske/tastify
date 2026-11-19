"""PlaylistService (spec §6.6): create, edit, reorder, regenerate and suggest.

Ownership (spec §12.3): every query is scoped to the signed-in user; another user's playlist is
reported as not found, so its existence is not revealed.

Feedback: adding tracks to a playlist by hand records `playlist_add` events (a strong positive,
spec §8.5) and updates the taste profile. Saving a whole generated collection does not, because it
is not a judgement on each track.
"""

import logging
import uuid
from collections.abc import Collection, Sequence
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.repository import CatalogueRepository
from app.domains.playlists.models import MAX_PLAYLISTS, MAX_TRACKS, Playlist, PlaylistTrack
from app.domains.playlists.schemas import (
    Generator,
    PlaylistCreate,
    PlaylistDetail,
    PlaylistList,
    PlaylistSummary,
    PlaylistTrackOut,
    PlaylistUpdate,
)
from app.domains.recommendations import explanations
from app.domains.recommendations.custom import CustomIn, CustomPlaylistService
from app.domains.recommendations.moods import MoodService
from app.domains.recommendations.personalized import EF_SEARCH, PersonalizedRecommendationService
from app.domains.recommendations.ranking import CANDIDATE_POOL, Candidate, rerank
from app.domains.recommendations.repository import RecommendationRepository
from app.domains.recommendations.schemas import (
    RecommendationItem,
    RecommendationResponse,
    Strategy,
)
from app.domains.recommendations.service import ModelUnavailableError, RecommendationService
from app.domains.users.events import EventType
from app.domains.users.schemas import InteractionBatch, InteractionIn
from app.domains.users.service import UserService

logger = logging.getLogger(__name__)

COLLAGE = 4
SUGGESTION_BETA = 0.2


class PlaylistError(Exception):
    """Base class for errors the API maps to HTTP responses."""


class PlaylistNotFoundError(PlaylistError):
    def __init__(self) -> None:
        super().__init__("Playlist not found")


class PlaylistRuleError(PlaylistError):
    """A request that breaks a playlist rule (HTTP 422)."""


class PlaylistService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.catalogue = CatalogueRepository(session)
        self.models = RecommendationRepository(session)

    # --- helpers -------------------------------------------------------------------------------

    async def _owned(self, user_id: uuid.UUID, playlist_id: uuid.UUID) -> Playlist:
        playlist = await self.session.scalar(
            select(Playlist).where(Playlist.id == playlist_id, Playlist.user_id == user_id)
        )
        if playlist is None:
            raise PlaylistNotFoundError()
        return playlist

    async def _track_ids(self, playlist_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self.session.scalars(
            select(PlaylistTrack.track_id)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
        )
        return list(rows)

    async def _valid_tracks(self, track_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        """De-duplicated, in order; raises if any track does not exist."""
        unique = list(dict.fromkeys(track_ids))
        if not unique:
            return []
        summaries = await self.catalogue.track_summaries(unique)
        missing = [str(t) for t in unique if t not in summaries]
        if missing:
            raise PlaylistRuleError(f"unknown tracks: {', '.join(missing[:20])}")
        return unique

    async def _write_tracks(self, playlist_id: uuid.UUID, track_ids: Sequence[uuid.UUID]) -> None:
        await self.session.execute(
            delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
        )
        self.session.add_all(
            PlaylistTrack(playlist_id=playlist_id, track_id=t, position=i)
            for i, t in enumerate(track_ids)
        )

    async def _touch(self, playlist: Playlist) -> None:
        playlist.updated_at = datetime.now(UTC)

    async def _summaries(self, playlists: Sequence[Playlist]) -> list[PlaylistSummary]:
        ids = [p.id for p in playlists]
        tracks: dict[uuid.UUID, list[uuid.UUID]] = {}
        if ids:
            rows = await self.session.execute(
                select(PlaylistTrack.playlist_id, PlaylistTrack.track_id)
                .where(PlaylistTrack.playlist_id.in_(ids))
                .order_by(PlaylistTrack.playlist_id, PlaylistTrack.position)
            )
            for playlist_id, track_id in rows:
                tracks.setdefault(playlist_id, []).append(track_id)
        summaries = await self.catalogue.track_summaries(
            list({t for ts in tracks.values() for t in ts})
        )
        out = []
        for playlist in playlists:
            members = [summaries[t] for t in tracks.get(playlist.id, []) if t in summaries]
            durations = [m.duration_ms for m in members]
            covers = list(dict.fromkeys(m.artwork_url for m in members if m.artwork_url))
            out.append(
                PlaylistSummary(
                    id=playlist.id,
                    name=playlist.name,
                    description=playlist.description,
                    kind=playlist.kind,
                    collection=playlist.collection,
                    track_count=len(members),
                    duration_ms=sum(d for d in durations if d is not None)
                    if members and all(d is not None for d in durations)
                    else None,
                    artwork_urls=covers[:COLLAGE],
                    created_at=playlist.created_at,
                    updated_at=playlist.updated_at,
                )
            )
        return out

    async def detail(self, playlist: Playlist) -> PlaylistDetail:
        (summary,) = await self._summaries([playlist])
        rows = (
            await self.session.execute(
                select(PlaylistTrack.track_id, PlaylistTrack.position, PlaylistTrack.added_at)
                .where(PlaylistTrack.playlist_id == playlist.id)
                .order_by(PlaylistTrack.position)
            )
        ).all()
        summaries = await self.catalogue.track_summaries([r[0] for r in rows])
        return PlaylistDetail(
            **summary.model_dump(),
            generator=playlist.generator,
            tracks=[
                PlaylistTrackOut(
                    **summaries[track_id].model_dump(), position=position, added_at=added_at
                )
                for track_id, position, added_at in rows
                if track_id in summaries
            ],
        )

    # --- generation ----------------------------------------------------------------------------

    async def generate(
        self, user_id: uuid.UUID, generator: Generator, exclude: Collection[uuid.UUID] = ()
    ) -> list[uuid.UUID]:
        """Tracks of a generated playlist, from the same services as the recommendation pages."""
        size = generator.size
        personalized = PersonalizedRecommendationService(self.session)
        if generator.collection in ("for_you", "hidden_gems"):
            response = await personalized.for_you(
                user_id, size, collection=generator.collection, exclude=exclude
            )
            return [i.track_id for i in response.recommendations]
        if generator.collection == "mood" and generator.mood is not None:
            mix = await MoodService(self.session).mix(generator.mood, size, user_id, exclude)
            return [i.track_id for i in mix.recommendations]
        if generator.collection == "genre" and generator.genre is not None:
            genre = await RecommendationService(self.session).genre(generator.genre, size * 2)
            items = [i.track_id for i in genre.recommendations if i.track_id not in exclude]
            return items[:size]
        if generator.collection == "artist_radio" and generator.artist_id is not None:
            radio = await personalized.artist_radio(generator.artist_id, size * 2)
            items = [i.track_id for i in radio.recommendations if i.track_id not in exclude]
            return items[:size]
        if generator.collection == "custom" and generator.prompt is not None:
            custom = await CustomPlaylistService(self.session).generate(
                CustomIn(
                    prompt=generator.prompt,
                    limit=min(size, 50),
                    exploration_level=generator.exploration_level,
                ),
                user_id,
                exclude,
            )
            return [i.track_id for i in custom.recommendations]
        raise PlaylistRuleError("incomplete generator")

    # --- operations ----------------------------------------------------------------------------

    async def list(self, user_id: uuid.UUID) -> PlaylistList:
        playlists = (
            await self.session.scalars(
                select(Playlist)
                .where(Playlist.user_id == user_id)
                .order_by(Playlist.updated_at.desc(), Playlist.id)
            )
        ).all()
        return PlaylistList(playlists=await self._summaries(playlists))

    async def create(self, user_id: uuid.UUID, data: PlaylistCreate) -> PlaylistDetail:
        count = await self.session.scalar(
            select(func.count()).select_from(Playlist).where(Playlist.user_id == user_id)
        )
        if (count or 0) >= MAX_PLAYLISTS:
            raise PlaylistRuleError(f"at most {MAX_PLAYLISTS} playlists")
        tracks = await self._valid_tracks(data.track_ids)
        if not tracks and data.generator is not None:
            tracks = await self.generate(user_id, data.generator)
        playlist = Playlist(
            user_id=user_id,
            name=data.name,
            description=data.description,
            kind="generated" if data.generator else "manual",
            collection=data.generator.collection if data.generator else None,
            generator=data.generator.model_dump(mode="json") if data.generator else None,
        )
        self.session.add(playlist)
        await self.session.flush()
        await self._write_tracks(playlist.id, tracks[:MAX_TRACKS])
        await self.session.commit()
        await self.session.refresh(playlist)
        if data.generator is None and tracks:
            await self._record_adds(user_id, tracks)
        logger.info(
            "playlist created user=%s playlist=%s tracks=%d", user_id, playlist.id, len(tracks)
        )
        return await self.detail(playlist)

    async def get(self, user_id: uuid.UUID, playlist_id: uuid.UUID) -> PlaylistDetail:
        return await self.detail(await self._owned(user_id, playlist_id))

    async def update(
        self, user_id: uuid.UUID, playlist_id: uuid.UUID, data: PlaylistUpdate
    ) -> PlaylistDetail:
        playlist = await self._owned(user_id, playlist_id)
        if data.name is not None:
            playlist.name = data.name
        if "description" in data.model_fields_set:
            playlist.description = (data.description or "").strip() or None
        await self._touch(playlist)
        await self.session.commit()
        return await self.detail(playlist)

    async def delete(self, user_id: uuid.UUID, playlist_id: uuid.UUID) -> None:
        playlist = await self._owned(user_id, playlist_id)
        await self.session.delete(playlist)
        await self.session.commit()

    async def add_tracks(
        self, user_id: uuid.UUID, playlist_id: uuid.UUID, track_ids: Sequence[uuid.UUID]
    ) -> PlaylistDetail:
        playlist = await self._owned(user_id, playlist_id)
        current = await self._track_ids(playlist.id)
        new = [t for t in await self._valid_tracks(track_ids) if t not in set(current)]
        if len(current) + len(new) > MAX_TRACKS:
            raise PlaylistRuleError(f"a playlist holds at most {MAX_TRACKS} tracks")
        self.session.add_all(
            PlaylistTrack(playlist_id=playlist.id, track_id=t, position=len(current) + i)
            for i, t in enumerate(new)
        )
        await self._touch(playlist)
        await self.session.commit()
        if new:
            await self._record_adds(user_id, new)
        return await self.detail(playlist)

    async def remove_track(
        self, user_id: uuid.UUID, playlist_id: uuid.UUID, track_id: uuid.UUID
    ) -> PlaylistDetail:
        playlist = await self._owned(user_id, playlist_id)
        current = await self._track_ids(playlist.id)
        if track_id not in current:
            raise PlaylistNotFoundError()
        await self._write_tracks(playlist.id, [t for t in current if t != track_id])
        await self._touch(playlist)
        await self.session.commit()
        return await self.detail(playlist)

    async def reorder(
        self, user_id: uuid.UUID, playlist_id: uuid.UUID, order: Sequence[uuid.UUID]
    ) -> PlaylistDetail:
        playlist = await self._owned(user_id, playlist_id)
        current = await self._track_ids(playlist.id)
        if len(order) != len(set(order)) or set(order) != set(current):
            raise PlaylistRuleError("the new order must list every track of the playlist once")
        for position, track_id in enumerate(order):
            await self.session.execute(
                update(PlaylistTrack)
                .where(PlaylistTrack.playlist_id == playlist.id, PlaylistTrack.track_id == track_id)
                .values(position=position)
            )
        await self._touch(playlist)
        await self.session.commit()
        return await self.detail(playlist)

    async def regenerate(self, user_id: uuid.UUID, playlist_id: uuid.UUID) -> PlaylistDetail:
        """A fresh set from the playlist's generator, avoiding its current tracks."""
        playlist = await self._owned(user_id, playlist_id)
        if playlist.generator is None:
            raise PlaylistRuleError("only generated playlists can be regenerated")
        generator = Generator.model_validate(playlist.generator)
        current = await self._track_ids(playlist.id)
        tracks = await self.generate(user_id, generator, exclude=set(current))
        if not tracks:
            raise PlaylistRuleError("no new tracks are available for this playlist right now")
        await self._write_tracks(playlist.id, tracks)
        await self._touch(playlist)
        await self.session.commit()
        return await self.detail(playlist)

    async def suggestions(
        self, user_id: uuid.UUID, playlist_id: uuid.UUID, limit: int
    ) -> RecommendationResponse:
        """Tracks that fit the playlist: nearest to the mean content embedding of its tracks,
        with a small popularity blend and two tracks per artist."""
        playlist = await self._owned(user_id, playlist_id)
        current = await self._track_ids(playlist.id)
        content = await self.models.active_version("content")
        popularity = await self.models.active_version("popularity")
        if content is None:
            raise ModelUnavailableError("content")
        vectors = await self.models.track_embeddings(content.id, current)
        items: list[RecommendationItem] = []
        if vectors:
            centre = np.mean(np.array(list(vectors.values())), axis=0)
            norm = float(np.linalg.norm(centre))
            if norm > 0:
                neighbours = await self.models.nearest_tracks(
                    content.id, (centre / norm).tolist(), CANDIDATE_POOL, EF_SEARCH
                )
                pool = [(t, s) for t, s in neighbours if t not in set(current)]
                facts = await self.models.track_facts(
                    [t for t, _ in pool], popularity.id if popularity else None
                )
                in_playlist = await self.models.song_keys(current)
                ranked = rerank(
                    (
                        Candidate(t, s, facts[t].popularity, facts[t].artist_id, facts[t].song_key)
                        for t, s in pool
                        if t in facts
                    ),
                    beta=SUGGESTION_BETA,
                    limit=limit,
                    exclude_dedup_keys=in_playlist.values(),
                )
                summaries = await self.catalogue.track_summaries([r.item for r in ranked])
                items = [
                    RecommendationItem(
                        track_id=r.item,
                        title=summaries[r.item].title,
                        artist=summaries[r.item].artist,
                        artist_id=summaries[r.item].artist_id,
                        album=summaries[r.item].album_title,
                        artwork_url=summaries[r.item].artwork_url,
                        score=round(r.score, 4),
                        reason=explanations.playlist_fit_reason(
                            playlist.name, r.candidate.similarity
                        ),
                    )
                    for r in ranked
                    if r.item in summaries
                ]
        versions = {"content": content.version}
        if popularity is not None:
            versions["popularity"] = popularity.version
        return RecommendationResponse(
            request_id=uuid.uuid4(),
            model_version=content.version,
            model_versions=versions,
            strategy=Strategy.SIMILAR_TRACKS,
            recommendations=items,
        )

    async def _record_adds(self, user_id: uuid.UUID, tracks: Sequence[uuid.UUID]) -> None:
        await UserService(self.session).record_events(
            user_id,
            InteractionBatch(
                events=[
                    InteractionIn(track_id=t, event_type=EventType.PLAYLIST_ADD)
                    for t in tracks[:MAX_TRACKS]
                ],
                source="playlist",
            ),
        )
