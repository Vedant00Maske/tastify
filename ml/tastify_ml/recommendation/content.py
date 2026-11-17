"""Content-based track embeddings (ADR-015).

Each track is described by three blocks, each scaled to unit-ish norm and weighted:

- genres:      genre tags weighted by their (smoothed) share of votes and by level (recording >
               album > artist), TF-IDF re-weighted so rare, specific genres count more than "rock";
- categorical: one-hot release decade, album type, artist area and artist type;
- numeric:     standardized log duration and audio features. Each feature source keeps its own
               columns, because Essentia and Echonest values are not interchangeable.

The weighted blocks are concatenated and reduced with truncated SVD to EMBEDDING_DIMENSIONS, then
L2-normalized, so cosine similarity is a dot product and fits a pgvector HNSW index.
Interactions are not used: the embedding depends on catalogue metadata only.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.preprocessing import normalize

from app.domains.recommendations.models import EMBEDDING_DIMENSIONS
from app.domains.recommendations.ranking import GENRE_PRIOR_VOTES, LEVEL_WEIGHTS
from tastify_ml.recommendation.catalogue_data import CatalogueData

# Heavy-tailed features are compared on a log scale (a 60 vs 120 BPM gap matters like 120 vs 240).
LOG_FEATURES = ("duration_ms", "tempo", "onset_rate")
Z_CLIP = 3.0


@dataclass(frozen=True)
class ContentConfig:
    genre_weight: float = 1.0
    categorical_weight: float = 0.35
    numeric_weight: float = 0.35
    # Pseudo-votes added to each tag's vote total (0 = raw vote shares).
    genre_prior_votes: float = GENRE_PRIOR_VOTES
    n_components: int = EMBEDDING_DIMENSIONS
    # Artist areas with fewer tracks than this get no column (too rare to generalize from).
    min_area_tracks: int = 20
    svd_iterations: int = 7
    random_state: int = 42

    def params(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContentModel:
    config: ContentConfig
    track_ids: np.ndarray
    # (n_items, n_components) float32, L2-normalized; all-zero rows have no content at all.
    embeddings: np.ndarray
    # The weighted, row-normalized feature matrix before SVD (for fidelity measurements).
    features: sp.csr_matrix
    explained_variance: float
    block_dimensions: dict[str, int] = field(default_factory=dict)

    @property
    def has_embedding(self) -> np.ndarray:
        return np.asarray(np.linalg.norm(self.embeddings, axis=1) > 0)


def genre_profiles(
    catalogue: CatalogueData, prior: float = GENRE_PRIOR_VOTES
) -> list[dict[str, float]]:
    """Per item: genre -> sum over levels of LEVEL_WEIGHTS[level] * smoothed tag weight."""
    genres = catalogue.tag_weights(prior)
    weighted = genres.assign(
        value=genres["weight"].to_numpy() * genres["level"].map(LEVEL_WEIGHTS).to_numpy()
    )
    summed = weighted.groupby(["item", "genre"], sort=False)["value"].sum()
    profiles: list[dict[str, float]] = [{} for _ in range(catalogue.n_items)]
    for item, genre, value in summed.reset_index().itertuples(index=False):
        profiles[int(item)][str(genre)] = float(value)
    return profiles


def genre_block(catalogue: CatalogueData, config: ContentConfig) -> tuple[sp.csr_matrix, int]:
    profiles = genre_profiles(catalogue, config.genre_prior_votes)
    counts = DictVectorizer(dtype=np.float64).fit_transform(profiles)
    tfidf = TfidfTransformer(norm="l2", smooth_idf=True, sublinear_tf=False).fit_transform(counts)
    return sp.csr_matrix(tfidf), int(counts.shape[1])


def categorical_block(catalogue: CatalogueData, config: ContentConfig) -> tuple[sp.csr_matrix, int]:
    tracks = catalogue.tracks
    area_counts = tracks["artist_area"].value_counts()
    common_areas = set(area_counts[area_counts >= config.min_area_tracks].index)
    rows: list[dict[str, float]] = []
    for year, album_type, area, artist_type in zip(
        tracks["release_year"],
        tracks["album_type"],
        tracks["artist_area"],
        tracks["artist_type"],
        strict=True,
    ):
        row: dict[str, float] = {}
        if pd.notna(year):
            row[f"decade={int(year) // 10 * 10}"] = 1.0
        if isinstance(album_type, str):
            row[f"album_type={album_type}"] = 1.0
        if area in common_areas:
            row[f"area={area}"] = 1.0
        if isinstance(artist_type, str):
            row[f"artist_type={artist_type}"] = 1.0
        rows.append(row)
    matrix = DictVectorizer(dtype=np.float64).fit_transform(rows)
    return sp.csr_matrix(normalize(matrix, norm="l2")), int(matrix.shape[1])


def numeric_block(catalogue: CatalogueData) -> tuple[sp.csr_matrix, int]:
    columns = {"duration_ms": catalogue.tracks["duration_ms"].to_numpy(dtype=float)}
    for name in catalogue.features.columns.drop("item"):
        columns[name] = catalogue.features[name].to_numpy(dtype=float)
    standardized = []
    for name, values in columns.items():
        if name.endswith(LOG_FEATURES):
            with np.errstate(divide="ignore", invalid="ignore"):
                values = np.where(values > 0, np.log(values), np.nan)
        observed = ~np.isnan(values)
        mean, std = np.nanmean(values), np.nanstd(values)
        z = np.zeros_like(values)
        if observed.any() and std > 0:
            z[observed] = np.clip((values[observed] - mean) / std, -Z_CLIP, Z_CLIP)
        standardized.append(z)
    matrix = np.column_stack(standardized)
    # Missing values are 0 (the mean), so they add nothing. Scaling by the largest number of
    # observed columns keeps the block's norm around 1 without favouring sparsely-featured tracks.
    max_observed = max(1, int((matrix != 0).sum(axis=1).max()))
    return sp.csr_matrix(matrix / np.sqrt(max_observed)), matrix.shape[1]


def build_features(
    catalogue: CatalogueData, config: ContentConfig
) -> tuple[sp.csr_matrix, dict[str, int]]:
    genres, n_genres = genre_block(catalogue, config)
    categorical, n_categorical = categorical_block(catalogue, config)
    numeric, n_numeric = numeric_block(catalogue)
    features = sp.hstack(
        [
            config.genre_weight * genres,
            config.categorical_weight * categorical,
            config.numeric_weight * numeric,
        ],
        format="csr",
    )
    dimensions = {"genres": n_genres, "categorical": n_categorical, "numeric": n_numeric}
    return sp.csr_matrix(normalize(features, norm="l2")), dimensions


def fit_content_model(catalogue: CatalogueData, config: ContentConfig) -> ContentModel:
    features, dimensions = build_features(catalogue, config)
    svd = TruncatedSVD(
        n_components=config.n_components,
        n_iter=config.svd_iterations,
        random_state=config.random_state,
    )
    reduced = svd.fit_transform(features)
    embeddings = normalize(reduced, norm="l2").astype(np.float32)
    return ContentModel(
        config=config,
        track_ids=catalogue.track_ids,
        embeddings=embeddings,
        features=features,
        explained_variance=float(svd.explained_variance_ratio_.sum()),
        block_dimensions=dimensions,
    )


def artist_embeddings(
    embeddings: np.ndarray, artist_codes: np.ndarray, listeners: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Per artist code: the L2-normalized mean of its track embeddings, weighted by
    1 + log(1 + listeners) so an artist is represented mostly by the tracks people play.
    Returns (embeddings, track counts), indexed by artist code."""
    n_artists = int(artist_codes.max()) + 1 if len(artist_codes) else 0
    weights = 1.0 + np.log1p(listeners.astype(np.float64))
    has_content = np.linalg.norm(embeddings, axis=1) > 0
    weights = np.where(has_content, weights, 0.0)
    totals = np.zeros((n_artists, embeddings.shape[1]), dtype=np.float64)
    np.add.at(totals, artist_codes, embeddings * weights[:, None])
    counts = np.bincount(artist_codes[has_content], minlength=n_artists)
    return normalize(totals, norm="l2").astype(np.float32), counts
