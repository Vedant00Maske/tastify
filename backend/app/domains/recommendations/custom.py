"""Playlists from a prompt: POST /recommendations/custom (Milestone 6, spec §9 and FR-016;
ADR-019).

The prompt is read by `prompts.parse` into genres, moods, artists and constraints. Candidates
come from the catalogue evidence those name: tracks tagged with the genres (and the moods'
genres), the named artists' tracks and their nearest artists' tracks. Constraints filter
(tempo, energy, era, exclusions, popularity), and the ranking combines how well a track fits the
requested genres, how close its artist is to the named artists, the listener's taste (signed in)
and popularity tempered by the requested exploration. The response says what was understood.
"""

import logging
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import Artist, TrackFeatures
from app.domains.catalogue.normalization import normalize_name
from app.domains.catalogue.repository import CatalogueRepository
from app.domains.recommendations import explanations
from app.domains.recommendations.diversity import DiversityPolicy, compose
from app.domains.recommendations.moods import MOODS
from app.domains.recommendations.prompts import ParsedPrompt, genre_vocabulary, parse
from app.domains.recommendations.repository import RecommendationRepository, TrackFacts
from app.domains.recommendations.schemas import (
    PersonalizedItem,
    RecommendationResponse,
    Strategy,
)
from app.domains.recommendations.service import ModelUnavailableError, RecommendationError
from app.domains.users.profile import profile_query
from app.domains.users.service import TasteProfileService

logger = logging.getLogger(__name__)

MIN_AFFINITY = 0.2
GENRE_CANDIDATES = 1200
ARTIST_NEIGHBOURS = 20
TRACKS_PER_ARTIST = 6
LESSER_KNOWN_MAX_POPULARITY = 0.55
POPULAR_MIN_POPULARITY = 0.5
ARTIST_MATCH_SIMILARITY = 0.55  # trigram similarity for a named artist that is not exact
POLICY = DiversityPolicy("custom", mmr_lambda=0.85, max_per_artist=2, discovery=True)
VOCABULARY_SIZE = 3000
_vocabulary: tuple[float, dict[str, str]] | None = None


class PromptNotUnderstoodError(RecommendationError):
    def __init__(self, ignored: list[str]) -> None:
        super().__init__(
            "No genre, mood or artist in this prompt matched the catalogue. Try something like "
            '"dreamy indie pop", "90s hip hop for a workout" or "like Radiohead, but newer".'
        )
        self.ignored = ignored


class CustomIn(BaseModel):
    prompt: str = Field(
        min_length=2, max_length=300, examples=["Indie rock with electronic influence"]
    )
    limit: int = Field(default=25, ge=1, le=50)
    exploration_level: float | None = Field(
        default=None, ge=0, le=1, description="0 = familiar artists, 1 = mostly new artists"
    )
    exclude_previously_heard: bool = True
    exclude: list[uuid.UUID] = Field(
        default_factory=list, max_length=100, description="Tracks to leave out (regenerate)"
    )


class ArtistRef(BaseModel):
    id: uuid.UUID
    name: str


class Interpretation(BaseModel):
    """What the prompt was read as; every part comes from words in the prompt."""

    genres: list[str]
    excluded_genres: list[str]
    moods: list[str]
    artists: list[ArtistRef]
    excluded_artists: list[ArtistRef]
    tempo: tuple[float | None, float | None]
    danceability: tuple[float | None, float | None]
    years: tuple[int | None, int | None]
    popularity: str | None
    exploration_level: float | None
    ignored: list[str]
    summary: str


class CustomResponse(RecommendationResponse):
    recommendations: list[PersonalizedItem]  # type: ignore[assignment]
    prompt: str
    interpretation: Interpretation
    personalized: bool


@dataclass
class _Candidate:
    track: uuid.UUID
    genre_fit: float = 0.0
    best_genre: str | None = None
    artist_fit: float = 0.0
    near_artist: str | None = None


def _within(value: float | None, bounds: tuple[float | None, float | None]) -> bool:
    low, high = bounds
    if value is None:
        return True
    return (low is None or value >= low) and (high is None or value <= high)


