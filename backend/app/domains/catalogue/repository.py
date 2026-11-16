"""Read access to the canonical catalogue."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import (
    Album,
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
    CreditOut,
    ExternalIdOut,
    FeaturesOut,
    GenreOut,
    SourceOut,
    TrackDetail,
    TrackSummary,
)

# pg_trgm similarity below which search results are noise.
MIN_SEARCH_SIMILARITY = 0.2


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
            )
            .join(TrackArtist, TrackArtist.track_id == Track.id)
            .where(Track.id.in_(track_ids))
            .order_by(Track.id, TrackArtist.position)
        )
        summaries: dict[uuid.UUID, TrackSummary] = {}
        credits: dict[uuid.UUID, list[tuple[str, str]]] = {}
        for track_id, title, duration_ms, release_year, name, join_phrase in rows:
            credits.setdefault(track_id, []).append((name, join_phrase))
            summaries[track_id] = TrackSummary(
                id=track_id,
                title=title,
                artist="",
                duration_ms=duration_ms,
                release_year=release_year,
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
        statement: Select[uuid.UUID] = (
            select(Track.id)
            .join(Artist, Artist.id == Track.artist_id)
            # `%` uses the trigram index on titles; `<%` matches the query inside "artist title".
            .where(
                Track.normalized_title.bool_op("%")(normalized)
                | literal(normalized).bool_op("<%")(haystack)
            )
            .where(score >= MIN_SEARCH_SIMILARITY)
            .order_by(score.desc(), Track.title)
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
