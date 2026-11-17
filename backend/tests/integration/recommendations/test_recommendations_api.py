"""End-to-end tests of the recommendation endpoints over a small, hand-built model.

Embeddings are placed so the expected neighbours are known exactly:
    seed "Alpha One" = e0; "Alpha Two"/"Alpha Three" (same artist) and "Beta One"/"Beta Two"
    lean towards e0; "Gamma One" is further away; "Delta One" is orthogonal.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import (
    Artist,
    ArtistGenre,
    Genre,
    Track,
    TrackArtist,
    TrackGenre,
)
from app.domains.recommendations.models import (
    EMBEDDING_DIMENSIONS,
    ArtistEmbedding,
    ModelVersion,
    TrackEmbedding,
    TrackPopularity,
)
from app.domains.recommendations.ranking import blended_score
from tests.integration.catalogue.conftest import register_source

pytestmark = pytest.mark.integration

BETA = 0.2


def vector(**components: float) -> list[float]:
    """A unit vector with the given components, e.g. vector(e0=1, e1=0.2)."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    for name, value in components.items():
        values[int(name[1:])] = value
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


@dataclass
class World:
    tracks: dict[str, uuid.UUID]
    artists: dict[str, uuid.UUID]
    vectors: dict[str, list[float]]
    popularity: dict[str, float]
    content_version: str
    popularity_version: str


TRACKS = {
    # title: (artist, embedding, popularity score, listeners, trending, release year, genre votes)
    "Alpha One": ("Alpha", vector(e0=1), 0.5, 50, None, 1994, {"rock": 10}),
    "Alpha One (copy)": ("Alpha", vector(e0=1, e5=0.01), 0.1, 2, None, 1994, {"rock": 10}),
    "Alpha Two": ("Alpha", vector(e0=1, e1=0.2), 0.3, 30, None, 1995, {"rock": 10}),
    "Alpha Three": ("Alpha", vector(e0=1, e1=0.25), 0.2, 20, None, 1996, {"rock": 10}),
    "Beta One": ("Beta", vector(e0=1, e1=0.3), 1.0, 100, 1.2, 1999, {"rock": 6, "jazz": 4}),
    "Beta Two": ("Beta", vector(e0=1, e2=0.6), 0.9, 90, -0.5, 2001, {"jazz": 10}),
    "Gamma One": ("Gamma", vector(e0=1, e3=1.5), 0.8, 80, 0.4, 1993, {"rock": 5}),
    "Delta One": ("Delta", vector(e4=1), 0.95, 95, None, 2010, {"jazz": 10}),
}
ARTIST_VECTORS = {
    "Alpha": vector(e0=1, e1=0.2),
    "Beta": vector(e0=1, e1=0.5),
    "Gamma": vector(e0=1, e3=1.5),
    "Delta": vector(e4=1),
}


