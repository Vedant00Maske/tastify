import json

import httpx
import pytest

from app.domains.integrations.clients.base import ProviderError, RateLimitedClient
from app.domains.integrations.clients.metabrainz import ListenBrainzClient, MusicBrainzClient

USER_AGENT = "TASTIFY-test/0.0 ( https://example.org )"


class FakeClock:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def transport(responses: list[httpx.Response], seen: list[httpx.Request]) -> httpx.MockTransport:
    queue = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(queue)

    return httpx.MockTransport(handler)


async def test_requests_identify_the_application() -> None:
    seen: list[httpx.Request] = []
    async with RateLimitedClient(
        "https://api.example/",
        USER_AGENT,
        transport=transport([httpx.Response(200, json={"ok": True})], seen),
        sleep=FakeClock().sleep,
    ) as client:
        assert await client.request_json("GET", "thing") == {"ok": True}

    assert seen[0].headers["User-Agent"] == USER_AGENT


async def test_consecutive_requests_are_spaced_by_the_minimum_interval() -> None:
    clock = FakeClock()
    async with RateLimitedClient(
        "https://api.example/",
        USER_AGENT,
        min_interval=1.0,
        transport=transport([httpx.Response(200, json={})] * 3, []),
        sleep=clock.sleep,
    ) as client:
        for _ in range(3):
            await client.request_json("GET", "thing")

    assert len(clock.sleeps) == 2
    assert all(0.9 < s <= 1.0 for s in clock.sleeps)


async def test_rate_limited_responses_are_retried_after_the_advertised_delay() -> None:
    clock = FakeClock()
    responses = [
        httpx.Response(429, headers={"X-RateLimit-Reset-In": "7"}),
        httpx.Response(503, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"done": 1}),
    ]
    async with RateLimitedClient(
        "https://api.example/",
        USER_AGENT,
        min_interval=0,
        transport=transport(responses, []),
        sleep=clock.sleep,
    ) as client:
        assert await client.request_json("GET", "thing") == {"done": 1}

    assert 7.0 in clock.sleeps
    assert 3.0 in clock.sleeps


async def test_client_errors_are_not_retried() -> None:
    seen: list[httpx.Request] = []
    async with RateLimitedClient(
        "https://api.example/",
        USER_AGENT,
        min_interval=0,
        transport=transport([httpx.Response(404, text="nope")], seen),
        sleep=FakeClock().sleep,
    ) as client:
        with pytest.raises(ProviderError, match="404"):
            await client.request_json("GET", "missing")

    assert len(seen) == 1


async def test_musicbrainz_genres_are_paged_until_complete() -> None:
    seen: list[httpx.Request] = []
    pages = [
        httpx.Response(
            200,
            json={
                "genre-count": 3,
                "genres": [{"id": "g1", "name": "pop"}, {"id": "g2", "name": "rock"}],
            },
        ),
        httpx.Response(200, json={"genre-count": 3, "genres": [{"id": "g3", "name": "jazz"}]}),
    ]
    async with MusicBrainzClient(
        USER_AGENT, transport=transport(pages, seen), sleep=FakeClock().sleep
    ) as mb:
        genres = await mb.all_genres()

    assert [g["name"] for g in genres] == ["pop", "rock", "jazz"]
    assert [r.url.params["offset"] for r in seen] == ["0", "2"]


async def test_listenbrainz_metadata_is_requested_in_one_batch() -> None:
    seen: list[httpx.Request] = []
    body = {"rec-1": {"recording": {"name": "A"}}, "rec-2": {"recording": {"name": "B"}}}
    async with ListenBrainzClient(
        USER_AGENT,
        transport=transport([httpx.Response(200, json=body)], seen),
        sleep=FakeClock().sleep,
    ) as lb:
        result = await lb.recording_metadata(["rec-1", "rec-2"])

    assert set(result) == {"rec-1", "rec-2"}
    assert seen[0].method == "POST"
    assert json.loads(seen[0].content) == {
        "recording_mbids": ["rec-1", "rec-2"],
        "inc": "artist tag release",
    }
