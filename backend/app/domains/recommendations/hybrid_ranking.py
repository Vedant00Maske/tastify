"""Hybrid rankers over the features in `features.py` (ADR-016).

- WeightedHybridRanker: S(u, t) = sum_c w_c * P_c(x_c), where each component score x_c is
  calibrated by Platt scaling, P_c = sigmoid(a_c x_c + b_c), fitted offline on a chronologically
  earlier period. Calibration puts every component on one scale (an estimate of the probability
  that the user plays the track), so the weights are comparable.
- TreeEnsembleRanker: a LightGBM LambdaRank model, evaluated here with numpy from LightGBM's own
  model dump, so the API does not depend on LightGBM. Offline tests check that it reproduces
  LightGBM's predictions.

Both are pure functions of the feature matrix: the same features always give the same scores.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from app.domains.recommendations.features import FEATURE_INDEX, FEATURE_NAMES

FloatArray = npt.NDArray[np.float64]
Features = npt.NDArray[np.float32]

# Weighted-hybrid components (spec §2.5 of the Milestone 3 plan: C, CF, H, N, P).
COMPONENT_FEATURES: Mapping[str, str] = {
    "content": "content_seed_max",
    "collaborative_item": "cf_item_score",
    "collaborative_mf": "cf_mf_score",
    "history": "profile_sim",
    "novelty": "novelty",
    "popularity": "popularity",
}

# Ranking demotes artists with a negative signal: relevance x (1 - penalty x negative). A policy,
# not a learned weight: the research data has no skips or dislikes to learn it from.
NEGATIVE_ARTIST_PENALTY = 0.5


class Ranker(Protocol):
    @property
    def kind(self) -> str: ...

    def score(self, features: Features) -> FloatArray: ...


@dataclass(frozen=True)
class Platt:
    a: float
    b: float

    def __call__(self, values: npt.NDArray[np.floating[Any]]) -> FloatArray:
        z = np.clip(self.a * np.asarray(values, dtype=np.float64) + self.b, -50.0, 50.0)
        return np.asarray(1.0 / (1.0 + np.exp(-z)), dtype=np.float64)


@dataclass(frozen=True)
class WeightedHybridRanker:
    weights: Mapping[str, float]
    calibration: Mapping[str, Platt]
    kind: str = "weighted"

    def __post_init__(self) -> None:
        unknown = set(self.weights) - set(COMPONENT_FEATURES)
        if unknown:
            raise ValueError(f"unknown components: {sorted(unknown)}")
        missing = {c for c, w in self.weights.items() if w != 0 and c not in self.calibration}
        if missing:
            raise ValueError(f"components without calibration: {sorted(missing)}")

    def components(self, features: Features) -> dict[str, FloatArray]:
        """Calibrated component scores (only components with a non-zero weight)."""
        return {
            name: self.calibration[name](features[:, FEATURE_INDEX[COMPONENT_FEATURES[name]]])
            for name, weight in self.weights.items()
            if weight != 0
        }

    def score(self, features: Features) -> FloatArray:
        total = np.zeros(len(features))
        for name, calibrated in self.components(features).items():
            total += self.weights[name] * calibrated
        return total

    def params(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "weights": dict(self.weights),
            "calibration": {k: {"a": v.a, "b": v.b} for k, v in self.calibration.items()},
        }

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "WeightedHybridRanker":
        return cls(
            weights={k: float(v) for k, v in params["weights"].items()},
            calibration={
                k: Platt(float(v["a"]), float(v["b"])) for k, v in params["calibration"].items()
            },
        )


# --- tree ensembles (LightGBM) ---------------------------------------------------------------

_ZERO_THRESHOLD = 1e-35  # LightGBM's kZeroThreshold


@dataclass(frozen=True)
class Tree:
    """Flat arrays over internal nodes; a child < 0 is the leaf ~child (LightGBM's encoding)."""

    feature: npt.NDArray[np.int64]
    threshold: FloatArray
    default_left: npt.NDArray[np.bool_]
    missing: npt.NDArray[np.int64]  # 0 none, 1 zero, 2 NaN
    left: npt.NDArray[np.int64]
    right: npt.NDArray[np.int64]
    leaf_value: FloatArray

    def predict(self, features: npt.NDArray[np.float64]) -> FloatArray:
        n = len(features)
        if len(self.feature) == 0:  # a single leaf
            return np.full(n, self.leaf_value[0])
        out = np.empty(n)
        node = np.zeros(n, dtype=np.int64)
        active = np.arange(n)
        while len(active):
            current = node[active]
            values = features[active, self.feature[current]]
            missing = self.missing[current]
            nan = np.isnan(values)
            # Missing type "none": NaN is read as 0 (LightGBM NumericalDecision).
            values = np.where(nan & (missing != 2), 0.0, values)
            is_missing = ((missing == 1) & (np.abs(values) <= _ZERO_THRESHOLD)) | (
                (missing == 2) & nan
            )
            go_left = np.where(
                is_missing, self.default_left[current], values <= self.threshold[current]
            )
            child = np.where(go_left, self.left[current], self.right[current])
            leaf = child < 0
            out[active[leaf]] = self.leaf_value[~child[leaf]]
            node[active[~leaf]] = child[~leaf]
            active = active[~leaf]
        return out

    def to_dict(self) -> dict[str, list[Any]]:
        return {
            "feature": self.feature.tolist(),
            "threshold": self.threshold.tolist(),
            "default_left": self.default_left.tolist(),
            "missing": self.missing.tolist(),
            "left": self.left.tolist(),
            "right": self.right.tolist(),
            "leaf_value": self.leaf_value.tolist(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Sequence[Any]]) -> "Tree":
        return cls(
            feature=np.asarray(data["feature"], dtype=np.int64),
            threshold=np.asarray(data["threshold"], dtype=np.float64),
            default_left=np.asarray(data["default_left"], dtype=np.bool_),
            missing=np.asarray(data["missing"], dtype=np.int64),
            left=np.asarray(data["left"], dtype=np.int64),
            right=np.asarray(data["right"], dtype=np.int64),
            leaf_value=np.asarray(data["leaf_value"], dtype=np.float64),
        )


_MISSING_TYPES = {"None": 0, "Zero": 1, "NaN": 2}


def _flatten(structure: Mapping[str, Any]) -> Tree:
    """LightGBM `dump_model()['tree_info'][i]['tree_structure']` -> Tree."""
    if "split_index" not in structure:
        return Tree(
            feature=np.zeros(0, dtype=np.int64),
            threshold=np.zeros(0),
            default_left=np.zeros(0, dtype=np.bool_),
            missing=np.zeros(0, dtype=np.int64),
            left=np.zeros(0, dtype=np.int64),
            right=np.zeros(0, dtype=np.int64),
            leaf_value=np.array([float(structure["leaf_value"])]),
        )
    internal: list[Mapping[str, Any]] = []
    leaves: list[float] = []

    def visit(node: Mapping[str, Any]) -> int:
        if "split_index" not in node:
            leaves.append(float(node["leaf_value"]))
            return ~(len(leaves) - 1)
        if node.get("decision_type", "<=") != "<=":
            raise ValueError("only numerical splits are supported")
        index = len(internal)
        internal.append(node)
        children.append([0, 0])
        children[index][0] = visit(node["left_child"])
        children[index][1] = visit(node["right_child"])
        return index

    children: list[list[int]] = []
    visit(structure)
    return Tree(
        feature=np.array([int(n["split_feature"]) for n in internal], dtype=np.int64),
        threshold=np.array([float(n["threshold"]) for n in internal]),
        default_left=np.array([bool(n["default_left"]) for n in internal], dtype=np.bool_),
        missing=np.array(
            [_MISSING_TYPES[str(n["missing_type"])] for n in internal], dtype=np.int64
        ),
        left=np.array([c[0] for c in children], dtype=np.int64),
        right=np.array([c[1] for c in children], dtype=np.int64),
        leaf_value=np.array(leaves),
    )


@dataclass(frozen=True)
class TreeEnsembleRanker:
    trees: tuple[Tree, ...]
    feature_names: tuple[str, ...]
    kind: str = "lambdarank"

    def __post_init__(self) -> None:
        unknown = set(self.feature_names) - set(FEATURE_NAMES)
        if unknown:
            raise ValueError(f"the model uses features this version does not compute: {unknown}")

    def _columns(self, features: Features) -> npt.NDArray[np.float64]:
        index = [FEATURE_INDEX[name] for name in self.feature_names]
        return np.asarray(features[:, index], dtype=np.float64)

    def score(self, features: Features) -> FloatArray:
        columns = self._columns(features)
        total = np.zeros(len(features))
        for tree in self.trees:
            total += tree.predict(columns)
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "feature_names": list(self.feature_names),
            "trees": [t.to_dict() for t in self.trees],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TreeEnsembleRanker":
        return cls(
            trees=tuple(Tree.from_dict(t) for t in data["trees"]),
            feature_names=tuple(data["feature_names"]),
        )

    @classmethod
    def from_lightgbm_dump(cls, dump: Mapping[str, Any]) -> "TreeEnsembleRanker":
        return cls(
            trees=tuple(_flatten(t["tree_structure"]) for t in dump["tree_info"]),
            feature_names=tuple(dump["feature_names"]),
        )


def normalized_relevance(scores: FloatArray) -> FloatArray:
    """Min-max scaled to [0, 1] within one candidate set (all equal -> 1)."""
    scores = np.asarray(scores, dtype=np.float64)
    if len(scores) == 0:
        return scores
    low, high = float(scores.min()), float(scores.max())
    if not math.isfinite(high - low) or high - low <= 0:
        return np.ones(len(scores))
    return (scores - low) / (high - low)


def demote_negative_artists(
    relevance: FloatArray, artist_negative: FloatArray, penalty: float = NEGATIVE_ARTIST_PENALTY
) -> FloatArray:
    """relevance in [0, 1] x (1 - penalty x negative signal in [0, 1])."""
    negative = np.clip(np.asarray(artist_negative, dtype=np.float64), 0.0, 1.0)
    return np.asarray(relevance * (1.0 - penalty * negative), dtype=np.float64)
