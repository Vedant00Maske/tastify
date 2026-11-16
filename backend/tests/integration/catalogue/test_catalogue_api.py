import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import TrackFeatures
from app.domains.catalogue.writer import CatalogueWriter
from tests.integration.catalogue.conftest import register_source
from tests.integration.catalogue.test_writer import fma_track, mb_track

pytestmark = pytest.mark.integration


@pytest.fixture
async def halo_id(session: AsyncSession) -> uuid.UUID:
    mb = CatalogueWriter(session, await register_source(session, "musicbrainz"))
    await mb.ensure_genre("pop")
    created = await mb.upsert_track(mb_track())
    fma = CatalogueWriter(session, await register_source(session, "fma"))
    await fma.upsert_track(fma_track())
    await session.commit()
    return created.track_id


@pytest.mark.parametrize(
    ("provider", "external_id"),
    [("musicbrainz", "mb-rec-1"), ("isrc", "ussm10804556"), ("fma", "fma-1")],
)
async def test_any_provider_identifier_returns_the_same_unified_track(
    client: AsyncClient, halo_id: uuid.UUID, provider: str, external_id: str
) -> None:
    response = await client.get(
        "/api/v1/tracks/lookup", params={"provider": provider, "external_id": external_id}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(halo_id)
    assert body["title"] == "Halo"
    assert body["artist"] == "Beyoncé"
    assert {(i["provider"], i["external_id"]) for i in body["external_ids"]} == {
        ("musicbrainz", "mb-rec-1"),
        ("isrc", "USSM10804556"),
        ("fma", "fma-1"),
    }
    assert {s["key"] for s in body["sources"]} == {"musicbrainz", "fma"}


async def test_track_detail_includes_album_and_credits(
    client: AsyncClient, halo_id: uuid.UUID
) -> None:
    body = (await client.get(f"/api/v1/tracks/{halo_id}")).json()

    assert body["album"]["title"] == "I Am... Sasha Fierce"
    assert body["release_year"] == 2008
    assert [c["name"] for c in body["credits"]] == ["Beyoncé"]


async def test_search_finds_tracks_by_artist_and_title(
    client: AsyncClient, halo_id: uuid.UUID
) -> None:
    response = await client.get("/api/v1/tracks/search", params={"q": "beyonce halo"})

    assert response.status_code == 200
    assert [r["id"] for r in response.json()["results"]] == [str(halo_id)]


async def test_artist_detail_counts_tracks(client: AsyncClient, halo_id: uuid.UUID) -> None:
    track = (await client.get(f"/api/v1/tracks/{halo_id}")).json()

    body = (await client.get(f"/api/v1/artists/{track['credits'][0]['artist_id']}")).json()

    assert body["name"] == "Beyoncé"
    assert body["track_count"] == 1
    assert ("musicbrainz", "mb-artist-1") in {
        (i["provider"], i["external_id"]) for i in body["external_ids"]
    }


async def test_unknown_identifiers_return_404(client: AsyncClient, halo_id: uuid.UUID) -> None:
    lookup = await client.get(
        "/api/v1/tracks/lookup", params={"provider": "spotify", "external_id": "nope"}
    )
    detail = await client.get(f"/api/v1/tracks/{uuid.uuid4()}")

    assert lookup.status_code == 404
    assert detail.status_code == 404


async def test_search_rejects_too_short_queries(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/tracks/search", params={"q": "a"})).status_code == 422


async def test_track_lists_every_contributing_source(
    client: AsyncClient, session: AsyncSession, halo_id: uuid.UUID
) -> None:
    features_source = await register_source(session, "acousticbrainz")
    session.add(
        TrackFeatures(
            track_id=halo_id,
            feature_source="acousticbrainz",
            feature_version="v1",
            tempo=120.0,
            source_id=features_source,
        )
    )
    await session.commit()

    body = (await client.get(f"/api/v1/tracks/{halo_id}")).json()

    assert {s["key"] for s in body["sources"]} == {"musicbrainz", "fma", "acousticbrainz"}
    assert body["features"][0]["tempo"] == 120.0
