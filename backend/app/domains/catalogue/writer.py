"""Loads validated source records into the canonical catalogue, applying entity resolution.

For each incoming track:

1. Already known by this provider id -> refresh it (re-runs are idempotent).
2. Otherwise gather candidates sharing an ISRC or the same artist/title matching key, and apply
   the resolution policy (app.domains.catalogue.resolution):
   - LINK: attach the incoming identifiers to the existing canonical track.
   - REVIEW: create a separate track and record the possible duplicates for verification.
   - NO_MATCH: create a new canonical track.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Float, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.ingestion import SourceAlbum, SourceArtist, SourceGenreTag, SourceTrack
from app.domains.catalogue.models import (
    Album,
    AlbumExternalId,
    Artist,
    ArtistExternalId,
    ArtistGenre,
    EntityMatchCandidate,
    Genre,
    Track,
    TrackArtist,
    TrackExternalId,
    TrackGenre,
)
from app.domains.catalogue.normalization import (
    clean_title,
    matching_key,
    normalize_name,
    parse_partial_date,
)
from app.domains.catalogue.resolution import MatchDecision, MatchResult, TrackEvidence, resolve

ISRC_PROVIDER = "isrc"
SOURCE_METHOD = "source"  # the identifier was asserted by the source itself


def track_matching_key(primary_artist: str, title: str) -> str:
    return f"{matching_key(primary_artist)}|{matching_key(clean_title(title))}"


def genre_key(name: str) -> str:
    return normalize_name(name.replace("-", " "))


class WriteOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    LINKED = "linked"
    CREATED_FOR_REVIEW = "created_for_review"


@dataclass(frozen=True)
class TrackWriteResult:
    track_id: uuid.UUID
    outcome: WriteOutcome
    match: MatchResult | None = None


# Called with (error_code, record_ref, message) for data problems found while writing.
IssueReporter = Callable[[str, str, str], None]


def _ignore_issue(code: str, ref: str, message: str) -> None:
    return None


class CatalogueWriter:
    def __init__(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
        *,
        create_unknown_genres: bool = False,
        report_issue: IssueReporter = _ignore_issue,
    ) -> None:
        self.session = session
        self.source_id = source_id
        self.create_unknown_genres = create_unknown_genres
        self.report_issue = report_issue
        self._genres: dict[str, uuid.UUID] = {}
        self._artists: dict[tuple[str, str], uuid.UUID] = {}
        self._albums: dict[tuple[str, str], uuid.UUID] = {}

    # --- genres ----------------------------------------------------------------------------

    async def load_genre_index(self) -> None:
        rows = await self.session.execute(select(Genre.id, Genre.name))
        self._genres = {genre_key(name): genre_id for genre_id, name in rows}

    async def ensure_genre(
        self, name: str, musicbrainz_id: str | None = None, parent_id: uuid.UUID | None = None
    ) -> uuid.UUID:
        key = genre_key(name)
        if key in self._genres:
            return self._genres[key]
        statement = (
            insert(Genre)
            .values(
                name=name.strip().lower(),
                musicbrainz_id=uuid.UUID(musicbrainz_id) if musicbrainz_id else None,
                parent_id=parent_id,
                source_id=self.source_id,
            )
            .on_conflict_do_update(index_elements=[Genre.name], set_={"name": Genre.name})
            .returning(Genre.id)
        )
        genre_id = (await self.session.execute(statement)).scalar_one()
        self._genres[key] = genre_id
        return genre_id

    async def _weighted_genres(self, tags: Sequence[SourceGenreTag]) -> list[tuple[uuid.UUID, int]]:
        votes: dict[uuid.UUID, int] = defaultdict(int)
        for tag in tags:
            genre_id = self._genres.get(genre_key(tag.name))
            if genre_id is None and (self.create_unknown_genres or tag.musicbrainz_id):
                genre_id = await self.ensure_genre(tag.name, tag.musicbrainz_id)
            if genre_id is not None:
                votes[genre_id] += tag.count
        return list(votes.items())

    async def _attach_track_genres(
        self, track_id: uuid.UUID, tags: Sequence[SourceGenreTag], level: str
    ) -> None:
        weighted = await self._weighted_genres(tags)
        if not weighted:
            return
        for genre_id, count in weighted:
            statement = insert(TrackGenre).values(
                track_id=track_id,
                genre_id=genre_id,
                source_id=self.source_id,
                level=level,
                weight=1.0,  # provisional; normalized below
                vote_count=count,
            )
            # A second record linked to the same track adds its votes to the existing ones.
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=["track_id", "genre_id", "source_id", "level"],
                    set_={"vote_count": TrackGenre.vote_count + statement.excluded.vote_count},
                )
            )
        same_group = (
            (TrackGenre.track_id == track_id)
            & (TrackGenre.source_id == self.source_id)
            & (TrackGenre.level == level)
        )
        total = select(func.sum(TrackGenre.vote_count)).where(same_group).scalar_subquery()
        await self.session.execute(
            update(TrackGenre)
            .where(same_group)
            .values(weight=cast(TrackGenre.vote_count, Float) / total)
        )

    # --- artists and albums -----------------------------------------------------------------

    async def upsert_artist(self, artist: SourceArtist) -> uuid.UUID:
        cache_key = (artist.provider, artist.external_id)
        if cache_key in self._artists:
            return self._artists[cache_key]
        artist_id = await self.session.scalar(
            select(ArtistExternalId.artist_id).where(
                ArtistExternalId.provider == artist.provider,
                ArtistExternalId.external_id == artist.external_id,
            )
        )
        if artist_id is None:
            artist_id = await self._create_artist(artist)
        self._artists[cache_key] = artist_id
        return artist_id

    async def _create_artist(self, artist: SourceArtist) -> uuid.UUID:
        artist_id = (
            await self.session.execute(
                insert(Artist)
                .values(
                    name=artist.name,
                    normalized_name=normalize_name(artist.name),
                    artist_type=artist.artist_type,
                    area=artist.area,
                    begin_year=artist.begin_year,
                    source_id=self.source_id,
                )
                .returning(Artist.id)
            )
        ).scalar_one()
        await self._attach_artist_id(artist_id, artist, SOURCE_METHOD, 1.0)
        weighted = await self._weighted_genres(artist.genres)
        total = sum(count for _, count in weighted)
        for genre_id, count in weighted:
            await self.session.execute(
                insert(ArtistGenre)
                .values(
                    artist_id=artist_id,
                    genre_id=genre_id,
                    source_id=self.source_id,
                    weight=count / total,
                    vote_count=count,
                )
                .on_conflict_do_nothing()
            )
        return artist_id

    async def _attach_artist_id(
        self, artist_id: uuid.UUID, artist: SourceArtist, method: str, confidence: float
    ) -> None:
        await self.session.execute(
            insert(ArtistExternalId)
            .values(
                artist_id=artist_id,
                provider=artist.provider,
                external_id=artist.external_id,
                match_method=method,
                confidence=confidence,
                source_id=self.source_id,
            )
            .on_conflict_do_nothing(index_elements=["provider", "external_id"])
        )
        self._artists[(artist.provider, artist.external_id)] = artist_id

    async def upsert_album(self, album: SourceAlbum, primary_artist_id: uuid.UUID) -> uuid.UUID:
        cache_key = (album.provider, album.external_id)
        if cache_key in self._albums:
            return self._albums[cache_key]
        album_id = await self.session.scalar(
            select(AlbumExternalId.album_id).where(
                AlbumExternalId.provider == album.provider,
                AlbumExternalId.external_id == album.external_id,
            )
        )
        if album_id is None:
            release_date, release_year = parse_partial_date(album.release_date)
            album_id = (
                await self.session.execute(
                    insert(Album)
                    .values(
                        title=album.title,
                        normalized_title=normalize_name(album.title),
                        album_type=album.album_type,
                        release_date=release_date,
                        release_year=release_year,
                        primary_artist_id=primary_artist_id,
                        source_id=self.source_id,
                    )
                    .returning(Album.id)
                )
            ).scalar_one()
            await self.session.execute(
                insert(AlbumExternalId)
                .values(
                    album_id=album_id,
                    provider=album.provider,
                    external_id=album.external_id,
                    match_method=SOURCE_METHOD,
                    confidence=1.0,
                    source_id=self.source_id,
                )
                .on_conflict_do_nothing(index_elements=["provider", "external_id"])
            )
        self._albums[cache_key] = album_id
        return album_id

    # --- tracks ----------------------------------------------------------------------------

    async def upsert_track(self, source: SourceTrack) -> TrackWriteResult:
        existing = await self.session.scalar(
            select(TrackExternalId.track_id).where(
                TrackExternalId.provider == source.provider,
                TrackExternalId.external_id == source.external_id,
            )
        )
        if existing is not None:
            await self._attach_track_ids(existing, source, SOURCE_METHOD, 1.0)
            return TrackWriteResult(existing, WriteOutcome.UPDATED)

        candidates = await self._candidates(source)
        resolution = resolve(source.evidence(), candidates)

        linked, match = resolution.linked, resolution.match
        if resolution.decision is MatchDecision.LINK and linked is not None and match is not None:
            await self._attach_track_ids(linked, source, match.method, match.confidence)
            await self._link_primary_artist(linked, source.primary_artist, match.confidence)
            await self._attach_track_genres(linked, source.genres, "recording")
            return TrackWriteResult(linked, WriteOutcome.LINKED, match)

        track_id = await self._create_track(source)
        if resolution.decision is MatchDecision.REVIEW:
            for candidate_id, result in resolution.review:
                await self.session.execute(
                    insert(EntityMatchCandidate)
                    .values(
                        track_id=track_id,
                        candidate_track_id=candidate_id,
                        confidence=result.confidence,
                        method=result.method,
                        evidence=result.signals,
                        source_id=self.source_id,
                    )
                    .on_conflict_do_nothing()
                )
            return TrackWriteResult(track_id, WriteOutcome.CREATED_FOR_REVIEW)
        return TrackWriteResult(track_id, WriteOutcome.CREATED)

    async def _create_track(self, source: SourceTrack) -> uuid.UUID:
        primary_artist_id = await self.upsert_artist(source.primary_artist)
        album_id = (
            await self.upsert_album(source.album, primary_artist_id) if source.album else None
        )
        release_date, release_year = parse_partial_date(source.release_date)
        track_id = (
            await self.session.execute(
                insert(Track)
                .values(
                    title=source.title,
                    normalized_title=normalize_name(source.title),
                    matching_key=track_matching_key(source.primary_artist.name, source.title),
                    duration_ms=source.duration_ms,
                    release_date=release_date,
                    release_year=release_year,
                    artist_id=primary_artist_id,
                    album_id=album_id,
                    source_id=self.source_id,
                )
                .returning(Track.id)
            )
        ).scalar_one()
        for position, credit in enumerate(source.credits):
            artist_id = (
                primary_artist_id if position == 0 else await self.upsert_artist(credit.artist)
            )
            await self.session.execute(
                insert(TrackArtist).values(
                    track_id=track_id,
                    position=position,
                    artist_id=artist_id,
                    credited_name=credit.credited_name or credit.artist.name,
                    join_phrase=credit.join_phrase,
                )
            )
        await self._attach_track_ids(track_id, source, SOURCE_METHOD, 1.0)
        await self._attach_track_genres(track_id, source.genres, "recording")
        if source.album:
            await self._attach_track_genres(track_id, source.album.genres, "album")
        return track_id

    async def _attach_track_ids(
        self, track_id: uuid.UUID, source: SourceTrack, method: str, confidence: float
    ) -> None:
        identifiers = [(source.provider, source.external_id)] + [
            (ISRC_PROVIDER, isrc) for isrc in source.isrcs
        ]
        owned_isrcs: list[str] = []
        for provider, external_id in identifiers:
            inserted = await self.session.execute(
                insert(TrackExternalId)
                .values(
                    track_id=track_id,
                    provider=provider,
                    external_id=external_id,
                    match_method=method if provider == source.provider else SOURCE_METHOD,
                    confidence=confidence if provider == source.provider else 1.0,
                    source_id=self.source_id,
                )
                .on_conflict_do_nothing(index_elements=["provider", "external_id"])
                .returning(TrackExternalId.track_id)
            )
            owner: uuid.UUID | None = inserted.scalar_one_or_none()
            if owner is None:
                owner = await self.session.scalar(
                    select(TrackExternalId.track_id).where(
                        TrackExternalId.provider == provider,
                        TrackExternalId.external_id == external_id,
                    )
                )
                if owner != track_id:
                    self.report_issue(
                        "identifier_conflict",
                        f"{source.provider}:{source.external_id}",
                        f"{provider} {external_id} already belongs to track {owner}",
                    )
            if provider == ISRC_PROVIDER and owner == track_id:
                owned_isrcs.append(external_id)
        if owned_isrcs:
            # Only an ISRC registered to this track may become its primary ISRC.
            await self.session.execute(
                update(Track)
                .where(Track.id == track_id, Track.isrc.is_(None))
                .values(isrc=owned_isrcs[0])
            )

    async def _link_primary_artist(
        self, track_id: uuid.UUID, artist: SourceArtist, confidence: float
    ) -> None:
        """Record this source's id for the linked track's artist, when the names agree."""
        if (artist.provider, artist.external_id) in self._artists:
            return
        known = await self.session.scalar(
            select(ArtistExternalId.artist_id).where(
                ArtistExternalId.provider == artist.provider,
                ArtistExternalId.external_id == artist.external_id,
            )
        )
        if known is not None:
            self._artists[(artist.provider, artist.external_id)] = known
            return
        row = (
            await self.session.execute(
                select(Artist.id, Artist.name)
                .join(Track, Track.artist_id == Artist.id)
                .where(Track.id == track_id)
            )
        ).one()
        if matching_key(row.name) == matching_key(artist.name):
            await self._attach_artist_id(row.id, artist, "track_link", confidence)

    async def _candidates(self, source: SourceTrack) -> list[tuple[uuid.UUID, TrackEvidence]]:
        key = track_matching_key(source.primary_artist.name, source.title)
        by_key = select(Track.id).where(Track.matching_key == key)
        if source.isrcs:
            by_isrc = select(TrackExternalId.track_id).where(
                TrackExternalId.provider == ISRC_PROVIDER,
                TrackExternalId.external_id.in_(source.isrcs),
            )
            ids = list((await self.session.scalars(by_key.union(by_isrc))).all())
        else:
            ids = list((await self.session.scalars(by_key)).all())
        if not ids:
            return []
        return await self.load_evidence(ids)

    async def load_evidence(
        self, track_ids: Sequence[uuid.UUID]
    ) -> list[tuple[uuid.UUID, TrackEvidence]]:
        credits = (
            select(TrackArtist.track_id, func.array_agg(TrackArtist.credited_name).label("names"))
            .where(TrackArtist.track_id.in_(track_ids))
            .group_by(TrackArtist.track_id)
            .subquery()
        )
        isrcs = (
            select(
                TrackExternalId.track_id, func.array_agg(TrackExternalId.external_id).label("isrcs")
            )
            .where(
                TrackExternalId.track_id.in_(track_ids), TrackExternalId.provider == ISRC_PROVIDER
            )
            .group_by(TrackExternalId.track_id)
            .subquery()
        )
        rows = await self.session.execute(
            select(
                Track.id,
                Track.title,
                Track.duration_ms,
                Album.title,
                credits.c.names,
                isrcs.c.isrcs,
            )
            .outerjoin(Album, Album.id == Track.album_id)
            .outerjoin(credits, credits.c.track_id == Track.id)
            .outerjoin(isrcs, isrcs.c.track_id == Track.id)
            .where(Track.id.in_(track_ids))
        )
        evidence: list[tuple[uuid.UUID, TrackEvidence]] = []
        for track_id, title, duration_ms, album_title, names, track_isrcs in rows:
            evidence.append(
                (
                    track_id,
                    TrackEvidence(
                        title=title,
                        artists=tuple(names or ()),
                        duration_ms=duration_ms,
                        isrcs=frozenset(track_isrcs or ()),
                        album=album_title,
                    ),
                )
            )
        return evidence


def outcome_counts(results: Sequence[TrackWriteResult]) -> dict[str, Any]:
    counts: dict[str, Any] = defaultdict(int)
    for result in results:
        counts[result.outcome.value] += 1
    return dict(counts)
