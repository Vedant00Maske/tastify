"""Personalized response cache (Milestone 7, ADR-020): served from cache only while nothing the
ranking depends on has changed; every serve gets its own request id."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_client
from app.domains.recommendations.logging_models import RecommendationRequest
from app.domains.recommendations.response_cache import PREFIX
from tests.integration.users.test_personalization_api import World, create_user, plays, world

pytestmark = pytest.mark.integration

__all__ = ["world"]


async def cached_keys() -> list[str]:
    return [key async for key in redis_client.scan_iter(f"{PREFIX}:*")]


async def for_you(client: AsyncClient, **params: int | str) -> dict[str, object]:
    response = await client.get("/api/v1/recommendations/for-you", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_repeat_requests_are_served_from_cache_with_fresh_ids(
    client: AsyncClient, session: AsyncSession, world: World
) -> None:
    await create_user(client)
    await client.post(
        "/api/v1/interactions", json={"events": list(plays(world, ["Creep", "Karma Police"]))}
    )
    first = await for_you(client)
    assert len(await cached_keys()) == 1
    second = await for_you(client)
    assert second["recommendations"] == first["recommendations"]
    assert second["request_id"] != first["request_id"]
    # Both serves are logged under their own ids, so feedback attribution still works.
    logged = await session.scalar(select(func.count()).select_from(RecommendationRequest))
    assert logged == 2
    other_limit = await for_you(client, limit=5)
    assert len(other_limit["recommendations"]) == 5  # type: ignore[arg-type]
    assert len(await cached_keys()) == 2


async def test_feedback_and_preferences_change_the_key(client: AsyncClient, world: World) -> None:
    await create_user(client)
    await client.post(
        "/api/v1/interactions", json={"events": list(plays(world, ["Creep", "Karma Police"]))}
    )
    first = await for_you(client)
    track = first["recommendations"][0]["track_id"]  # type: ignore[index]
    dislike = await client.post(
        "/api/v1/interactions",
        json={"events": [{"track_id": track, "event_type": "dislike"}]},
    )
    assert dislike.status_code == 201
    after_feedback = await for_you(client)
    ids = [item["track_id"] for item in after_feedback["recommendations"]]  # type: ignore[attr-defined]
    assert track not in ids  # recomputed, not the cached mix
    keys = await cached_keys()
    assert len(keys) == 2

    preferences = await client.put(
        "/api/v1/users/me/preferences", json={"exploration_mode": "explorer"}
    )
    assert preferences.status_code == 200, preferences.text
    await for_you(client)
    assert len(await cached_keys()) == 3


async def test_users_never_share_entries(client: AsyncClient, world: World) -> None:
    first_user = await create_user(client)
    await for_you(client)
    from httpx import ASGITransport

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        second_user = await create_user(other)
        await other.get("/api/v1/recommendations/for-you")
    keys = await cached_keys()
    assert {key.split(":")[3] for key in keys} <= {first_user, second_user}
    assert all(uuid.UUID(key.split(":")[3]) for key in keys)


async def test_feedback_schedules_a_precompute_that_the_next_home_page_uses(
    client: AsyncClient, session: AsyncSession, world: World
) -> None:
    from app.core.redis import redis_client
    from app.domains.recommendations import precompute
    from app.main import app

    scheduled: list[tuple[uuid.UUID, str | None]] = []

    class Recorder(precompute.PrecomputeScheduler):
        async def schedule(self, user_id: uuid.UUID, zone: str | None) -> None:
            scheduled.append((user_id, zone))

    app.dependency_overrides[precompute.get_precompute_scheduler] = Recorder
    user_id = uuid.UUID(await create_user(client))
    recorded = await client.post(
        "/api/v1/interactions",
        json={"events": list(plays(world, ["Creep", "Karma Police"]))},
        headers={"X-Timezone": "Europe/Berlin"},
    )
    assert recorded.status_code == 201
    assert scheduled == [(user_id, "Europe/Berlin")]

    # What the worker runs: both home-page mixes for the new state, then nothing to do.
    assert await precompute.warm(session, redis_client, user_id, "Europe/Berlin") == [
        "for_you",
        "hidden_gems",
    ]
    assert await precompute.warm(session, redis_client, user_id, "Europe/Berlin") == []
    headers = {"X-Timezone": "Europe/Berlin"}
    home = await client.get("/api/v1/recommendations/for-you", headers=headers)
    assert home.headers["x-cache"] == "hit"
    gems = await client.get("/api/v1/recommendations/hidden-gems", headers=headers)
    assert gems.headers["x-cache"] == "hit"
    other_zone = await client.get("/api/v1/recommendations/for-you")
    assert other_zone.headers["x-cache"] == "miss"
