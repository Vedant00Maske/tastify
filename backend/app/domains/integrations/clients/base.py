"""A polite async HTTP client: spacing between requests, provider rate-limit headers and retries.

MetaBrainz services require at most one request per second per application, a descriptive
User-Agent, and backing off on 429/503 (docs/INTEGRATIONS.md).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Self

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

Sleep = Callable[[float], Awaitable[None]]


class ProviderError(RuntimeError):
    pass


class RateLimitedClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        *,
        min_interval: float = 1.0,
        max_retries: int = 6,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _wait_turn(self) -> None:
        async with self._lock:
            delay = self._next_request_at - time.monotonic()
            if delay > 0:
                await self._sleep(delay)
            self._next_request_at = time.monotonic() + self._min_interval

    def _respect_rate_limit_headers(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_in = response.headers.get("X-RateLimit-Reset-In")
        if remaining == "0" and reset_in:
            self._next_request_at = max(self._next_request_at, time.monotonic() + float(reset_in))

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        for header in ("Retry-After", "X-RateLimit-Reset-In"):
            value = response.headers.get(header)
            if value:
                try:
                    return max(1.0, float(value))
                except ValueError:
                    pass
        return min(60.0, 2.0**attempt)

    async def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        for attempt in range(1, self._max_retries + 1):
            await self._wait_turn()
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise ProviderError(f"{method} {path} failed: {exc}") from exc
                await self._sleep(min(60.0, 2.0**attempt))
                continue
            self._respect_rate_limit_headers(response)
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                wait = self._retry_after(response, attempt)
                logger.warning(
                    "%s %s -> %s; retrying in %.0fs", method, path, response.status_code, wait
                )
                await self._sleep(wait)
                continue
            if response.status_code >= 400:
                raise ProviderError(
                    f"{method} {path} -> HTTP {response.status_code}: {response.text[:200]}"
                )
            return response.json() if response.content else None
        raise ProviderError(f"{method} {path} failed after {self._max_retries} attempts")