def summarize(parsed: ParsedPrompt, artists: list[ArtistRef], excluded: list[ArtistRef]) -> str:
    parts: list[str] = []
    if parsed.genres:
        parts.append(" + ".join(parsed.genres))
    if parsed.moods:
        parts.append(", ".join(MOODS[m].title for m in parsed.moods) + " mood")
    if artists:
        parts.append("near " + ", ".join(a.name for a in artists))
    low, high = parsed.tempo
    if low or high:
        parts.append(
            f"{low:.0f}-{high:.0f} BPM"
            if low and high
            else (f"over {low:.0f} BPM" if low else f"under {high:.0f} BPM")
        )
    if parsed.danceability != (None, None):
        parts.append("danceable" if parsed.danceability[0] else "calm")
    first, last = parsed.years
    if first or last:
        if first and last:
            parts.append(f"{first}-{last}")
        else:
            parts.append(f"from {first}" if first else f"until {last}")
    if parsed.popularity:
        parts.append("lesser-known" if parsed.popularity == "lesser_known" else "popular")
    if parsed.exploration is not None:
        parts.append("new artists" if parsed.exploration >= 0.5 else "familiar artists")
    if parsed.excluded_genres or excluded:
        parts.append("no " + ", ".join([*parsed.excluded_genres, *(a.name for a in excluded)]))
    return "; ".join(parts) if parts else "nothing specific"


