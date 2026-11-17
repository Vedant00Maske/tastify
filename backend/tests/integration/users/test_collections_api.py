"""Milestone 4 collections (moods, hidden gems, surprise, because-you-listened), playlists and
the catalogue additions (artist search, genres, artwork), on the Milestone 3 test world."""

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.catalogue.repository import cover_art_url
from app.domains.users.models import UserInteraction
from tests.integration.users.test_personalization_api import (
    World,
    create_user,
    rock_fan,
    world,
)

pytestmark = pytest.mark.integration

__all__ = ["world"]


async def get(client: AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"/api/v1{path}", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- moods and personal collections ----------------------------------------------------------


async def test_moods_are_listed_and_mixed_for_anyone(client: AsyncClient, world: World) -> None:
    moods = await get(client, "/recommendations/moods")
    keys = [m["key"] for m in moods["moods"]]
    assert "midnight-drive" in keys
    assert len(keys) == 8
    mix = await get(client, "/recommendations/mood/midnight-drive", limit=5)
    assert mix["strategy"] == "mood"
    assert mix["personalized"] is False
    titles = {r["title"] for r in mix["recommendations"]}
    assert titles  # the dream pop tracks fit Midnight Drive
    assert titles <= {"Apocalypse", "Sunsetz"}
    assert all("Fits Midnight Drive" in r["reason"] for r in mix["recommendations"])
    missing = await client.get("/api/v1/recommendations/mood/no-such-mood")
    assert missing.status_code == 404


async def test_mood_mix_regenerates_without_excluded_tracks(
    client: AsyncClient, world: World
) -> None:
    apocalypse = str(world.tracks["Apocalypse"])
    mix = await get(client, "/recommendations/mood/midnight-drive", limit=5, exclude=[apocalypse])
    assert [r["title"] for r in mix["recommendations"]] == ["Sunsetz"]


async def test_signed_in_mood_mix_skips_heard_tracks(client: AsyncClient, world: World) -> None:
    await create_user(client)
    await client.post(
        "/api/v1/interactions",
        json={"events": [{"track_id": str(world.tracks["Apocalypse"]), "event_type": "play"}]},
    )
    mix = await get(client, "/recommendations/mood/midnight-drive", limit=5)
    assert mix["personalized"] is True
    assert [r["title"] for r in mix["recommendations"]] == ["Sunsetz"]


async def test_stored_taste_profile_keeps_strongest_genres_first(
    client: AsyncClient, world: World
) -> None:
    await rock_fan(client, world)
    preferences = await get(client, "/users/me/preferences")
    preferences["preferred_genres"] = ["dream pop"]
    preferences["preferred_artists"] = [a["artist_id"] for a in preferences["preferred_artists"]]
    preferences["excluded_artists"] = [a["artist_id"] for a in preferences["excluded_artists"]]
    response = await client.put("/api/v1/users/me/preferences", json=preferences)
    assert response.status_code == 200, response.text
    # The first read rebuilds and stores the profile; the second loads it back from JSONB.
    for _ in range(2):
        taste = await get(client, "/users/me/taste")
        scores = [g["score"] for g in taste["genres"]]
        assert scores == sorted(scores, reverse=True)
        assert "dream pop" in [g["genre"] for g in taste["genres"] if g["score"] == 1.0]


async def test_hidden_gems_are_lesser_known(client: AsyncClient, world: World) -> None:
    await rock_fan(client, world)
    gems = await get(client, "/recommendations/hidden-gems", limit=10)
    assert gems["strategy"] == "hidden_gems"
    titles = [r["title"] for r in gems["recommendations"]]
    # Only the Newband tracks (10-20 listeners) are under the hidden-gem popularity bar here.
    assert titles
    assert all(world.artist_of[t] == "Newband" for t in titles)
    assert all("hidden gem" in r["reason"] for r in gems["recommendations"])


async def test_surprise_returns_one_discovery(client: AsyncClient, world: World) -> None:
    await rock_fan(client, world)
    body = await get(client, "/recommendations/surprise")
    assert body["strategy"] == "surprise"
    assert len(body["recommendations"]) == 1
    assert body["recommendations"][0]["reason"].startswith("Something new for you")


async def test_because_you_listened_uses_co_listening(client: AsyncClient, world: World) -> None:
    await rock_fan(client, world)
    body = await get(client, "/recommendations/because-you-listened", seeds=2, limit=3)
    assert body["sections"]
    heard = {"Creep", "Karma Police", "Do I Wanna Know"}
    for section in body["sections"]:
        assert section["seed"]["title"] in heard
        assert section["source"] == "collaborative"
        titles = {r["title"] for r in section["recommendations"]}
        assert not titles & heard
        assert all(world.artist_of[t] in {"Radiohead", "Arctic", "Newband"} for t in titles)


# --- playlists -------------------------------------------------------------------------------


async def test_playlist_lifecycle(client: AsyncClient, session: AsyncSession, world: World) -> None:
    await create_user(client)
    tracks = [str(world.tracks[t]) for t in ("Creep", "Drop", "Sunsetz")]
    created = await client.post(
        "/api/v1/playlists",
        json={"name": "  Late   night ", "description": "for driving", "track_ids": tracks},
    )
    assert created.status_code == 201, created.text
    playlist = created.json()
    assert playlist["name"] == "Late night"
    assert playlist["kind"] == "manual"
    assert playlist["track_count"] == 3
    pid = playlist["id"]
    # Adding by hand is feedback: playlist_add events, and duplicates are skipped.
    added = await client.post(
        f"/api/v1/playlists/{pid}/tracks",
        json={"track_ids": [tracks[0], str(world.tracks["Bass"])]},
    )
    assert [t["title"] for t in added.json()["tracks"]] == ["Creep", "Drop", "Sunsetz", "Bass"]
    events = await session.scalar(
        select(func.count())
        .select_from(UserInteraction)
        .where(UserInteraction.event_type == "playlist_add")
    )
    assert events == 4  # three on create, one new on add
    order = [t["id"] for t in reversed(added.json()["tracks"])]
    reordered = await client.put(f"/api/v1/playlists/{pid}/tracks/order", json={"track_ids": order})
    assert [t["title"] for t in reordered.json()["tracks"]] == ["Bass", "Sunsetz", "Drop", "Creep"]
    bad_order = await client.put(
        f"/api/v1/playlists/{pid}/tracks/order", json={"track_ids": order[:2]}
    )
    assert bad_order.status_code == 422
    removed = await client.delete(f"/api/v1/playlists/{pid}/tracks/{tracks[1]}")
    assert [t["position"] for t in removed.json()["tracks"]] == [0, 1, 2]
    renamed = await client.patch(
        f"/api/v1/playlists/{pid}", json={"name": "Night", "description": ""}
    )
    assert renamed.json()["name"] == "Night"
    assert renamed.json()["description"] is None
    listing = await get(client, "/playlists")
    assert [p["name"] for p in listing["playlists"]] == ["Night"]
    suggestions = await get(client, f"/playlists/{pid}/suggestions", limit=3)
    assert suggestions["recommendations"]
    assert not {r["track_id"] for r in suggestions["recommendations"]} & set(order)
    assert (await client.delete(f"/api/v1/playlists/{pid}")).status_code == 204
    assert (await client.get(f"/api/v1/playlists/{pid}")).status_code == 404


async def test_playlists_are_private(client: AsyncClient, world: World) -> None:
    await create_user(client)
    created = await client.post("/api/v1/playlists", json={"name": "Mine"})
    pid = created.json()["id"]
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await create_user(other)
        assert (await other.get(f"/api/v1/playlists/{pid}")).status_code == 404
        assert (await other.delete(f"/api/v1/playlists/{pid}")).status_code == 404
        assert (await other.get("/api/v1/playlists")).json()["playlists"] == []
    assert (await client.get(f"/api/v1/playlists/{pid}")).status_code == 200


async def test_generated_playlist_regenerates_with_fresh_tracks(
    client: AsyncClient, world: World
) -> None:
    await create_user(client)
    created = await client.post(
        "/api/v1/playlists",
        json={
            "name": "Rock radio",
            "generator": {"collection": "genre", "genre": "rock", "size": 5},
        },
    )
    assert created.status_code == 201, created.text
    playlist = created.json()
    assert playlist["kind"] == "generated"
    assert playlist["collection"] == "genre"
    first = {t["id"] for t in playlist["tracks"]}
    assert first
    again = await client.post(f"/api/v1/playlists/{playlist['id']}/regenerate")
    assert again.status_code == 200, again.text
    assert not {t["id"] for t in again.json()["tracks"]} & first
    manual = await client.post("/api/v1/playlists", json={"name": "Hand made"})
    refused = await client.post(f"/api/v1/playlists/{manual.json()['id']}/regenerate")
    assert refused.status_code == 422
    incomplete = await client.post(
        "/api/v1/playlists", json={"name": "x", "generator": {"collection": "mood"}}
    )
    assert incomplete.status_code == 422


async def test_unknown_tracks_cannot_be_added(client: AsyncClient, world: World) -> None:
    await create_user(client)
    response = await client.post(
        "/api/v1/playlists", json={"name": "x", "track_ids": [str(uuid.uuid4())]}
    )
    assert response.status_code == 422


# --- catalogue -------------------------------------------------------------------------------


async def test_artist_search_and_genres(client: AsyncClient, world: World) -> None:
    found = await get(client, "/artists/search", q="radiohed")
    assert found["results"][0]["name"] == "Radiohead"
    assert found["results"][0]["genres"] == ["rock"]
    assert found["results"][0]["track_count"] == 3
    genres = await get(client, "/genres", limit=10)
    assert {g["name"] for g in genres["genres"]} == {"rock", "pop", "electronic", "dream pop"}
    assert genres["genres"][0] == {"name": "rock", "tracks": 8}


def test_cover_art_urls_follow_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    mbid = "f5093c06-23e3-404f-aeaa-40f72885ee3a"
    assert cover_art_url(mbid) == settings.cover_art_url.format(mbid=mbid)
    assert cover_art_url(None) is None
    monkeypatch.setattr(settings, "cover_art_enabled", False)
    assert cover_art_url(mbid) is None
