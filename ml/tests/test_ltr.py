"""Rankers: the backend's numpy tree evaluator must reproduce LightGBM's predictions."""

import json

import numpy as np
import pytest

from app.domains.recommendations.features import FEATURE_NAMES, FEATURES
from app.domains.recommendations.hybrid_ranking import TreeEnsembleRanker
from soniqueo_ml.recommendation.lineage import lineage, most_restrictive
from soniqueo_ml.recommendation.ltr import (
    LambdaRankConfig,
    RankingData,
    fit_platt,
    train_lambdarank,
)


def synthetic(queries: int, seed: int) -> tuple[list[np.ndarray], list[np.ndarray]]:
    rng = np.random.default_rng(seed)
    features, labels = [], []
    for _ in range(queries):
        x = rng.normal(size=(30, len(FEATURES))).astype(np.float32)
        x[rng.random(x.shape) < 0.05] = 0.0
        y = (x[:, 5] + 0.5 * x[:, 6] + rng.normal(scale=0.5, size=30)) > 1.2
        features.append(x)
        labels.append(y)
    return features, labels


CONFIG = LambdaRankConfig(num_leaves=7, min_data_in_leaf=5, max_rounds=30, num_threads=1)


def test_tree_evaluator_matches_lightgbm_predictions() -> None:
    features, labels = synthetic(60, seed=1)
    data = RankingData.stack(features, labels)
    model = train_lambdarank(data, FEATURE_NAMES, CONFIG, rounds=30)
    exported = model.export()
    test, _ = synthetic(5, seed=2)
    stacked = np.vstack(test)
    stacked[0, 5] = np.nan  # LightGBM's missing-value handling must be reproduced too
    assert exported.score(stacked) == pytest.approx(model.predict(stacked), abs=1e-9)
    restored = TreeEnsembleRanker.from_dict(json.loads(json.dumps(exported.to_dict())))
    assert restored.score(stacked) == pytest.approx(model.predict(stacked), abs=1e-9)


def test_training_is_deterministic_and_uses_feature_subsets() -> None:
    features, labels = synthetic(40, seed=3)
    columns = ("cf_item_score", "cf_mf_score", "popularity")
    data = RankingData.stack(features, labels, columns)
    first = train_lambdarank(data, columns, CONFIG, rounds=20)
    second = train_lambdarank(data, columns, CONFIG, rounds=20)
    assert first.export().to_dict() == second.export().to_dict()
    assert set(first.importance()) == set(columns)
    assert first.export().feature_names == columns


def test_early_stopping_on_validation() -> None:
    train, train_labels = synthetic(60, seed=4)
    valid, valid_labels = synthetic(20, seed=5)
    model = train_lambdarank(
        RankingData.stack(train, train_labels),
        FEATURE_NAMES,
        LambdaRankConfig(num_leaves=7, min_data_in_leaf=5, max_rounds=200, early_stopping_rounds=5),
        RankingData.stack(valid, valid_labels),
    )
    assert 1 <= model.best_iteration < 200
    assert model.validation_ndcg is not None
    assert 0 < model.validation_ndcg <= 1


def test_ranking_data_keeps_only_queries_with_positives() -> None:
    x = np.zeros((3, len(FEATURES)), dtype=np.float32)
    data = RankingData.stack(
        [x, x, x[:2]],
        [np.array([0, 1, 0], bool), np.zeros(3, bool), np.array([1, 0], bool)],
        rows=[np.ones(3, bool), np.ones(3, bool), np.array([True, False])],
    )
    assert data.groups.tolist() == [3, 1]
    with pytest.raises(ValueError, match="no query has a positive"):
        RankingData.stack([x], [np.zeros(3, bool)])


def test_platt_calibration_is_increasing_in_a_predictive_score() -> None:
    rng = np.random.default_rng(0)
    features = rng.normal(size=(2000, len(FEATURES))).astype(np.float32)
    labels = features[:, FEATURE_NAMES.index("cf_mf_score")] + rng.normal(size=2000) > 1.0
    calibration = fit_platt(features, labels)
    assert calibration["collaborative_mf"].a > 0
    assert abs(calibration["novelty"].a) < calibration["collaborative_mf"].a


def test_lineage_marks_content_signals_non_commercial() -> None:
    assert lineage("hybrid")["usage_restriction"] == "non_commercial"
    assert not lineage("hybrid")["commercial_use"]
    assert lineage("hybrid-cc0")["commercial_use"]
    assert lineage("collaborative")["usage_restriction"] == "none"
    assert most_restrictive(["none", "research_only", "non_commercial"]) == "research_only"
    signals = {s["signal"] for s in lineage("content")["signals"]}
    assert "genre tags" in signals