class CustomPlaylistService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = RecommendationRepository(session)
        self.catalogue = CatalogueRepository(session)
        self.profiles = TasteProfileService(session)

    async def _vocabulary(self) -> dict[str, str]:
        """Catalogue genre names (the most used `VOCABULARY_SIZE`), cached for ten minutes."""
        global _vocabulary
        now = datetime.now(UTC).timestamp()
        if _vocabulary is None or now - _vocabulary[0] > 600:
            names = [g.name for g in await self.catalogue.top_genres(VOCABULARY_SIZE)]
            _vocabulary = (now, genre_vocabulary(names))
        return _vocabulary[1]

    async def _artist(self, phrase: str) -> ArtistRef | None:
        """The catalogue artist a phrase names: exact normalized name first, then the closest
        trigram match above ARTIST_MATCH_SIMILARITY (most tracks wins ties)."""
        normalized = normalize_name(phrase)
        if not normalized:
            return None
        exact = (
            await self.session.execute(
                select(Artist.id, Artist.name).where(Artist.normalized_name == normalized).limit(1)
            )
        ).first()
        if exact:
            return ArtistRef(id=exact[0], name=exact[1])
        similarity = func.similarity(Artist.normalized_name, normalized)
        row = (
            await self.session.execute(
                select(Artist.id, Artist.name, similarity)
                .where(Artist.normalized_name.op("%")(normalized))
                .order_by(similarity.desc())
                .limit(1)
            )
        ).first()
        if row and float(row[2]) >= ARTIST_MATCH_SIMILARITY:
            return ArtistRef(id=row[0], name=row[1])
        return None

    async def generate(
        self, data: CustomIn, user_id: uuid.UUID | None, exclude: Collection[uuid.UUID] = ()
    ) -> CustomResponse:
        parsed = parse(data.prompt, await self._vocabulary(), datetime.now(UTC).year)
        artists: list[ArtistRef] = []
        for phrase in parsed.artist_phrases:
            if (found := await self._artist(phrase)) and found not in artists:
                artists.append(found)
            elif not found:
                parsed.ignored.append(phrase)
        excluded_artists: list[ArtistRef] = []
        for phrase in parsed.excluded_artist_phrases:
            if found := await self._artist(phrase):
                excluded_artists.append(found)
            else:
                parsed.ignored.append(f"no {phrase}")
        if not (parsed.genres or parsed.moods or artists):
            raise PromptNotUnderstoodError(parsed.ignored)
        exploration = (
            data.exploration_level if data.exploration_level is not None else parsed.exploration
        )

        popularity = await self.repository.active_version("popularity")
        content = await self.repository.active_version("content")
        if popularity is None:
            raise ModelUnavailableError("popularity")

        # --- candidates
        candidates: dict[uuid.UUID, _Candidate] = {}
        genre_names = list(
            dict.fromkeys([*parsed.genres, *(g for m in parsed.moods for g in MOODS[m].genres)])
        )
        tempo, danceability = parsed.tempo, parsed.danceability
        if parsed.moods and tempo == (None, None):
            tempo = MOODS[parsed.moods[0]].tempo
        if parsed.moods and danceability == (None, None):
            danceability = MOODS[parsed.moods[0]].danceability
        if genre_names:
            ids = await self.repository.genre_ids(genre_names)
            for member in await self.repository.tag_members(
                list(ids.values()), popularity.id, MIN_AFFINITY, GENRE_CANDIDATES
            ):
                if not (
                    _within(member.tempo, tempo) and _within(member.danceability, danceability)
                ):
                    continue
                candidates[member.track_id] = _Candidate(member.track_id)
        if artists and content is not None:
            neighbours: dict[uuid.UUID, tuple[float, str]] = {a.id: (1.0, a.name) for a in artists}
            for anchor in artists:
                vector = await self.repository.artist_embedding(content.id, anchor.id)
                if vector is None:
                    continue
                for artist_id, distance in await self.repository.nearest_artists(
                    content.id, vector, ARTIST_NEIGHBOURS, 100
                ):
                    similarity = 1.0 - float(distance)
                    if similarity > neighbours.get(artist_id, (0.0, ""))[0]:
                        neighbours[artist_id] = (similarity, anchor.name)
            tracks_by_artist = await self.repository.top_tracks_by_artist(
                list(neighbours), content.id, popularity.id, TRACKS_PER_ARTIST
            )
            for artist_id, tracks in tracks_by_artist.items():
                similarity, anchor_name = neighbours[artist_id]
                for track in tracks:
                    entry = candidates.setdefault(track, _Candidate(track))
                    if similarity > entry.artist_fit:
                        entry.artist_fit, entry.near_artist = similarity, anchor_name
        if not candidates:
            return await self._respond(
                data,
                parsed,
                artists,
                excluded_artists,
                exploration,
                [],
                [],
                {},
                False,
                popularity.version,
            )

        # --- personal filters and taste
        blocked = set(exclude) | set(data.exclude)
        excluded_ids = {a.id for a in excluded_artists}
        query = None
        known_artists: frozenset[uuid.UUID] = frozenset()
        personalized = False
        if user_id is not None:
            context = await self.profiles.current(user_id)
            await self.session.commit()
            if context.personalization_enabled:
                personalized = True
                profile = context.profile
                if data.exclude_previously_heard:
                    blocked |= set(profile.heard_tracks)
                blocked |= set(profile.disliked_tracks)
                excluded_ids |= set(profile.excluded_artists)
                known_artists = profile.known_artists
                query = profile_query(
                    profile.long_term_embedding,
                    profile.short_term_embedding,
                    context.config.short_term_weight,
                )

        tracks = [t for t in candidates if t not in blocked]
        facts = await self.repository.track_facts(tracks, popularity.id)
        tracks = [t for t in tracks if t in facts and facts[t].artist_id not in excluded_ids]
        first, last = parsed.years
        tracks = [
            t
            for t in tracks
            if (first is None or (facts[t].release_year or 0) >= first)
            and (last is None or (facts[t].release_year or 9999) <= last)
        ]
        if parsed.popularity == "lesser_known":
            tracks = [t for t in tracks if facts[t].popularity <= LESSER_KNOWN_MAX_POPULARITY]
        elif parsed.popularity == "popular":
            tracks = [t for t in tracks if facts[t].popularity >= POPULAR_MIN_POPULARITY]
        # Tempo and energy also bind artist-based candidates (genre members were checked above).
        if tracks and (tempo != (None, None) or danceability != (None, None)):
            features = {
                row[0]: (row[1], row[2])
                for row in (
                    await self.session.execute(
                        select(
                            TrackFeatures.track_id, TrackFeatures.tempo, TrackFeatures.danceability
                        ).where(
                            TrackFeatures.track_id.in_(tracks),
                            TrackFeatures.feature_source == "acousticbrainz",
                        )
                    )
                ).all()
            }
            tracks = [
                t
                for t in tracks
                if _within(features.get(t, (None, None))[0], tempo)
                and _within(features.get(t, (None, None))[1], danceability)
            ]
        genres = await self.repository.genre_profiles(tracks)
        tracks = [
            t
            for t in tracks
            if not any(genres.get(t, {}).get(g, 0.0) >= 0.3 for g in parsed.excluded_genres)
        ]
        if not tracks:
            return await self._respond(
                data,
                parsed,
                artists,
                excluded_artists,
                exploration,
                [],
                [],
                facts,
                personalized,
                popularity.version,
            )

        # --- scoring
        requested = [
            *parsed.genres,
            *(g for m in parsed.moods for g in MOODS[m].genres if g not in parsed.genres),
        ]
        for t in tracks:
            profile_genres = genres.get(t, {})
            values = [min(1.0, profile_genres.get(g, 0.0)) for g in parsed.genres] or [
                max((min(1.0, profile_genres.get(g, 0.0)) for g in requested), default=0.0)
            ]
            entry = candidates[t]
            # Several requested genres: reward tracks that bring all of them, not one very well.
            entry.genre_fit = 0.6 * max(values) + 0.4 * (sum(values) / len(values))
            entry.best_genre = max(
                requested, key=lambda g: profile_genres.get(g, 0.0), default=None
            )
        embeddings = None
        taste = np.zeros(len(tracks))
        if content is not None:
            vectors = await self.repository.track_embeddings(content.id, tracks)
            if vectors:
                size = len(next(iter(vectors.values())))
                embeddings = np.array([vectors.get(t, [0.0] * size) for t in tracks])
                if query is not None:
                    taste = np.clip(embeddings @ query, 0.0, 1.0)
        genre_fit = np.array([candidates[t].genre_fit for t in tracks])
        artist_fit = np.array([candidates[t].artist_fit for t in tracks])
        pop = np.array([facts[t].popularity for t in tracks])
        weights = {
            "genre": 0.5 if requested else 0.0,
            "artist": 0.35 if artists else 0.0,
            "taste": 0.2 if query is not None else 0.0,
        }
        total = sum(weights.values()) or 1.0
        level = 0.5 if exploration is None else exploration
        scores = (
            weights["genre"] * genre_fit + weights["artist"] * artist_fit + weights["taste"] * taste
        ) / total + 0.15 * (1.0 - level) * pop
        artists_of = [facts[t].artist_id for t in tracks]
        discovery = np.array([personalized and a not in known_artists for a in artists_of])
        picked = compose(
            scores,
            limit=data.limit,
            policy=POLICY,
            artists=artists_of,
            song_keys=[facts[t].song_key for t in tracks],
            embeddings=embeddings,
            discovery=discovery if personalized and exploration is not None else None,
            discovery_target=level if personalized and exploration is not None else None,
        )
        chosen = [tracks[i] for i in picked]
        reasons = [
            explanations.custom_reason(
                genre=candidates[tracks[i]].best_genre if requested else None,
                genre_fit=float(genre_fit[i]),
                artist=candidates[tracks[i]].near_artist,
                artist_fit=float(artist_fit[i]),
                year=facts[tracks[i]].release_year if parsed.years != (None, None) else None,
                # The artist the user named is not news to them, whatever their history says.
                new_artist=bool(discovery[i]) and artist_fit[i] < 0.999,
                taste=float(taste[i]) if query is not None else None,
            )
            for i in picked
        ]
        return await self._respond(
            data,
            parsed,
            artists,
            excluded_artists,
            exploration,
            [
                (t, float(scores[i]), bool(discovery[i]))
                for t, i in zip(chosen, picked, strict=True)
            ],
            reasons,
            facts,
            personalized,
            popularity.version if content is None else content.version,
        )

    async def _respond(
        self,
        data: CustomIn,
        parsed: ParsedPrompt,
        artists: list[ArtistRef],
        excluded: list[ArtistRef],
        exploration: float | None,
        picked: list[tuple[uuid.UUID, float, bool]],
        reasons: list[str],
        facts: dict[uuid.UUID, TrackFacts],
        personalized: bool,
        model_version: str,
    ) -> CustomResponse:
        summaries = await self.catalogue.track_summaries([t for t, _, _ in picked])
        items = [
            PersonalizedItem(
                track_id=track,
                title=summaries[track].title,
                artist=summaries[track].artist,
                artist_id=summaries[track].artist_id,
                album=summaries[track].album_title,
                artwork_url=summaries[track].artwork_url,
                score=round(score, 4),
                reason=reason,
                discovery=discovery,
                sources=[],
            )
            for (track, score, discovery), reason in zip(picked, reasons, strict=True)
            if track in summaries
        ]
        interpretation = Interpretation(
            genres=parsed.genres,
            excluded_genres=parsed.excluded_genres,
            moods=parsed.moods,
            artists=artists,
            excluded_artists=excluded,
            tempo=parsed.tempo,
            danceability=parsed.danceability,
            years=parsed.years,
            popularity=parsed.popularity,
            exploration_level=exploration,
            ignored=list(dict.fromkeys(parsed.ignored)),
            summary=summarize(parsed, artists, excluded),
        )
        response = CustomResponse(
            request_id=uuid.uuid4(),
            model_version=model_version,
            model_versions={"custom": "prompt-v1", "content": model_version},
            strategy=Strategy.CUSTOM,
            recommendations=items,
            prompt=data.prompt,
            interpretation=interpretation,
            personalized=personalized,
        )
        logger.info(
            "custom playlist request_id=%s understood=%r count=%d",
            response.request_id,
            interpretation.summary,
            len(items),
        )
        return response
