"""Recommenders under offline evaluation.

Each one returns, for every user of an EvaluationTask, K item indices (padded with -1) that are
not in the user's training history. The content and artist recommenders mirror the API
endpoints: same candidate pool, and the backend's own `rerank` (popularity blend, artist cap,
duplicate removal), so the metrics describe what is actually served.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

from app.domains.recommendations.ranking import (
    CANDIDATE_POOL,
    DEFAULT_MAX_PER_ARTIST,
    GENRE_POPULARITY_WEIGHT,
    MIN_GENRE_AFFINITY,
    SIMILAR_ARTISTS_POOL,
    TRACKS_PER_SIMILAR_ARTIST,
    Candidate,
    genre_score,
    rerank,
)
from tastify_ml.evaluation.split import EvaluationTask

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
Embeddings = npt.NDArray[np.float32]


class Recommender(Protocol):
    name: str

    def recommend(self, task: EvaluationTask, k: int) -> IntArray: ...


def _empty(task: EvaluationTask, k: int) -> IntArray:
    return np.full((len(task), k), -1, dtype=np.int64)


def _first_unseen(ranking: IntArray, seen: IntArray, k: int) -> IntArray:
    """The first k items of a global ranking that the user has not heard."""
    head = ranking[: k + len(seen)]
    chosen = head[~np.isin(head, seen)][:k]
    out = np.full(k, -1, dtype=np.int64)
    out[: len(chosen)] = chosen
    return out


@dataclass
class RandomRecommender:
    """Uniformly random unseen items: the floor every model must clear."""

    n_items: int
    seed: int = 42
    name: str = "random"

    def recommend(self, task: EvaluationTask, k: int) -> IntArray:
        rng = np.random.default_rng(self.seed)
        out = _empty(task, k)
        for user, seen in enumerate(task.history):
            draw = rng.choice(self.n_items, size=min(self.n_items, k + len(seen)), replace=False)
            chosen = draw[~np.isin(draw, seen)][:k]
            out[user, : len(chosen)] = chosen
        return out


@dataclass
class RankedListRecommender:
    """Everyone gets the same global ranking, minus what they already heard."""

    name: str
    ranking: IntArray

    def recommend(self, task: EvaluationTask, k: int) -> IntArray:
        out = _empty(task, k)
        for user, seen in enumerate(task.history):
            out[user] = _first_unseen(self.ranking, seen, k)
        return out


def popularity_ranking(listeners: IntArray) -> IntArray:
    """Most listeners first; ties by item index (deterministic)."""
    return np.lexsort((np.arange(len(listeners)), -listeners)).astype(np.int64)


def trending_ranking(trending_score: FloatArray, listeners: IntArray) -> IntArray:
    """Reliable rising trends first, ordered like GET /recommendations/popular?kind=trending;
    then, because evaluation needs full lists, everything else by popularity."""
    rising = np.nan_to_num(trending_score, nan=0.0) > 0
    trend = np.where(rising, trending_score, -np.inf)
    return np.lexsort((np.arange(len(listeners)), -listeners, -trend)).astype(np.int64)


@dataclass
class GenrePopularityRecommender:
    """The user's dominant genre (play-weighted genre affinity of their history), ranked like
    GET /recommendations/genre/{genre} (genre score, then the artist cap); filled up with global
    popularity when the genre has too few unheard tracks."""

    affinity: sp.csr_matrix  # (n_items, n_genres): strongest level-weighted tag weight
    popularity: FloatArray
    artist_codes: IntArray
    fallback: IntArray
    name: str = "genre-popularity"
    pool: int = CANDIDATE_POOL
    _members: dict[int, tuple[IntArray, FloatArray]] = field(
        default_factory=dict, init=False, repr=False
    )

    def _genre_members(self, genre: int) -> tuple[IntArray, FloatArray]:
        """Members of a genre and their affinity, best genre score first (ties by item)."""
        if genre not in self._members:
            column = self.affinity.getcol(genre).tocoo()
            keep = column.data >= MIN_GENRE_AFFINITY
            members = column.row[keep].astype(np.int64)
            affinity = column.data[keep].astype(np.float64)
            scores = np.array(
                [
                    genre_score(float(a), float(self.popularity[i]))
                    for i, a in zip(members, affinity, strict=True)
                ]
            )
            order = np.lexsort((members, -scores)) if len(members) else np.array([], dtype=np.int64)
            self._members[genre] = (members[order], affinity[order])
        return self._members[genre]

    def recommend(self, task: EvaluationTask, k: int) -> IntArray:
        out = _empty(task, k)
        affinity_t = self.affinity.T.tocsr()
        for user, (seen, plays) in enumerate(zip(task.history, task.history_plays, strict=True)):
            profile = affinity_t[:, seen] @ np.log1p(plays.astype(np.float64))
            chosen = np.full(k, -1, dtype=np.int64)
            if np.any(profile > 0):
                members, affinity = self._genre_members(int(np.argmax(profile)))
                unseen = ~np.isin(members, seen)
                chosen = _rerank_items(
                    members[unseen][: self.pool],
                    affinity[unseen][: self.pool],
                    self.popularity,
                    self.artist_codes,
                    None,
                    beta=GENRE_POPULARITY_WEIGHT,
                    k=k,
                    max_per_artist=DEFAULT_MAX_PER_ARTIST,
                )
            missing = chosen < 0
            if missing.any():
                extra = _first_unseen(self.fallback, np.concatenate([seen, chosen[~missing]]), k)
                chosen[missing] = extra[: int(missing.sum())]
            out[user] = chosen
        return out


def _rerank_items(
    pool: IntArray,
    similarities: FloatArray,
    popularity: FloatArray,
    artist_codes: IntArray,
    dedup_keys: Sequence[str] | None,
    *,
    beta: float,
    k: int,
    max_per_artist: int | None,
    exclude_keys: Sequence[str] = (),
) -> IntArray:
    candidates = [
        Candidate(
            int(item),
            float(similarity),
            float(popularity[item]),
            int(artist_codes[item]),
            None if dedup_keys is None else dedup_keys[item],
        )
        for item, similarity in zip(pool, similarities, strict=True)
    ]
    ranked = rerank(
        candidates,
        beta=beta,
        limit=k,
        max_per_artist=max_per_artist,
        exclude_dedup_keys=exclude_keys,
    )
    out = np.full(k, -1, dtype=np.int64)
    out[: len(ranked)] = [r.item for r in ranked]
    return out


@dataclass
class ContentRecommender:
    """Nearest neighbours in content-embedding space, re-ranked like the API.

    mode="seed": the query is the user's favourite track (GET /recommendations/similar/{id}).
    mode="profile": the query is the play-weighted mean of the user's history embeddings.
    """

    name: str
    embeddings: Embeddings
    popularity: FloatArray
    artist_codes: IntArray
    dedup_keys: Sequence[str]
    beta: float
    mode: Literal["seed", "profile"] = "seed"
    pool: int = CANDIDATE_POOL
    max_per_artist: int | None = DEFAULT_MAX_PER_ARTIST
    batch: int = 1024

    def _queries(self, task: EvaluationTask, users: range) -> Embeddings:
        if self.mode == "seed":
            return self.embeddings[task.seeds[users.start : users.stop]]
        rows = []
        for user in users:
            weights = np.log1p(task.history_plays[user].astype(np.float32))
            vector = weights @ self.embeddings[task.history[user]]
            norm = np.linalg.norm(vector)
            rows.append(vector / norm if norm > 0 else vector)
        return np.vstack(rows).astype(np.float32)

    def recommend(self, task: EvaluationTask, k: int) -> IntArray:
        out = _empty(task, k)
        pool = min(self.pool, task.n_items - 1)
        for start in range(0, len(task), self.batch):
            users = range(start, min(start + self.batch, len(task)))
            sims = self._queries(task, users) @ self.embeddings.T
            for row, user in enumerate(users):
                sims[row, task.history[user]] = -np.inf
            top = np.argpartition(-sims, pool, axis=1)[:, :pool]
            for row, user in enumerate(users):
                candidates = top[row][np.argsort(-sims[row, top[row]], kind="stable")]
                candidates = candidates[np.isfinite(sims[row, candidates])]
                exclude = [self.dedup_keys[task.seeds[user]]] if self.mode == "seed" else []
                out[user] = _rerank_items(
                    candidates.astype(np.int64),
                    sims[row, candidates].astype(np.float64),
                    self.popularity,
                    self.artist_codes,
                    self.dedup_keys,
                    beta=self.beta,
                    k=k,
                    max_per_artist=self.max_per_artist,
                    exclude_keys=exclude,
                )
        return out


@dataclass
class SimilarArtistRecommender:
    """The user's most played artist -> most similar artists -> their most popular unheard
    tracks, ranked like GET /recommendations/artist/{artist_id}."""

    artist_embeddings: Embeddings
    artist_codes: IntArray
    popularity: FloatArray
    dedup_keys: Sequence[str]
    beta: float
    name: str = "content-artist"
    max_per_artist: int | None = DEFAULT_MAX_PER_ARTIST
    _tracks_by_artist: list[IntArray] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        order = np.lexsort((np.arange(len(self.popularity)), -self.popularity))
        n_artists = len(self.artist_embeddings)
        grouped: list[list[int]] = [[] for _ in range(n_artists)]
        for item in order:
            grouped[self.artist_codes[item]].append(int(item))
        self._tracks_by_artist = [np.array(g, dtype=np.int64) for g in grouped]
        self._has_embedding = np.linalg.norm(self.artist_embeddings, axis=1) > 0

    def recommend(self, task: EvaluationTask, k: int) -> IntArray:
        out = _empty(task, k)
        for user, (seen, plays) in enumerate(zip(task.history, task.history_plays, strict=True)):
            artist_plays = np.bincount(
                self.artist_codes[seen], weights=plays, minlength=len(self.artist_embeddings)
            )
            seed_artist = int(np.argmax(artist_plays))
            sims = self.artist_embeddings @ self.artist_embeddings[seed_artist]
            sims[seed_artist] = -np.inf
            sims[~self._has_embedding] = -np.inf
            nearest = np.argsort(-sims, kind="stable")
            # Drop the seed artist and artists without content, like the API's nearest-artist query.
            nearest = nearest[np.isfinite(sims[nearest])][:SIMILAR_ARTISTS_POOL]
            pool: list[int] = []
            similarities: list[float] = []
            for artist in nearest:
                tracks = self._tracks_by_artist[artist]
                unseen = tracks[~np.isin(tracks, seen)][:TRACKS_PER_SIMILAR_ARTIST]
                pool.extend(int(t) for t in unseen)
                similarities.extend([float(sims[artist])] * len(unseen))
            out[user] = _rerank_items(
                np.array(pool, dtype=np.int64),
                np.array(similarities),
                self.popularity,
                self.artist_codes,
                self.dedup_keys,
                beta=self.beta,
                k=k,
                max_per_artist=self.max_per_artist,
            )
        return out
