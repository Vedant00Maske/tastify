"""Runs recommenders over an evaluation task and summarizes their metrics."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from tastify_ml.evaluation import metrics
from tastify_ml.evaluation.recommenders import Recommender
from tastify_ml.evaluation.split import EvaluationTask

IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class MetricContext:
    """Item-level facts the beyond-accuracy metrics need (shared by all models)."""

    embeddings: npt.NDArray[np.float32]
    artist_codes: IntArray
    information: npt.NDArray[np.float64]


@dataclass
class ModelResult:
    name: str
    metrics: dict[str, float]
    # Half-widths of 95% confidence intervals for the per-user accuracy metrics.
    ci95: dict[str, float]
    users: int
    seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metrics": self.metrics,
            "ci95": self.ci95,
            "users": self.users,
            "seconds": round(self.seconds, 2),
        }


def evaluate(
    recommender: Recommender,
    task: EvaluationTask,
    context: MetricContext | None,
    ks: Sequence[int] = (10, 20),
) -> ModelResult:
    """Accuracy at every K, plus beyond-accuracy metrics when a context is given."""
    started = time.perf_counter()
    lists = recommender.recommend(task, max(ks))
    seconds = time.perf_counter() - started
    return evaluate_lists(recommender.name, lists, task, context, ks, seconds)


def evaluate_lists(
    name: str,
    lists: IntArray,
    task: EvaluationTask,
    context: MetricContext | None,
    ks: Sequence[int] = (10, 20),
    seconds: float = 0.0,
) -> ModelResult:
    """`evaluate` for precomputed recommendation lists (n_users, >= max(ks))."""
    values: dict[str, float] = {}
    ci95: dict[str, float] = {}
    for k in ks:
        for metric, per_user in metrics.accuracy_metrics(lists, task.relevant, k).items():
            values[f"{metric}@{k}"], ci95[f"{metric}@{k}"] = metrics.mean_with_ci(per_user)
        values[f"coverage@{k}"] = metrics.coverage(lists, k, task.n_items)
        if context is not None:
            values[f"diversity@{k}"] = float(
                metrics.intra_list_diversity(lists, k, context.embeddings).mean()
            )
            values[f"artist_diversity@{k}"] = float(
                metrics.artist_diversity(lists, k, context.artist_codes).mean()
            )
            values[f"novelty@{k}"] = float(metrics.novelty(lists, k, context.information).mean())
    return ModelResult(name, values, ci95, len(task), seconds)
