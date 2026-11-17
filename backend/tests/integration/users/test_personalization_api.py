"""End-to-end tests of the Milestone 3 user API and personalized recommendations.

The world has four taste areas, each with its own content axis and collaborative factor:
rock (Radiohead, Arctic, Newband), pop (Popstar), electronic (DJ) and dream pop (Cigs). A user who
plays rock gets rock first; modes, exclusions, cold start and source failures are checked on top.
"""

import io
import json
import math
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import Artist, ArtistGenre, Genre, Track, TrackArtist, TrackGenre
from app.domains.recommendations.models import (
    CF_DIMENSIONS,
    EMBEDDING_DIMENSIONS,
    ArtistEmbedding,
    ModelArtifact,
    ModelVersion,
    TrackCollaborativeFactors,
    TrackEmbedding,
    TrackNeighbour,
    TrackPopularity,
)
from app.domains.recommendations.personalized import ARTIFACTS
from tests.integration.catalogue.conftest import register_source

pytestmark = pytest.mark.integration

AXES = {"rock": 0, "pop": 1, "electronic": 2, "dream pop": 3}
ARTISTS = {
    "Radiohead": "rock",
    "Arctic": "rock",
    "Newband": "rock",
    "Popstar": "pop",
    "DJ": "electronic",
    "Cigs": "dream pop",
}
# Tracks per artist, with listeners (popularity).
TRACKS = {
    "Radiohead": [("Creep", 90), ("Karma Police", 80), ("No Surprises", 70)],
    "Arctic": [("Do I Wanna Know", 85), ("505", 75)],
    "Newband": [("New Song One", 20), ("New Song Two", 15), ("New Song Three", 10)],
    "Popstar": [("Hit One", 100), ("Hit Two", 95)],
    "DJ": [("Drop", 60), ("Bass", 50)],
    "Cigs": [("Apocalypse", 40), ("Sunsetz", 30)],
}


def unit(size: int, axis: int, wobble: float, other: int) -> list[float]:
    values = [0.0] * size
    values[axis] = 1.0
    values[other % size] += wobble
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


@dataclass
class World:
    tracks: dict[str, uuid.UUID]
    artist_of: dict[str, str]
    artists: dict[str, uuid.UUID]
    versions: dict[str, ModelVersion]


