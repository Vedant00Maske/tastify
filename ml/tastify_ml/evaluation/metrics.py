"""Offline recommendation metrics.

Recommendation lists are an (n_users, K) integer array of item indices, padded with -1 when a
model returns fewer than K items. Relevance is binary: an item is relevant if the user listened
to it in the test window and had not heard it in training.

Accuracy (per user, then averaged):
- Precision@K = hits / K
- Recall@K    = hits / |relevant|
- NDCG@K      = DCG / ideal DCG, with gain 1 and discount 1 / log2(rank + 1)
- MAP@K       = mean over hit ranks of precision at that rank, divided by min(|relevant|, K)
- HitRate@K   = share of users with at least one hit

Beyond accuracy:
- Coverage@K     = distinct recommended items / catalogue size
- Diversity@K    = 1 - mean pairwise cosine similarity of the list (content embeddings)
- ArtistDiv@K    = distinct artists / list length
- Novelty@K      = mean self-information -log2 p(item), p = share of training users who played it
"""

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

Z_95 = 1.96


def _discounts(k: int) -> FloatArray:
    return 1.0 / np.log2(np.arange(2, k + 2, dtype=np.float64))


def accuracy_metrics(
    recommendations: IntArray, relevant: Sequence[IntArray], k: int
) -> dict[str, FloatArray]:
    """Per-user precision, recall, NDCG, AP and hit indicator at K."""
    n_users = len(relevant)
    if recommendations.shape[0] != n_users:
        raise ValueError("one recommendation list per user is required")
    discounts = _discounts(k)
    out = {name: np.zeros(n_users) for name in ("precision", "recall", "ndcg", "map", "hit_rate")}
    for user in range(n_users):
        top = recommendations[user, :k]
        targets = relevant[user]
        if len(targets) == 0:
            raise ValueError("every evaluated user needs at least one relevant item")
        hits = np.isin(top, targets) & (top >= 0)
        n_hits = int(hits.sum())
        if n_hits == 0:
            continue
        n_ideal = min(len(targets), k)
        out["precision"][user] = n_hits / k
        out["recall"][user] = n_hits / len(targets)
        out["ndcg"][user] = float((hits * discounts[: len(top)]).sum() / discounts[:n_ideal].sum())
        ranks = np.flatnonzero(hits) + 1
        out["map"][user] = float((np.arange(1, n_hits + 1) / ranks).sum() / n_ideal)
        out["hit_rate"][user] = 1.0
    return out


def coverage(recommendations: IntArray, k: int, n_items: int) -> float:
    top = recommendations[:, :k]
    return len(np.unique(top[top >= 0])) / n_items


def intra_list_diversity(
    recommendations: IntArray, k: int, embeddings: npt.NDArray[np.floating], batch: int = 2048
) -> FloatArray:
    """Per user: 1 - mean pairwise cosine similarity (embeddings are L2-normalized)."""
    top = recommendations[:, :k]
    out = np.zeros(len(top))
    for start in range(0, len(top), batch):
        block = top[start : start + batch]
        valid = block >= 0
        vectors = embeddings[np.where(valid, block, 0)] * valid[..., None]
        sims = np.einsum("uid,ujd->uij", vectors, vectors)
        n = valid.sum(axis=1).astype(np.float64)
        pairs = n * (n - 1)
        off_diagonal = sims.sum(axis=(1, 2)) - np.einsum("uii->u", sims)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[start : start + batch] = np.where(pairs > 0, 1.0 - off_diagonal / pairs, 0.0)
    return out


def artist_diversity(recommendations: IntArray, k: int, artist_codes: IntArray) -> FloatArray:
    out = np.zeros(len(recommendations))
    for user, row in enumerate(recommendations[:, :k]):
        valid = row[row >= 0]
        if len(valid):
            out[user] = len(np.unique(artist_codes[valid])) / len(valid)
    return out


def self_information(listeners: IntArray, n_users: int) -> FloatArray:
    """-log2 of the (add-one smoothed) share of users who played each item."""
    return np.asarray(-np.log2((listeners + 1.0) / (n_users + 1.0)), dtype=np.float64)


def novelty(recommendations: IntArray, k: int, information: FloatArray) -> FloatArray:
    top = recommendations[:, :k]
    valid = top >= 0
    values = np.where(valid, information[np.where(valid, top, 0)], 0.0)
    counts = valid.sum(axis=1)
    return np.where(counts > 0, values.sum(axis=1) / np.maximum(counts, 1), 0.0)


def mean_with_ci(values: FloatArray) -> tuple[float, float]:
    """Mean and the half-width of its normal-approximation 95% confidence interval."""
    if len(values) < 2:
        return float(values.mean()) if len(values) else 0.0, 0.0
    return float(values.mean()), float(Z_95 * values.std(ddof=1) / np.sqrt(len(values)))
