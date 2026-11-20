import numpy as np
import pandas as pd
import pytest

from app.domains.recommendations.ranking import (
    LEVEL_WEIGHTS,
    genre_affinity,
    smoothed_tag_weight,
)
from soniqueo_ml.evaluation.experiment import genre_affinity_matrix
from soniqueo_ml.recommendation.catalogue_data import CatalogueData
from soniqueo_ml.recommendation.content import (
    ContentConfig,
    artist_embeddings,
    fit_content_model,
    genre_profiles,
    numeric_block,
)
from tests.recommendation_fixtures import make_catalogue

SMALL = ContentConfig(n_components=4)


def rock_and_jazz() -> CatalogueData:
    tracks: list[dict[str, object]] = [
        {"track_id": "r1", "artist_id": "A", "release_year": 1994},
        {"track_id": "r2", "artist_id": "B", "release_year": 1995},
        {"track_id": "r3", "artist_id": "B", "release_year": 1996},
        {"track_id": "j1", "artist_id": "C", "release_year": 1959},
        {"track_id": "j2", "artist_id": "D", "release_year": 1958},
        {"track_id": "x", "artist_id": "E", "release_year": None, "duration_ms": None},
    ]
    genres = [
        (0, "rock", "recording", 8, 8),
        (0, "grunge", "album", 4, 8),
        (1, "rock", "recording", 8, 10),
        (1, "grunge", "recording", 2, 10),
        (2, "rock", "artist", 1, 1),
        (3, "jazz", "recording", 6, 6),
        (4, "jazz", "recording", 7, 10),
        (4, "bebop", "album", 3, 10),
    ]
    return make_catalogue(tracks, genres)


def test_genre_profiles_sum_level_weighted_smoothed_tags() -> None:
    profiles = genre_profiles(rock_and_jazz(), prior=2.0)
    assert profiles[0] == pytest.approx({"rock": 8 / 10, "grunge": 4 / 10 * LEVEL_WEIGHTS["album"]})
    # A single vote is shrunk to 1/3 of its raw share.
    assert profiles[2] == pytest.approx({"rock": 1 / 3 * LEVEL_WEIGHTS["artist"]})
    assert profiles[5] == {}
    assert genre_profiles(rock_and_jazz(), prior=0.0)[2] == pytest.approx(
        {"rock": LEVEL_WEIGHTS["artist"]}
    )


def test_tag_weights_keep_the_strongest_source() -> None:
    catalogue = rock_and_jazz()
    extra = catalogue.genres.iloc[[0]].assign(source="other", votes=1, total=9)
    catalogue.genres = pd.concat([catalogue.genres, extra], ignore_index=True)
    weights = catalogue.tag_weights(prior=2.0)
    rock = weights[(weights["item"] == 0) & (weights["genre"] == "rock")]
    assert rock["weight"].tolist() == pytest.approx([8 / 10])


def test_embeddings_are_unit_length_and_group_by_genre() -> None:
    model = fit_content_model(rock_and_jazz(), SMALL)

    norms = np.linalg.norm(model.embeddings, axis=1)
    assert norms[model.has_embedding] == pytest.approx(1.0, abs=1e-5)
    sims = model.embeddings @ model.embeddings.T
    assert sims[0, 1] > sims[0, 3]  # rock is closer to rock than to jazz
    assert sims[3, 4] > sims[3, 1]
    assert model.block_dimensions["genres"] == 4
    assert 0 < model.explained_variance <= 1


def test_content_model_is_deterministic() -> None:
    first = fit_content_model(rock_and_jazz(), SMALL)
    second = fit_content_model(rock_and_jazz(), SMALL)
    assert np.allclose(first.embeddings, second.embeddings)


def test_numeric_block_standardizes_and_leaves_missing_values_at_zero() -> None:
    catalogue = make_catalogue(
        [
            {"track_id": str(i), "artist_id": "A", "duration_ms": d}
            for i, d in enumerate([1, 2, 4, None])
        ],
        features={"acousticbrainz_tempo": [60.0, 120.0, None, 240.0]},
    )
    block, columns = numeric_block(catalogue)
    dense = block.toarray()
    assert columns == 2
    assert dense[3, 0] == 0.0  # missing duration
    assert dense[2, 1] == 0.0  # missing tempo
    # Log scale: 60 -> 120 -> 240 BPM are evenly spaced.
    assert dense[1, 1] == pytest.approx(0.0, abs=1e-9)
    assert dense[0, 1] == pytest.approx(-dense[3, 1])


def test_artist_embeddings_weight_tracks_by_listeners() -> None:
    embeddings = np.array([[1, 0], [0, 1], [0, 1], [0, 0]], dtype=np.float32)
    codes = np.array([0, 0, 1, 1])
    vectors, counts = artist_embeddings(embeddings, codes, np.array([0, 100, 5, 9]))

    weight_a, weight_b = 1.0, 1.0 + np.log1p(100)
    expected = np.array([weight_a, weight_b]) / np.hypot(weight_a, weight_b)
    assert vectors[0] == pytest.approx(expected, abs=1e-6)
    assert vectors[1] == pytest.approx([0, 1])
    assert counts.tolist() == [2, 1]  # the all-zero embedding does not count


def test_affinity_matrix_matches_the_serving_rule() -> None:
    catalogue = rock_and_jazz()
    matrix, names = genre_affinity_matrix(catalogue)
    rock = names.index("rock")
    for item in range(catalogue.n_items):
        tags = catalogue.genres[
            (catalogue.genres["item"] == item) & (catalogue.genres["genre"] == "rock")
        ]
        weights = [
            smoothed_tag_weight(v, t) for v, t in zip(tags["votes"], tags["total"], strict=True)
        ]
        expected = genre_affinity(zip(tags["level"], weights, strict=True))
        assert matrix[item, rock] == pytest.approx(expected)