async def _version(
    session: AsyncSession, model_type: str, params: dict[str, Any], data: dict[str, Any]
) -> ModelVersion:
    version = ModelVersion(
        model_type=model_type,
        version=f"{model_type}-test",
        status="active",
        params=params,
        training_data=data,
        trained_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    return version


WEIGHTED = {
    "kind": "weighted",
    "weights": {
        "collaborative_item": 1.0,
        "collaborative_mf": 1.0,
        "history": 1.0,
        "content": 1.0,
        "popularity": 0.2,
        "novelty": 0.0,
    },
    "calibration": {
        name: {"a": 3.0, "b": -1.0}
        for name in ("collaborative_item", "collaborative_mf", "history", "content", "popularity")
    },
}


@pytest.fixture
async def world(session: AsyncSession) -> World:
    ARTIFACTS.items.clear()
    source_id = await register_source(session, "musicbrainz")
    genres = {name: Genre(name=name, source_id=source_id) for name in AXES}
    artists = {
        name: Artist(name=name, normalized_name=name.lower(), source_id=source_id)
        for name in ARTISTS
    }
    session.add_all([*genres.values(), *artists.values()])
    await session.flush()
    for name, genre in ARTISTS.items():
        session.add(
            ArtistGenre(
                artist_id=artists[name].id,
                genre_id=genres[genre].id,
                source_id=source_id,
                weight=1.0,
                vote_count=5,
            )
        )
    content = await _version(session, "content", {"beta": {"artist": 0.3}}, {})
    popularity = await _version(session, "popularity", {"recent_days": 3}, {"users": 200})
    collaborative = await _version(
        session,
        "collaborative",
        {
            "fold_in": {
                "regularization": 0.1,
                "alpha": 1.0,
                "bm25_k1": 100.0,
                "bm25_b": 0.8,
                "average_length": 3.0,
            }
        },
        {},
    )
    hybrid = await _version(
        session,
        "hybrid",
        {
            "ranker": "weighted",
            "weighted": WEIGHTED,
            "candidates": {"source_limit": 50, "exploration_artists": 5, "popular_genres": 2},
            "diversity": {"mmr_lambda": 0.9, "default_mode": "auto"},
            "cold_start_popularity_weight": 0.3,
        },
        {},
    )

    tracks: dict[str, uuid.UUID] = {}
    artist_of: dict[str, str] = {}
    factors: list[list[float]] = []
    counter = 0
    for artist, entries in TRACKS.items():
        axis = AXES[ARTISTS[artist]]
        for title, listeners in entries:
            counter += 1
            track = Track(
                title=title,
                normalized_title=title.lower(),
                matching_key=f"{artist.lower()}|{title.lower()}",
                artist_id=artists[artist].id,
                source_id=source_id,
            )
            session.add(track)
            await session.flush()
            tracks[title], artist_of[title] = track.id, artist
            factor = unit(CF_DIMENSIONS, axis, 0.3, 10 + counter)
            factors.append(factor)
            session.add_all(
                [
                    TrackArtist(
                        track_id=track.id,
                        position=0,
                        artist_id=artists[artist].id,
                        credited_name=artist,
                    ),
                    TrackEmbedding(
                        model_version_id=content.id,
                        track_id=track.id,
                        embedding=unit(EMBEDDING_DIMENSIONS, axis, 0.2, 10 + counter),
                    ),
                    TrackPopularity(
                        model_version_id=popularity.id,
                        track_id=track.id,
                        listeners=listeners,
                        plays=listeners * 2,
                        score=math.log1p(listeners) / math.log1p(100),
                        recent_listeners=listeners // 2,
                        trending_score=None,
                    ),
                    TrackGenre(
                        track_id=track.id,
                        genre_id=genres[ARTISTS[artist]].id,
                        source_id=source_id,
                        level="recording",
                        weight=1.0,
                        vote_count=6,
                    ),
                    TrackCollaborativeFactors(
                        model_version_id=collaborative.id,
                        track_id=track.id,
                        factors=factor,
                        idf=1.0,
                    ),
                ]
            )
    for name, genre in ARTISTS.items():
        session.add(
            ArtistEmbedding(
                model_version_id=content.id,
                artist_id=artists[name].id,
                track_count=len(TRACKS[name]),
                embedding=unit(EMBEDDING_DIMENSIONS, AXES[genre], 0.1, 50),
            )
        )
    # Co-listening: tracks of the same taste area are neighbours.
    for a, ta in artist_of.items():
        for b, tb in artist_of.items():
            if a != b and ARTISTS[ta] == ARTISTS[tb]:
                session.add(
                    TrackNeighbour(
                        model_version_id=collaborative.id,
                        track_id=tracks[a],
                        neighbour_id=tracks[b],
                        score=0.5 if ta == tb else 0.3,
                    )
                )
    y = np.array(factors)
    buffer = io.BytesIO()
    np.save(buffer, y.T @ y, allow_pickle=False)
    session.add(
        ModelArtifact(
            model_version_id=collaborative.id,
            name="gram",
            media_type="application/x-npy",
            content=buffer.getvalue(),
            sha256="0" * 64,
        )
    )
    await session.commit()
    return World(
        tracks,
        artist_of,
        {n: a.id for n, a in artists.items()},
        {
            "content": content,
            "popularity": popularity,
            "collaborative": collaborative,
            "hybrid": hybrid,
        },
    )


async def create_user(client: AsyncClient) -> str:
    """Register a fresh account; the client's session cookie now belongs to it."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"listener-{uuid.uuid4().hex[:12]}@example.com",
            "password": "correct horse battery",
            "accept_terms": True,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def plays(
    world: World, titles: list[str], times: int = 3, **extra: Any
) -> Iterator[dict[str, Any]]:
    for title in titles:
        for _ in range(times):
            yield {"track_id": str(world.tracks[title]), "event_type": "play", **extra}


async def rock_fan(client: AsyncClient, world: World) -> str:
    user = await create_user(client)
    events = [
        *plays(world, ["Creep", "Karma Police"], 4),
        *plays(world, ["Do I Wanna Know"], 3),
        {"track_id": str(world.tracks["Creep"]), "event_type": "like"},
    ]
    response = await client.post("/api/v1/interactions", json={"events": events})
    assert response.status_code == 201, response.text
    return user


async def recommendations(client: AsyncClient, user: str, **params: Any) -> dict[str, Any]:
    response = await client.get("/api/v1/recommendations/for-you", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- users and interactions ------------------------------------------------------------------


async def test_signed_in_user_and_signed_out_requests(client: AsyncClient, world: World) -> None:
    user = await create_user(client)
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200
    assert response.json()["id"] == user
    await client.post("/api/v1/auth/logout")
    for path in ("/users/me", "/recommendations/for-you", "/interactions/history"):
        assert (await client.get(f"/api/v1{path}")).status_code == 401


async def test_interactions_build_and_update_the_taste_profile(
    client: AsyncClient, world: World
) -> None:
    await create_user(client)
    events = list(plays(world, ["Creep", "Karma Police", "Do I Wanna Know"]))
    response = await client.post("/api/v1/interactions", json={"events": events})
    body = response.json()
    assert response.status_code == 201
    assert body["recorded"] == 9
    assert body["duplicates"] == 0
    profile = body["profile"]
    assert [a["name"] for a in profile["artist_affinity"]] == ["Radiohead", "Arctic"]
    assert profile["genre_affinity"][0]["genre"] == "rock"
    assert profile["history_size"] == 3
    assert profile["interaction_count"] == 9

    # New interactions update the profile immediately.
    more = list(plays(world, ["Drop", "Bass"], 6))
    body = (await client.post("/api/v1/interactions", json={"events": more})).json()
    assert body["profile"]["history_size"] == 5
    assert "DJ" in [a["name"] for a in body["profile"]["artist_affinity"]]


async def test_retried_events_are_recorded_once(client: AsyncClient, world: World) -> None:
    await create_user(client)
    track = str(world.tracks["Creep"])
    batch = {
        "events": [
            {"track_id": track, "event_type": "play", "client_event_id": "e-1"},
            {"track_id": track, "event_type": "play", "client_event_id": "e-2"},
            {"track_id": track, "event_type": "play", "client_event_id": "e-2"},
        ]
    }
    first = (await client.post("/api/v1/interactions", json=batch)).json()
    second = (await client.post("/api/v1/interactions", json=batch)).json()
    assert (first["recorded"], first["duplicates"]) == (2, 1)
    assert (second["recorded"], second["duplicates"]) == (0, 3)
    assert second["profile"]["interaction_count"] == 2


async def test_invalid_interactions_are_rejected(client: AsyncClient, world: World) -> None:
    await create_user(client)
    url = "/api/v1/interactions"
    unknown = await client.post(
        url, json={"events": [{"track_id": str(uuid.uuid4()), "event_type": "play"}]}
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["kind"] == "tracks"
    track = str(world.tracks["Creep"])
    bad_type = await client.post(url, json={"events": [{"track_id": track, "event_type": "clap"}]})
    assert bad_type.status_code == 422
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    in_future = await client.post(
        url, json={"events": [{"track_id": track, "event_type": "play", "occurred_at": future}]}
    )
    assert in_future.status_code == 422
    naive = await client.post(
        url,
        json={
            "events": [
                {"track_id": track, "event_type": "play", "occurred_at": "2026-01-01T00:00:00"}
            ]
        },
    )
    assert naive.status_code == 422
    assert (await client.post(url, json={"events": []})).status_code == 422


async def test_interaction_history_pages_backwards(client: AsyncClient, world: World) -> None:
    await create_user(client)
    start = datetime.now(UTC) - timedelta(hours=10)
    events = [
        {
            "track_id": str(world.tracks["Creep"]),
            "event_type": "play",
            "occurred_at": (start + timedelta(hours=i)).isoformat(),
        }
        for i in range(5)
    ]
    await client.post("/api/v1/interactions", json={"events": events})
    page = (await client.get("/api/v1/interactions/history", params={"limit": 3})).json()
    assert len(page["items"]) == 3
    assert page["next_before"] is not None
    rest = (
        await client.get(
            "/api/v1/interactions/history",
            params={"limit": 3, "before": page["next_before"]},
        )
    ).json()
    assert len(rest["items"]) == 2
    assert rest["next_before"] is None


# --- preferences and profile -----------------------------------------------------------------


async def test_preferences_round_trip_and_validation(client: AsyncClient, world: World) -> None:
    await create_user(client)
    url = "/api/v1/users/me/preferences"
    default = (await client.get(url)).json()
    assert default["exploration_mode"] is None
    assert default["personalization_enabled"] is True
    update = {
        "exploration_mode": "explorer",
        "preferred_artists": [str(world.artists["DJ"])],
        "excluded_artists": [str(world.artists["Popstar"])],
        "preferred_genres": ["Electronic"],
        "excluded_genres": ["pop"],
    }
    saved = await client.put(url, json=update)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["exploration_mode"] == "explorer"
    assert [a["name"] for a in body["preferred_artists"]] == ["DJ"]
    assert [a["name"] for a in body["excluded_artists"]] == ["Popstar"]
    assert body["preferred_genres"] == ["electronic"]
    assert body["excluded_genres"] == ["pop"]

    profile = (await client.get("/api/v1/users/me/taste-profile")).json()
    assert profile["artist_affinity"][0]["name"] == "DJ"
    assert profile["discovery_target"] == 0.8
    assert profile["genre_affinity"][0]["genre"] == "electronic"

    unknown_artist = await client.put(url, json={"preferred_artists": [str(uuid.uuid4())]})
    assert unknown_artist.status_code == 422
    unknown_genre = await client.put(url, json={"preferred_genres": ["polka-core"]})
    assert unknown_genre.status_code == 422
    conflict = await client.put(
        url,
        json={
            "preferred_artists": [str(world.artists["DJ"])],
            "excluded_artists": [str(world.artists["DJ"])],
        },
    )
    assert conflict.status_code == 422


async def test_taste_profile_can_include_embeddings(client: AsyncClient, world: World) -> None:
    await rock_fan(client, world)
    body = (
        await client.get("/api/v1/users/me/taste-profile", params={"include_embeddings": "true"})
    ).json()
    assert len(body["long_term_embedding"]) == EMBEDDING_DIMENSIONS
    assert body["content_model_version"] == "content-test"
    assert body["listening_frequency"]["liked"] == 1.0
    plain = (await client.get("/api/v1/users/me/taste-profile")).json()
    assert plain["long_term_embedding"] is None


# --- for you ---------------------------------------------------------------------------------


async def test_for_you_personalizes_with_attribution(client: AsyncClient, world: World) -> None:
    user = await rock_fan(client, world)
    body = await recommendations(client, user, limit=6)
    titles = [r["title"] for r in body["recommendations"]]
    assert body["strategy"] == "personalized"
    assert body["model_versions"] == {
        "hybrid": "hybrid-test",
        "collaborative": "collaborative-test",
        "content": "content-test",
        "popularity": "popularity-test",
    }
    assert not {"Creep", "Karma Police", "Do I Wanna Know"} & set(titles)
    # The strongest unheard rock tracks lead.
    assert world.artist_of[titles[0]] in {"Radiohead", "Arctic", "Newband"}
    statuses = {s["source"]: s["status"] for s in body["candidate_sources"]}
    assert statuses["collaborative_item"] == "ok"
    assert statuses["collaborative_mf"] == "ok"
    for item in body["recommendations"]:
        assert item["reason"]
        assert item["sources"]
        assert all(s["model_version"] for s in item["sources"])
    # Per-artist cap of the for-you policy.
    artists = [world.artist_of[t] for t in titles]
    assert max(artists.count(a) for a in set(artists)) <= 2
    # Same inputs, same list.
    again = await recommendations(client, user, limit=6)
    assert [r["track_id"] for r in again["recommendations"]] == [
        r["track_id"] for r in body["recommendations"]
    ]


async def test_exploration_modes_change_the_mix(client: AsyncClient, world: World) -> None:
    user = await rock_fan(client, world)
    familiar = await recommendations(client, user, limit=5, exploration="familiar")
    explorer = await recommendations(client, user, limit=5, exploration="explorer")
    assert familiar["composition"]["discovery_target"] == 0.2
    assert explorer["composition"]["discovery_target"] == 0.8
    assert explorer["composition"]["discovery"] > familiar["composition"]["discovery"]
    for item in explorer["recommendations"]:
        known = world.artist_of[item["title"]] in {"Radiohead", "Arctic"}
        assert item["discovery"] is not known


async def test_dislikes_exclusions_and_skips_shape_the_list(
    client: AsyncClient, world: World
) -> None:
    user = await rock_fan(client, world)
    events = [
        {"track_id": str(world.tracks["No Surprises"]), "event_type": "dislike"},
        *(
            {"track_id": str(world.tracks[t]), "event_type": "skip", "position_ms": 4000}
            for t in ("Hit One", "Hit Two", "Hit One")
        ),
    ]
    await client.post("/api/v1/interactions", json={"events": events})
    await client.put(
        "/api/v1/users/me/preferences",
        json={"excluded_artists": [str(world.artists["Cigs"])]},
    )
    profile = (await client.get("/api/v1/users/me/taste-profile")).json()
    assert [a["name"] for a in profile["negative_artists"]] == ["Popstar"]
    body = await recommendations(client, user, limit=20)
    titles = {r["title"] for r in body["recommendations"]}
    assert "No Surprises" not in titles
    assert not {"Apocalypse", "Sunsetz"} & titles
    # Skipped tracks are heard, so never recommended again.
    assert not {"Hit One", "Hit Two"} & titles


async def test_cold_start_users_get_recommendations(client: AsyncClient, world: World) -> None:
    newcomer = await create_user(client)
    body = await recommendations(client, newcomer, limit=5)
    assert body["strategy"] == "cold_start"
    assert len(body["recommendations"]) == 5
    assert body["recommendations"][0]["title"] == "Hit One"  # most popular

    declared = await create_user(client)
    await client.put(
        "/api/v1/users/me/preferences",
        json={"preferred_artists": [str(world.artists["DJ"])], "preferred_genres": ["electronic"]},
    )
    body = await recommendations(client, declared, limit=3)
    assert body["strategy"] == "cold_start"
    assert world.artist_of[body["recommendations"][0]["title"]] == "DJ"


async def test_personalization_opt_out_ignores_personal_data(
    client: AsyncClient, world: World
) -> None:
    user = await rock_fan(client, world)
    await client.put("/api/v1/users/me/preferences", json={"personalization_enabled": False})
    body = await recommendations(client, user, limit=5)
    assert body["composition"]["exploration_mode"] == "off"
    assert all(not r["discovery"] for r in body["recommendations"])
    assert body["recommendations"][0]["title"] == "Hit One"


async def test_a_failing_source_does_not_fail_the_request(
    client: AsyncClient, session: AsyncSession, world: World
) -> None:
    ARTIFACTS.items.clear()
    await session.execute(delete(ModelArtifact).where(ModelArtifact.name == "gram"))
    await session.commit()
    user = await rock_fan(client, world)
    body = await recommendations(client, user, limit=5)
    statuses = {s["source"]: s for s in body["candidate_sources"]}
    assert statuses["collaborative_mf"]["status"] == "failed"
    assert "gram" in statuses["collaborative_mf"]["detail"]
    assert statuses["collaborative_item"]["status"] == "ok"
    assert len(body["recommendations"]) == 5


async def test_lambdarank_ranker_is_served_from_its_artifact(
    client: AsyncClient, session: AsyncSession, world: World
) -> None:
    hybrid = world.versions["hybrid"]
    trees = {
        "feature_names": ["cf_item_score", "popularity"],
        "tree_info": [
            {
                "tree_structure": {
                    "split_index": 0,
                    "split_feature": 0,
                    "threshold": 0.0,
                    "decision_type": "<=",
                    "default_left": True,
                    "missing_type": "None",
                    "left_child": {"leaf_value": 0.0},
                    "right_child": {"leaf_value": 1.0},
                }
            }
        ],
    }
    from app.domains.recommendations.hybrid_ranking import TreeEnsembleRanker

    content = json.dumps(TreeEnsembleRanker.from_lightgbm_dump(trees).to_dict()).encode()
    session.add(
        ModelArtifact(
            model_version_id=hybrid.id,
            name="ranker",
            media_type="application/json",
            content=content,
            sha256="0" * 64,
        )
    )
    hybrid.params = {**hybrid.params, "ranker": "lambdarank"}
    session.add(hybrid)
    await session.commit()
    user = await rock_fan(client, world)
    body = await recommendations(client, user, limit=4)
    assert body["ranker"] == "lambdarank"
    assert len(body["recommendations"]) == 4


# --- artist radio ----------------------------------------------------------------------------


async def test_artist_radio_mixes_the_artist_with_similar_artists(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(
        f"/api/v1/recommendations/artist-radio/{world.artists['Radiohead']}", params={"limit": 5}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy"] == "artist_radio"
    artists = [world.artist_of[r["title"]] for r in body["recommendations"]]
    assert 1 <= artists.count("Radiohead") <= math.ceil(0.4 * 5)
    assert all(artists.count(a) <= 2 for a in set(artists) - {"Radiohead"})
    missing = await client.get(f"/api/v1/recommendations/artist-radio/{uuid.uuid4()}")
    assert missing.status_code == 404
