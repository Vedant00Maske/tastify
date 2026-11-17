"""Mood mixes (Milestone 4): configured mood recipes ranked against the user's taste.

The catalogue has no mood labels, so a mood is a documented recipe (spec: "configured mood
parameters"): genre tags that carry the mood, plus optional tempo (BPM) and danceability ranges
from AcousticBrainz. A track belongs to a mood when one of its genre affinities reaches
MIN_MOOD_AFFINITY and its measured features (if any) fall in the ranges; tracks without audio
features are judged on genres alone.

Ranking: mood fit, closeness to the user's taste profile and popularity, blended; then the "mood"
diversity policy (MMR, two tracks per artist). Signed-out callers get the unpersonalized blend.
"""

import logging
import uuid
from collections.abc import Collection
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.repository import CatalogueRepository
from app.domains.recommendations import explanations
from app.domains.recommendations.diversity import POLICIES, compose
from app.domains.recommendations.models import ModelVersion
from app.domains.recommendations.repository import RecommendationRepository, TagMember
from app.domains.recommendations.schemas import (
    RecommendationItem,
    RecommendationResponse,
    Strategy,
)
from app.domains.recommendations.service import ModelUnavailableError, NotFoundError
from app.domains.users.profile import profile_query
from app.domains.users.service import TasteProfileService

logger = logging.getLogger(__name__)

MIN_MOOD_AFFINITY = 0.25
CANDIDATES = 600
# (mood fit, taste similarity, popularity)
PERSONAL_WEIGHTS = (0.5, 0.3, 0.2)
ANONYMOUS_WEIGHTS = (0.6, 0.0, 0.4)


@dataclass(frozen=True)
class MoodRecipe:
    key: str
    title: str
    description: str
    genres: tuple[str, ...]
    tempo: tuple[float | None, float | None] = (None, None)
    danceability: tuple[float | None, float | None] = (None, None)

    def fits(self, member: TagMember) -> bool:
        return _within(member.tempo, self.tempo) and _within(member.danceability, self.danceability)


def _within(value: float | None, bounds: tuple[float | None, float | None]) -> bool:
    low, high = bounds
    if value is None:
        return True
    return (low is None or value >= low) and (high is None or value <= high)


MOODS: dict[str, MoodRecipe] = {
    recipe.key: recipe
    for recipe in (
        MoodRecipe(
            "midnight-drive",
            "Midnight Drive",
            "Synths, neon and steady motion for empty roads after dark.",
            (
                "synthwave",
                "darkwave",
                "new wave",
                "synth-pop",
                "chillwave",
                "post-punk",
                "dream pop",
            ),
            tempo=(85, 130),
        ),
        MoodRecipe(
            "deep-focus",
            "Deep Focus",
            "Unobtrusive, textured music that keeps you in the zone.",
            (
                "ambient",
                "post-rock",
                "modern classical",
                "idm",
                "downtempo",
                "lo-fi",
                "instrumental",
            ),
            danceability=(None, 0.55),
        ),
        MoodRecipe(
            "rainy-afternoon",
            "Rainy Afternoon",
            "Soft, warm songs for grey skies and a cup of something hot.",
            ("indie folk", "folk", "chamber pop", "singer-songwriter", "slowcore", "dream pop"),
            tempo=(None, 120),
        ),
        MoodRecipe(
            "feel-good",
            "Feel Good",
            "Bright grooves and big choruses to lift the day.",
            ("funk", "disco", "soul", "motown", "dance-pop", "indie pop", "funk rock"),
            tempo=(95, None),
            danceability=(0.45, None),
        ),
        MoodRecipe(
            "melancholic-hours",
            "Melancholic Hours",
            "Bittersweet, slow-burning songs for reflective moments.",
            ("slowcore", "shoegaze", "emo", "post-rock", "dream pop", "singer-songwriter"),
            tempo=(None, 125),
        ),
        MoodRecipe(
            "slow-sunday",
            "Slow Sunday",
            "Unhurried jazz, soul and folk for a lazy morning.",
            ("jazz", "soul jazz", "bossa nova", "soft rock", "lounge", "soul", "folk pop"),
            tempo=(None, 115),
        ),
        MoodRecipe(
            "workout-energy",
            "Workout Energy",
            "Fast, heavy and driving: tracks that keep you moving.",
            ("edm", "house", "drum and bass", "techno", "hard rock", "metal", "trap", "electro"),
            tempo=(118, None),
            danceability=(0.4, None),
        ),
        MoodRecipe(
            "after-hours",
            "After Hours",
            "Late-night R&B, deep house and smoky downtempo.",
            ("alternative r&b", "contemporary r&b", "deep house", "trip hop", "downtempo"),
            tempo=(80, 128),
        ),
    )
}


