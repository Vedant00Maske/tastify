"""The content model's embeddings and what the hybrid needs from them, aligned with the catalogue.

The hybrid uses the *published* content model (the vectors the API serves), loaded from its
artifacts in ml/data/models/<version>/. Without artifacts the model is refitted with the given
configuration (deterministic: fixed SVD random state).
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from tastify_ml.recommendation.catalogue_data import CatalogueData
from tastify_ml.recommendation.content import ContentConfig, fit_content_model, genre_profiles

logger = logging.getLogger(__name__)

Embeddings = npt.NDArray[np.float32]


@dataclass
class ContentAssets:
    version: str | None
    embeddings: Embeddings  # (n_items, d), L2-normalized, zero rows = no content
    neighbours: npt.NDArray[np.int64]  # (n_items, k): nearest items by cosine, best first
    neighbour_similarity: npt.NDArray[np.float32]
    genre_profiles: list[dict[str, float]]
    primary_genre: list[str | None]

    @property
    def has_embedding(self) -> npt.NDArray[np.bool_]:
        return np.asarray(np.linalg.norm(self.embeddings, axis=1) > 0)


def nearest_neighbours(
    embeddings: Embeddings, k: int, batch: int = 2048
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float32]]:
    """Exact top-k cosine neighbours of every item (self excluded; items without content have
    none: their similarities are 0 and they are skipped by consumers)."""
    n = len(embeddings)
    k = min(k, n - 1)
    neighbours = np.zeros((n, k), dtype=np.int64)
    similarity = np.zeros((n, k), dtype=np.float32)
    for start in range(0, n, batch):
        stop = min(start + batch, n)
        sims = embeddings[start:stop] @ embeddings.T
        sims[np.arange(stop - start), np.arange(start, stop)] = -np.inf
        top = np.argpartition(-sims, k, axis=1)[:, :k]
        top_sims = np.take_along_axis(sims, top, axis=1)
        order = np.argsort(-top_sims, axis=1, kind="stable")
        neighbours[start:stop] = np.take_along_axis(top, order, axis=1)
        similarity[start:stop] = np.take_along_axis(top_sims, order, axis=1)
    return neighbours, similarity


def _published_embeddings(catalogue: CatalogueData, directory: Path) -> Embeddings | None:
    vectors_path, ids_path = directory / "embeddings.npy", directory / "track_ids.txt"
    if not vectors_path.exists() or not ids_path.exists():
        return None
    vectors = np.load(vectors_path)
    ids = ids_path.read_text(encoding="utf-8").split("\n")
    index = catalogue.item_index()
    aligned = np.zeros((catalogue.n_items, vectors.shape[1]), dtype=np.float32)
    rows = [(index[t], i) for i, t in enumerate(ids) if t in index]
    if rows:
        items, source = (np.array(x) for x in zip(*rows, strict=True))
        aligned[items] = vectors[source]
    return aligned


def load_content_assets(
    catalogue: CatalogueData,
    config: ContentConfig,
    *,
    version: str | None,
    models_dir: Path | None,
    neighbours: int = 100,
) -> ContentAssets:
    embeddings = None
    if version is not None and models_dir is not None:
        embeddings = _published_embeddings(catalogue, models_dir / version)
        if embeddings is None:
            logger.warning("No artifacts for %s: refitting the content model", version)
    if embeddings is None:
        embeddings = fit_content_model(catalogue, config).embeddings
        version = version if version is not None else None
    neighbour_ids, neighbour_sims = nearest_neighbours(embeddings, neighbours)
    profiles = genre_profiles(catalogue, config.genre_prior_votes)
    primary = [max(p.items(), key=lambda kv: kv[1])[0] if p else None for p in profiles]
    return ContentAssets(version, embeddings, neighbour_ids, neighbour_sims, profiles, primary)
