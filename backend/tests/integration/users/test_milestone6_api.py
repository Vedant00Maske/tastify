"""Milestone 6: prompt playlists, recommendation logs, experiments and session context, on the
Milestone 3 test world."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.recommendations import logging_service
from app.domains.recommendations.logging_models import RecommendationLog, RecommendationRequest
from app.domains.users.models import UserInteraction
from tests.integration.users.test_personalization_api import (
    World,
    create_user,
    rock_fan,
    world,
)

pytestmark = pytest.mark.integration

__all__ = ["world"]


async def custom(client: AsyncClient, prompt: str, **extra: Any) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/recommendations/custom", json={"prompt": prompt, "limit": 10, **extra}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture(autouse=True)
def _no_cached_experiments() -> None:
    logging_service.forget_experiments()


# --- prompt playlists --------------------------------------------------------------------------


async def test_prompt_playlist_by_genre(client: AsyncClient, world: World) -> None:
    body = await custom(client, "some dream pop please")
    assert body["strategy"] == "custom"
    assert body["interpretation"]["genres"] == ["dream pop"]
    assert body["interpretation"]["summary"] == "dream pop"
    titles = {r["title"] for r in body["recommendations"]}
    assert titles == {"Apocalypse", "Sunsetz"}
    assert all("dream pop (fit" in r["reason"] for r in body["recommendations"])
    assert body["personalized"] is False


async def test_prompt_playlist_by_artist_with_exclusions(client: AsyncClient, world: World) -> None:
    body = await custom(client, "songs like Radiohead, no electronic")
    interpretation = body["interpretation"]
    assert [a["name"] for a in interpretation["artists"]] == ["Radiohead"]
    assert interpretation["excluded_genres"] == ["electronic"]
    artists = {world.artist_of[r["title"]] for r in body["recommendations"]}
    assert "Radiohead" in artists
    assert "DJ" not in artists
    radiohead = [r for r in body["recommendations"] if world.artist_of[r["title"]] == "Radiohead"]
    assert all(r["reason"].startswith("By Radiohead, as you asked") for r in radiohead)


async def test_unmatched_prompt_is_explained(client: AsyncClient, world: World) -> None:
    response = await client.post(
        "/api/v1/recommendations/custom", json={"prompt": "glorbic snarfwave"}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "prompt_not_understood"
    assert detail["ignored"] == ["glorbic", "snarfwave"]


async def test_signed_in_prompt_is_personal_and_logged(
    client: AsyncClient, world: World, session: AsyncSession
) -> None:
    await rock_fan(client, world)  # played Creep, Karma Police, Do I Wanna Know
    body = await custom(client, "rock")
    assert body["personalized"] is True
    titles = {r["title"] for r in body["recommendations"]}
    assert not titles & {"Creep", "Karma Police", "Do I Wanna Know"}  # heard tracks left out
    again = await custom(client, "rock", exclude_previously_heard=False)
    assert {"Creep", "Karma Police"} & {r["title"] for r in again["recommendations"]}
    logged = (
        await session.scalars(
            select(RecommendationRequest).where(RecommendationRequest.category == "custom")
        )
    ).all()
    assert len(logged) == 2
    assert logged[0].context["summary"] == "rock"


async def test_prompt_playlists_can_be_saved_and_regenerated(
    client: AsyncClient, world: World
) -> None:
    await create_user(client)
    created = await client.post(
        "/api/v1/playlists",
        json={"name": "Dreamy", "generator": {"collection": "custom", "prompt": "dream pop"}},
    )
    assert created.status_code == 201, created.text
    playlist = created.json()
    assert playlist["collection"] == "custom"
    assert {t["title"] for t in playlist["tracks"]} == {"Apocalypse", "Sunsetz"}
    missing = await client.post(
        "/api/v1/playlists", json={"name": "x", "generator": {"collection": "custom"}}
    )
    assert missing.status_code == 422


# --- logs, feedback attribution and experiments -----------------------------------------------


async def test_for_you_is_logged_and_feedback_attributed(
    client: AsyncClient, world: World, session: AsyncSession
) -> None:
    await rock_fan(client, world)
    mix = (await client.get("/api/v1/recommendations/for-you", params={"limit": 5})).json()
    request = await session.get(RecommendationRequest, uuid.UUID(mix["request_id"]))
    assert request is not None
    assert (request.category, request.items) == ("for_you", len(mix["recommendations"]))
    assert request.latency_ms is not None
    items = await session.scalar(
        select(func.count())
        .select_from(RecommendationLog)
        .where(RecommendationLog.request_id == request.id)
    )
    assert items == len(mix["recommendations"])

    first = mix["recommendations"][0]["track_id"]
    await client.post(
        "/api/v1/interactions",
        json={
            "events": [{"track_id": first, "event_type": "like", "request_id": mix["request_id"]}]
        },
    )
    liked = (
        await session.scalars(select(UserInteraction).where(UserInteraction.event_type == "like"))
    ).all()
    assert [str(e.request_id) for e in liked if str(e.track_id) == first] == [mix["request_id"]]


async def test_experiment_assigns_variants_and_reports_outcomes(
    client: AsyncClient, world: World, session: AsyncSession
) -> None:
    await logging_service.save_experiment(
        session,
        "context-ranking",
        "session nudge on and off",
        "for_you",
        [
            {"name": "control", "weight": 1, "params": {"session_weight": 0}},
            {"name": "session", "weight": 1, "params": {"session_weight": 0.1}},
        ],
    )
    await logging_service.set_status(session, "context-ranking", "running")

    seen: dict[str, str] = {}
    for _ in range(6):
        await rock_fan(client, world)
        mix = (await client.get("/api/v1/recommendations/for-you", params={"limit": 5})).json()
        assert mix["experiment"] == "context-ranking"
        assert mix["context"]["session_weight"] == (0.0 if mix["variant"] == "control" else 0.1)
        seen[mix["request_id"]] = mix["variant"]
        # The same user always gets the same variant.
        repeat = (await client.get("/api/v1/recommendations/for-you")).json()
        assert repeat["variant"] == mix["variant"]
        await client.post(
            "/api/v1/interactions",
            json={
                "events": [
                    {
                        "track_id": mix["recommendations"][0]["track_id"],
                        "event_type": "save",
                        "request_id": mix["request_id"],
                    }
                ]
            },
        )

    report = await logging_service.report(session, "context-ranking")
    variants = {v["name"]: v for v in report["variants"]}
    assert sum(v["positive"] for v in variants.values()) == 6
    assert sum(v["users"] for v in variants.values()) == 6
    assert report["comparisons"] == [] or report["comparisons"][0]["verdict"] == "not enough data"

    await logging_service.set_status(session, "context-ranking", "stopped")
    after = (await client.get("/api/v1/recommendations/for-you")).json()
    assert after["experiment"] is None


async def test_session_listening_nudges_for_you(
    client: AsyncClient, world: World, session: AsyncSession
) -> None:
    await create_user(client)
    now = datetime.now(UTC)

    def events(titles: list[str], kind: str, minutes_ago: int) -> list[dict[str, Any]]:
        return [
            {
                "track_id": str(world.tracks[title]),
                "event_type": kind,
                "occurred_at": (now - timedelta(minutes=minutes_ago + i)).isoformat(),
            }
            for i, title in enumerate(titles)
        ]

    # Rock history from earlier today, then a dream pop session in the last few minutes.
    history = events(["Creep", "Karma Police", "Do I Wanna Know", "505"] * 3, "play", 180)
    current = events(["Apocalypse", "Sunsetz"], "save", 2)
    response = await client.post("/api/v1/interactions", json={"events": history + current})
    assert response.status_code == 201, response.text
    mix = (
        await client.get(
            "/api/v1/recommendations/for-you",
            params={"limit": 10},
            headers={"X-Timezone": "Not/AZone"},  # ignored, never an error
        )
    ).json()
    assert mix["context"]["session_events"] == 2
    assert mix["context"]["session_weight"] == 0.1
    assert "daypart" not in mix["context"]  # time of day is off by default