class MoodOut(BaseModel):
    key: str
    title: str
    description: str
    genres: list[str]


class MoodListResponse(BaseModel):
    moods: list[MoodOut]


class MoodMixResponse(RecommendationResponse):
    mood: MoodOut
    personalized: bool


def mood_out(recipe: MoodRecipe) -> MoodOut:
    return MoodOut(
        key=recipe.key,
        title=recipe.title,
        description=recipe.description,
        genres=list(recipe.genres),
    )


class MoodService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = RecommendationRepository(session)
        self.catalogue = CatalogueRepository(session)
        self.profiles = TasteProfileService(session)

    async def _require(self, model_type: str) -> ModelVersion:
        version = await self.repository.active_version(model_type)
        if version is None:
            raise ModelUnavailableError(model_type)
        return version

    async def mix(
        self,
        key: str,
        limit: int,
        user_id: uuid.UUID | None = None,
        exclude: Collection[uuid.UUID] = (),
    ) -> MoodMixResponse:
        recipe = MOODS.get(key)
        if recipe is None:
            raise NotFoundError("Mood")
        popularity = await self._require("popularity")
        content = await self.repository.active_version("content")
        genre_ids = await self.repository.genre_ids(recipe.genres)
        members = [
            m
            for m in await self.repository.tag_members(
                list(genre_ids.values()), popularity.id, MIN_MOOD_AFFINITY, CANDIDATES
            )
            if recipe.fits(m) and m.track_id not in exclude
        ]
        blocked: set[uuid.UUID] = set()
        query = None
        excluded_artists: frozenset[uuid.UUID] = frozenset()
        if user_id is not None:
            context = await self.profiles.current(user_id)
            await self.session.commit()
            if context.personalization_enabled:
                profile = context.profile
                blocked = set(profile.heard_tracks)
                excluded_artists = profile.excluded_artists | frozenset(profile.negative_artists)
                query = profile_query(
                    profile.long_term_embedding,
                    profile.short_term_embedding,
                    context.config.short_term_weight,
                )
        members = [m for m in members if m.track_id not in blocked]
        tracks = [m.track_id for m in members]
        facts = await self.repository.track_facts(tracks, popularity.id)
        members = [
            m
            for m in members
            if m.track_id in facts and facts[m.track_id].artist_id not in excluded_artists
        ]
        tracks = [m.track_id for m in members]
        embeddings = None
        similarity = np.zeros(len(members))
        if content is not None and members:
            vectors = await self.repository.track_embeddings(content.id, tracks)
            if vectors:
                size = len(next(iter(vectors.values())))
                embeddings = np.array([vectors.get(t, [0.0] * size) for t in tracks])
                if query is not None:
                    similarity = np.clip(embeddings @ query, 0.0, 1.0)
        fit, taste, pop = PERSONAL_WEIGHTS if query is not None else ANONYMOUS_WEIGHTS
        scores = (
            np.array([fit * m.affinity + pop * m.popularity for m in members], dtype=np.float64)
            + taste * similarity
        )
        picked = compose(
            scores,
            limit=limit,
            policy=POLICIES["mood"],
            artists=[facts[t].artist_id for t in tracks],
            song_keys=[facts[t].song_key for t in tracks],
            embeddings=embeddings,
        )
        chosen = [members[i] for i in picked]
        summaries = await self.catalogue.track_summaries([m.track_id for m in chosen])
        items = [
            RecommendationItem(
                track_id=m.track_id,
                title=summaries[m.track_id].title,
                artist=summaries[m.track_id].artist,
                artist_id=summaries[m.track_id].artist_id,
                album=summaries[m.track_id].album_title,
                artwork_url=summaries[m.track_id].artwork_url,
                score=round(float(scores[i]), 4),
                reason=explanations.mood_reason(
                    recipe.title,
                    m.genre,
                    m.tempo,
                    float(similarity[i]) if query is not None else None,
                ),
            )
            for i, m in zip(picked, chosen, strict=True)
            if m.track_id in summaries
        ]
        versions: dict[str, str] = {"popularity": popularity.version}
        if content is not None:
            versions["content"] = content.version
        response = MoodMixResponse(
            request_id=uuid.uuid4(),
            model_version=popularity.version,
            model_versions=versions,
            strategy=Strategy.MOOD,
            recommendations=items,
            mood=mood_out(recipe),
            personalized=query is not None,
        )
        logger.info(
            "recommendations request_id=%s strategy=mood mood=%s candidates=%d count=%d",
            response.request_id,
            key,
            len(members),
            len(items),
        )
        return response


def describe_moods() -> MoodListResponse:
    return MoodListResponse(moods=[mood_out(r) for r in MOODS.values()])
