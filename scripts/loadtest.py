"""Load test for the TASTIFY API (Milestone 7; docs/reports/load-test.md).

Simulates signed-in listeners: each virtual user registers, plays and likes some popular tracks
(so recommendations are personal, not cold start), then loops over realistic actions with think
time: opening the home page (its requests in parallel, as the web app does), searching, opening
a track and similar tracks, browsing popular charts and mood mixes, liking a track, and
occasionally describing a playlist in words. Reports p50/p95/p99 latency per endpoint.

Each virtual user sends its own X-Forwarded-For address, as distinct clients behind the reverse
proxy would, so per-client rate limits apply per user (the API must trust the load generator's
address: TRUSTED_PROXIES includes 127.0.0.1 by default).

Usage (from the repository root, with the API running and the catalogue loaded):

    backend/.venv/Scripts/python scripts/loadtest.py --users 20 --duration 120
    backend/.venv/Scripts/python scripts/loadtest.py --base http://127.0.0.1:8000 \
        --users 50 --duration 300 --report docs/reports/load-test-raw.md

Test accounts are deleted at the end (unless --keep).
"""

import argparse
import asyncio
import contextlib
import random
import statistics
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

SEARCH_WORDS = [
    "love", "night", "blue", "radio", "dream", "fire", "heart", "rain", "city", "summer",
    "black", "girl", "home", "light", "time", "dance", "gold", "wild", "moon", "river",
]  # fmt: skip
PROMPTS = [
    "chill 90s hip hop, no metal",
    "upbeat indie rock for a run",
    "melancholic electronic for late nights",
    "hidden gems of dream pop",
    "energetic punk from the 1970s",
]
PASSWORD = "load test password"


