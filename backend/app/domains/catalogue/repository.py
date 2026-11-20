"""Read access to the canonical catalogue."""

import uuid
from collections.abc import Sequence

from sqlalchemy import ScalarSelect, Select, func, literal, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.catalogue.models import (
    Album,
    AlbumExternalId,
    Artist,
    ArtistExternalId,
    ArtistGenre,
    DataSource,
    Genre,
    Track,
    TrackArtist,
    TrackExternalId,
    TrackFeatures,
    TrackGenre,
)
from app.domains.catalogue.normalization import normalize_name
from app.domains.catalogue.schemas import (
    AlbumRef,
    ArtistDetail,
    ArtistSummary,
    CreditOut,
    ExternalIdOut,
    FeaturesOut,
    GenreOut,
    GenreSummary,
    SourceOut,
    TrackDetail,
    TrackSummary,
)

# pg_trgm similarity below which search results are noise.
MIN_SEARCH_SIMILARITY = 0.2


def cover_art_url(release_group_mbid: str | None) -> str | None:
    """Cover Art Archive front cover of a MusicBrainz release group (ADR-017 for the posture)."""
    settings = get_settings()
    if not release_group_mbid or not settings.cover_art_enabled:
        return None
    return settings.cover_art_url.format(mbid=release_group_mbid)


def release_group_mbid() -> ScalarSelect[str]:
    """Correlated scalar subquery: the MusicBrainz release-group id of `Album`."""
    return (
        select(func.min(AlbumExternalId.external_id))
        .where(AlbumExternalId.album_id == Album.id, AlbumExternalId.provider == "musicbrainz")
        .correlate(Album)
        .scalar_subquery()
    )


def credit_display(credits: Sequence[tuple[str, str]]) -> str:
    """Join (credited_name, join_phrase) pairs the way MusicBrainz displays artist credits."""
    return "".join(f"{name}{join_phrase}" for name, join_phrase in credits).strip()


class CatalogueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_track_id(self, provider: str, external_id: str) -> uuid.UUID | None:
        return await self.session.scalar(
            select(TrackExternalId.track_id).where(
                TrackExternalId.provider == provider, TrackExternalId.external_id == external_id
            )
        )

    async def track_summaries(
        self, track_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, TrackSummary]:
        if not track_ids:
            return {}
        rows = await self.session.execute(
            select(
                Track.id,
                Track.title,
                Track.duration_ms,
                Track.release_year,
                TrackArtist.credited_name,
                TrackArtist.join_phrase,
                Track.artist_id,
                Album.title,
                release_group_mbid(),
            )
            .join(TrackArtist, TrackArtist.track_id == Track.id)
            .outerjoin(Album, Album.id == Track.album_id)
            .where(Track.id.in_(set(track_ids)))
            .order_by(Track.id, TrackArtist.position)
        )
        summaries: dict[uuid.UUID, TrackSummary] = {}
        credits: dict[uuid.UUID, list[tuple[str, str]]] = {}
        for row in rows:
            track_id, title, duration_ms, release_year, name, join_phrase = row[:6]
            artist_id, album, mbid = row[6:]
            credits.setdefault(track_id, []).append((name, join_phrase))
            summaries[track_id] = TrackSummary(
                id=track_id,
                title=title,
                artist="",
                duration_ms=duration_ms,
                release_year=release_year,
                artist_id=artist_id,
                album_title=album,
                artwork_url=cover_art_url(mbid),
            )
        return {
            track_id: summary.model_copy(update={"artist": credit_display(credits[track_id])})
            for track_id, summary in summaries.items()
        }

    async def search_tracks(self, query: str, limit: int) -> list[TrackSummary]:
        """Fuzzy search over "artist title" using trigram similarity."""
        normalized = normalize_name(query)
        if not normalized:
            return []
        # A function call (not `||`) so custom operators below bind to the whole "artist title".
        haystack = func.concat(Artist.normalized_name, literal(" "), Track.normalized_title)
        score = func.greatest(
            func.similarity(Track.normalized_title, normalized),
            func.word_similarity(normalized, haystack),
        )
        needle = literal(normalized)
        # Candidates come only through the trigram indexes (Milestone 7: a condition on the
        # concatenated "artist title" cannot use an index and scanned every track): tracks whose
        # title matches the query or contains it as a word, and tracks of artists whose name
        # matches or is contained. The same score then ranks just those candidates.
        by_title = select(Track.id.label("id")).where(
            Track.normalized_title.bool_op("%")(normalized)
            | needle.bool_op("<%")(Track.normalized_title)
        )
        by_artist = (
            select(Track.id.label("id"))
            .join(Artist, Artist.id == Track.artist_id)
            .where(
                Artist.normalized_name.bool_op("%")(normalized)
                | needle.bool_op("<%")(Artist.normalized_name)
            )
        )
        candidates = union(by_title, by_artist).subquery()
        statement: Select[uuid.UUID] = (
            select(Track.id)
            .join(candidates, candidates.c.id == Track.id)
            .join(Artist, Artist.id == Track.artist_id)
            # The original match rule, now evaluated on the candidates only.
            .where(Track.normalized_title.bool_op("%")(normalized) | needle.bool_op("<%")(haystack))
            .where(score >= MIN_SEARCH_SIMILARITY)
            .order_by(score.desc(), Track.title, Track.id)
            .limit(limit)
        )
        ids = list((await self.session.scalars(statement)).all())
        summaries = await self.track_summaries(ids)
        return [summaries[track_id] for track_id in ids if track_id in summaries]

    async def get_track(self, track_id: uuid.UUID) -> TrackDetail | None:
        track = await self.session.get(Track, track_id)
        if track is None:
            return None
        credit_rows = (
            await self.session.execute(
                select(TrackArtist.artist_id, TrackArtist.credited_name, TrackArtist.join_phrase)
                .where(TrackArtist.track_id == track_id)
                .order_by(TrackArtist.position)
            )
        ).all()
        album = await self.session.get(Album, track.album_id) if track.album_id else None
        album_mbid = (
            await self.session.scalar(
                select(func.min(AlbumExternalId.external_id)).where(
                    AlbumExternalId.album_id == album.id,
                    AlbumExternalId.provider == "musicbrainz",
                )
            )
            if album
            else None
        )
        genre_rows = await self.session.execute(
            select(Genre.name, TrackGenre.weight, TrackGenre.level, DataSource.key)
            .join(Genre, Genre.id == TrackGenre.genre_id)
            .join(DataSource, DataSource.id == TrackGenre.source_id)
            .where(TrackGenre.track_id == track_id)
            .order_by(TrackGenre.level, TrackGenre.weight.desc())
        )
        feature_rows = (
            await self.session.scalars(
                select(TrackFeatures).where(TrackFeatures.track_id == track_id)
            )
        ).all()
        id_rows = (
            await self.session.scalars(
                select(TrackExternalId)
                .where(TrackExternalId.track_id == track_id)
                .order_by(TrackExternalId.provider, TrackExternalId.external_id)
            )
        ).all()
        genre_source_ids = await self.session.scalars(
            select(TrackGenre.source_id).where(TrackGenre.track_id == track_id).distinct()
        )
        # Every source that contributed identifiers, genres or features, so licences are complete.
        source_ids = {
            track.source_id,
            *(row.source_id for row in id_rows),
            *(row.source_id for row in feature_rows),
            *genre_source_ids,
        }
        sources = (
            await self.session.scalars(
                select(DataSource).where(DataSource.id.in_(source_ids)).order_by(DataSource.key)
            )
        ).all()
        return TrackDetail(
            id=track.id,
            title=track.title,
            artist=credit_display([(name, join) for _, name, join in credit_rows]),
            duration_ms=track.duration_ms,
            release_year=track.release_year,
            artist_id=track.artist_id,
            album_title=album.title if album else None,
            artwork_url=cover_art_url(album_mbid),
            isrc=track.isrc,
            credits=[
                CreditOut(artist_id=artist_id, name=name, join_phrase=join)
                for artist_id, name, join in credit_rows
            ],
            album=AlbumRef(
                id=album.id,
                title=album.title,
                album_type=album.album_type,
                release_year=album.release_year,
            )
            if album
            else None,
            genres=[
                GenreOut(name=name, weight=round(weight, 4), level=level, source=source)
                for name, weight, level, source in genre_rows
            ],
            features=[
                FeaturesOut(
                    source=row.feature_source,
                    version=row.feature_version,
                    tempo=row.tempo,
                    energy=row.energy,
                    danceability=row.danceability,
                    valence=row.valence,
                    acousticness=row.acousticness,
                    instrumentalness=row.instrumentalness,
                    loudness=row.loudness,
                    onset_rate=row.onset_rate,
                )
                for row in feature_rows
            ],
            external_ids=[
                ExternalIdOut(
                    provider=row.provider,
                    external_id=row.external_id,
                    match_method=row.match_method,
                    confidence=row.confidence,
                )
                for row in id_rows
            ],
            sources=[
                SourceOut(key=s.key, license=s.license, usage_restriction=s.usage_restriction)
                for s in sources
            ],
        )

    async def get_artist(self, artist_id: uuid.UUID) -> ArtistDetail | None:
        artist = await self.session.get(Artist, artist_id)
        if artist is None:
            return None
        genre_rows = await self.session.execute(
            select(Genre.name, ArtistGenre.weight, DataSource.key)
            .join(Genre, Genre.id == ArtistGenre.genre_id)
            .join(DataSource, DataSource.id == ArtistGenre.source_id)
            .where(ArtistGenre.artist_id == artist_id)
            .order_by(ArtistGenre.weight.desc())
        )
        id_rows = (
            await self.session.scalars(
                select(ArtistExternalId).where(ArtistExternalId.artist_id == artist_id)
            )
        ).all()
        track_count = await self.session.scalar(
            select(func.count(func.distinct(TrackArtist.track_id))).where(
                TrackArtist.artist_id == artist_id
            )
        )
        return ArtistDetail(
            id=artist.id,
            name=artist.name,
            artist_type=artist.artist_type,
            area=artist.area,
            begin_year=artist.begin_year,
            genres=[
                GenreOut(name=name, weight=round(weight, 4), level="artist", source=source)
                for name, weight, source in genre_rows
            ],
            external_ids=[
                ExternalIdOut(
                    provider=row.provider,
                    external_id=row.external_id,
                    match_method=row.match_method,
                    confidence=row.confidence,
                )
                for row in id_rows
            ],
            track_count=track_count or 0,
        )

    async def search_artists(self, query: str, limit: int) -> list[ArtistSummary]:
        """Fuzzy artist search (trigram index on normalized names); best match first, then the
        artists with more catalogue tracks."""
        normalized = normalize_name(query)
        if not normalized:
            return []
        score = func.similarity(Artist.normalized_name, normalized)
        track_count = (
            select(func.count(Track.id)).where(Track.artist_id == Artist.id).scalar_subquery()
        )
        rows = (
            await self.session.execute(
                select(Artist.id, Artist.name, Artist.area, track_count)
                .where(
                    Artist.normalized_name.bool_op("%")(normalized)
                    | Artist.normalized_name.startswith(normalized)
                )
                .where(track_count > 0)
                .order_by(score.desc(), track_count.desc(), Artist.name)
                .limit(limit)
            )
        ).all()
        return await self.artist_summaries([(r[0], r[1], r[2], int(r[3])) for r in rows])

    async def artist_summaries(
        self, rows: Sequence[tuple[uuid.UUID, str, str | None, int]]
    ) -> list[ArtistSummary]:
        ids = [r[0] for r in rows]
        if not ids:
            return []
        genre_rows = await self.session.execute(
            select(ArtistGenre.artist_id, Genre.name)
            .join(Genre, Genre.id == ArtistGenre.genre_id)
            .where(ArtistGenre.artist_id.in_(ids))
            .order_by(ArtistGenre.artist_id, ArtistGenre.vote_count.desc(), Genre.name)
        )
        genres: dict[uuid.UUID, list[str]] = {}
        for artist_id, name in genre_rows:
            if len(genres.setdefault(artist_id, [])) < 3:
                genres[artist_id].append(name)
        cover = (
            select(Album.primary_artist_id, func.min(AlbumExternalId.external_id))
            .join(AlbumExternalId, AlbumExternalId.album_id == Album.id)
            .where(
                Album.primary_artist_id.in_(ids),
                AlbumExternalId.provider == "musicbrainz",
            )
            .group_by(Album.primary_artist_id)
        )
        covers = {row[0]: row[1] for row in await self.session.execute(cover)}
        return [
            ArtistSummary(
                id=artist_id,
                name=name,
                area=area,
                genres=genres.get(artist_id, []),
                track_count=tracks,
                artwork_url=cover_art_url(covers.get(artist_id)),
            )
            for artist_id, name, area, tracks in rows
        ]

    async def top_genres(self, limit: int) -> list[GenreSummary]:
        """Genres with the most tagged tracks in the served catalogue."""
        tracks = func.count(func.distinct(TrackGenre.track_id))
        rows = await self.session.execute(
            select(Genre.name, tracks)
            .join(TrackGenre, TrackGenre.genre_id == Genre.id)
            .join(Track, Track.id == TrackGenre.track_id)
            .join(DataSource, DataSource.id == Track.source_id)
            .where(DataSource.usage_restriction != "research_only")
            .group_by(Genre.name)
            .order_by(tracks.desc(), Genre.name)
            .limit(limit)
        )
        return [GenreSummary(name=name, tracks=int(count)) for name, count in rows]
