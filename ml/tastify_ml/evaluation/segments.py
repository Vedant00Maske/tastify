"""Per-user and per-segment views of offline results (docs/reports/hybrid-benchmark.md).

- history-size buckets: how much a model needs to know about a user;
- dominant genre: the user's strongest genre in training (play-weighted genre affinity);
- popularity strata of the *relevant* items (head = top 1% of tracks by training listeners,
  mid = next 9%, tail = the rest): which kinds of future listens a model can predict;
- discovery: share of recommended tracks by artists the user never played, and recall of
  relevant tracks by new artists;
- paired differences between two models on the same users, with a 95% confidence interval.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

from tastify_ml.evaluation import metrics
from tastify_ml.evaluation.split import EvaluationTask

IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]

HISTORY_BUCKETS = ((1, 4), (5, 9), (10, 24), (25, 99), (100, None))


def bucket_label(low: int, high: int | None) -> str:
    return f"{low}+" if high is None else f"{low}-{high}"


def history_buckets(task: EvaluationTask) -> npt.NDArray[np.object_]:
    sizes = np.array([len(h) for h in task.history])
    labels = np.empty(len(sizes), dtype=object)
    for low, high in HISTORY_BUCKETS:
        mask = (sizes >= low) & (sizes <= (high if high is not None else np.inf))
        labels[mask] = bucket_label(low, high)
    return labels


def dominant_genres(
    task: EvaluationTask, affinity: sp.csr_matrix, names: Sequence[str], top: int = 8
) -> npt.NDArray[np.object_]:
    """Each user's strongest genre (log-play-weighted affinity); genres outside the `top` most
    common are "other"."""
    affinity_t = affinity.T.tocsr()
    best = []
    for seen, plays in zip(task.history, task.history_plays, strict=True):
        profile = affinity_t[:, seen] @ np.log1p(plays.astype(np.float64))
        best.append(names[int(np.argmax(profile))] if np.any(profile > 0) else "unknown")
    labels = np.array(best, dtype=object)
    values, counts = np.unique(labels[labels != "unknown"], return_counts=True)
    common = set(values[np.argsort(-counts)][:top])
    return np.array([g if g in common else "other" for g in labels], dtype=object)


def popularity_strata(listeners: IntArray) -> npt.NDArray[np.object_]:
    order = np.argsort(-listeners, kind="stable")
    labels = np.full(len(listeners), "tail", dtype=object)
    n = len(listeners)
    labels[order[: max(1, n // 100)]] = "head"
    labels[order[max(1, n // 100) : max(1, n // 10)]] = "mid"
    return labels


def segment_metrics(
    lists: IntArray, task: EvaluationTask, labels: npt.NDArray[np.object_], k: int = 10
) -> dict[str, dict[str, float]]:
    per_user = metrics.accuracy_metrics(lists, task.relevant, k)
    out: dict[str, dict[str, float]] = {}
    for label in sorted(set(labels)):
        mask = labels == label
        out[str(label)] = {
            "users": int(mask.sum()),
            f"ndcg@{k}": float(per_user["ndcg"][mask].mean()),
            f"recall@{k}": float(per_user["recall"][mask].mean()),
            f"hit_rate@{k}": float(per_user["hit_rate"][mask].mean()),
        }
    return out


def stratified_recall(
    lists: IntArray, task: EvaluationTask, strata: npt.NDArray[np.object_], k: int = 10
) -> dict[str, dict[str, float]]:
    """Per stratum: share of relevant items in that stratum that were recommended (micro
    average), and the stratum's share of all recommendations."""
    hits: dict[str, int] = {}
    totals: dict[str, int] = {}
    recommended: dict[str, int] = {}
    for row, targets in zip(lists[:, :k], task.relevant, strict=True):
        valid = row[row >= 0]
        found = np.isin(targets, valid)
        for label, hit in zip(strata[targets], found, strict=True):
            totals[label] = totals.get(label, 0) + 1
            hits[label] = hits.get(label, 0) + int(hit)
        for label in strata[valid]:
            recommended[label] = recommended.get(label, 0) + 1
    n_recommended = sum(recommended.values()) or 1
    return {
        label: {
            "relevant": totals.get(label, 0),
            f"recall@{k}": hits.get(label, 0) / totals[label] if totals.get(label) else 0.0,
            "share_of_recommendations": recommended.get(label, 0) / n_recommended,
        }
        for label in ("head", "mid", "tail")
    }


def known_artists(task: EvaluationTask, artist_codes: IntArray) -> list[set[int]]:
    return [set(artist_codes[h].tolist()) for h in task.history]


def discovery_metrics(
    lists: IntArray,
    task: EvaluationTask,
    artist_codes: IntArray,
    known: Sequence[set[int]],
    k: int = 10,
) -> dict[str, float]:
    """discovery_share: recommended tracks by artists new to the user; discovery_recall: relevant
    new-artist tracks that were recommended (micro average); new_artist_relevant: share of the
    relevant tracks that are by new artists."""
    shares, hits, totals, relevant_new = [], 0, 0, 0
    n_relevant = 0
    for row, targets, artists in zip(lists[:, :k], task.relevant, known, strict=True):
        valid = row[row >= 0]
        if len(valid):
            shares.append(float(np.mean([a not in artists for a in artist_codes[valid]])))
        new = np.array([a not in artists for a in artist_codes[targets]], dtype=bool)
        relevant_new += int(new.sum())
        n_relevant += len(targets)
        totals += int(new.sum())
        hits += int(np.isin(targets[new], valid).sum())
    return {
        f"discovery_share@{k}": float(np.mean(shares)) if shares else 0.0,
        f"discovery_recall@{k}": hits / totals if totals else 0.0,
        "new_artist_relevant": relevant_new / n_relevant if n_relevant else 0.0,
    }


def paired_difference(
    lists_a: IntArray, lists_b: IntArray, task: EvaluationTask, k: int = 10
) -> dict[str, float]:
    """Mean per-user NDCG@k of A minus B, with a 95% CI (normal approximation, paired)."""
    a = metrics.accuracy_metrics(lists_a, task.relevant, k)["ndcg"]
    b = metrics.accuracy_metrics(lists_b, task.relevant, k)["ndcg"]
    mean, half = metrics.mean_with_ci(a - b)
    return {
        "difference": mean,
        "ci95": half,
        "relative": mean / float(b.mean()) if b.mean() > 0 else float("nan"),
        "a_wins": float(np.mean(a > b)),
        "b_wins": float(np.mean(b > a)),
    }


def summarize_segments(
    results: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    return {name: dict(values) for name, values in results.items()}
