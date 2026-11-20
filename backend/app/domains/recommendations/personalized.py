"""Personalized recommendations (Milestone 3, ADR-016).

For you: taste profile -> six independent candidate sources -> merge (with source attribution)
-> filter -> features -> hybrid ranker (weighted or LambdaRank, from the active `hybrid` version)
-> negative-artist demotion -> diversity-aware composition (MMR, artist cap, familiar/discovery
balance from the exploration mode).

Each candidate source runs in its own SAVEPOINT: if one fails (model missing, query error), it is
reported as failed and the others still produce a list. Cold start: with no interactions, the
declared favourite artists and genres drive the candidates and the score is a similarity /
popularity blend; with nothing declared, a diverse popular mix.

Artist radio: the artist's own tracks plus those of similar artists, with the category's own
diversity policy (the seed artist may fill up to 40% of the list).

The pure parts (generators, merger, filter, features, rankers, composition) are the same
functions the offline evaluation runs (docs/reports/hybrid-benchmark.md).
"""

import io
import json
import logging
import math
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.domains.catalogue.models import Artist
from app.domains.catalogue.repository import CatalogueRepository
from app.domains.catalogue.schemas import TrackSummary
from app.domains.recommendations import context as ctx
from app.domains.recommendations import explanations
from app.domains.recommendations.candidate_generation import (
    CandidateFilter,
    CandidateList,
    CandidateSet,
    Source,
    merge_candidates,
)
from app.domains.recommendations.candidate_generation.collaborative_candidates import (
    bm25_row,
    collaborative_candidates,
    fold_in,
)
from app.domains.recommendations.candidate_generation.content_candidates import (
    content_candidates,
)
from app.domains.recommendations.candidate_generation.exploration_candidates import (
    exploration_candidates,
)
from app.domains.recommendations.candidate_generation.history_candidates import (
    history_candidates,
)
from app.domains.recommendations.candidate_generation.popularity_candidates import (
    popularity_candidates,
)
from app.domains.recommendations.diversity import POLICIES, DiversityPolicy, compose
from app.domains.recommendations.features import FeatureInputs, feature_matrix
from app.domains.recommendations.hybrid_ranking import (
    Ranker,
    TreeEnsembleRanker,
    WeightedHybridRanker,
    demote_negative_artists,
    normalized_relevance,
)
from app.domains.recommendations.models import ModelVersion
from app.domains.recommendations.ranking import (
    CANDIDATE_POOL,
    GENRE_POPULARITY_WEIGHT,
    MIN_GENRE_AFFINITY,
    SIMILAR_ARTISTS_POOL,
    Candidate,
    blended_score,
    genre_score,
    rerank,
)
from app.domains.recommendations.repository import RecommendationRepository, TrackFacts
from app.domains.recommendations.schemas import (
    BecauseYouListened,
    CandidateSourceOut,
    Composition,
    PersonalizedItem,
    PersonalizedResponse,
    RecommendationItem,
    RecommendationResponse,
    SourceStatusOut,
    Strategy,
)
from app.domains.recommendations.service import (
    ModelUnavailableError,
    NotFoundError,
    NotInModelError,
)
from app.domains.users.profile import ExplorationMode, TasteProfile, profile_query
from app.domains.users.service import ProfileContext, TasteProfileService

logger = logging.getLogger(__name__)

FloatArray = npt.NDArray[np.float64]
EF_SEARCH = 400
# The user's strongest tracks used for collaborative scoring and fold-in (bounded query cost).
MAX_CF_HISTORY = 1000
# Item-item scoring reads every neighbour row of these tracks (up to 200 each): the strongest 300
# carry almost all of the weight, and the query stays small for heavy listeners.
MAX_ITEM_HISTORY = 300
# Over-fetch from vector indexes so that enough unheard tracks remain after exclusion.
MAX_OVERFETCH = 300
# Hidden gems: popularity score log(1 + listeners) / log(1 + max listeners) at most this (about
# 50 listeners over the 14-day window when the most played track has 1,350), mostly new artists.
HIDDEN_GEM_MAX_POPULARITY = 0.55
HIDDEN_GEM_DISCOVERY = 0.8
SURPRISE_POOL = 10


SESSION_REASON_THRESHOLD = 0.03  # nudge (weight x fit) large enough to mention


@dataclass(frozen=True)
class RequestContext:
    """Where and when the request happens: the viewer's time zone (from the browser) and now."""

    zone: tzinfo | None = None
    now: datetime | None = None

    @property
    def zone_name(self) -> str | None:
        return None if self.zone is None else str(self.zone)


@dataclass(frozen=True)
class HybridSettings:
    """Serving settings of the active hybrid version (defaults when none is published)."""

    version: ModelVersion | None
    ranker_kind: str = "weighted"
    weighted: dict[str, Any] = field(default_factory=dict)
    source_limit: int = 200
    content_neighbours: int = 100
    exploration_artists: int = 60
    tracks_per_artist: int = 2
    exploration_limit: int = 100
    popularity_limit: int = 100
    popular_genres: int = 2
    mmr_lambda: float = POLICIES["for_you"].mmr_lambda
    default_mode: str = "auto"
    cold_start_popularity_weight: float = 0.3

    @classmethod
    def from_version(cls, version: ModelVersion | None) -> "HybridSettings":
        if version is None:
            return cls(None)
        params = version.params
        candidates = params.get("candidates", {})
        return cls(
            version,
            ranker_kind=str(params.get("ranker", "weighted")),
            weighted=dict(params.get("weighted", {})),
            source_limit=int(candidates.get("source_limit", 200)),
            content_neighbours=int(candidates.get("content_neighbours", 100)),
            exploration_artists=int(candidates.get("exploration_artists", 60)),
            tracks_per_artist=int(candidates.get("tracks_per_artist", 2)),
            exploration_limit=int(candidates.get("exploration_limit", 100)),
            popularity_limit=int(candidates.get("popularity_limit", 100)),
            popular_genres=int(candidates.get("popular_genres", 2)),
            mmr_lambda=float(params.get("diversity", {}).get("mmr_lambda", 0.8)),
            default_mode=str(params.get("diversity", {}).get("default_mode", "auto")),
            cold_start_popularity_weight=float(params.get("cold_start_popularity_weight", 0.3)),
        )

    def for_you_policy(self) -> DiversityPolicy:
        return replace(POLICIES["for_you"], mmr_lambda=self.mmr_lambda)


