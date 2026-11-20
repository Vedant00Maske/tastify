"""Data access for serving recommendations: model versions, vector search and ranking facts."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Float,
    Select,
    and_,
    case,
    cast,
    func,
    literal,
    select,
    text,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memo import TimedCache
from app.domains.catalogue.models import (
    Artist,
    ArtistGenre,
    Genre,
    Track,
    TrackFeatures,
    TrackGenre,
)
from app.domains.recommendations.models import (
    ArtistEmbedding,
    ModelArtifact,
    ModelVersion,
    TrackCollaborativeFactors,
    TrackEmbedding,
    TrackNeighbour,
    TrackPopularity,
)
from app.domains.recommendations.ranking import GENRE_PRIOR_VOTES, LEVEL_WEIGHTS, song_key


@dataclass(frozen=True, slots=True)
class TrackFacts:
    artist_id: uuid.UUID
    # ranking.song_key: versions of the same song share it.
    song_key: str
    release_year: int | None
    popularity: float
    listeners: int


@dataclass(frozen=True, slots=True)
class PopularRow:
    track_id: uuid.UUID
    score: float
    listeners: int
    recent_listeners: int
    trending_score: float | None


@dataclass(frozen=True, slots=True)
class TagMember:
    track_id: uuid.UUID
    genre: str
    affinity: float
    popularity: float
    listeners: int
    tempo: float | None
    danceability: float | None


@dataclass(frozen=True, slots=True)
class GenreMember:
    track_id: uuid.UUID
    affinity: float
    popularity: float
    listeners: int


def _level_weight(level: ColumnElement[str]) -> ColumnElement[float]:
    """SQL CASE mapping a track_genres level to its LEVEL_WEIGHTS factor."""
    return case(
        *((level == name, literal(weight)) for name, weight in LEVEL_WEIGHTS.items()),
        else_=literal(0.0),
    )


def _track_tag_weights(
    where: ColumnElement[bool],
) -> Select[tuple[uuid.UUID, uuid.UUID, str, float]]:
    """(track_id, genre_id, level, weight) for track tags matching `where`, with weight =
    ranking.smoothed_tag_weight over the votes of the same track, source and level."""
    tags = select(TrackGenre).where(where).subquery()
    totals = (
        select(
            TrackGenre.track_id,
            TrackGenre.source_id,
            TrackGenre.level,
            func.sum(TrackGenre.vote_count).label("total"),
        )
        .where(TrackGenre.track_id.in_(select(tags.c.track_id)))
        .group_by(TrackGenre.track_id, TrackGenre.source_id, TrackGenre.level)
        .subquery()
    )
    weight = cast(tags.c.vote_count, Float) / (totals.c.total + GENRE_PRIOR_VOTES)
    return select(tags.c.track_id, tags.c.genre_id, tags.c.level, weight.label("weight")).join(
        totals,
        and_(
            totals.c.track_id == tags.c.track_id,
            totals.c.source_id == tags.c.source_id,
            totals.c.level == tags.c.level,
        ),
    )


def _artist_tag_weights(where: ColumnElement[bool]) -> Select[tuple[uuid.UUID, uuid.UUID, float]]:
    """(artist_id, genre_id, weight) for artist tags matching `where`, smoothed per artist and
    source."""
    tags = select(ArtistGenre).where(where).subquery()
    totals = (
        select(
            ArtistGenre.artist_id,
            ArtistGenre.source_id,
            func.sum(ArtistGenre.vote_count).label("total"),
        )
        .where(ArtistGenre.artist_id.in_(select(tags.c.artist_id)))
        .group_by(ArtistGenre.artist_id, ArtistGenre.source_id)
        .subquery()
    )
    weight = cast(tags.c.vote_count, Float) / (totals.c.total + GENRE_PRIOR_VOTES)
    return select(tags.c.artist_id, tags.c.genre_id, weight.label("weight")).join(
        totals,
        and_(totals.c.artist_id == tags.c.artist_id, totals.c.source_id == tags.c.source_id),
    )


# Genre and tag member rankings (Milestone 7): expensive queries (hundreds of ms) whose results
# depend only on the catalogue and the popularity version in the key. One hour bounds staleness
# after a catalogue update that keeps the version.
MEMBERS: TimedCache[list[Any]] = TimedCache("genre_members", size=512, ttl_seconds=3600)


def _floats(vector: Any) -> list[float]:
    """A stored vector as Python floats. pgvector returns numpy arrays: `tolist` converts in C,
    with the same values as converting element by element."""
    if hasattr(vector, "tolist"):
        return list(vector.tolist())
    return [float(v) for v in vector]


class RecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_version(self, model_type: str) -> ModelVersion | None:
        return await self.session.scalar(
            select(ModelVersion).where(
                ModelVersion.model_type == model_type, ModelVersion.status == "active"
            )
        )

    # --- vectors -----------------------------------------------------------------------------

    async def track_embedding(
        self, version_id: uuid.UUID, track_id: uuid.UUID
    ) -> list[float] | None:
        vector = await self.session.scalar(
            select(TrackEmbedding.embedding).where(
                TrackEmbedding.model_version_id == version_id, TrackEmbedding.track_id == track_id
            )
        )
        return None if vector is None else _floats(vector)

    async def artist_embedding(
        self, version_id: uuid.UUID, artist_id: uuid.UUID
    ) -> list[float] | None:
        vector = await self.session.scalar(
            select(ArtistEmbedding.embedding).where(
                ArtistEmbedding.model_version_id == version_id,
                ArtistEmbedding.artist_id == artist_id,
            )
        )
        return None if vector is None else _floats(vector)

    async def _tune_search(self, ef_search: int) -> None:
        # Scoped to the current transaction. iterative_scan keeps exact result counts when the
        # version filter removes rows the index returned (e.g. while two versions coexist).
        await self.session.execute(
            text(
                "SELECT set_config('hnsw.ef_search', :ef, true), "
                "set_config('hnsw.iterative_scan', 'strict_order', true)"
            ),
            {"ef": str(ef_search)},
        )

    async def nearest_tracks(
        self, version_id: uuid.UUID, vector: Sequence[float], limit: int, ef_search: int
    ) -> list[tuple[uuid.UUID, float]]:
        """Approximate nearest tracks by cosine similarity (HNSW index), most similar first."""
        await self._tune_search(ef_search)
        distance = TrackEmbedding.embedding.cosine_distance(vector)
        rows = await self.session.execute(
            select(TrackEmbedding.track_id, distance)
            .where(TrackEmbedding.model_version_id == version_id)
            .order_by(distance)
            .limit(limit)
        )
        return [(track_id, 1.0 - float(d)) for track_id, d in rows]

    async def nearest_tracks_for_seeds(
        self, version_id: uuid.UUID, seeds: Sequence[uuid.UUID], limit: int, ef_search: int
    ) -> dict[uuid.UUID, list[tuple[uuid.UUID, float]]]:
        """`nearest_tracks` for many seed tracks in one round trip (Milestone 7 optimization):
        a LATERAL join runs one HNSW index search per seed, using the seeds' stored embeddings.
        Seeds without an embedding in this version are absent from the result."""
        if not seeds:
            return {}
        await self._tune_search(ef_search)
        rows = await self.session.execute(
            text(
                """
                SELECT s.track_id AS seed, n.track_id, n.distance
                FROM track_embeddings AS s
                CROSS JOIN LATERAL (
                    SELECT e.track_id, e.embedding <=> s.embedding AS distance
                    FROM track_embeddings AS e
                    WHERE e.model_version_id = :version
                    ORDER BY e.embedding <=> s.embedding
                    LIMIT :limit
                ) AS n
                WHERE s.model_version_id = :version AND s.track_id = ANY(:seeds)
                ORDER BY s.track_id, n.distance
                """
            ),
            {"version": version_id, "seeds": list(seeds), "limit": limit},
        )
        found: dict[uuid.UUID, list[tuple[uuid.UUID, float]]] = {}
        for seed, track_id, distance in rows:
            found.setdefault(seed, []).append((track_id, 1.0 - float(distance)))
        return found

    async def nearest_artists(
        self, version_id: uuid.UUID, vector: Sequence[float], limit: int, ef_search: int
    ) -> list[tuple[uuid.UUID, float]]:
        await self._tune_search(ef_search)
        distance = ArtistEmbedding.embedding.cosine_distance(vector)
        rows = await self.session.execute(
            select(ArtistEmbedding.artist_id, distance)
            .where(ArtistEmbedding.model_version_id == version_id)
            .order_by(distance)
            .limit(limit)
        )
        return [(artist_id, 1.0 - float(d)) for artist_id, d in rows]

    # --- ranking facts -----------------------------------------------------------------------

    async def track_facts(
        self, track_ids: Sequence[uuid.UUID], popularity_version_id: uuid.UUID | None
    ) -> dict[uuid.UUID, TrackFacts]:
        if not track_ids:
            return {}
        popularity = TrackPopularity.__table__.alias("p")
        rows = await self.session.execute(
            select(
                Track.id,
                Track.artist_id,
                Track.title,
                Track.release_year,
                func.coalesce(popularity.c.score, 0.0),
                func.coalesce(popularity.c.listeners, 0),
            )
            .outerjoin(
                popularity,
                and_(
                    popularity.c.track_id == Track.id,
                    popularity.c.model_version_id == popularity_version_id,
                ),
            )
            .where(Track.id.in_(track_ids))
        )
        return {
            track_id: TrackFacts(
                artist_id, song_key(artist_id, title), year, float(score), int(listeners)
            )
            for track_id, artist_id, title, year, score, listeners in rows
        }

    async def top_tracks_by_artist(
        self,
        artist_ids: Sequence[uuid.UUID],
        content_version_id: uuid.UUID,
        popularity_version_id: uuid.UUID | None,
        per_artist: int,
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """Each artist's most popular tracks among those in the content model (ties by id)."""
        if not artist_ids:
            return {}
        popularity = TrackPopularity.__table__.alias("p")
        score = func.coalesce(popularity.c.score, 0.0)
        rank = (
            func.row_number()
            .over(partition_by=Track.artist_id, order_by=(score.desc(), Track.id))
            .label("rank")
        )
        ranked = (
            select(Track.artist_id, Track.id.label("track_id"), rank)
            .join(
                TrackEmbedding,
                and_(
                    TrackEmbedding.track_id == Track.id,
                    TrackEmbedding.model_version_id == content_version_id,
                ),
            )
            .outerjoin(
                popularity,
                and_(
                    popularity.c.track_id == Track.id,
                    popularity.c.model_version_id == popularity_version_id,
                ),
            )
            .where(Track.artist_id.in_(artist_ids))
            .subquery()
        )
        rows = await self.session.execute(
            select(ranked.c.artist_id, ranked.c.track_id)
            .where(ranked.c.rank <= per_artist)
            .order_by(ranked.c.artist_id, ranked.c.rank)
        )
        tracks: dict[uuid.UUID, list[uuid.UUID]] = {}
        for artist_id, track_id in rows:
            tracks.setdefault(artist_id, []).append(track_id)
        return tracks

    async def genre_profiles(
        self, track_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float]]:
        """Per track: genre -> sum over levels of level factor x smoothed tag weight (strongest
        source per level), exactly as the content model builds its genre profiles."""
        if not track_ids:
            return {}
        track_tags = _track_tag_weights(TrackGenre.track_id.in_(track_ids)).subquery()
        track_level = select(
            track_tags.c.track_id,
            track_tags.c.genre_id,
            (func.max(track_tags.c.weight) * _level_weight(track_tags.c.level)).label("value"),
        ).group_by(track_tags.c.track_id, track_tags.c.genre_id, track_tags.c.level)
        artist_ids = select(Track.artist_id).where(Track.id.in_(track_ids))
        artist_tags = _artist_tag_weights(ArtistGenre.artist_id.in_(artist_ids)).subquery()
        artist_level = (
            select(
                Track.id,
                artist_tags.c.genre_id,
                (func.max(artist_tags.c.weight) * LEVEL_WEIGHTS["artist"]).label("value"),
            )
            .join(artist_tags, artist_tags.c.artist_id == Track.artist_id)
            .where(Track.id.in_(track_ids))
            .group_by(Track.id, artist_tags.c.genre_id)
        )
        tags = union_all(track_level, artist_level).subquery()
        rows = await self.session.execute(
            select(tags.c.track_id, Genre.name, func.sum(tags.c.value))
            .join(Genre, Genre.id == tags.c.genre_id)
            .group_by(tags.c.track_id, Genre.name)
        )
        profiles: dict[uuid.UUID, dict[str, float]] = {}
        for track_id, name, value in rows:
            profiles.setdefault(track_id, {})[name] = float(value)
        return profiles

    async def artist_genres(self, artist_id: uuid.UUID) -> dict[str, float]:
        tags = _artist_tag_weights(ArtistGenre.artist_id == artist_id).subquery()
        rows = await self.session.execute(
            select(Genre.name, func.max(tags.c.weight))
            .join(Genre, Genre.id == tags.c.genre_id)
            .group_by(Genre.name)
        )
        return {name: float(weight) for name, weight in rows}

    # --- genres and popularity ---------------------------------------------------------------

    async def find_genre(self, name: str) -> Genre | None:
        wanted = name.strip().lower()
        candidates = (
            wanted,
            wanted.replace("-", " "),
            wanted.replace("_", " "),
            wanted.replace(" ", "-"),
        )
        genres = (
            await self.session.scalars(select(Genre).where(func.lower(Genre.name).in_(candidates)))
        ).all()
        # Prefer the exact spelling ("k-pop" over "k pop").
        return min(genres, key=lambda g: candidates.index(g.name.lower()), default=None)

    async def genre_members(
        self,
        genre_id: uuid.UUID,
        popularity_version_id: uuid.UUID,
        min_affinity: float,
        popularity_weight: float,
        limit: int,
    ) -> list[GenreMember]:
        """`_genre_members`, cached per process (MEMBERS): the same for every user."""
        key = ("genre", genre_id, popularity_version_id, min_affinity, popularity_weight, limit)
        cached = MEMBERS.get(key)
        if cached is None:
            cached = await self._genre_members(
                genre_id, popularity_version_id, min_affinity, popularity_weight, limit
            )
            MEMBERS.put(key, cached)
        return list(cached)

    async def _genre_members(
        self,
        genre_id: uuid.UUID,
        popularity_version_id: uuid.UUID,
        min_affinity: float,
        popularity_weight: float,
        limit: int,
    ) -> list[GenreMember]:
        """Tracks tagged with the genre, best genre score first (see ranking.genre_score).

        Affinity = strongest level factor x smoothed tag weight over the track's recording and
        album tags and its artist's tags (ranking.genre_affinity)."""
        track_tags = _track_tag_weights(TrackGenre.genre_id == genre_id).subquery()
        artist_tags = _artist_tag_weights(ArtistGenre.genre_id == genre_id).subquery()
        tagged = union_all(
            select(
                track_tags.c.track_id.label("track_id"),
                (track_tags.c.weight * _level_weight(track_tags.c.level)).label("affinity"),
            ),
            select(
                Track.id.label("track_id"),
                (artist_tags.c.weight * LEVEL_WEIGHTS["artist"]).label("affinity"),
            ).join(artist_tags, artist_tags.c.artist_id == Track.artist_id),
        ).subquery()
        affinity = (
            select(tagged.c.track_id, func.max(tagged.c.affinity).label("affinity"))
            .group_by(tagged.c.track_id)
            .subquery()
        )
        score = cast(
            (1.0 - popularity_weight) * affinity.c.affinity
            + popularity_weight * TrackPopularity.score,
            Float,
        )
        rows = await self.session.execute(
            select(
                affinity.c.track_id,
                affinity.c.affinity,
                TrackPopularity.score,
                TrackPopularity.listeners,
            )
            .join(TrackPopularity, TrackPopularity.track_id == affinity.c.track_id)
            .where(
                TrackPopularity.model_version_id == popularity_version_id,
                affinity.c.affinity >= min_affinity,
            )
            .order_by(score.desc(), affinity.c.track_id)
            .limit(limit)
        )
        return [
            GenreMember(track_id, float(a), float(p), int(listeners))
            for track_id, a, p, listeners in rows
        ]

    async def popular(
        self,
        popularity_version_id: uuid.UUID,
        limit: int,
        *,
        trending: bool = False,
        artist_id: uuid.UUID | None = None,
    ) -> list[PopularRow]:
        statement = select(
            TrackPopularity.track_id,
            TrackPopularity.score,
            TrackPopularity.listeners,
            TrackPopularity.recent_listeners,
            TrackPopularity.trending_score,
        ).where(TrackPopularity.model_version_id == popularity_version_id)
        if artist_id is not None:
            statement = statement.join(Track, Track.id == TrackPopularity.track_id).where(
                Track.artist_id == artist_id
            )
        if trending:
            # Only reliable, rising trends (trending_score is NULL when unreliable).
            statement = statement.where(TrackPopularity.trending_score > 0).order_by(
                TrackPopularity.trending_score.desc(),
                TrackPopularity.listeners.desc(),
                TrackPopularity.track_id,
            )
        else:
            statement = statement.where(TrackPopularity.listeners > 0).order_by(
                TrackPopularity.listeners.desc(), TrackPopularity.track_id
            )
        rows = await self.session.execute(statement.limit(limit))
        return [PopularRow(*row) for row in rows]

    async def artist_name(self, artist_id: uuid.UUID) -> str | None:
        return await self.session.scalar(select(Artist.name).where(Artist.id == artist_id))

    # --- Milestone 3: vectors by id, collaborative data and artifacts ------------------------

    async def track_embeddings(
        self, version_id: uuid.UUID, track_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[float]]:
        if not track_ids:
            return {}
        rows = await self.session.execute(
            select(TrackEmbedding.track_id, TrackEmbedding.embedding).where(
                TrackEmbedding.model_version_id == version_id,
                TrackEmbedding.track_id.in_(set(track_ids)),
            )
        )
        return {t: _floats(e) for t, e in rows}

    async def artist_embeddings(
        self, version_id: uuid.UUID, artist_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[float]]:
        if not artist_ids:
            return {}
        rows = await self.session.execute(
            select(ArtistEmbedding.artist_id, ArtistEmbedding.embedding).where(
                ArtistEmbedding.model_version_id == version_id,
                ArtistEmbedding.artist_id.in_(set(artist_ids)),
            )
        )
        return {a: _floats(e) for a, e in rows}

    async def cf_factors(
        self, version_id: uuid.UUID, track_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[list[float], float]]:
        """track_id -> (ALS factors, BM25 idf)."""
        if not track_ids:
            return {}
        rows = await self.session.execute(
            select(
                TrackCollaborativeFactors.track_id,
                TrackCollaborativeFactors.factors,
                TrackCollaborativeFactors.idf,
            ).where(
                TrackCollaborativeFactors.model_version_id == version_id,
                TrackCollaborativeFactors.track_id.in_(set(track_ids)),
            )
        )
        return {t: (_floats(f), float(idf)) for t, f, idf in rows}

    async def nearest_by_inner_product(
        self, version_id: uuid.UUID, vector: Sequence[float], limit: int, ef_search: int
    ) -> list[tuple[uuid.UUID, float]]:
        """Tracks with the largest factors . vector (HNSW on the negative inner product)."""
        await self._tune_search(ef_search)
        distance = TrackCollaborativeFactors.factors.max_inner_product(vector)
        rows = await self.session.execute(
            select(TrackCollaborativeFactors.track_id, distance)
            .where(TrackCollaborativeFactors.model_version_id == version_id)
            .order_by(distance)
            .limit(limit)
        )
        return [(track_id, -float(d)) for track_id, d in rows]

    async def neighbour_rows(
        self, version_id: uuid.UUID, track_ids: Sequence[uuid.UUID]
    ) -> list[tuple[uuid.UUID, uuid.UUID, float]]:
        """Item-item neighbour rows (track, neighbour, similarity) of the given tracks."""
        if not track_ids:
            return []
        rows = await self.session.execute(
            select(
                TrackNeighbour.track_id, TrackNeighbour.neighbour_id, TrackNeighbour.score
            ).where(
                TrackNeighbour.model_version_id == version_id,
                TrackNeighbour.track_id.in_(set(track_ids)),
            )
        )
        return [(t, n, float(s)) for t, n, s in rows]

    async def artifact(self, version_id: uuid.UUID, name: str) -> ModelArtifact | None:
        return await self.session.get(ModelArtifact, (version_id, name))

    async def song_keys(self, track_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not track_ids:
            return {}
        rows = await self.session.execute(
            select(Track.id, Track.artist_id, Track.title).where(Track.id.in_(set(track_ids)))
        )
        return {t: song_key(a, title) for t, a, title in rows}

    # --- Milestone 4: mood and discovery collections -------------------------------------------

    async def genre_ids(self, names: Sequence[str]) -> dict[str, uuid.UUID]:
        """Genre ids by exact (lower-case) name; unknown names are left out."""
        if not names:
            return {}
        rows = await self.session.execute(
            select(Genre.name, Genre.id).where(
                func.lower(Genre.name).in_([n.lower() for n in names])
            )
        )
        return {name.lower(): genre_id for name, genre_id in rows}

    async def tag_members(
        self,
        genre_ids: Sequence[uuid.UUID],
        popularity_version_id: uuid.UUID,
        min_affinity: float,
        limit: int,
    ) -> list[TagMember]:
        """`_tag_members`, cached per process (MEMBERS): mood mixes and prompt playlists ask for
        the same genre sets again and again, and the answer is the same for every user."""
        key = ("tags", tuple(sorted(genre_ids)), popularity_version_id, min_affinity, limit)
        cached = MEMBERS.get(key)
        if cached is None:
            cached = await self._tag_members(genre_ids, popularity_version_id, min_affinity, limit)
            MEMBERS.put(key, cached)
        return list(cached)

    async def _tag_members(
        self,
        genre_ids: Sequence[uuid.UUID],
        popularity_version_id: uuid.UUID,
        min_affinity: float,
        limit: int,
    ) -> list[TagMember]:
        """Tracks whose strongest affinity to any of `genre_ids` reaches `min_affinity`, with that
        genre, their popularity and AcousticBrainz tempo and danceability (when measured). Most
        central first (affinity, then popularity)."""
        if not genre_ids:
            return []
        track_tags = _track_tag_weights(TrackGenre.genre_id.in_(genre_ids)).subquery()
        artist_tags = _artist_tag_weights(ArtistGenre.genre_id.in_(genre_ids)).subquery()
        tagged = union_all(
            select(
                track_tags.c.track_id.label("track_id"),
                track_tags.c.genre_id.label("genre_id"),
                (track_tags.c.weight * _level_weight(track_tags.c.level)).label("affinity"),
            ),
            select(
                Track.id.label("track_id"),
                artist_tags.c.genre_id.label("genre_id"),
                (artist_tags.c.weight * LEVEL_WEIGHTS["artist"]).label("affinity"),
            ).join(artist_tags, artist_tags.c.artist_id == Track.artist_id),
        ).subquery()
        ranked = select(
            tagged.c.track_id,
            tagged.c.genre_id,
            tagged.c.affinity,
            func.row_number()
            .over(
                partition_by=tagged.c.track_id,
                order_by=(tagged.c.affinity.desc(), tagged.c.genre_id),
            )
            .label("rank"),
        ).subquery()
        features = (
            select(TrackFeatures.track_id, TrackFeatures.tempo, TrackFeatures.danceability)
            .where(TrackFeatures.feature_source == "acousticbrainz")
            .subquery()
        )
        rows = await self.session.execute(
            select(
                ranked.c.track_id,
                Genre.name,
                ranked.c.affinity,
                TrackPopularity.score,
                TrackPopularity.listeners,
                features.c.tempo,
                features.c.danceability,
            )
            .join(Genre, Genre.id == ranked.c.genre_id)
            .join(TrackPopularity, TrackPopularity.track_id == ranked.c.track_id)
            .outerjoin(features, features.c.track_id == ranked.c.track_id)
            .where(
                ranked.c.rank == 1,
                ranked.c.affinity >= min_affinity,
                TrackPopularity.model_version_id == popularity_version_id,
            )
            .order_by(ranked.c.affinity.desc(), TrackPopularity.score.desc(), ranked.c.track_id)
            .limit(limit)
        )
        return [
            TagMember(t, g, float(a), float(p), int(n), tempo, dance)
            for t, g, a, p, n, tempo, dance in rows
        ]
