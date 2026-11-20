"""Pipeline -> database -> API: publishing models and serving them."""

import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.ingestion import SourceArtist, SourceCredit, SourceGenreTag, SourceTrack
from app.domains.catalogue.provenance import ensure_data_source
from app.domains.catalogue.writer import CatalogueWriter
from app.domains.recommendations.models import (
    EMBEDDING_DIMENSIONS,
    ArtistEmbedding,
    ModelVersion,
    TrackEmbedding,
    TrackPopularity,
)
from app.domains.recommendations.service import RecommendationService
from soniqueo_ml.recommendation.catalogue_data import load_catalogue
from soniqueo_ml.recommendation.popularity import compute_popularity
from soniqueo_ml.recommendation.publish import VersionSpec, publish_content, publish_popularity
from soniqueo_ml.recommendation.retrieval_benchmark import run_retrieval_benchmark
from tests.recommendation_fixtures import T0, listens

pytestmark = pytest.mark.integration

SONGS = [
    ("mb-1", "Alpha", "First", ["rock"]),
    ("mb-2", "Alpha", "Second", ["rock"]),
    ("mb-3", "Beta", "Third", ["rock", "pop"]),
    ("mb-4", "Beta", "Fourth", ["pop"]),
    ("mb-5", "Gamma", "Fifth", ["jazz"]),
    ("mb-6", "Gamma", "Sixth", ["jazz"]),
]


def source_track(
    provider: str, external_id: str, artist: str, title: str, genres: list[str]
) -> SourceTrack:
    return SourceTrack(
        provider=provider,
        external_id=external_id,
        title=title,
        credits=[
            SourceCredit(
                artist=SourceArtist(
                    provider=provider, external_id=f"{provider}-{artist}", name=artist
                ),
                credited_name=artist,
            )
        ],
        duration_ms=200_000,
        release_date="2001",
        genres=[SourceGenreTag(name=g) for g in genres],
    )


async def _source(session: AsyncSession, key: str, restriction: str) -> uuid.UUID:
    return await ensure_data_source(
        session,
        key=key,
        name=key,
        homepage_url=f"https://{key}.example",
        license="test",
        license_url="https://example.org",
        usage_restriction=restriction,
    )


@pytest.fixture
async def catalogue_ids(session: AsyncSession) -> list[str]:
    musicbrainz = CatalogueWriter(
        session, await _source(session, "musicbrainz", "non_commercial"), create_unknown_genres=True
    )
    ids = [
        str((await musicbrainz.upsert_track(source_track("musicbrainz", *song))).track_id)
        for song in SONGS
    ]
    fma = CatalogueWriter(
        session, await _source(session, "fma", "research_only"), create_unknown_genres=True
    )
    await fma.upsert_track(source_track("fma", "fma-1", "Free Artist", "Free Song", ["rock"]))
    await session.commit()
    return ids


def spec(model_type: str, marker: int) -> VersionSpec:
    return VersionSpec(
        model_type,
        {"marker": marker, "beta": {"seed": 0.0, "artist": 0.0}},
        {"window_days": 7},
        {},
        datetime(2026, 11, 16, tzinfo=UTC),
    )


def vectors(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    matrix = rng.normal(size=(n, EMBEDDING_DIMENSIONS)).astype(np.float32)
    return np.asarray(matrix / np.linalg.norm(matrix, axis=1, keepdims=True), dtype=np.float32)


async def test_load_catalogue_separates_research_only_sources(
    session: AsyncSession, catalogue_ids: list[str]
) -> None:
    served = await load_catalogue(session)
    research = await load_catalogue(session, research_only=True)

    assert sorted(served.track_ids) == sorted(catalogue_ids)
    assert research.tracks["title"].tolist() == ["Free Song"]
    third = served.item_index()[catalogue_ids[2]]
    assert set(served.genres.loc[served.genres["item"] == third, "genre"]) == {"rock", "pop"}
    assert served.artist_codes().max() == 2


async def test_publishing_activates_new_versions_and_drops_old_rows(
    session: AsyncSession, catalogue_ids: list[str]
) -> None:
    data = listens(
        [("u1", catalogue_ids[0], 1), ("u2", catalogue_ids[0], 2), ("u1", catalogue_ids[2], 2)]
    )
    popularity = compute_popularity(
        data, np.array(catalogue_ids, dtype=object), T0 + pd.Timedelta(days=3)
    )

    first = await publish_popularity(session, spec("popularity", 1), popularity)
    second = await publish_popularity(session, spec("popularity", 2), popularity)
    again = await publish_popularity(session, spec("popularity", 2), popularity)

    assert first["version"] != second["version"] == again["version"]
    assert second["retired"] == [first["version"]]
    versions = {v.version: v.status for v in (await session.scalars(select(ModelVersion))).all()}
    assert versions == {first["version"]: "retired", second["version"]: "active"}
    rows = await session.scalar(select(func.count()).select_from(TrackPopularity))
    assert rows == len(catalogue_ids)  # only the active version keeps serving rows


async def test_published_content_is_served_and_benchmarked(
    session: AsyncSession, catalogue_ids: list[str]
) -> None:
    embeddings = vectors(len(catalogue_ids))
    embeddings[5] = 0  # a track without content is not published
    track_ids = np.array(catalogue_ids, dtype=object)
    served = await load_catalogue(session)
    artist_ids = np.asarray(pd.unique(served.tracks["artist_id"]), dtype=object)

    result = await publish_content(
        session,
        spec("content", 1),
        track_ids,
        embeddings,
        artist_ids,
        vectors(len(artist_ids), seed=1),
        np.array([2, 2, 1], dtype=np.int64),
    )

    assert result["track_embeddings"] == 5
    assert result["artist_embeddings"] == 3
    assert await session.scalar(select(func.count()).select_from(TrackEmbedding)) == 5
    assert await session.scalar(select(func.count()).select_from(ArtistEmbedding)) == 3

    response = await RecommendationService(session).similar_tracks(
        uuid.UUID(catalogue_ids[0]), limit=10, max_per_artist=5
    )
    sims = embeddings[:5] @ embeddings[0]
    expected = [catalogue_ids[i] for i in np.argsort(-sims)[1:]]
    assert [str(r.track_id) for r in response.recommendations] == expected
    assert response.model_version == result["version"]

    content = await session.scalar(
        select(ModelVersion).where(
            ModelVersion.model_type == "content", ModelVersion.status == "active"
        )
    )
    assert content is not None
    benchmark = await run_retrieval_benchmark(
        session, content.id, track_ids, embeddings, queries=4, k=2
    )
    methods = {m["method"]: m for m in benchmark["methods"]}
    assert methods["pgvector exact (sequential scan)"]["recall"] == 1.0
    assert methods["pgvector HNSW ef_search=400"]["recall"] == 1.0
    assert benchmark["vectors"] == 5
