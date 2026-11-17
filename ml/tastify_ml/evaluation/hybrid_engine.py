"""Offline candidate generation and features for the hybrid recommender (ADR-016).

For each evaluated user this runs what the API runs for a TASTIFY user, with the backend's own
functions: the taste profile (`build_taste_profile`), the six candidate generators, the merger
and the filter, and `feature_matrix`. Only retrieval differs: exact numpy search here, pgvector and
SQL in the API (the retrieval benchmark measures the difference).

Models are trained per period on interactions before its cutoff (`train_period_models`), so
nothing from the predicted window leaks into candidates or features.
"""

import logging
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import scipy.sparse as sp

from app.domains.recommendations.candidate_generation import (
    SOURCE_ORDER,
    CandidateFilter,
    CandidateList,
    Source,
    merge_candidates,
    run_isolated,
)
from app.domains.recommendations.candidate_generation.collaborative_candidates import (
    collaborative_candidates,
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
from app.domains.recommendations.features import FeatureInputs, feature_matrix
from app.domains.recommendations.ranking import MIN_GENRE_AFFINITY, genre_score
from app.domains.users.events import TrackSignals
from app.domains.users.profile import (
    TasteProfile,
    TasteProfileConfig,
    build_taste_profile,
    profile_query,
)
from tastify_ml.evaluation import metrics
from tastify_ml.recommendation.catalogue_data import CatalogueData
from tastify_ml.recommendation.collaborative import (
    ALSConfig,
    ALSModel,
    ItemItemConfig,
    ItemItemModel,
    train_als,
    train_item_item,
)
from tastify_ml.recommendation.content import artist_embeddings
from tastify_ml.recommendation.content_assets import ContentAssets
from tastify_ml.recommendation.popularity import PopularityConfig, compute_popularity
from tastify_ml.recommendation.signals import UserSignals, compute_signals

logger = logging.getLogger(__name__)

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class HybridConfig:
    profile: TasteProfileConfig = field(default_factory=TasteProfileConfig)
    als: ALSConfig = field(default_factory=ALSConfig)
    item_item: ItemItemConfig = field(default_factory=ItemItemConfig)
    # Candidates kept per source.
    source_limit: int = 200
    # Content neighbours fetched per seed track.
    content_neighbours: int = 100
    exploration_artists: int = 60
    tracks_per_artist: int = 2
    exploration_limit: int = 100
    popularity_limit: int = 100
    popular_genres: int = 2
    sources: tuple[Source, ...] = SOURCE_ORDER

    def params(self) -> dict[str, Any]:
        out = asdict(self)
        out["sources"] = [s.value for s in self.sources]
        return out


@dataclass
class ItemFacts:
    """Catalogue facts per item index."""

    artist_codes: IntArray
    song_keys: list[str]
    genre_affinity: sp.csc_matrix  # (items, genres): served genre affinity (ranking.genre_affinity)
    genre_names: list[str]

    def __post_init__(self) -> None:
        self.genre_column = {name: i for i, name in enumerate(self.genre_names)}


@dataclass
class PeriodModels:
    """Everything learned from the interactions before `cutoff`."""

    name: str
    cutoff: pd.Timestamp
    signals: UserSignals
    popularity: pd.DataFrame
    als: ALSModel
    item_item: ItemItemModel
    artist_embeddings: npt.NDArray[np.float32]
    tracks_by_artist: list[list[int]]
    global_ranking: list[tuple[int, float]]
    novelty: FloatArray
    train_users: int
    seconds: dict[str, float]
    _genre_rankings: dict[str, list[tuple[int, float]]] = field(default_factory=dict, repr=False)

    @property
    def score(self) -> FloatArray:
        return self.popularity["score"].to_numpy(dtype=np.float64)

    @property
    def listeners(self) -> IntArray:
        return self.popularity["listeners"].to_numpy(dtype=np.int64)

    def genre_ranking(self, genre: str, facts: ItemFacts, limit: int) -> list[tuple[int, float]]:
        """Members of a genre, best genre score first (GET /recommendations/genre ranking)."""
        if genre not in self._genre_rankings:
            column = facts.genre_column.get(genre)
            ranking: list[tuple[int, float]] = []
            if column is not None:
                values = facts.genre_affinity.getcol(column).tocoo()
                keep = values.data >= MIN_GENRE_AFFINITY
                members = values.row[keep]
                scores = np.array(
                    [
                        genre_score(float(a), float(self.score[i]))
                        for i, a in zip(members, values.data[keep], strict=True)
                    ]
                )
                order = np.lexsort((members, -scores)) if len(members) else np.array([], int)
                ranking = [(int(members[i]), float(scores[i])) for i in order[:limit]]
            self._genre_rankings[genre] = ranking
        return self._genre_rankings[genre]


def train_period_models(
    name: str,
    interactions: pd.DataFrame,
    catalogue: CatalogueData,
    content: ContentAssets,
    facts: ItemFacts,
    cutoff: pd.Timestamp,
    config: HybridConfig,
    popularity_config: PopularityConfig,
) -> PeriodModels:
    seconds: dict[str, float] = {}
    started = time.perf_counter()
    item_of = pd.Series(np.arange(catalogue.n_items), index=catalogue.track_ids)
    signals = compute_signals(interactions, item_of, cutoff, config.profile)
    seconds["signals"] = time.perf_counter() - started

    started = time.perf_counter()
    train = interactions[interactions["listened_at"] < cutoff]
    popularity = compute_popularity(train, catalogue.track_ids, cutoff, popularity_config)
    seconds["popularity"] = time.perf_counter() - started

    matrix = signals.matrix("positive")
    started = time.perf_counter()
    als = train_als(matrix, config.als)
    seconds["als"] = time.perf_counter() - started
    started = time.perf_counter()
    item_item = train_item_item(matrix, config.item_item)
    seconds["item_item"] = time.perf_counter() - started

    listeners = popularity["listeners"].to_numpy(dtype=np.int64)
    artists, _ = artist_embeddings(content.embeddings, facts.artist_codes, listeners)
    order = np.lexsort((np.arange(len(listeners)), -listeners))
    has_content = content.has_embedding
    tracks_by_artist: list[list[int]] = [[] for _ in range(len(artists))]
    for item in order:
        if has_content[item]:
            tracks_by_artist[facts.artist_codes[item]].append(int(item))
    score = popularity["score"].to_numpy(dtype=np.float64)
    global_ranking = [(int(i), float(score[i])) for i in order[:500] if listeners[i] > 0]
    train_users = int(train["user_key"].nunique())
    information = metrics.self_information(listeners, train_users)
    novelty = information / information.max() if information.max() > 0 else information
    logger.info(
        "%s models: %d users, matrix nnz %d (%s)",
        name,
        len(signals),
        matrix.nnz,
        ", ".join(f"{k} {v:.1f}s" for k, v in seconds.items()),
    )
    return PeriodModels(
        name=name,
        cutoff=cutoff,
        signals=signals,
        popularity=popularity,
        als=als,
        item_item=item_item,
        artist_embeddings=artists,
        tracks_by_artist=tracks_by_artist,
        global_ranking=global_ranking,
        novelty=np.asarray(novelty, dtype=np.float64),
        train_users=train_users,
        seconds=seconds,
    )


@dataclass
class UserCandidates:
    """One user's filtered, merged candidates with features, ready for ranking."""

    user: str
    items: IntArray
    features: npt.NDArray[np.float32]
    labels: BoolArray
    artists: IntArray
    song_keys: list[str]
    discovery: BoolArray  # artist new to the user
    ranks: npt.NDArray[np.float32]  # (n, len(SOURCE_ORDER)) retrieval ranks, inf if absent
    discovery_target: float  # the behaviour-derived ("auto") target
    history_size: int
    statuses: dict[str, str]
    # Relevant items before filtering that some source retrieved (for recall analysis).
    n_relevant: int
    # All relevant items of the user (the denominator of recall and ideal DCG).
    n_targets: int
    known_artists: frozenset[int]

    def __len__(self) -> int:
        return len(self.items)

    def subset(self, rows: BoolArray) -> "UserCandidates":
        index = np.flatnonzero(rows)
        return UserCandidates(
            user=self.user,
            items=self.items[index],
            features=self.features[index],
            labels=self.labels[index],
            artists=self.artists[index],
            song_keys=[self.song_keys[i] for i in index.tolist()],
            discovery=self.discovery[index],
            ranks=self.ranks[index],
            discovery_target=self.discovery_target,
            history_size=self.history_size,
            statuses=self.statuses,
            n_relevant=self.n_relevant,
            n_targets=self.n_targets,
            known_artists=self.known_artists,
        )


def _top(
    row: FloatArray, exclude: IntArray, k: int, positive_only: bool
) -> list[tuple[int, float]]:
    """The k best entries of a dense score row, excluding `exclude` (and non-positive scores)."""
    values = row.copy()
    values[exclude] = -np.inf
    if positive_only:
        values[values <= 0] = -np.inf
    k = min(k, len(values) - 1)
    top = np.argpartition(-values, k)[:k]
    top = top[np.argsort(-values[top], kind="stable")]
    top = top[np.isfinite(values[top])]
    return list(zip(top.tolist(), values[top].tolist(), strict=True))


class CandidateEngine:
    def __init__(
        self,
        models: PeriodModels,
        content: ContentAssets,
        facts: ItemFacts,
        config: HybridConfig,
        batch: int = 400,
    ) -> None:
        self.models = models
        self.content = content
        self.facts = facts
        self.config = config
        self.batch = batch
        self.embeddings = content.embeddings
        self.versions = dict.fromkeys(SOURCE_ORDER, f"{models.name}-offline")

    def profile(self, position: int) -> tuple[TasteProfile[Any, Any], TrackSignals[np.int64]]:
        signals = self.models.signals.user_signals(position)
        items = signals.keys
        profile = build_taste_profile(
            signals,
            track_artists=self.facts.artist_codes[items].tolist(),
            track_embeddings=self.embeddings[items],
            track_genres=[self.content.genre_profiles[i] for i in items],
            config=self.config.profile,
        )
        return profile, signals

    def generate(
        self, users: Sequence[str], relevant: Mapping[str, IntArray] | None = None
    ) -> Iterator[UserCandidates]:
        for start in range(0, len(users), self.batch):
            yield from self._batch(users[start : start + self.batch], relevant or {})

    def _batch(
        self, users: Sequence[str], relevant: Mapping[str, IntArray]
    ) -> Iterator[UserCandidates]:
        models, config = self.models, self.config
        positions = [models.signals.position[u] for u in users]
        profiles = []
        rows, cols, values = [], [], []
        user_vectors = np.zeros((len(users), models.als.item_factors.shape[1]))
        queries = np.zeros((len(users), self.embeddings.shape[1]))
        for b, position in enumerate(positions):
            profile, signals = self.profile(position)
            profiles.append((profile, signals))
            items = signals.keys.astype(np.int64)
            rows.extend([b] * len(items))
            cols.extend(items.tolist())
            values.extend(signals.positive.tolist())
            user_vectors[b] = models.als.user_vector(items, signals.positive)
            query = profile_query(
                profile.long_term_embedding,
                profile.short_term_embedding,
                config.profile.short_term_weight,
            )
            if query is not None:
                queries[b] = query
        weights = sp.csr_matrix(
            (values, (rows, cols)), shape=(len(users), self.facts.artist_codes.shape[0])
        )
        item_scores = models.item_item.scores(weights).toarray()
        mf_scores = user_vectors @ models.als.item_factors.T.astype(np.float64)
        profile_scores = queries @ self.embeddings.T.astype(np.float64)
        weight_totals = np.asarray(weights.sum(axis=1)).ravel()
        for b, user in enumerate(users):
            profile, signals = profiles[b]
            yield self._user(
                user,
                profile,
                signals.keys.astype(np.int64),
                item_scores[b] / max(weight_totals[b], 1e-12),
                item_scores[b],
                mf_scores[b],
                profile_scores[b] if queries[b].any() else None,
                relevant.get(user),
            )

    def _sources(
        self,
        profile: TasteProfile[int, int],
        heard: IntArray,
        item_row: FloatArray,
        mf_row: FloatArray,
        profile_row: FloatArray | None,
    ) -> list[CandidateList[int]]:
        config, models, facts = self.config, self.models, self.facts
        exclude = profile.heard_tracks
        limit = config.source_limit
        enabled = set(config.sources)
        out: list[CandidateList[int]] = []

        def add(source: Source, make: Any) -> None:
            if source in enabled:
                out.append(run_isolated(source, make))

        add(
            Source.COLLABORATIVE_ITEM,
            lambda: collaborative_candidates(
                Source.COLLABORATIVE_ITEM,
                _top(item_row, heard, limit, positive_only=True),
                exclude=exclude,
                limit=limit,
                model_version=self.versions[Source.COLLABORATIVE_ITEM],
            ),
        )
        add(
            Source.COLLABORATIVE_MF,
            lambda: collaborative_candidates(
                Source.COLLABORATIVE_MF,
                _top(mf_row, heard, limit, positive_only=False),
                exclude=exclude,
                limit=limit,
                model_version=self.versions[Source.COLLABORATIVE_MF],
            ),
        )
        add(
            Source.PROFILE,
            lambda: history_candidates(
                None if profile_row is None else _top(profile_row, heard, limit, False),
                exclude=exclude,
                limit=limit,
                model_version=self.versions[Source.PROFILE],
            ),
        )

        def content() -> CandidateList[int]:
            seeds = [*profile.seed_tracks, *profile.recent_tracks]
            k = config.content_neighbours
            seed_neighbours = [
                (
                    int(s),
                    list(
                        zip(
                            self.content.neighbours[s, :k].tolist(),
                            self.content.neighbour_similarity[s, :k].tolist(),
                            strict=True,
                        )
                    ),
                )
                for s in seeds
            ]
            candidates, _ = content_candidates(
                seed_neighbours,
                exclude=exclude,
                limit=limit,
                model_version=self.versions[Source.CONTENT],
            )
            return candidates

        add(Source.CONTENT, content)

        def exploration() -> CandidateList[int]:
            if profile.long_term_embedding is None:
                similar = None
            else:
                sims = models.artist_embeddings @ profile.long_term_embedding.astype(np.float32)
                top = np.argsort(-sims, kind="stable")[: config.exploration_artists * 3]
                similar = [(int(a), float(sims[a])) for a in top if sims[a] > 0]
            needed = {a: models.tracks_by_artist[a] for a, _ in (similar or [])}
            candidates, _ = exploration_candidates(
                similar,
                needed,
                known_artists=profile.known_artists,
                avoided_artists=profile.excluded_artists | set(profile.negative_artists),
                exclude=exclude,
                tracks_per_artist=config.tracks_per_artist,
                limit=config.exploration_limit,
                model_version=self.versions[Source.EXPLORATION],
            )
            return candidates

        add(Source.EXPLORATION, exploration)

        def popularity() -> CandidateList[int]:
            genres = list(profile.genre_affinity)[: config.popular_genres]
            return popularity_candidates(
                [models.genre_ranking(g, facts, 300) for g in genres],
                models.global_ranking,
                exclude=exclude,
                limit=config.popularity_limit,
                model_version=self.versions[Source.POPULARITY],
            )

        add(Source.POPULARITY, popularity)
        return out

    def _user(
        self,
        user: str,
        profile: TasteProfile[int, int],
        heard: IntArray,
        item_row_normalized: FloatArray,
        item_row: FloatArray,
        mf_row: FloatArray,
        profile_row: FloatArray | None,
        relevant: IntArray | None,
    ) -> UserCandidates:
        facts, models = self.facts, self.models
        lists = self._sources(profile, heard, item_row, mf_row, profile_row)
        merged = merge_candidates(lists)
        n_relevant = 0
        if relevant is not None and len(merged):
            n_relevant = int(np.isin(np.fromiter(merged.items, np.int64), relevant).sum())
        merged_items = np.fromiter(merged.items, dtype=np.int64, count=len(merged))
        candidate_filter: CandidateFilter[int, int] = CandidateFilter(
            heard=profile.heard_tracks,
            disliked=profile.disliked_tracks,
            excluded_artists=profile.excluded_artists,
            heard_song_keys=frozenset(facts.song_keys[i] for i in heard.tolist()),
        )
        kept, _ = candidate_filter.apply(
            merged,
            artists=facts.artist_codes[merged_items].tolist(),
            song_keys=[facts.song_keys[i] for i in merged_items.tolist()],
        )
        items = np.fromiter(kept.items, dtype=np.int64, count=len(kept))
        artists = facts.artist_codes[items]
        vectors = self.embeddings[items].astype(np.float64)
        seeds = [*profile.seed_tracks, *profile.recent_tracks]
        seed_similarity = (
            vectors @ self.embeddings[np.array(seeds, dtype=np.int64)].T.astype(np.float64)
            if seeds
            else None
        )
        long_term, short_term = profile.long_term_embedding, profile.short_term_embedding
        features = feature_matrix(
            FeatureInputs(
                popularity=models.score[items],
                novelty=models.novelty[items],
                artist_affinity=np.array(
                    [profile.artist_affinity.get(int(a), 0.0) for a in artists]
                ),
                artist_known=np.isin(artists, list(profile.known_artists)).astype(np.float64),
                artist_negative=np.array(
                    [profile.negative_artists.get(int(a), 0.0) for a in artists]
                ),
                source_ranks=kept.ranks,
                history_size=profile.history_size,
                exploration=profile.exploration_preference,
                seed_similarity=seed_similarity,
                profile_sim=None if profile_row is None else profile_row[items],
                profile_long_sim=None if long_term is None else vectors @ long_term,
                profile_short_sim=None if short_term is None else vectors @ short_term,
                cf_item_score=item_row_normalized[items],
                cf_mf_score=mf_row[items],
            )
        )
        known = np.isin(artists, list(profile.known_artists))
        return UserCandidates(
            user=user,
            items=items,
            features=features,
            labels=np.isin(items, relevant) if relevant is not None else np.zeros(len(items), bool),
            artists=artists.astype(np.int64),
            song_keys=[facts.song_keys[i] for i in items.tolist()],
            discovery=~known,
            ranks=kept.ranks.astype(np.float32),
            discovery_target=profile.discovery_target(),
            history_size=profile.history_size,
            statuses={r.source.value: r.status.value for r in merged.reports},
            n_relevant=n_relevant,
            n_targets=0 if relevant is None else len(relevant),
            known_artists=frozenset(int(a) for a in profile.known_artists),
        )