@dataclass
class Stats:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, dict[int, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    started: float = 0.0
    finished: float = 0.0

    def record(self, name: str, seconds: float, status: int) -> None:
        self.latencies[name].append(seconds)
        if status >= 400:
            self.errors[name][status] += 1


class VirtualUser:
    def __init__(self, index: int, base: str, stats: Stats, think: float) -> None:
        self.address = f"10.{index // 250}.{index % 250}.{random.randint(1, 250)}"
        self.client = httpx.AsyncClient(
            base_url=f"{base.rstrip('/')}/api/v1",
            headers={"X-Forwarded-For": self.address, "X-Timezone": "Europe/Berlin"},
            timeout=30.0,
        )
        self.stats = stats
        self.think = think
        self.tracks: list[str] = []
        self.moods: list[str] = []

    async def call(
        self, name: str, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            self.stats.record(name, time.perf_counter() - started, 599)
            raise
        cache = response.headers.get("x-cache")
        if (
            cache
        ):  # personalized mixes: report cache hits and computed responses separately
            name = f"{name} ({'cached' if cache == 'hit' else 'computed'})"
        self.stats.record(name, time.perf_counter() - started, response.status_code)
        return response

    async def setup(self) -> None:
        email = f"loadtest-{uuid.uuid4().hex[:12]}@example.com"
        response = await self.call(
            "register",
            "POST",
            "/auth/register",
            json={"email": email, "password": PASSWORD, "accept_terms": True},
        )
        response.raise_for_status()
        popular = await self.call(
            "popular", "GET", "/recommendations/popular", params={"limit": 50}
        )
        items = popular.json().get("recommendations", [])
        self.tracks = [item["track_id"] for item in items]
        moods = await self.call("moods", "GET", "/recommendations/moods")
        self.moods = [m["key"] for m in moods.json().get("moods", []) if "key" in m]
        liked = random.sample(self.tracks, k=min(12, len(self.tracks)))
        events = [{"track_id": t, "event_type": "play"} for t in liked] + [
            {"track_id": t, "event_type": "like"} for t in liked[:6]
        ]
        await self.call(
            "interactions", "POST", "/interactions", json={"events": events}
        )
        await self.call(
            "me.update", "PATCH", "/users/me", json={"onboarding_completed": True}
        )

    async def home(self) -> None:
        await asyncio.gather(
            self.call("me", "GET", "/users/me"),
            self.call(
                "for-you", "GET", "/recommendations/for-you", params={"limit": 25}
            ),
            self.call(
                "hidden-gems",
                "GET",
                "/recommendations/hidden-gems",
                params={"limit": 20},
            ),
            self.call(
                "because-you-listened", "GET", "/recommendations/because-you-listened"
            ),
            self.call("moods", "GET", "/recommendations/moods"),
            self.call("history", "GET", "/interactions/history", params={"limit": 50}),
        )

    async def search(self) -> None:
        word = random.choice(SEARCH_WORDS)
        response = await self.call(
            "search", "GET", "/tracks/search", params={"q": word}
        )
        results = (
            response.json().get("results", []) if response.status_code == 200 else []
        )
        if results:
            await self.track(random.choice(results)["id"])

    async def track(self, track_id: str | None = None) -> None:
        track_id = track_id or random.choice(self.tracks)
        await asyncio.gather(
            self.call("track", "GET", f"/tracks/{track_id}"),
            self.call("similar", "GET", f"/recommendations/similar/{track_id}"),
        )

    async def like(self) -> None:
        track = random.choice(self.tracks)
        event = random.choice(["like", "play", "skip"])
        await self.call(
            "interactions",
            "POST",
            "/interactions",
            json={"events": [{"track_id": track, "event_type": event}]},
        )

    async def mood(self) -> None:
        if self.moods:
            mood = random.choice(self.moods)
            await self.call("mood-mix", "GET", f"/recommendations/mood/{mood}")

    async def popular(self) -> None:
        await self.call(
            "popular", "GET", "/recommendations/popular", params={"limit": 20}
        )

    async def prompt(self) -> None:
        await self.call(
            "custom",
            "POST",
            "/recommendations/custom",
            json={"prompt": random.choice(PROMPTS)},
        )

    async def run(self, until: float) -> None:
        actions = [
            (self.home, 30),
            (self.search, 20),
            (self.track, 15),
            (self.like, 15),
            (self.mood, 8),
            (self.popular, 7),
            (self.prompt, 5),
        ]
        functions, weights = zip(*actions, strict=True)
        while time.monotonic() < until:
            action = random.choices(functions, weights=weights)[0]
            with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
                await action()
            await asyncio.sleep(random.uniform(0.5, 1.5) * self.think)

    async def close(self, keep: bool) -> bool:
        """Delete the test account; False if that failed (the account is left behind)."""
        deleted = True
        if not keep:
            try:
                response = await self.client.request(
                    "DELETE", "/users/me", json={"password": PASSWORD}
                )
                deleted = response.status_code == 204
            except httpx.HTTPError:
                deleted = False
        await self.client.aclose()
        return deleted


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def report(stats: Stats, args: argparse.Namespace) -> str:
    elapsed = stats.finished - stats.started
    total = sum(
        len(v) for k, v in stats.latencies.items() if k not in ("register", "me.update")
    )
    lines = [
        (
            f"Load test: {args.users} virtual users, {args.duration} s measured after "
            f"{args.warmup} s warm-up, think time {args.think} s, against {args.base}"
        ),
        f"Requests: {total} in {elapsed:.0f} s ({total / max(elapsed, 1):.1f} per second)",
        "",
        "| Endpoint | Requests | p50 ms | p95 ms | p99 ms | max ms | Errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name in sorted(stats.latencies):
        values = stats.latencies[name]
        errors = (
            ", ".join(f"{code}x{n}" for code, n in sorted(stats.errors[name].items()))
            or "-"
        )
        lines.append(
            f"| {name} | {len(values)} | {statistics.median(values) * 1000:.0f} "
            f"| {percentile(values, 0.95) * 1000:.0f} | {percentile(values, 0.99) * 1000:.0f} "
            f"| {max(values) * 1000:.0f} | {errors} |"
        )
    return "\n".join(lines) + "\n"


async def main(args: argparse.Namespace) -> None:
    stats = Stats()
    users = [VirtualUser(i, args.base, stats, args.think) for i in range(args.users)]
    await asyncio.gather(*(u.setup() for u in users))
    if args.warmup:  # let every API process load models and fill its caches first
        warm_until = time.monotonic() + args.warmup
        await asyncio.gather(*(u.run(warm_until) for u in users))
    stats.latencies.clear()  # measure the steady state, not account setup or warm-up
    stats.errors.clear()
    stats.started = time.monotonic()
    until = stats.started + args.duration
    await asyncio.gather(*(u.run(until) for u in users))
    stats.finished = time.monotonic()
    text = report(stats, args)
    print(text)
    left = [u.address for u in users if not await u.close(args.keep)]  # one at a time
    if left:
        print(f"{len(left)} test accounts could not be deleted")
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--duration", type=int, default=60, help="seconds")
    parser.add_argument(
        "--warmup", type=int, default=0, help="unmeasured seconds first"
    )
    parser.add_argument(
        "--think", type=float, default=1.0, help="mean think time, seconds"
    )
    parser.add_argument("--report", help="write the results table to this file")
    parser.add_argument("--keep", action="store_true", help="keep the test accounts")
    asyncio.run(main(parser.parse_args()))
