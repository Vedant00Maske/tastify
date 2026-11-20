"""Training the hybrid rankers (ADR-016).

- Platt calibration of each weighted-hybrid component, fitted on an earlier period's candidates;
- LightGBM LambdaRank on candidate features, one query per user, labels = the user played the
  track in the following window. Training is deterministic (fixed seeds, `deterministic=True`,
  single-threaded histogram construction is not required for that, row-wise mode is).

The trained booster is exported as the backend's `TreeEnsembleRanker`, whose numpy evaluation the
tests check against LightGBM's own predictions.
"""

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
from sklearn.linear_model import LogisticRegression

from app.domains.recommendations.features import FEATURE_INDEX, FEATURE_NAMES
from app.domains.recommendations.hybrid_ranking import COMPONENT_FEATURES, Platt, TreeEnsembleRanker

logger = logging.getLogger(__name__)

Features = npt.NDArray[np.float32]


def fit_platt(features: Features, labels: npt.NDArray[np.bool_]) -> dict[str, Platt]:
    """Per component: logistic regression of the label on the raw component score."""
    calibration: dict[str, Platt] = {}
    for component, feature in COMPONENT_FEATURES.items():
        x = features[:, FEATURE_INDEX[feature]].astype(np.float64).reshape(-1, 1)
        if np.ptp(x) == 0 or labels.all() or not labels.any():
            calibration[component] = Platt(0.0, 0.0)
            continue
        model = LogisticRegression(C=1e6, max_iter=1000)
        model.fit(x, labels.astype(np.int64))
        calibration[component] = Platt(float(model.coef_[0, 0]), float(model.intercept_[0]))
    return calibration


@dataclass(frozen=True)
class LambdaRankConfig:
    num_leaves: int = 31
    learning_rate: float = 0.05
    min_data_in_leaf: int = 100
    feature_fraction: float = 0.9
    bagging_fraction: float = 0.8
    bagging_freq: int = 1
    lambdarank_truncation_level: int = 20
    max_rounds: int = 1000
    early_stopping_rounds: int = 50
    seed: int = 42
    num_threads: int = 8

    def params(self) -> dict[str, Any]:
        return asdict(self)

    def lightgbm_params(self) -> dict[str, Any]:
        return {
            "objective": "lambdarank",
            "metric": "ndcg",
            "eval_at": [10],
            "num_leaves": self.num_leaves,
            "learning_rate": self.learning_rate,
            "min_data_in_leaf": self.min_data_in_leaf,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": self.bagging_freq,
            "lambdarank_truncation_level": self.lambdarank_truncation_level,
            "seed": self.seed,
            "deterministic": True,
            "force_row_wise": True,
            "num_threads": self.num_threads,
            "verbosity": -1,
        }


@dataclass
class RankingData:
    """Stacked candidate rows with one query (user) per group, best-first order irrelevant."""

    features: Features
    labels: npt.NDArray[np.bool_]
    groups: npt.NDArray[np.int64]

    @classmethod
    def stack(
        cls,
        features: Sequence[Features],
        labels: Sequence[npt.NDArray[np.bool_]],
        columns: Sequence[str] = FEATURE_NAMES,
        rows: Sequence[npt.NDArray[np.bool_]] | None = None,
    ) -> "RankingData":
        """Only queries with at least one positive (others carry no ranking signal)."""
        index = [FEATURE_INDEX[c] for c in columns]
        kept_features, kept_labels, groups = [], [], []
        for i, (x, y) in enumerate(zip(features, labels, strict=True)):
            if rows is not None:
                x, y = x[rows[i]], y[rows[i]]
            if len(y) == 0 or not y.any():
                continue
            kept_features.append(x[:, index])
            kept_labels.append(y)
            groups.append(len(y))
        if not groups:
            raise ValueError("no query has a positive label")
        return cls(
            np.vstack(kept_features).astype(np.float32),
            np.concatenate(kept_labels),
            np.array(groups, dtype=np.int64),
        )

    def dataset(self, columns: Sequence[str], reference: lgb.Dataset | None = None) -> lgb.Dataset:
        return lgb.Dataset(
            self.features,
            label=self.labels.astype(np.int32),
            group=self.groups,
            feature_name=list(columns),
            reference=reference,
            free_raw_data=False,
        )


@dataclass
class TrainedRanker:
    booster: lgb.Booster
    columns: tuple[str, ...]
    best_iteration: int
    validation_ndcg: float | None

    def predict(self, features: Features) -> npt.NDArray[np.float64]:
        index = [FEATURE_INDEX[c] for c in self.columns]
        return np.asarray(
            self.booster.predict(features[:, index], num_iteration=self.best_iteration),
            dtype=np.float64,
        )

    def export(self) -> TreeEnsembleRanker:
        dump = self.booster.dump_model(num_iteration=self.best_iteration)
        return TreeEnsembleRanker.from_lightgbm_dump(dump)

    def importance(self) -> dict[str, float]:
        gains = self.booster.feature_importance("gain", iteration=self.best_iteration)
        total = float(gains.sum()) or 1.0
        return {c: round(float(g) / total, 4) for c, g in zip(self.columns, gains, strict=True)}


def train_lambdarank(
    train: RankingData,
    columns: Sequence[str],
    config: LambdaRankConfig,
    valid: RankingData | None = None,
    rounds: int | None = None,
) -> TrainedRanker:
    """With `valid`: early stopping on validation NDCG@10. Without: exactly `rounds` rounds."""
    params = config.lightgbm_params()
    train_set = train.dataset(columns)
    callbacks: list[Any] = []
    valid_sets: list[lgb.Dataset] = []
    if valid is not None:
        valid_sets = [valid.dataset(columns, reference=train_set)]
        callbacks.append(lgb.early_stopping(config.early_stopping_rounds, verbose=False))
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=rounds or config.max_rounds,
        valid_sets=valid_sets,
        callbacks=callbacks,
    )
    best = (
        booster.best_iteration
        if valid is not None and booster.best_iteration
        else booster.num_trees()
    )
    score = None
    if valid is not None:
        score = float(booster.best_score["valid_0"]["ndcg@10"])
    logger.info("LambdaRank: %d rounds, validation NDCG@10 (candidates) %s", best, score)
    return TrainedRanker(booster, tuple(columns), int(best), score)