class _ArtifactCache:
    """Parsed artifacts by (version id, name). Versions are immutable, so entries never go stale;
    the cache is bounded so retired versions eventually leave memory."""

    def __init__(self, name: str, size: int = 8) -> None:
        self.name = name
        self.size = size
        self.items: OrderedDict[tuple[uuid.UUID, str], Any] = OrderedDict()
        # Worker threads (precomputed mixes) share these caches; the API's single event loop
        # never contends for the lock.
        self._lock = threading.Lock()

    def get(self, key: tuple[uuid.UUID, str]) -> Any | None:
        with self._lock:
            value = self.items.get(key)
            if value is not None:
                self.items.move_to_end(key)
        metrics.cache_lookup(self.name, hit=value is not None)
        return value

    def put(self, key: tuple[uuid.UUID, str], value: Any) -> None:
        with self._lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)


ARTIFACTS = _ArtifactCache("model_artifacts")
# Popularity rankings per (popularity version, genre): not personal, and fixed for a published
# version, so they are computed once per process (Milestone 6 optimization, ADR-019).
POPULARITY_CACHE = _ArtifactCache("popularity_rankings", size=256)
CONTEXT_POOL = 250  # only candidates this close to the top can be moved into the mix
GENRE_CACHE_SIZE = 50_000
_genre_cache: OrderedDict[tuple[uuid.UUID | None, uuid.UUID], dict[str, float]] = OrderedDict()
_genre_lock = threading.Lock()


@dataclass
class _Request:
    """Per-request state shared by the candidate sources."""

    context: ProfileContext
    content: ModelVersion | None
    popularity: ModelVersion
    collaborative: ModelVersion | None
    settings: HybridSettings
    heard: frozenset[uuid.UUID]
    cf_values: dict[uuid.UUID, float]
    item_scores: dict[uuid.UUID, float] = field(default_factory=dict)
    item_best_seed: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    user_factors: FloatArray | None = None
    content_seed_of: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    exploration_artist_of: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    query: FloatArray | None = None

    @property
    def profile(self) -> TasteProfile[uuid.UUID, uuid.UUID]:
        return self.context.profile

    @property
    def overfetch(self) -> int:
        return self.settings.source_limit + min(len(self.heard), MAX_OVERFETCH)


class PersonalizedRecommendationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = RecommendationRepository(session)
        self.catalogue = CatalogueRepository(session)
        self.profiles = TasteProfileService(session)

    # --- helpers -----------------------------------------------------------------------------

    async def _genres(self, tracks: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, float]]:
        """Track genre profiles, cached per content version (catalogue data that only changes
        when the catalogue is rebuilt, which publishes a new content version)."""
        content = await self.repository.active_version("content")
        version = content.id if content is not None else None
        found: dict[uuid.UUID, dict[str, float]] = {}
        missing: list[uuid.UUID] = []
        with _genre_lock:
            for track in tracks:
                cached = _genre_cache.get((version, track))
                if cached is None:
                    missing.append(track)
                else:
                    _genre_cache.move_to_end((version, track))
                    found[track] = cached
        if missing:
            loaded = await self.repository.genre_profiles(missing)
            with _genre_lock:
                for track in missing:
                    profile = loaded.get(track, {})
                    found[track] = profile
                    _genre_cache[(version, track)] = profile
                while len(_genre_cache) > GENRE_CACHE_SIZE:
                    _genre_cache.popitem(last=False)
        if tracks:
            metrics.CACHE_REQUESTS.labels("genre_profiles", "hit").inc(len(tracks) - len(missing))
            metrics.CACHE_REQUESTS.labels("genre_profiles", "miss").inc(len(missing))
        return found

    async def _isolated(
        self, source: Source, generate: Callable[[], Awaitable[CandidateList[uuid.UUID]]]
    ) -> CandidateList[uuid.UUID]:
        try:
            async with self.session.begin_nested():
                return await generate()
        except Exception as error:  # isolation: a failing source must not fail the request
            logger.warning("candidate source %s failed: %s", source.value, error, exc_info=True)
            return CandidateList.failed(source, error)

    async def _require(self, model_type: str) -> ModelVersion:
        version = await self.repository.active_version(model_type)
        if version is None:
            raise ModelUnavailableError(model_type)
        return version

    async def _artifact(self, version: ModelVersion, name: str) -> bytes | None:
        artifact = await self.repository.artifact(version.id, name)
        return None if artifact is None else artifact.content

    async def _ranker(self, settings: HybridSettings) -> Ranker:
        version = settings.version
        if version is not None and settings.ranker_kind == "lambdarank":
            key = (version.id, "ranker")
            cached = ARTIFACTS.get(key)
            if cached is None:
                content = await self._artifact(version, "ranker")
                if content is None:
                    raise RuntimeError(f"{version.version} has no ranker artifact")
                cached = TreeEnsembleRanker.from_dict(json.loads(content))
                ARTIFACTS.put(key, cached)
            ranker: Ranker = cached
            return ranker
        if settings.weighted:
            return WeightedHybridRanker.from_params(settings.weighted)
        # No hybrid version: equal calibrated weights of the core components.
        return WeightedHybridRanker.from_params(
            {
                "weights": {"collaborative_item": 1.0, "collaborative_mf": 1.0, "history": 1.0},
                "calibration": {
                    "collaborative_item": {"a": 1.0, "b": 0.0},
                    "collaborative_mf": {"a": 1.0, "b": 0.0},
                    "history": {"a": 1.0, "b": 0.0},
                },
            }
        )

    async def _gram(self, version: ModelVersion) -> FloatArray:
        key = (version.id, "gram")
        cached = ARTIFACTS.get(key)
        if cached is None:
            content = await self._artifact(version, "gram")
            if content is None:
                raise RuntimeError(f"{version.version} has no gram artifact")
            cached = np.load(io.BytesIO(content), allow_pickle=False)
            ARTIFACTS.put(key, cached)
        return np.asarray(cached, dtype=np.float64)

    # --- candidate sources -------------------------------------------------------------------

    async def _collaborative_item(self, request: _Request) -> CandidateList[uuid.UUID]:
        if request.collaborative is None:
            return CandidateList.skipped(Source.COLLABORATIVE_ITEM, "no collaborative model")
        if not request.cf_values:
            return CandidateList.skipped(Source.COLLABORATIVE_ITEM, "no listening history")
        history = dict(list(request.cf_values.items())[:MAX_ITEM_HISTORY])
        rows = await self.repository.neighbour_rows(request.collaborative.id, list(history))
        best: dict[uuid.UUID, tuple[float, uuid.UUID]] = {}
        for item, neighbour, similarity in rows:
            contribution = history[item] * similarity
            request.item_scores[neighbour] = request.item_scores.get(neighbour, 0.0) + contribution
            if neighbour not in best or contribution > best[neighbour][0]:
                best[neighbour] = (contribution, item)
        request.item_best_seed = {n: item for n, (_, item) in best.items()}
        ranked = sorted(
            ((t, s) for t, s in request.item_scores.items() if s > 0),
            key=lambda kv: (-kv[1], str(kv[0])),
        )
        return collaborative_candidates(
            Source.COLLABORATIVE_ITEM,
            ranked,
            exclude=request.heard,
            limit=request.settings.source_limit,
            model_version=request.collaborative.version,
        )

    async def _collaborative_mf(self, request: _Request) -> CandidateList[uuid.UUID]:
        version = request.collaborative
        if version is None:
            return CandidateList.skipped(Source.COLLABORATIVE_MF, "no collaborative model")
        if not request.cf_values:
            return CandidateList.skipped(Source.COLLABORATIVE_MF, "no listening history")
        factors = await self.repository.cf_factors(version.id, list(request.cf_values))
        if not factors:
            return CandidateList.skipped(Source.COLLABORATIVE_MF, "history outside the model")
        fold = version.params["fold_in"]
        items = list(factors)
        values = np.array([request.cf_values[t] for t in items])
        idf = np.array([factors[t][1] for t in items])
        weights = bm25_row(
            values,
            idf,
            float(fold["average_length"]),
            float(fold["bm25_k1"]),
            float(fold["bm25_b"]),
        )
        request.user_factors = fold_in(
            np.array([factors[t][0] for t in items]),
            float(fold["alpha"]) * weights,
            await self._gram(version),
            float(fold["regularization"]),
        )
        nearest = await self.repository.nearest_by_inner_product(
            version.id, request.user_factors.tolist(), request.overfetch, EF_SEARCH
        )
        return collaborative_candidates(
            Source.COLLABORATIVE_MF,
            nearest,
            exclude=request.heard,
            limit=request.settings.source_limit,
            model_version=version.version,
        )

    async def _profile(self, request: _Request) -> CandidateList[uuid.UUID]:
        if request.content is None:
            return CandidateList.skipped(Source.PROFILE, "no content model")
        if request.query is None:
            return history_candidates(
                None, exclude=request.heard, limit=0, model_version=request.content.version
            )
        nearest = await self.repository.nearest_tracks(
            request.content.id, request.query.tolist(), request.overfetch, EF_SEARCH
        )
        return history_candidates(
            nearest,
            exclude=request.heard,
            limit=request.settings.source_limit,
            model_version=request.content.version,
        )

    async def _content(self, request: _Request) -> CandidateList[uuid.UUID]:
        if request.content is None:
            return CandidateList.skipped(Source.CONTENT, "no content model")
        profile = request.profile
        seeds = [*profile.seed_tracks, *profile.recent_tracks]
        # One query for every seed's neighbours (was one round trip per seed). A seed listed
        # twice (strong and recent) still counts twice, as before.
        neighbours_of = await self.repository.nearest_tracks_for_seeds(
            request.content.id,
            list(dict.fromkeys(seeds)),
            request.settings.content_neighbours + 1,
            EF_SEARCH,
        )
        seed_neighbours = [
            (seed, [(t, s) for t, s in neighbours_of[seed] if t != seed])
            for seed in seeds
            if seed in neighbours_of
        ]
        candidates, seed_of = content_candidates(
            seed_neighbours,
            exclude=request.heard,
            limit=request.settings.source_limit,
            model_version=request.content.version,
        )
        request.content_seed_of = seed_of
        return candidates

    async def _exploration(self, request: _Request) -> CandidateList[uuid.UUID]:
        if request.content is None:
            return CandidateList.skipped(Source.EXPLORATION, "no content model")
        profile = request.profile
        long_term = profile.long_term_embedding
        if long_term is None:
            candidates, _ = exploration_candidates(
                None,
                {},
                known_artists=profile.known_artists,
                avoided_artists=frozenset(),
                exclude=request.heard,
                tracks_per_artist=0,
                limit=0,
                model_version=request.content.version,
            )
            return candidates
        settings = request.settings
        similar = await self.repository.nearest_artists(
            request.content.id, long_term.tolist(), settings.exploration_artists * 3, EF_SEARCH
        )
        avoided = profile.excluded_artists | set(profile.negative_artists)
        new_artists = [a for a, _ in similar if a not in profile.known_artists and a not in avoided]
        top = await self.repository.top_tracks_by_artist(
            new_artists,
            request.content.id,
            request.popularity.id,
            settings.tracks_per_artist + 2,
        )
        candidates, artist_of = exploration_candidates(
            similar,
            top,
            known_artists=profile.known_artists,
            avoided_artists=avoided,
            exclude=request.heard,
            tracks_per_artist=settings.tracks_per_artist,
            limit=settings.exploration_limit,
            model_version=request.content.version,
        )
        request.exploration_artist_of = artist_of
        return candidates

    async def _popularity(self, request: _Request) -> CandidateList[uuid.UUID]:
        popularity = request.popularity
        genre_rankings = []
        for name in list(request.profile.genre_affinity)[: request.settings.popular_genres]:
            key = (popularity.id, f"genre:{name}")
            ranking = POPULARITY_CACHE.get(key)
            if ranking is None:
                genre = await self.repository.find_genre(name)
                members = (
                    []
                    if genre is None
                    else await self.repository.genre_members(
                        genre.id, popularity.id, MIN_GENRE_AFFINITY, GENRE_POPULARITY_WEIGHT, 300
                    )
                )
                ranking = [(m.track_id, genre_score(m.affinity, m.popularity)) for m in members]
                POPULARITY_CACHE.put(key, ranking)
            if ranking:
                genre_rankings.append(ranking)
        popular = POPULARITY_CACHE.get((popularity.id, "popular"))
        if popular is None:
            rows = await self.repository.popular(popularity.id, 500)
            popular = [(row.track_id, row.score) for row in rows]
            POPULARITY_CACHE.put((popularity.id, "popular"), popular)
        return popularity_candidates(
            genre_rankings,
            popular,
            exclude=request.heard,
            limit=request.settings.popularity_limit,
            model_version=popularity.version,
        )

    # --- for you -----------------------------------------------------------------------------

    async def for_you(
        self,
        user_id: uuid.UUID,
        limit: int,
        mode: ExplorationMode | None = None,
        *,
        collection: str = "for_you",
        exclude: Collection[uuid.UUID] = (),
        request_context: RequestContext | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> PersonalizedResponse:
        """The personal mix. `collection` "hidden_gems" keeps only lesser-known tracks (popularity
        score at most HIDDEN_GEM_MAX_POPULARITY) under the hidden-gems policy; `exclude` removes
        tracks (e.g. a playlist's current tracks when it is regenerated)."""
        if collection not in ("for_you", "hidden_gems"):
            raise ValueError(f"unknown collection {collection}")
        started = time.perf_counter()
        context = await self.profiles.current(user_id)
        popularity = await self._require("popularity")
        content = await self.repository.active_version("content")
        collaborative = await self.repository.active_version("collaborative")
        hybrid = await self.repository.active_version("hybrid")
        settings = HybridSettings.from_version(hybrid)
        profile, signals = context.profile, context.signals
        personalized = context.personalization_enabled

        keys = list(signals.keys)
        strongest = np.argsort(-signals.positive, kind="stable")[:MAX_CF_HISTORY]
        cf_values = {
            keys[i]: float(signals.positive[i])
            for i in strongest.tolist()
            if signals.positive[i] > 0 and not signals.disliked[i]
        }
        if not personalized:
            # Opt-out: no personal data in ranking; only what was heard is not repeated.
            profile = replace(
                profile,
                long_term_embedding=None,
                short_term_embedding=None,
                genre_affinity={},
                artist_affinity={},
                negative_artists={},
                known_artists=frozenset(),
                seed_tracks=(),
                recent_tracks=(),
                history_size=0,
            )
            context = replace(context, profile=profile)
            cf_values = {}
        request = _Request(
            context=context,
            content=content,
            popularity=popularity,
            collaborative=collaborative,
            settings=settings,
            heard=profile.heard_tracks | frozenset(exclude),
            cf_values=cf_values,
            query=profile_query(
                profile.long_term_embedding,
                profile.short_term_embedding,
                context.config.short_term_weight,
            ),
        )
        lists = [
            await self._isolated(
                Source.COLLABORATIVE_ITEM, lambda: self._collaborative_item(request)
            ),
            await self._isolated(Source.COLLABORATIVE_MF, lambda: self._collaborative_mf(request)),
            await self._isolated(Source.PROFILE, lambda: self._profile(request)),
            await self._isolated(Source.CONTENT, lambda: self._content(request)),
            await self._isolated(Source.EXPLORATION, lambda: self._exploration(request)),
            await self._isolated(Source.POPULARITY, lambda: self._popularity(request)),
        ]
        merged = merge_candidates(lists)
        items = list(merged.items)
        facts = await self.repository.track_facts(items, popularity.id)
        heard_keys = await self.repository.song_keys(list(profile.heard_tracks))
        candidate_filter: CandidateFilter[uuid.UUID, uuid.UUID] = CandidateFilter(
            heard=request.heard,
            disliked=profile.disliked_tracks,
            excluded_artists=profile.excluded_artists,
            heard_song_keys=frozenset(heard_keys.values()),
        )
        kept, removed = candidate_filter.apply(
            merged,
            artists=[facts[t].artist_id if t in facts else uuid.UUID(int=0) for t in items],
            song_keys=[facts[t].song_key if t in facts else None for t in items],
            eligible=[t in facts for t in items],
        )
        retrieved = time.perf_counter()
        metrics.RECOMMENDATION_LATENCY.labels(collection, "candidates").observe(retrieved - started)
        metrics.RECOMMENDATION_CANDIDATES.labels(collection).observe(len(merged))
        gems = collection == "hidden_gems"
        if gems:
            lesser_known = [
                row
                for row, track in enumerate(kept.items)
                if facts[track].popularity <= HIDDEN_GEM_MAX_POPULARITY
            ]
            kept = kept.subset(lesser_known)
        cold = profile.history_size == 0
        strategy = Strategy.PERSONALIZED if not cold else Strategy.COLD_START
        if gems:
            strategy = Strategy.HIDDEN_GEMS
        if len(kept) == 0:
            return self._response(
                user_id,
                context,
                strategy,
                settings,
                [],
                kept,
                [],
                {},
                mode,
                popularity,
                content,
                collaborative,
                hybrid,
                "none",
            )

        candidates = list(kept.items)
        embeddings = await self._matrix(content, candidates)
        artists = [facts[t].artist_id for t in candidates]
        features = await self._features(request, kept, facts, embeddings, artists)
        if cold:
            similarity = features[:, 2].astype(np.float64)  # profile_sim
            popularity_score = np.array([facts[t].popularity for t in candidates])
            scores = np.array(
                [
                    blended_score(s, p, settings.cold_start_popularity_weight)
                    for s, p in zip(similarity, popularity_score, strict=True)
                ]
            )
            ranker_name = "cold-start blend"
        else:
            ranker = await self._ranker(settings)
            scores = ranker.score(features)
            ranker_name = ranker.kind
        negative = np.array([profile.negative_artists.get(a, 0.0) for a in artists])
        relevance = demote_negative_artists(normalized_relevance(scores), negative)
        context_fits, applied = await self._context(
            user_id,
            profile,
            candidates,
            relevance,
            request_context,
            params or {},
            personalized and not cold,
        )
        relevance = relevance + context_fits
        default = (
            None if settings.default_mode == "auto" else ExplorationMode(settings.default_mode)
        )
        chosen_mode = mode or profile.exploration_mode or default
        target = None if not personalized else profile.discovery_target(chosen_mode)
        discovery = np.array([personalized and a not in profile.known_artists for a in artists])
        policy = settings.for_you_policy()
        if gems:
            policy = POLICIES["hidden_gems"]
            target = None if not personalized else max(target or 0.0, HIDDEN_GEM_DISCOVERY)
        picked = compose(
            relevance,
            limit=limit,
            policy=policy,
            artists=artists,
            song_keys=[facts[t].song_key for t in candidates],
            embeddings=embeddings,
            discovery=discovery if not cold else None,
            discovery_target=target if not cold else None,
        )
        reasons = await self._reasons(request, kept, picked, facts, features)
        if gems:
            reasons = [
                explanations.hidden_gem_reason(reason, facts[candidates[i]].listeners)
                for reason, i in zip(reasons, picked, strict=True)
            ]
        if applied.get("session_events"):
            reasons = [
                f"{reason}; in tune with what you are playing now"
                if context_fits[i] >= SESSION_REASON_THRESHOLD
                else reason
                for reason, i in zip(reasons, picked, strict=True)
            ]
        ordered = [(candidates[i], float(relevance[i]), bool(discovery[i]), i) for i in picked]
        summaries = await self.catalogue.track_summaries([t for t, _, _, _ in ordered])
        titles = summaries
        logger.info(
            "for-you user=%s strategy=%s candidates=%d removed=%s ranker=%s",
            user_id,
            strategy.value,
            len(merged),
            removed,
            ranker_name,
        )
        mode_label = (
            (chosen_mode.value if chosen_mode is not None else "auto") if personalized else "off"
        )
        finished = time.perf_counter()
        metrics.RECOMMENDATION_LATENCY.labels(collection, "ranking").observe(finished - retrieved)
        metrics.RECOMMENDATION_LATENCY.labels(collection, "total").observe(finished - started)
        return self._response(
            user_id,
            context,
            strategy,
            settings,
            ordered,
            kept,
            reasons,
            facts,
            mode,
            popularity,
            content,
            collaborative,
            hybrid,
            ranker_name,
            target=target,
            mode_label=mode_label,
            policy=policy.category,
            titles=titles,
            applied_context=applied,
        )

    async def _context(
        self,
        user_id: uuid.UUID,
        profile: TasteProfile[uuid.UUID, uuid.UUID],
        candidates: Sequence[uuid.UUID],
        relevance: FloatArray,
        request_context: RequestContext | None,
        params: Mapping[str, Any],
        enabled: bool,
    ) -> tuple[FloatArray, dict[str, Any]]:
        """Context nudges (context.py): the session (previous hour) and, only when an experiment
        switches it on, the time of day. Returns per-candidate adjustments and what was used."""
        nudges = np.zeros(len(candidates))
        session_weight = float(params.get("session_weight", ctx.DEFAULT_SESSION_WEIGHT))
        daypart_weight = float(params.get("daypart_weight", ctx.DEFAULT_DAYPART_WEIGHT))
        applied: dict[str, Any] = {
            "session_weight": session_weight,
            "daypart_weight": daypart_weight,
        }
        overall = ctx.normalized(profile.genre_affinity)
        if session_weight <= 0 and daypart_weight <= 0:
            return nudges, applied
        if not enabled or not candidates or not overall:
            return nudges, applied
        now = (request_context.now if request_context else None) or datetime.now(UTC)
        events = await self.profiles.users.events(user_id)
        positive = [
            (track, when)
            for track, kind, when in zip(
                events.track_ids, events.event_types, events.occurred_at, strict=True
            )
            if kind in ctx.POSITIVE_EVENTS
        ]
        window = now - timedelta(minutes=ctx.SESSION_WINDOW_MINUTES)
        recent = [track for track, when in positive if window <= when <= now]
        zone = request_context.zone if request_context else None
        # The composer only looks at the best `pool` candidates, and a nudge of at most the
        # weight cannot lift a track from further down: only the top CONTEXT_POOL are scored.
        rows = np.argsort(-relevance, kind="stable")[:CONTEXT_POOL]
        scored = [candidates[i] for i in rows]
        needed = set(scored) | set(recent)
        if daypart_weight > 0 and zone is not None:
            needed |= {track for track, _ in positive}
        genres = await self._genres(list(needed))
        if session_weight > 0:
            session = ctx.build_session(genres.get(t, {}) for t in recent)
            applied["session_events"] = session.events
            if session.events >= ctx.MIN_SESSION_EVENTS:
                nudges[rows] += session_weight * np.array(
                    [ctx.session_fit(session, overall, genres.get(t, {})) for t in scored]
                )
        if daypart_weight > 0 and zone is not None:
            part = ctx.daypart_of(now, zone)
            history = ctx.build_context_profile(
                (ctx.daypart_of(when, zone), genres.get(track, {})) for track, when in positive
            )
            applied["daypart"] = part
            applied["daypart_events"] = history.evidence(part)
            nudges[rows] += daypart_weight * np.array(
                [ctx.context_fit(history, part, genres.get(t, {})) for t in scored]
            )
        return nudges, applied

    async def _matrix(
        self, content: ModelVersion | None, tracks: Sequence[uuid.UUID]
    ) -> FloatArray | None:
        if content is None:
            return None
        vectors = await self.repository.track_embeddings(content.id, tracks)
        if not vectors:
            return None
        dimension = len(next(iter(vectors.values())))
        matrix = np.zeros((len(tracks), dimension))
        for row, track in enumerate(tracks):
            if track in vectors:
                matrix[row] = vectors[track]
        return matrix

    async def _features(
        self,
        request: _Request,
        candidates: CandidateSet[uuid.UUID],
        facts: dict[uuid.UUID, TrackFacts],
        embeddings: FloatArray | None,
        artists: list[uuid.UUID],
    ) -> npt.NDArray[np.float32]:
        profile = request.profile
        tracks = list(candidates.items)
        n = len(tracks)
        listeners = np.array([facts[t].listeners for t in tracks], dtype=np.float64)
        train_users = float(request.popularity.training_data.get("users", 0) or 0)
        if train_users > 0:
            information = -np.log2((listeners + 1.0) / (train_users + 1.0))
            novelty = information / math.log2(train_users + 1.0)
        else:
            novelty = np.zeros(n)
        seed_similarity = profile_sim = long_sim = short_sim = None
        if embeddings is not None and request.content is not None:
            seeds = [*profile.seed_tracks, *profile.recent_tracks]
            seed_vectors = await self.repository.track_embeddings(request.content.id, seeds)
            if seed_vectors:
                seed_similarity = embeddings @ np.array(list(seed_vectors.values())).T
            if request.query is not None:
                profile_sim = embeddings @ request.query
            if profile.long_term_embedding is not None:
                long_sim = embeddings @ profile.long_term_embedding
            if profile.short_term_embedding is not None:
                short_sim = embeddings @ profile.short_term_embedding
        total = sum(request.cf_values.values())
        cf_item = (
            np.array([request.item_scores.get(t, 0.0) for t in tracks]) / total
            if total > 0
            else None
        )
        cf_mf = None
        if request.user_factors is not None and request.collaborative is not None:
            factors = await self.repository.cf_factors(request.collaborative.id, tracks)
            cf_mf = np.array(
                [
                    float(np.dot(factors[t][0], request.user_factors)) if t in factors else 0.0
                    for t in tracks
                ]
            )
        return feature_matrix(
            FeatureInputs(
                popularity=np.array([facts[t].popularity for t in tracks]),
                novelty=np.asarray(novelty, dtype=np.float64),
                artist_affinity=np.array([profile.artist_affinity.get(a, 0.0) for a in artists]),
                artist_known=np.array([float(a in profile.known_artists) for a in artists]),
                artist_negative=np.array([profile.negative_artists.get(a, 0.0) for a in artists]),
                source_ranks=candidates.ranks,
                history_size=profile.history_size,
                exploration=profile.exploration_preference,
                seed_similarity=seed_similarity,
                profile_sim=profile_sim,
                profile_long_sim=long_sim,
                profile_short_sim=short_sim,
                cf_item_score=cf_item,
                cf_mf_score=cf_mf,
            )
        )

    async def _reasons(
        self,
        request: _Request,
        candidates: CandidateSet[uuid.UUID],
        picked: Sequence[int],
        facts: dict[uuid.UUID, TrackFacts],
        features: npt.NDArray[np.float32],
    ) -> list[str]:
        """The strongest recorded evidence for each picked track."""
        profile = request.profile
        tracks = [candidates.items[i] for i in picked]
        seeds = set(request.content_seed_of.values()) | set(request.item_best_seed.values())
        titles = await self.catalogue.track_summaries([*seeds, *tracks])
        names = await self.profiles.users.artist_names([facts[t].artist_id for t in tracks])
        genres = await self._genres(tracks)
        plays = dict(zip(request.context.signals.keys, request.context.signals.plays, strict=True))
        reasons = []
        for row, track in zip(picked, tracks, strict=True):
            artist = facts[track].artist_id
            found = {c.source for c in candidates.attribution(row)}
            shared = explanations.shared_genres(profile.genre_affinity, genres.get(track, {}))
            seed = request.content_seed_of.get(track)
            co_seed = request.item_best_seed.get(track)
            affinity = profile.artist_affinity.get(artist, 0.0)
            if Source.CONTENT in found and seed is not None and seed in titles:
                similarity = float(features[row, 0])
                reasons.append(
                    explanations.seed_similarity_reason(
                        titles[seed].title, similarity, int(plays.get(seed, 0))
                    )
                )
            elif affinity >= 0.3 and artist in names:
                reasons.append(explanations.familiar_artist_reason(names[artist], affinity))
            elif Source.COLLABORATIVE_ITEM in found and co_seed is not None and co_seed in titles:
                reasons.append(explanations.co_listened_reason(titles[co_seed].title))
            elif Source.EXPLORATION in found and artist in names:
                reasons.append(
                    explanations.new_artist_reason(names[artist], shared, float(features[row, 2]))
                )
            elif Source.COLLABORATIVE_MF in found:
                rank = int(candidates.ranks[row, candidates.column(Source.COLLABORATIVE_MF)])
                reasons.append(explanations.collaborative_reason(rank))
            elif Source.POPULARITY in found and not profile.history_size:
                reasons.append(explanations.popular_reason(facts[track].listeners, 14))
            else:
                reasons.append(explanations.profile_reason(shared, float(features[row, 2])))
        return reasons

    def _response(
        self,
        user_id: uuid.UUID | None,
        context: ProfileContext | None,
        strategy: Strategy,
        settings: HybridSettings,
        ordered: Sequence[tuple[uuid.UUID, float, bool, int]],
        candidates: CandidateSet[uuid.UUID],
        reasons: Sequence[str],
        facts: dict[uuid.UUID, TrackFacts],
        mode: ExplorationMode | None,
        popularity: ModelVersion,
        content: ModelVersion | None,
        collaborative: ModelVersion | None,
        hybrid: ModelVersion | None,
        ranker: str,
        *,
        target: float | None = None,
        mode_label: str | None = None,
        policy: str = "for_you",
        titles: Mapping[uuid.UUID, TrackSummary] | None = None,
        applied_context: dict[str, Any] | None = None,
    ) -> PersonalizedResponse:
        versions = {
            v.model_type: v.version
            for v in (hybrid, collaborative, content, popularity)
            if v is not None
        }
        primary = hybrid or collaborative or content or popularity
        items = []
        for (track, score, discovery, row), reason in zip(ordered, reasons, strict=True):
            summary = (titles or {}).get(track)
            items.append(
                PersonalizedItem(
                    track_id=track,
                    title=summary.title if summary else "",
                    artist=summary.artist if summary else "",
                    artist_id=summary.artist_id if summary else None,
                    album=summary.album_title if summary else None,
                    artwork_url=summary.artwork_url if summary else None,
                    score=round(score, 4),
                    reason=reason,
                    discovery=discovery,
                    sources=[
                        CandidateSourceOut(
                            source=c.source.value,
                            retrieval_score=round(c.retrieval_score, 4),
                            rank=c.rank,
                            model_version=c.model_version,
                        )
                        for c in candidates.attribution(row)
                    ],
                )
            )
        response = PersonalizedResponse(
            request_id=uuid.uuid4(),
            model_version=primary.version,
            model_versions=versions,
            strategy=strategy,
            recommendations=items,
            user_id=user_id,
            profile_version=None if context is None else context.profile.profile_version,
            ranker=ranker,
            composition=Composition(
                familiar=sum(1 for i in items if not i.discovery),
                discovery=sum(1 for i in items if i.discovery),
                discovery_target=target,
                exploration_mode=mode_label or (mode.value if mode else "auto"),
                diversity_policy=policy,
            ),
            candidate_sources=[
                SourceStatusOut(
                    source=r.source.value,
                    status=r.status.value,
                    candidates=r.candidates,
                    model_version=r.model_version,
                    detail=r.detail,
                )
                for r in candidates.reports
            ],
            context=applied_context or {},
        )
        logger.info(
            "recommendations request_id=%s strategy=%s model=%s count=%d",
            response.request_id,
            strategy.value,
            primary.version,
            len(items),
        )
        return response

    # --- artist radio --------------------------------------------------------------------------

    async def artist_radio(self, artist_id: uuid.UUID, limit: int) -> RecommendationResponse:
        """The artist's most popular tracks mixed with those of similar artists. Category policy:
        the seed artist may fill up to `seed_artist_share` of the list, others two tracks each,
        with MMR to avoid near-duplicate picks."""
        content = await self._require("content")
        popularity = await self._require("popularity")
        artist = await self.session.get(Artist, artist_id)
        if artist is None:
            raise NotFoundError("Artist")
        vector = await self.repository.artist_embedding(content.id, artist_id)
        if vector is None:
            raise NotInModelError("Artist")
        policy = POLICIES["artist_radio"]
        similar = [
            (a, s)
            for a, s in await self.repository.nearest_artists(
                content.id, vector, SIMILAR_ARTISTS_POOL + 1, EF_SEARCH
            )
            if a != artist_id
        ][:SIMILAR_ARTISTS_POOL]
        seed_share = policy.seed_artist_share or 0.0
        own = await self.repository.top_tracks_by_artist(
            [artist_id], content.id, popularity.id, max(1, math.ceil(seed_share * limit) * 2)
        )
        others = await self.repository.top_tracks_by_artist(
            [a for a, _ in similar], content.id, popularity.id, 3
        )
        pool = [(t, 1.0) for t in own.get(artist_id, [])]
        pool += [(t, s) for a, s in similar for t in others.get(a, [])]
        tracks = [t for t, _ in pool]
        facts = await self.repository.track_facts(tracks, popularity.id)
        pool = [(t, s) for t, s in pool if t in facts]
        tracks = [t for t, _ in pool]
        beta = float(content.params.get("beta", {}).get("artist", 0.5))
        relevance = np.array([blended_score(s, facts[t].popularity, beta) for t, s in pool])
        picked = compose(
            relevance,
            limit=limit,
            policy=policy,
            artists=[facts[t].artist_id for t in tracks],
            song_keys=[facts[t].song_key for t in tracks],
            embeddings=await self._matrix(content, tracks),
            seed_artist=artist_id,
        )
        seed_genres = await self.repository.artist_genres(artist_id)
        chosen = [tracks[i] for i in picked]
        genres = await self._genres(chosen)
        similarity = dict(pool)
        reasons = {}
        for track in chosen:
            if facts[track].artist_id == artist_id:
                reasons[track] = explanations.artist_radio_reason(
                    artist.name, facts[track].listeners
                )
            else:
                reasons[track] = explanations.similar_artist_reason(
                    artist.name,
                    similarity[track],
                    explanations.shared_genres(seed_genres, genres.get(track, {})),
                )
        summaries = await self.catalogue.track_summaries(chosen)
        items = [
            RecommendationItem(
                track_id=track,
                title=summaries[track].title,
                artist=summaries[track].artist,
                artist_id=summaries[track].artist_id,
                album=summaries[track].album_title,
                artwork_url=summaries[track].artwork_url,
                score=round(float(relevance[i]), 4),
                reason=reasons[track],
            )
            for i, track in zip(picked, chosen, strict=True)
            if track in summaries
        ]
        response = RecommendationResponse(
            request_id=uuid.uuid4(),
            model_version=content.version,
            model_versions={"content": content.version, "popularity": popularity.version},
            strategy=Strategy.ARTIST_RADIO,
            recommendations=items,
        )
        logger.info(
            "recommendations request_id=%s strategy=artist_radio model=%s count=%d",
            response.request_id,
            content.version,
            len(items),
        )
        return response

    # --- surprise and "because you listened to" -------------------------------------------------

    async def surprise(self, user_id: uuid.UUID) -> PersonalizedResponse:
        """One discovery picked at random from the user's top explorer-mode recommendations (a
        fresh pick on every request; the candidates themselves are the personal ranking)."""
        response = await self.for_you(user_id, SURPRISE_POOL, ExplorationMode.EXPLORER)
        pool = [i for i in response.recommendations if i.discovery] or response.recommendations
        if not pool:
            return response.model_copy(update={"strategy": Strategy.SURPRISE})
        pick = secrets.choice(pool)
        item = pick.model_copy(update={"reason": explanations.surprise_reason(pick.reason)})
        return response.model_copy(
            update={"strategy": Strategy.SURPRISE, "recommendations": [item]}
        )

    async def because_you_listened(
        self, user_id: uuid.UUID, seeds: int, limit: int
    ) -> list[BecauseYouListened]:
        """For the user's strongest recent tracks: what listeners of that track also play
        (item-item neighbours), else its content neighbours; unheard tracks only."""
        context = await self.profiles.current(user_id)
        if not context.personalization_enabled:
            return []
        popularity = await self._require("popularity")
        content = await self.repository.active_version("content")
        collaborative = await self.repository.active_version("collaborative")
        profile = context.profile
        seed_tracks = list(dict.fromkeys([*profile.recent_tracks, *profile.seed_tracks]))[:seeds]
        summaries = await self.catalogue.track_summaries(seed_tracks)
        heard = profile.heard_tracks
        heard_keys = set((await self.repository.song_keys(list(heard))).values())
        sections: list[BecauseYouListened] = []
        for seed in seed_tracks:
            if seed not in summaries:
                continue
            pool: list[tuple[uuid.UUID, float]] = []
            source = "collaborative"
            if collaborative is not None:
                rows = await self.repository.neighbour_rows(collaborative.id, [seed])
                pool = sorted(((n, s) for _, n, s in rows), key=lambda kv: (-kv[1], str(kv[0])))
            if not pool and content is not None:
                vector = await self.repository.track_embedding(content.id, seed)
                if vector is not None:
                    source = "content"
                    pool = await self.repository.nearest_tracks(
                        content.id, vector, CANDIDATE_POOL, EF_SEARCH
                    )
            pool = [(t, s) for t, s in pool if t != seed and t not in heard]
            facts = await self.repository.track_facts([t for t, _ in pool], popularity.id)
            ranked = rerank(
                (
                    Candidate(t, s, facts[t].popularity, facts[t].artist_id, facts[t].song_key)
                    for t, s in pool
                    if t in facts
                    and facts[t].song_key not in heard_keys
                    and facts[t].artist_id not in profile.excluded_artists
                ),
                beta=0.0,
                limit=limit,
            )
            items_summaries = await self.catalogue.track_summaries([r.item for r in ranked])
            title = summaries[seed].title
            reason = (
                explanations.co_listened_reason(title)
                if source == "collaborative"
                else explanations.seed_similarity_reason(title, 0.0, 0).split(" (")[0]
            )
            items = [
                RecommendationItem(
                    track_id=r.item,
                    title=items_summaries[r.item].title,
                    artist=items_summaries[r.item].artist,
                    artist_id=items_summaries[r.item].artist_id,
                    album=items_summaries[r.item].album_title,
                    artwork_url=items_summaries[r.item].artwork_url,
                    score=round(r.score, 4),
                    reason=reason,
                )
                for r in ranked
                if r.item in items_summaries
            ]
            if items:
                sections.append(
                    BecauseYouListened(seed=summaries[seed], source=source, recommendations=items)
                )
        await self.session.commit()
        return sections
