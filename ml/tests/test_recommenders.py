import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

from app.domains.recommendations.ranking import Candidate, rerank
from soniqueo_ml.evaluation.recommenders import (
    ContentRecommender,
    GenrePopularityRecommender,
    RandomRecommender,
    RankedListRecommender,
    SimilarArtistRecommender,
    popularity_ranking,
    trending_ranking,
)
from soniqueo_ml.evaluation.split import EvaluationTask


def task(history: list[list[int]], seeds: list[int], n_items: int) -> EvaluationTask:
    return EvaluationTask(
        users=np.array([f"u{i}" for i in range(len(history))], dtype=object),
        history=[np.array(h, dtype=np.int64) for h in history],
        history_plays=[np.ones(len(h), dtype=np.int64) for h in history],
        relevant=[np.array([0]) for _ in history],
        seeds=np.array(seeds, dtype=np.int64),
        n_items=n_items,
    )


def unit(*rows: list[float]) -> npt.NDArray[np.float32]:
    matrix = np.array(rows, dtype=np.float32)
    return np.asarray(matrix / np.linalg.norm(matrix, axis=1, keepdims=True), dtype=np.float32)


def test_rankings_are_deterministic() -> None:
    listeners = np.array([5, 9, 9, 0])
    assert popularity_ranking(listeners).tolist() == [1, 2, 0, 3]
    trending = np.array([np.nan, 0.5, -0.2, 1.0])
    # Rising reliable trends first (3, then 1), then the rest by popularity.
    assert trending_ranking(trending, listeners).tolist() == [3, 1, 2, 0]


def test_global_rankings_skip_heard_items() -> None:
    recommender = RankedListRecommender("popularity", np.array([4, 3, 2, 1, 0]))
    lists = recommender.recommend(task([[4, 2], [9]], [4, 9], 10), k=3)
    assert lists.tolist() == [[3, 1, 0], [4, 3, 2]]


def test_random_recommender_is_seeded_and_excludes_history() -> None:
    recommender = RandomRecommender(n_items=50, seed=3)
    first = recommender.recommend(task([[1, 2, 3]], [1], 50), k=10)
    again = recommender.recommend(task([[1, 2, 3]], [1], 50), k=10)
    assert first.tolist() == again.tolist()
    assert not set(first[0]) & {1, 2, 3}
    assert len(set(first[0])) == 10


def test_content_seed_mode_matches_the_backend_rerank() -> None:
    embeddings = unit([1, 0], [1, 0.1], [1, 0.3], [1, 0.5], [0.2, 1], [1, 0.05])
    popularity = np.array([0.1, 0.2, 0.9, 0.5, 1.0, 0.3])
    artists = np.array([0, 1, 1, 1, 2, 0])
    keys = ["a|x", "b|y", "b|z", "b|w", "c|v", "a|x"]  # item 5 duplicates the seed
    recommender = ContentRecommender(
        "content-seed", embeddings, popularity, artists, keys, beta=0.3, max_per_artist=2
    )

    lists = recommender.recommend(task([[0]], [0], 6), k=4)

    sims = embeddings @ embeddings[0]
    expected = rerank(
        [
            Candidate(i, float(sims[i]), float(popularity[i]), int(artists[i]), keys[i])
            for i in range(1, 6)
        ],
        beta=0.3,
        limit=4,
        max_per_artist=2,
        exclude_dedup_keys=["a|x"],
    )
    assert lists[0].tolist()[: len(expected)] == [r.item for r in expected]
    assert 5 not in lists[0]
    assert sum(artists[i] == 1 for i in lists[0] if i >= 0) == 2


def test_content_profile_mode_uses_the_history_mean() -> None:
    embeddings = unit([1, 0], [0, 1], [1, 1], [1, 0.9], [-1, 0])
    recommender = ContentRecommender(
        "content-profile",
        embeddings,
        np.zeros(5),
        np.arange(5),
        [str(i) for i in range(5)],
        beta=0.0,
        mode="profile",
    )
    lists = recommender.recommend(task([[0, 1]], [0], 5), k=2)
    assert lists[0].tolist() == [2, 3]


def test_genre_popularity_follows_the_dominant_genre() -> None:
    # Items 0-1 heard (rock); rock members 2-4 ranked by genre score; item 5 is jazz.
    affinity = sp.csr_matrix(
        np.array([[1, 0], [1, 0], [1, 0], [0.5, 0], [0.05, 0], [0, 1]], dtype=np.float64)
    )
    popularity = np.array([0.0, 0.0, 0.1, 1.0, 1.0, 1.0])
    artists = np.array([0, 1, 2, 2, 2, 3])
    recommender = GenrePopularityRecommender(
        affinity, popularity, artists, fallback=np.array([5, 4, 3, 2, 1, 0])
    )

    lists = recommender.recommend(task([[0, 1]], [0], 6), k=3)

    # Item 4 is below the minimum affinity; the cap allows two of artist 2; then the fallback.
    assert lists[0].tolist() == [3, 2, 5]


def test_similar_artist_recommender_uses_neighbouring_artists_top_tracks() -> None:
    artist_vectors = unit([1, 0], [1, 0.2], [0, 1])
    artist_codes = np.array([0, 1, 1, 1, 2])
    popularity = np.array([0.0, 0.5, 0.9, 0.1, 1.0])
    recommender = SimilarArtistRecommender(
        artist_vectors, artist_codes, popularity, [str(i) for i in range(5)], beta=0.0
    )

    lists = recommender.recommend(task([[0, 2]], [0], 5), k=3)

    # Artist 1 is most similar; its top unheard tracks are 1 then 3; artist 2 comes next.
    assert lists[0].tolist() == [1, 3, 4]
