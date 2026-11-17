"""Offline signals, profiles and candidate generation on a small synthetic world."""

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from app.domains.recommendations.candidate_generation import SOURCE_ORDER
from app.domains.recommendations.features import FEATURES
from app.domains.users.events import EventType, TrackSignals, aggregate_events
from app.domains.users.profile import TasteProfileConfig
from tastify_ml.evaluation.experiment import genre_affinity_matrix, song_keys
from tastify_ml.evaluation.hybrid_engine import (
    CandidateEngine,
    HybridConfig,
    ItemFacts,
    train_period_models,
)
from tastify_ml.recommendation.catalogue_data import CatalogueData
from tastify_ml.recommendation.collaborative import ALSConfig, ItemItemConfig
from tastify_ml.recommendation.content_assets import ContentAssets, nearest_neighbours
from tastify_ml.recommendation.popularity import PopularityConfig
from tastify_ml.recommendation.signals import compute_signals
from tests.recommendation_fixtures import T0, listens, make_catalogue

CONFIG = HybridConfig(
    als=ALSConfig(factors=4, iterations=5),
    item_item=ItemItemConfig(neighbours=5),
    source_limit=10,
    content_neighbours=5,
    exploration_artists=3,
    popularity_limit=10,
)
# Two taste areas: rock (items 0-5, artists a0-a2) and jazz (items 6-11, artists a3-a5).
N_ITEMS = 12


def catalogue() -> CatalogueData:
    tracks: list[dict[str, object]] = [
        {"track_id": f"t{i}", "artist_id": f"a{i // 2}", "title": f"Song {i}"}
        for i in range(N_ITEMS)
    ]
    genres = [(i, "rock" if i < 6 else "jazz", "recording", 5, 5) for i in range(N_ITEMS)]
    return make_catalogue(tracks, genres)


def interactions() -> pd.DataFrame:
    rows = []
    for user in range(30):
        area = range(0, 6) if user % 2 == 0 else range(6, 12)
        for day, item in enumerate(area):
            if (user + item) % 3:
                rows.append((f"u{user}", f"t{item}", float(day)))
    return listens(rows)


def content(cat: CatalogueData) -> ContentAssets:
    embeddings = np.zeros((N_ITEMS, 4), dtype=np.float32)
    embeddings[:6, 0] = 1.0
    embeddings[6:, 1] = 1.0
    embeddings[np.arange(N_ITEMS), 2] = np.linspace(0.0, 0.3, N_ITEMS)
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    neighbours, similarity = nearest_neighbours(embeddings, 5)
    profiles = [{"rock" if i < 6 else "jazz": 1.0} for i in range(N_ITEMS)]
    primary: list[str | None] = [next(iter(p)) for p in profiles]
    return ContentAssets("content-test", embeddings, neighbours, similarity, profiles, primary)


@pytest.fixture
def setup():  # type: ignore[no-untyped-def]
    cat = catalogue()
    assets = content(cat)
    affinity, names = genre_affinity_matrix(cat)
    facts = ItemFacts(cat.artist_codes().astype(np.int64), song_keys(cat), affinity.tocsc(), names)
    cutoff = T0 + pd.Timedelta(days=7)
    models = train_period_models(
        "test", interactions(), cat, assets, facts, cutoff, CONFIG, PopularityConfig()
    )
    return cat, assets, facts, models


def test_signals_match_the_backend_aggregation_per_user() -> None:
    cat = catalogue()
    frame = interactions()
    as_of = T0 + pd.Timedelta(days=7)
    item_of = pd.Series(np.arange(N_ITEMS), index=cat.track_ids)
    signals = compute_signals(frame, item_of, as_of, TasteProfileConfig())
    assert len(signals) == 30
    user = signals.position["u3"]
    mine = signals.user_signals(user)
    rows = frame[frame["user_key"] == "u3"]
    config = TasteProfileConfig()
    ages = (as_of - rows["listened_at"]).to_numpy() / np.timedelta64(1, "D")
    reference: TrackSignals[np.int64] = aggregate_events(
        rows["track_id"].map(item_of).to_numpy(),
        [EventType.PLAY.value] * len(rows),
        ages.astype(np.float64),
        None,
        weights=config.feedback,
        long_decay=config.long_decay,
        short_decay=config.short_decay,
    )
    np.testing.assert_array_equal(mine.keys, reference.keys)
    assert mine.positive == pytest.approx(reference.positive)
    matrix = signals.matrix("positive")
    assert isinstance(matrix, sp.csr_matrix)
    assert matrix.shape == (30, N_ITEMS)
    assert matrix[user].toarray().ravel()[mine.keys] == pytest.approx(mine.positive)


def test_candidates_are_unheard_attributed_and_featurized(setup) -> None:  # type: ignore[no-untyped-def]
    _, assets, facts, models = setup
    engine = CandidateEngine(models, assets, facts, CONFIG, batch=4)
    relevant = {"u0": np.array([1, 7])}
    out = list(engine.generate(["u0", "u1", "u2"], relevant))
    assert [c.user for c in out] == ["u0", "u1", "u2"]
    first = out[0]
    heard = models.signals.user_signals(models.signals.position["u0"]).keys
    assert not set(first.items.tolist()) & set(heard.tolist())
    assert first.features.shape == (len(first.items), len(FEATURES))
    assert np.isfinite(first.features).all()
    assert first.ranks.shape == (len(first.items), len(SOURCE_ORDER))
    assert np.isfinite(first.ranks).any(axis=1).all()  # every candidate has a source
    assert first.n_targets == 2
    assert first.labels.sum() <= 2
    assert set(first.statuses) == {s.value for s in SOURCE_ORDER}
    # A rock listener's best collaborative candidates are rock tracks.
    rock_rows = first.items < 6
    assert rock_rows.any()


def test_candidate_generation_is_deterministic(setup) -> None:  # type: ignore[no-untyped-def]
    _, assets, facts, models = setup
    engine = CandidateEngine(models, assets, facts, CONFIG)
    first = list(engine.generate(["u4", "u5"]))
    second = list(engine.generate(["u4", "u5"]))
    for a, b in zip(first, second, strict=True):
        np.testing.assert_array_equal(a.items, b.items)
        np.testing.assert_array_equal(a.features, b.features)


def test_a_failing_source_is_isolated(setup, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _, assets, facts, models = setup

    def broken(*args: object, **kwargs: object) -> list[tuple[int, float]]:
        raise RuntimeError("genre index unavailable")

    monkeypatch.setattr(models, "genre_ranking", broken)
    engine = CandidateEngine(models, assets, facts, CONFIG)
    result = next(engine.generate(["u0"]))
    assert result.statuses["popularity"] == "failed"
    assert result.statuses["collaborative_item"] == "ok"
    assert len(result.items) > 0


def test_cc0_configuration_runs_only_cc0_sources(setup) -> None:  # type: ignore[no-untyped-def]
    _, assets, facts, models = setup
    sources = (SOURCE_ORDER[0], SOURCE_ORDER[1], SOURCE_ORDER[-1])
    engine = CandidateEngine(models, assets, facts, HybridConfig(sources=sources, source_limit=10))
    result = next(engine.generate(["u0"]))
    assert set(result.statuses) == {s.value for s in sources}
