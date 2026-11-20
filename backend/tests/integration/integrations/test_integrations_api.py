"""Milestone 5: provider connections, history import, playlist export and failure isolation,
against in-memory provider servers (fakes.py) and the Milestone 3 test world."""

import base64
import os
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.integrations import get_providers
from app.core.config import get_settings
from app.domains.catalogue.models import Track, TrackExternalId
from app.domains.integrations.models import ProviderConnection
from app.domains.integrations.providers.listenbrainz import ListenBrainzProvider
from app.domains.integrations.providers.musicbrainz import MusicBrainzProvider
from app.domains.integrations.providers.spotify import SpotifyProvider
from app.domains.integrations.providers.youtube import YouTubeProvider
from app.domains.users.models import UserInteraction
from tests.integration.catalogue.conftest import register_source
from tests.integration.integrations.fakes import (
    FakeListenBrainz,
    FakeMusicBrainz,
    FakeSpotify,
    FakeYouTube,
)
from tests.integration.users.test_personalization_api import World, create_user, world

pytestmark = pytest.mark.integration

__all__ = ["world"]

CREEP_MBID = "8f3471b5-7e6a-48da-86a9-c1c07a0f47ae"
POLICE_ISRC = "GBAYE9700001"
DOIWANNA_MBID = "11111111-2222-4333-8444-555555555555"


class Fakes:
    def __init__(self) -> None:
        self.lb = FakeListenBrainz()
        self.spotify = FakeSpotify()
        self.youtube = FakeYouTube()
        self.mb = FakeMusicBrainz()

    def providers(self) -> dict[str, Any]:
        return {
            "listenbrainz": ListenBrainzProvider(
                httpx.MockTransport(self.lb.handler), min_interval=0
            ),
            "spotify": SpotifyProvider(httpx.MockTransport(self.spotify.handler)),
            "youtube": YouTubeProvider(httpx.MockTransport(self.youtube.handler)),
            "musicbrainz": MusicBrainzProvider(
                httpx.MockTransport(self.mb.handler), min_interval=0
            ),
        }


@pytest.fixture
async def fakes(monkeypatch: pytest.MonkeyPatch, session: AsyncSession, world: World) -> Fakes:
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(
        settings, "integrations_token_key", base64.b64encode(os.urandom(32)).decode()
    )
    monkeypatch.setattr(settings, "spotify_client_id", "spotify-client")
    monkeypatch.setattr(settings, "spotify_client_secret", None)
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "google_client_secret", "google-secret")
    monkeypatch.setattr(settings, "app_public_url", "http://127.0.0.1:3000")
    monkeypatch.setattr(settings, "youtube_daily_quota", 10_000)

    # Evidence to match against: an MBID for Creep and Do I Wanna Know, an ISRC for Karma
    # Police, and the catalogue's real artist-and-title key for 505.
    source = await register_source(session, "musicbrainz")
    for title, mbid in (("Creep", CREEP_MBID), ("Do I Wanna Know", DOIWANNA_MBID)):
        session.add(
            TrackExternalId(
                track_id=world.tracks[title],
                provider="musicbrainz",
                external_id=mbid,
                match_method="exact",
                confidence=1.0,
                source_id=source,
            )
        )
    await session.execute(
        update(Track).where(Track.id == world.tracks["Karma Police"]).values(isrc=POLICE_ISRC)
    )
    await session.execute(
        update(Track).where(Track.id == world.tracks["505"]).values(matching_key="arctic|505")
    )
    await session.commit()

    instance = Fakes()
    app.dependency_overrides[get_providers] = instance.providers
    return instance


async def connect_listenbrainz(client: AsyncClient, fakes: Fakes) -> None:
    response = await client.post(
        "/api/v1/integrations/listenbrainz/connect", json={"token": fakes.lb.token}
    )
    assert response.status_code == 200, response.text


def provider(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in body["providers"] if p["provider"] == name)


# --- listing and connecting --------------------------------------------------------------------


