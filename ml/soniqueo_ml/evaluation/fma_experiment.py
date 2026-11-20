"""Research-only FMA experiment: do audio features alone find tracks of the same genre?

FMA is a separate, research-only source (ADR-013), so it never enters the served model. Here its
Echonest audio features are evaluated against FMA's own top-level genre label (`genre_top`): for
every labelled track, the share of its K nearest neighbours (cosine, audio features only) that
have the same label, compared with what random neighbours would give.
"""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.preprocessing import normalize
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from soniqueo_ml.data.ingestion import fma
from soniqueo_ml.recommendation.catalogue_data import CatalogueData
from soniqueo_ml.recommendation.content import ContentConfig, categorical_block, numeric_block


async def genre_labels(session: AsyncSession, archive_path: Path) -> pd.Series:
    """Catalogue track_id -> FMA genre_top, for FMA tracks that have one."""
    archive = fma.open_metadata(archive_path)
    tracks = fma.read_tracks(archive)
    top = tracks["track.genre_top"].dropna()
    rows = await session.execute(
        text("SELECT external_id, track_id::text FROM track_external_ids WHERE provider = 'fma'")
    )
    catalogue_id = {int(external): track for external, track in rows}
    labels = {
        catalogue_id[int(str(i))]: str(g) for i, g in top.items() if int(str(i)) in catalogue_id
    }
    return pd.Series(labels, name="genre_top")


def _neighbour_precision(
    features: sp.csr_matrix, labels: np.ndarray, k: int, batch: int = 1024
) -> np.ndarray:
    matrix = normalize(features, norm="l2")
    out = np.zeros(matrix.shape[0])
    for start in range(0, matrix.shape[0], batch):
        stop = min(start + batch, matrix.shape[0])
        sims = np.asarray((matrix[start:stop] @ matrix.T).todense())
        sims[np.arange(stop - start), np.arange(start, stop)] = -np.inf
        top = np.argpartition(-sims, k, axis=1)[:, :k]
        out[start:stop] = (labels[top] == labels[start:stop, None]).mean(axis=1)
    return out


def run_fma_experiment(catalogue: CatalogueData, labels: pd.Series, k: int = 10) -> dict[str, Any]:
    tracks = catalogue.tracks
    labelled = tracks["track_id"].isin(labels.index).to_numpy()
    items = np.flatnonzero(labelled)
    y = labels.loc[tracks["track_id"].to_numpy()[items]].to_numpy()

    numeric, n_numeric = numeric_block(catalogue)
    categorical, _ = categorical_block(catalogue, ContentConfig())
    variants = {
        "audio": numeric[items],
        "audio+metadata": sp.hstack([numeric[items], 0.5 * categorical[items]], format="csr"),
    }
    shares = pd.Series(y).value_counts(normalize=True)
    results: dict[str, Any] = {
        "tracks": len(items),
        "genres": int(shares.size),
        "numeric_columns": n_numeric,
        "k": k,
        f"random_precision@{k}": float((shares**2).sum()),
    }
    per_genre: dict[str, dict[str, float]] = {}
    for name, features in variants.items():
        precision = _neighbour_precision(sp.csr_matrix(features), y, k)
        results[f"{name}_precision@{k}"] = float(precision.mean())
        for genre, value in pd.Series(precision).groupby(y).mean().items():
            share = float(shares.loc[str(genre)])
            per_genre.setdefault(str(genre), {"share": share})[name] = float(value)
    results["per_genre"] = dict(sorted(per_genre.items(), key=lambda kv: -kv[1]["share"]))
    return results