async def _version(
    session: AsyncSession, model_type: str, params: dict[str, object]
) -> ModelVersion:
    version = ModelVersion(
        model_type=model_type,
        version=f"{model_type}-test",
        status="active",
        params=params,
        training_data={"window_days": 14},
        trained_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    return version


@pytest.fixture
async def world(session: AsyncSession) -> World:
    source_id = await register_source(session, "musicbrainz")
    genres = {name: Genre(name=name, source_id=source_id) for name in ("rock", "jazz", "k-pop")}
    artists = {
        name: Artist(name=name, normalized_name=name.lower(), source_id=source_id)
        for name in ARTIST_VECTORS
    }
    session.add_all([*genres.values(), *artists.values()])
    await session.flush()
    session.add(
        ArtistGenre(
            artist_id=artists["Alpha"].id, genre_id=genres["rock"].id, source_id=source_id, weight=1
        )
    )

    content = await _version(session, "content", {"beta": {"seed": BETA, "artist": BETA}})
    popularity = await _version(session, "popularity", {"recent_days": 3})
    tracks: dict[str, uuid.UUID] = {}
    for title, (artist, embedding, score, listeners, trend, year, tags) in TRACKS.items():
        key_title = title.removesuffix(" (copy)").lower()
        track = Track(
            title=title,
            normalized_title=title.lower(),
            matching_key=f"{artist.lower()}|{key_title}",
            release_year=year,
            artist_id=artists[artist].id,
            source_id=source_id,
        )
        session.add(track)
        await session.flush()
        tracks[title] = track.id
        session.add_all(
            [
                TrackArtist(
                    track_id=track.id,
                    position=0,
                    artist_id=artists[artist].id,
                    credited_name=artist,
                ),
                TrackEmbedding(model_version_id=content.id, track_id=track.id, embedding=embedding),
                TrackPopularity(
                    model_version_id=popularity.id,
                    track_id=track.id,
                    listeners=listeners,
                    plays=listeners * 2,
                    score=score,
                    recent_listeners=listeners // 2,
                    trending_score=trend,
                ),
                *(
                    TrackGenre(
                        track_id=track.id,
                        genre_id=genres[name].id,
                        source_id=source_id,
                        level="recording",
                        weight=votes / sum(tags.values()),
                        vote_count=votes,
                    )
                    for name, votes in tags.items()
                ),
            ]
        )
    session.add_all(
        ArtistEmbedding(
            model_version_id=content.id, artist_id=artists[name].id, track_count=1, embedding=v
        )
        for name, v in ARTIST_VECTORS.items()
    )
    # A track outside the model (no embedding, no popularity), e.g. from a research-only source.
    outside = Track(
        title="Outside",
        normalized_title="outside",
        matching_key="delta|outside",
        artist_id=artists["Delta"].id,
        source_id=source_id,
    )
    session.add(outside)
    await session.flush()
    session.add(
        TrackArtist(
            track_id=outside.id, position=0, artist_id=artists["Delta"].id, credited_name="Delta"
        )
    )
    tracks["Outside"] = outside.id
    await session.commit()
    return World(
        tracks=tracks,
        artists={name: a.id for name, a in artists.items()},
        vectors={title: spec[1] for title, spec in TRACKS.items()},
        popularity={title: spec[2] for title, spec in TRACKS.items()},
        content_version=content.version,
        popularity_version=popularity.version,
    )


def _titles(body: dict[str, object]) -> list[str]:
    items = body["recommendations"]
    assert isinstance(items, list)
    return [item["title"] for item in items]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_similar_tracks_ranks_neighbours_with_the_popularity_blend(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(f"/api/v1/recommendations/similar/{world.tracks['Alpha One']}")

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "similar_tracks"
    assert body["model_version"] == world.content_version
    assert body["model_versions"] == {
        "content": world.content_version,
        "popularity": world.popularity_version,
    }
    uuid.UUID(body["request_id"])

    seed = world.vectors["Alpha One"]
    expected = sorted(
        (t for t in TRACKS if t not in {"Alpha One", "Alpha One (copy)"}),
        key=lambda t: -blended_score(_cosine(seed, world.vectors[t]), world.popularity[t], BETA),
    )
    # The seed and its duplicate are excluded, so the default cap (two per artist) removes nothing.
    assert _titles(body) == expected
    scores = [item["score"] for item in body["recommendations"]]
    assert scores == sorted(scores, reverse=True)
    top = body["recommendations"][0]
    assert top["score"] == pytest.approx(
        blended_score(
            _cosine(seed, world.vectors[top["title"]]), world.popularity[top["title"]], BETA
        ),
        abs=1e-3,
    )


async def test_similar_tracks_excludes_seed_duplicates_and_explains(
    client: AsyncClient, world: World
) -> None:
    body = (
        await client.get(
            f"/api/v1/recommendations/similar/{world.tracks['Alpha One']}",
            params={"limit": 3, "max_per_artist": 1},
        )
    ).json()

    titles = _titles(body)
    # Beta Two and Alpha Three are skipped by the one-per-artist cap.
    assert titles == ["Beta One", "Alpha Two", "Gamma One"]
    artists = [item["artist"] for item in body["recommendations"]]
    assert len(set(artists)) == len(artists)
    reasons = {item["title"]: item["reason"] for item in body["recommendations"]}
    assert "rock" in reasons["Beta One"]
    assert "(similarity 0." in reasons["Beta One"]


async def test_similar_tracks_errors(
    client: AsyncClient, world: World, session: AsyncSession
) -> None:
    unknown = await client.get(f"/api/v1/recommendations/similar/{uuid.uuid4()}")
    assert unknown.status_code == 404
    outside = await client.get(f"/api/v1/recommendations/similar/{world.tracks['Outside']}")
    assert outside.status_code == 404
    assert "not covered" in outside.json()["detail"]
    invalid = await client.get(
        f"/api/v1/recommendations/similar/{world.tracks['Alpha One']}", params={"limit": 0}
    )
    assert invalid.status_code == 422

    await session.execute(update(ModelVersion).values(status="retired"))
    await session.commit()
    unavailable = await client.get(f"/api/v1/recommendations/similar/{world.tracks['Alpha One']}")
    assert unavailable.status_code == 503


async def test_artist_recommendations_use_similar_artists_top_tracks(
    client: AsyncClient, world: World
) -> None:
    body = (await client.get(f"/api/v1/recommendations/artist/{world.artists['Alpha']}")).json()

    assert body["strategy"] == "similar_artists"
    titles = _titles(body)
    assert not any(t.startswith("Alpha") for t in titles)
    # Beta is the most similar artist, then Gamma; Delta is orthogonal (similarity 0) but still
    # within the pool, so it ranks last.
    assert titles[:2] == ["Beta One", "Beta Two"]
    assert titles.index("Gamma One") < titles.index("Delta One")
    assert "Alpha" in body["recommendations"][0]["reason"]
    missing = await client.get(f"/api/v1/recommendations/artist/{uuid.uuid4()}")
    assert missing.status_code == 404


async def test_genre_recommendations_rank_members_by_genre_score(
    client: AsyncClient, world: World
) -> None:
    response = await client.get("/api/v1/recommendations/genre/JAZZ")

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "genre"
    assert body["model_version"] == world.popularity_version
    # Smoothed affinities (votes / (total + 2)): Delta One and Beta Two 10/12, Beta One 4/12.
    # Scores 0.3 x affinity + 0.7 x popularity: 0.915 > 0.880 > 0.800.
    assert _titles(body) == ["Delta One", "Beta Two", "Beta One"]
    assert "jazz" in body["recommendations"][0]["reason"]
    # Artist-level genres count too: Alpha's tracks are rock through their artist.
    rock = (await client.get("/api/v1/recommendations/genre/rock", params={"limit": 50})).json()
    assert {"Alpha One", "Alpha Two"} <= set(_titles(rock))
    assert len([t for t in _titles(rock) if t.startswith("Alpha")]) == 2
    empty = (await client.get("/api/v1/recommendations/genre/k pop")).json()
    assert empty["recommendations"] == []
    assert (await client.get("/api/v1/recommendations/genre/polka")).status_code == 404


async def test_popular_and_trending(client: AsyncClient, world: World) -> None:
    popular = (await client.get("/api/v1/recommendations/popular", params={"limit": 3})).json()
    assert popular["strategy"] == "popular"
    assert _titles(popular) == ["Beta One", "Delta One", "Beta Two"]
    assert "100 listeners in the last 14 days" in popular["recommendations"][0]["reason"]

    trending = (
        await client.get("/api/v1/recommendations/popular", params={"kind": "trending"})
    ).json()
    assert trending["strategy"] == "trending"
    # Only reliable rising trends: Beta Two's trend is negative, the others have none.
    assert _titles(trending) == ["Beta One", "Gamma One"]
    assert trending["recommendations"][0]["score"] == pytest.approx(1.2)

    by_artist = (
        await client.get(
            "/api/v1/recommendations/popular", params={"artist_id": str(world.artists["Alpha"])}
        )
    ).json()
    assert _titles(by_artist) == ["Alpha One", "Alpha Two", "Alpha Three", "Alpha One (copy)"]
    unknown = await client.get(
        "/api/v1/recommendations/popular", params={"artist_id": str(uuid.uuid4())}
    )
    assert unknown.status_code == 404