async def test_providers_are_listed_with_capabilities(client: AsyncClient, fakes: Fakes) -> None:
    assert (await client.get("/api/v1/integrations")).status_code == 401
    await create_user(client)
    body = (await client.get("/api/v1/integrations")).json()
    assert body["tokens_configured"] is True
    assert [p["provider"] for p in body["providers"]] == [
        "listenbrainz",
        "spotify",
        "youtube",
        "musicbrainz",
    ]
    lb = provider(body, "listenbrainz")
    assert lb["auth"] == "token"
    assert lb["capabilities"] == ["export_playlist", "import_history"]
    assert lb["connection"] is None
    assert provider(body, "youtube")["max_export_tracks"] == 50


async def test_unconfigured_server_cannot_connect(
    client: AsyncClient, fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_user(client)
    monkeypatch.setattr(get_settings(), "integrations_token_key", None)
    monkeypatch.setattr(get_settings(), "spotify_client_id", None)
    body = (await client.get("/api/v1/integrations")).json()
    assert body["tokens_configured"] is False
    assert provider(body, "spotify")["available"] is False
    response = await client.post(
        "/api/v1/integrations/listenbrainz/connect", json={"token": fakes.lb.token}
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "not_configured"
    assert fakes.lb.calls == []  # the provider is not contacted without a key
    assert (await client.get("/api/v1/integrations/spotify/authorize")).status_code == 503


async def test_listenbrainz_token_is_validated_and_stored_encrypted(
    client: AsyncClient, fakes: Fakes, session: AsyncSession
) -> None:
    await create_user(client)
    bad = await client.post(
        "/api/v1/integrations/listenbrainz/connect", json={"token": "not-the-token"}
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_credentials"
    await connect_listenbrainz(client, fakes)
    body = (await client.get("/api/v1/integrations")).json()
    connection = provider(body, "listenbrainz")["connection"]
    assert connection["status"] == "active"
    assert connection["external_name"] == fakes.lb.user
    stored = (await session.scalars(select(ProviderConnection))).one()
    assert stored.access_token.startswith("v1:")
    assert fakes.lb.token not in stored.access_token
    assert fakes.lb.token not in (await client.get("/api/v1/users/me/export")).text


# --- importing ---------------------------------------------------------------------------------


async def test_listenbrainz_import_matches_and_is_incremental(
    client: AsyncClient, fakes: Fakes, session: AsyncSession, world: World
) -> None:
    await create_user(client)
    await connect_listenbrainz(client, fakes)
    fakes.lb.listen(1_700_000_300, "Radiohead", "Creep", mbid=CREEP_MBID)
    fakes.lb.listen(1_700_000_200, "Radiohead", "Karma Police", isrc=POLICE_ISRC)
    fakes.lb.listen(1_700_000_100, "Arctic", "505")
    fakes.lb.listen(1_700_000_000, "Nobody", "Not In The Catalogue")

    refused = await client.post("/api/v1/integrations/listenbrainz/import", json={"consent": False})
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "consent_required"

    first = await client.post("/api/v1/integrations/listenbrainz/import", json={"consent": True})
    assert first.status_code == 200, first.text
    assert {k: first.json()[k] for k in ("status", "fetched", "matched", "imported")} == {
        "status": "completed",
        "fetched": 4,
        "matched": 3,
        "imported": 3,
    }
    events = (
        await session.scalars(
            select(UserInteraction).where(UserInteraction.source == "listenbrainz")
        )
    ).all()
    assert {e.track_id for e in events} == {
        world.tracks["Creep"],
        world.tracks["Karma Police"],
        world.tracks["505"],
    }
    assert all(e.event_type == "play" for e in events)

    # Incremental: only listens newer than the last import are fetched again.
    fakes.lb.listen(1_700_000_400, "Radiohead", "Creep", mbid=CREEP_MBID)
    second = (
        await client.post("/api/v1/integrations/listenbrainz/import", json={"consent": True})
    ).json()
    assert (second["fetched"], second["imported"]) == (1, 1)
    # The listens feed the taste profile like any other event.
    profile = (await client.get("/api/v1/users/me/taste-profile")).json()
    assert profile["interaction_count"] == 4


async def test_spotify_oauth_import_and_token_refresh(
    client: AsyncClient, fakes: Fakes, session: AsyncSession, world: World
) -> None:
    await create_user(client)
    authorize = (await client.get("/api/v1/integrations/spotify/authorize")).json()["url"]
    query = parse_qs(urlparse(authorize).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://127.0.0.1:3000/api/v1/integrations/spotify/callback"]
    state = query["state"][0]

    callback = await client.get(
        "/api/v1/integrations/spotify/callback", params={"code": fakes.spotify.code, "state": state}
    )
    assert callback.status_code == 303
    assert "status=connected" in callback.headers["location"]
    assert len(fakes.spotify.verifiers) == 1  # PKCE verifier sent to the token endpoint
    replay = await client.get(
        "/api/v1/integrations/spotify/callback", params={"code": fakes.spotify.code, "state": state}
    )
    assert "reason=invalid_state" in replay.headers["location"]

    fakes.spotify.saved = [
        {
            "added_at": "2026-11-01T10:00:00Z",
            "track": {
                "id": "sp-police",
                "name": "Karma Police",
                "artists": [{"name": "Radiohead"}],
                "external_ids": {"isrc": POLICE_ISRC},
            },
        }
    ]
    fakes.spotify.recent = [
        {
            "played_at": "2026-11-02T10:00:00Z",
            "track": {"id": "sp-505", "name": "505", "artists": [{"name": "Arctic"}]},
        }
    ]
    # The stored access token has been revoked on Spotify's side: SONIQUEO refreshes once.
    fakes.spotify.access = "rotated-elsewhere"
    imported = await client.post("/api/v1/integrations/spotify/import", json={"consent": True})
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 2
    assert "token refresh_token" in fakes.spotify.calls
    kinds = {
        (e.track_id, e.event_type)
        for e in (
            await session.scalars(
                select(UserInteraction).where(UserInteraction.source == "spotify")
            )
        ).all()
    }
    assert kinds == {(world.tracks["Karma Police"], "like"), (world.tracks["505"], "play")}

    # When the refresh token is no longer accepted either, the user is asked to reconnect.
    fakes.spotify.access = "rotated-again"
    fakes.spotify.refresh_fails = True
    failed = await client.post("/api/v1/integrations/spotify/import", json={"consent": True})
    assert failed.status_code == 409
    assert failed.json()["detail"]["code"] == "reauth_required"
    body = (await client.get("/api/v1/integrations")).json()
    assert provider(body, "spotify")["connection"]["status"] == "reauth_required"


# --- exporting ---------------------------------------------------------------------------------


async def make_playlist(client: AsyncClient, world: World, titles: list[str]) -> str:
    response = await client.post(
        "/api/v1/playlists",
        json={"name": "Night drive", "track_ids": [str(world.tracks[t]) for t in titles]},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_listenbrainz_export_is_retry_safe(
    client: AsyncClient, fakes: Fakes, world: World
) -> None:
    await create_user(client)
    await connect_listenbrainz(client, fakes)
    playlist = await make_playlist(client, world, ["Creep", "Do I Wanna Know", "Karma Police"])

    fakes.lb.fail_add = 10  # every retry of the first add fails
    failed = await client.post(
        f"/api/v1/playlists/{playlist}/export", json={"provider": "listenbrainz"}
    )
    assert failed.status_code == 502
    assert len(fakes.lb.playlists) == 1  # created once, remembered before filling

    fakes.lb.fail_add = 0
    done = await client.post(
        f"/api/v1/playlists/{playlist}/export", json={"provider": "listenbrainz"}
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["status"], body["exported"], body["unmatched"], body["attempts"]) == (
        "completed",
        2,
        1,  # Karma Police has no recording MBID in the catalogue
        2,
    )
    assert body["external_url"].startswith("https://listenbrainz.org/playlist/")
    (remote,) = fakes.lb.playlists
    assert fakes.lb.items(remote) == [CREEP_MBID, DOIWANNA_MBID]

    # Exporting again replaces the items instead of duplicating them or the playlist.
    again = await client.post(
        f"/api/v1/playlists/{playlist}/export", json={"provider": "listenbrainz"}
    )
    assert again.status_code == 200
    assert len(fakes.lb.playlists) == 1
    assert fakes.lb.items(remote) == [CREEP_MBID, DOIWANNA_MBID]

    exports = (await client.get(f"/api/v1/playlists/{playlist}/exports")).json()["exports"]
    assert [(e["provider"], e["status"]) for e in exports] == [("listenbrainz", "completed")]


async def test_lost_remote_playlist_is_found_again_by_its_marker(
    client: AsyncClient, fakes: Fakes, world: World, session: AsyncSession
) -> None:
    await create_user(client)
    await connect_listenbrainz(client, fakes)
    playlist = await make_playlist(client, world, ["Creep"])
    await client.post(f"/api/v1/playlists/{playlist}/export", json={"provider": "listenbrainz"})
    # SONIQUEO lost the remote id (say the process died before saving it).
    await session.execute(text("UPDATE playlist_exports SET external_playlist_id = NULL"))
    await session.commit()
    again = await client.post(
        f"/api/v1/playlists/{playlist}/export", json={"provider": "listenbrainz"}
    )
    assert again.status_code == 200
    assert len(fakes.lb.playlists) == 1  # found by the marker in its description


async def test_spotify_export_by_isrc(client: AsyncClient, fakes: Fakes, world: World) -> None:
    await create_user(client)
    state = parse_qs(
        urlparse((await client.get("/api/v1/integrations/spotify/authorize")).json()["url"]).query
    )["state"][0]
    await client.get(
        "/api/v1/integrations/spotify/callback", params={"code": fakes.spotify.code, "state": state}
    )
    fakes.spotify.catalogue = {POLICE_ISRC: "sp-police"}
    playlist = await make_playlist(client, world, ["Karma Police", "Creep"])
    for _ in range(2):
        response = await client.post(
            f"/api/v1/playlists/{playlist}/export", json={"provider": "spotify"}
        )
        assert response.status_code == 200, response.text
    (remote,) = fakes.spotify.playlists.values()
    assert remote["items"] == ["spotify:track:sp-police"]
    assert response.json()["unmatched"] == 1
    # Searched once per track (ISRC for Karma Police, title and artist for Creep); the second
    # export used the cached ids, the miss included.
    assert sum(1 for c in fakes.spotify.calls if c == "GET search") == 2


async def test_youtube_export_respects_the_daily_quota(
    client: AsyncClient, fakes: Fakes, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_user(client)
    state = parse_qs(
        urlparse((await client.get("/api/v1/integrations/youtube/authorize")).json()["url"]).query
    )["state"][0]
    connected = await client.get(
        "/api/v1/integrations/youtube/callback", params={"code": fakes.youtube.code, "state": state}
    )
    assert "status=connected" in connected.headers["location"]
    fakes.youtube.videos = {"Radiohead Creep": "vid-creep", "Arctic 505": "vid-505"}
    playlist = await make_playlist(client, world, ["Creep", "505"])

    monkeypatch.setattr(get_settings(), "youtube_daily_quota", 250)
    refused = await client.post(
        f"/api/v1/playlists/{playlist}/export", json={"provider": "youtube"}
    )
    assert refused.status_code == 429
    assert refused.json()["detail"]["code"] == "quota_exceeded"
    assert not any(c.endswith("search") for c in fakes.youtube.calls)  # stopped before spending

    monkeypatch.setattr(get_settings(), "youtube_daily_quota", 10_000)
    done = await client.post(f"/api/v1/playlists/{playlist}/export", json={"provider": "youtube"})
    assert done.status_code == 200, done.text
    (remote,) = fakes.youtube.playlists.values()
    assert [video for _, video in remote["items"]] == ["vid-creep", "vid-505"]

    writes_before = sum(1 for c in fakes.youtube.calls if c.startswith(("POST", "DELETE")))
    again = await client.post(f"/api/v1/playlists/{playlist}/export", json={"provider": "youtube"})
    assert again.status_code == 200
    writes_after = sum(1 for c in fakes.youtube.calls if c.startswith(("POST", "DELETE")))
    assert writes_after == writes_before  # unchanged playlist: nothing inserted or deleted


async def test_exports_require_ownership_and_a_connection(
    client: AsyncClient, fakes: Fakes, world: World
) -> None:
    await create_user(client)
    playlist = await make_playlist(client, world, ["Creep"])
    missing = await client.post(
        f"/api/v1/playlists/{playlist}/export", json={"provider": "listenbrainz"}
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "not_connected"
    unsupported = await client.post(
        f"/api/v1/playlists/{playlist}/export", json={"provider": "musicbrainz"}
    )
    assert unsupported.status_code == 400

    await create_user(client)  # another account
    await connect_listenbrainz(client, fakes)
    foreign = await client.post(
        f"/api/v1/playlists/{playlist}/export", json={"provider": "listenbrainz"}
    )
    assert foreign.status_code == 404


# --- isolation, disconnecting, search -----------------------------------------------------------


async def test_provider_outage_is_isolated(client: AsyncClient, fakes: Fakes) -> None:
    await create_user(client)
    await connect_listenbrainz(client, fakes)
    fakes.lb.down = True
    response = await client.post("/api/v1/integrations/listenbrainz/import", json={"consent": True})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "provider_failed"
    (run,) = (await client.get("/api/v1/integrations/imports")).json()
    assert (run["status"], run["error"]) == ("failed", "ListenBrainz is unavailable right now")
    # Everything else keeps working.
    assert (await client.get("/api/v1/recommendations/for-you")).status_code == 200
    body = (await client.get("/api/v1/integrations")).json()
    assert provider(body, "listenbrainz")["connection"]["status"] == "active"


async def test_disconnect_can_delete_imported_history(
    client: AsyncClient, fakes: Fakes, session: AsyncSession, world: World
) -> None:
    await create_user(client)
    await connect_listenbrainz(client, fakes)
    fakes.lb.listen(1_700_000_300, "Radiohead", "Creep", mbid=CREEP_MBID)
    await client.post("/api/v1/integrations/listenbrainz/import", json={"consent": True})
    await client.post(
        "/api/v1/interactions",
        json={"events": [{"track_id": str(world.tracks["Hit One"]), "event_type": "like"}]},
    )
    response = await client.delete(
        "/api/v1/integrations/listenbrainz", params={"delete_imported": "true"}
    )
    assert response.status_code == 204
    sources = (await session.scalars(select(UserInteraction.source))).all()
    assert sources == ["app"]
    assert (await session.scalars(select(ProviderConnection))).all() == []


async def test_musicbrainz_search_marks_catalogue_tracks(
    client: AsyncClient, fakes: Fakes, world: World
) -> None:
    await create_user(client)
    fakes.mb.recordings = [
        {
            "id": CREEP_MBID,
            "title": "Creep",
            "length": 238000,
            "artist-credit": [{"name": "Radiohead", "joinphrase": ""}],
            "releases": [{"title": "Pablo Honey"}],
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Creep (live)",
            "artist-credit": [{"name": "Radiohead"}],
        },
    ]
    body = (
        await client.get("/api/v1/integrations/musicbrainz/search", params={"q": 'creep "live"'})
    ).json()
    assert [r["track_id"] for r in body["results"]] == [str(world.tracks["Creep"]), None]
    assert body["results"][0]["url"] == f"https://musicbrainz.org/recording/{CREEP_MBID}"
    # User input is escaped: it is searched as words, never as Lucene syntax.
    assert fakes.mb.queries == [
        'recording:"creep \\"live\\""^4 OR '
        '(recording:(creep \\"live\\") AND artist:(creep \\"live\\"))^2'
    ]
