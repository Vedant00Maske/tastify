"""Recommendation strategies served by the API (Milestone 2, ADR-015).

- similar tracks:  nearest content embeddings of a seed track, re-ranked (popularity blend,
                   artist cap, duplicate removal);
- similar artists: the artist embeddings nearest to a seed artist, then each similar artist's most
                   popular tracks, re-ranked the same way;
- genre:           tracks tagged with a genre, ranked by popularity and genre affinity;
- popular:         overall popularity or reliable trends, optionally for one artist.

All ranking rules live in `ranking.py` and are shared with the offline evaluation.
"""

import logging
import math
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import Artist, Track
from app.domains.catalogue.repository import CatalogueRepository
from app.domains.recommendations import explanations
from app.domains.recommendations.models import ModelVersion
from app.domains.recommendations.ranking import (
    CANDIDATE_POOL,
    DEFAULT_MAX_PER_ARTIST,
    GENRE_POPULARITY_WEIGHT,
    MIN_GENRE_AFFINITY,
    SIMILAR_ARTISTS_POOL,
    TRACKS_PER_SIMILAR_ARTIST,
    Candidate,
    Ranked,
    rerank,
    song_key,
)
from app.domains.recommendations.repository import RecommendationRepository
from app.domains.recommendations.schemas import (
    PopularKind,
    RecommendationItem,
    RecommendationResponse,
    Strategy,
)

logger = logging.getLogger(__name__)

# HNSW candidate list size; at least the number of neighbours requested.
EF_SEARCH = 2 * CANDIDATE_POOL
DEFAULT_BETA = 0.3


class RecommendationError(Exception):
    """Base class for errors the API maps to HTTP responses."""


class NotFoundError(RecommendationError):
    def __init__(self, entity: str) -> None:
        super().__init__(f"{entity} not found")


class NotInModelError(RecommendationError):
    def __init__(self, entity: str) -> None:
        super().__init__(f"{entity} is not covered by the active recommendation model")


class ModelUnavailableError(RecommendationError):
    def __init__(self, model_type: str) -> None:
        super().__init__(f"No active {model_type} model; run `python -m soniqueo_ml recommend all`")


def _beta(version: ModelVersion, mode: str) -> float:
    betas = version.params.get("beta", {})
    return float(betas.get(mode, DEFAULT_BETA))


def _decade(year: int | None) -> int | None:
    return None if year is None else year // 10 * 10


class RecommendationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = RecommendationRepository(session)
        self.catalogue = CatalogueRepository(session)

    async def _require(self, model_type: str) -> ModelVersion:
        version = await self.repository.active_version(model_type)
        if version is None:
            raise ModelUnavailableError(model_type)
        return version

    def _response(
        self,
        strategy: Strategy,
        primary: ModelVersion,
        others: Sequence[ModelVersion | None],
        items: list[RecommendationItem],
    ) -> RecommendationResponse:
        versions = {v.model_type: v.version for v in (primary, *others) if v is not None}
        response = RecommendationResponse(
            request_id=uuid.uuid4(),
            model_version=primary.version,
            model_versions=versions,
            strategy=strategy,
            recommendations=items,
        )
        logger.info(
            "recommendations request_id=%s strategy=%s model=%s count=%d",
            response.request_id,
            strategy.value,
            primary.version,
            len(items),
        )
        return response

    async def _items(
        self, ranked: Sequence[Ranked[uuid.UUID]], reasons: dict[uuid.UUID, str]
    ) -> list[RecommendationItem]:
        summaries = await self.catalogue.track_summaries([r.item for r in ranked])
        return [
            RecommendationItem(
                track_id=r.item,
                title=summaries[r.item].title,
                artist=summaries[r.item].artist,
                artist_id=summaries[r.item].artist_id,
                album=summaries[r.item].album_title,
                artwork_url=summaries[r.item].artwork_url,
                score=round(r.score, 4),
                reason=reasons[r.item],
            )
            for r in ranked
            if r.item in summaries
        ]

    # --- similar tracks ----------------------------------------------------------------------

    async def similar_tracks(
        self, track_id: uuid.UUID, limit: int, max_per_artist: int = DEFAULT_MAX_PER_ARTIST
    ) -> RecommendationResponse:
        content = await self._require("content")
        popularity = await self.repository.active_version("popularity")
        seed = await self.session.get(Track, track_id)
        if seed is None:
            raise NotFoundError("Track")
        vector = await self.repository.track_embedding(content.id, track_id)
        if vector is None:
            raise NotInModelError("Track")

        neighbours = await self.repository.nearest_tracks(
            content.id, vector, CANDIDATE_POOL + 1, EF_SEARCH
        )
        neighbours = [(t, s) for t, s in neighbours if t != track_id]
        facts = await self.repository.track_facts(
            [t for t, _ in neighbours], popularity.id if popularity else None
        )
        ranked = rerank(
            (
                Candidate(t, s, facts[t].popularity, facts[t].artist_id, facts[t].song_key)
                for t, s in neighbours
                if t in facts
            ),
            beta=_beta(content, "seed"),
            limit=limit,
            max_per_artist=max_per_artist,
            exclude_dedup_keys=[song_key(seed.artist_id, seed.title)],
        )

        profiles = await self.repository.genre_profiles([track_id, *(r.item for r in ranked)])
        seed_genres = profiles.get(track_id, {})
        seed_artist = await self.repository.artist_name(seed.artist_id)
        reasons = {}
        for r in ranked:
            fact = facts[r.item]
            same_decade = _decade(fact.release_year)
            reasons[r.item] = explanations.similar_track_reason(
                seed.title,
                r.candidate.similarity,
                explanations.shared_genres(seed_genres, profiles.get(r.item, {})),
                same_artist_name=seed_artist if fact.artist_id == seed.artist_id else None,
                same_decade=same_decade
                if same_decade is not None and same_decade == _decade(seed.release_year)
                else None,
            )
        items = await self._items(ranked, reasons)
        return self._response(Strategy.SIMILAR_TRACKS, content, [popularity], items)

    # --- similar artists ---------------------------------------------------------------------

    async def similar_artists(self, artist_id: uuid.UUID, limit: int) -> RecommendationResponse:
        content = await self._require("content")
        popularity = await self.repository.active_version("popularity")
        artist = await self.session.get(Artist, artist_id)
        if artist is None:
            raise NotFoundError("Artist")
        vector = await self.repository.artist_embedding(content.id, artist_id)
        if vector is None:
            raise NotInModelError("Artist")

        similar = await self.repository.nearest_artists(
            content.id, vector, SIMILAR_ARTISTS_POOL + 1, EF_SEARCH
        )
        similar = [(a, s) for a, s in similar if a != artist_id][:SIMILAR_ARTISTS_POOL]
        similarity_of = dict(similar)
        top_tracks = await self.repository.top_tracks_by_artist(
            [a for a, _ in similar],
            content.id,
            popularity.id if popularity else None,
            TRACKS_PER_SIMILAR_ARTIST,
        )
        pool = [(t, a) for a, _ in similar for t in top_tracks.get(a, [])]
        facts = await self.repository.track_facts(
            [t for t, _ in pool], popularity.id if popularity else None
        )
        ranked = rerank(
            (
                Candidate(t, similarity_of[a], facts[t].popularity, a, facts[t].song_key)
                for t, a in pool
                if t in facts
            ),
            beta=_beta(content, "artist"),
            limit=limit,
        )
        seed_genres = await self.repository.artist_genres(artist_id)
        profiles = await self.repository.genre_profiles([r.item for r in ranked])
        reasons = {
            r.item: explanations.similar_artist_reason(
                artist.name,
                r.candidate.similarity,
                explanations.shared_genres(seed_genres, profiles.get(r.item, {})),
            )
            for r in ranked
        }
        items = await self._items(ranked, reasons)
        return self._response(Strategy.SIMILAR_ARTISTS, content, [popularity], items)

    # --- genre -------------------------------------------------------------------------------

    async def genre(self, name: str, limit: int) -> RecommendationResponse:
        popularity = await self._require("popularity")
        genre = await self.repository.find_genre(name)
        if genre is None:
            raise NotFoundError("Genre")
        members = await self.repository.genre_members(
            genre.id, popularity.id, MIN_GENRE_AFFINITY, GENRE_POPULARITY_WEIGHT, CANDIDATE_POOL
        )
        facts = await self.repository.track_facts([m.track_id for m in members], popularity.id)
        ranked = rerank(
            (
                Candidate(
                    m.track_id,
                    m.affinity,
                    m.popularity,
                    facts[m.track_id].artist_id,
                    facts[m.track_id].song_key,
                )
                for m in members
                if m.track_id in facts
            ),
            beta=GENRE_POPULARITY_WEIGHT,
            limit=limit,
        )
        listeners = {m.track_id: m.listeners for m in members}
        reasons = {
            r.item: explanations.genre_reason(genre.name, r.candidate.similarity, listeners[r.item])
            for r in ranked
        }
        items = await self._items(ranked, reasons)
        return self._response(Strategy.GENRE, popularity, [], items)

    # --- popular -----------------------------------------------------------------------------

    async def popular(
        self, limit: int, kind: PopularKind, artist_id: uuid.UUID | None = None
    ) -> RecommendationResponse:
        popularity = await self._require("popularity")
        if artist_id is not None and await self.session.get(Artist, artist_id) is None:
            raise NotFoundError("Artist")
        trending = kind is PopularKind.TRENDING
        rows = await self.repository.popular(
            popularity.id, limit, trending=trending, artist_id=artist_id
        )
        window_days = int(popularity.training_data.get("window_days", 0))
        recent_days = int(popularity.params.get("recent_days", 0))
        ranked: list[Ranked[uuid.UUID]] = []
        reasons: dict[uuid.UUID, str] = {}
        for row in rows:
            score = row.trending_score if trending and row.trending_score is not None else row.score
            ranked.append(Ranked(Candidate(row.track_id, 0.0, row.score, row.track_id), score))
            reasons[row.track_id] = (
                explanations.trending_reason(
                    row.recent_listeners, math.exp(row.trending_score), recent_days
                )
                if trending and row.trending_score is not None
                else explanations.popular_reason(row.listeners, window_days)
            )
        items = await self._items(ranked, reasons)
        strategy = Strategy.TRENDING if trending else Strategy.POPULAR
        return self._response(strategy, popularity, [], items)
