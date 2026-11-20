"""HTTP middleware for production hardening (Milestone 7, ADR-020).

`RequestContextMiddleware`, outermost:

- assigns a request id (kept from `X-Request-ID` when it is well formed) and returns it;
- refuses bodies larger than `MAX_REQUEST_BODY_BYTES` (413), declared or streamed;
- adds security headers to every API response;
- writes one access log line and records metrics per request, labelled with the route template
  (never the raw path, which contains ids, or the query string, which may contain secrets).
"""

import logging
import time
from typing import Any

from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics
from app.core.config import get_settings
from app.core.request_context import new_request_id, request_id_var

logger = logging.getLogger("soniqueo.access")

# Interactive docs load Swagger UI's scripts and styles; everything else is JSON.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class BodyTooLargeError(HTTPException):
    """Raised while a route reads a streamed body past the limit. An HTTPException, so FastAPI's
    body parsing passes it through as a 413 instead of turning it into a 400."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body too large")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return str(value.decode("latin-1"))
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        settings = get_settings()
        self.max_body = settings.max_request_body_bytes
        self.hsts = settings.is_deployed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_request_id(_header(scope, b"x-request-id"))
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False
        path: str = scope["path"]
        is_docs = path.endswith(_DOCS_PATHS)

        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_body:
            await self._too_large(send, request_id)
            self._finish(scope, 413, started)
            request_id_var.reset(token)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body:
                    raise BodyTooLargeError
            return message

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = request_id
                headers.setdefault("x-content-type-options", "nosniff")
                headers.setdefault("x-frame-options", "DENY")
                headers.setdefault("referrer-policy", "no-referrer")
                headers.setdefault("cross-origin-resource-policy", "same-origin")
                # Personal data must not be stored by browsers or shared caches unless a route
                # explicitly allows it.
                headers.setdefault("cache-control", "no-store")
                if not is_docs:
                    headers.setdefault(
                        "content-security-policy", "default-src 'none'; frame-ancestors 'none'"
                    )
                if self.hsts:
                    headers.setdefault(
                        "strict-transport-security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        metrics.HTTP_IN_FLIGHT.inc()
        try:
            await self.app(scope, limited_receive, send_with_headers)
        except BodyTooLargeError:
            if not response_started:
                await self._too_large(send, request_id)
            status_code = 413
        except PoolTimeoutError:
            # Every database connection is busy: the service is overloaded, not broken. Say so
            # (503 + Retry-After) so clients and the proxy back off instead of reporting a bug.
            logger.warning("database pool exhausted")
            metrics.OVERLOADED.inc()
            status_code = 503
            if not response_started:
                await self._json(
                    send,
                    503,
                    b'{"detail":"Service busy, try again shortly"}',
                    request_id,
                    extra=[(b"retry-after", b"2")],
                )
        except Exception:
            # Logged with the traceback (and reported to error tracking); the client gets a
            # generic 500 with the request id, never error details.
            logger.exception("unhandled error")
            status_code = 500
            if not response_started:
                await self._json(
                    send,
                    500,
                    b'{"detail":"Internal server error","request_id":"'
                    + request_id.encode()
                    + b'"}',
                    request_id,
                )
        finally:
            metrics.HTTP_IN_FLIGHT.dec()
            self._finish(scope, status_code, started)
            request_id_var.reset(token)

    @classmethod
    async def _too_large(cls, send: Send, request_id: str) -> None:
        await cls._json(send, 413, b'{"detail":"Request body too large"}', request_id)

    @staticmethod
    async def _json(
        send: Send,
        status_code: int,
        body: bytes,
        request_id: str,
        extra: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", request_id.encode()),
                    (b"cache-control", b"no-store"),
                    *(extra or []),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _finish(scope: Scope, status_code: int, started: float) -> None:
        elapsed = time.perf_counter() - started
        route: Any = scope.get("route")
        template = getattr(route, "path", None) or "unmatched"
        method = scope["method"]
        if template == "/metrics":
            return  # scrapes are not traffic
        metrics.HTTP_REQUESTS.labels(method, template, str(status_code)).inc()
        metrics.HTTP_LATENCY.labels(method, template).observe(elapsed)
        if status_code >= 500:
            level = logging.ERROR
        elif "/health" in template:
            level = logging.DEBUG  # probes every few seconds would drown real traffic
        else:
            level = logging.INFO
        logger.log(
            level,
            "%s %s %s %.1fms",
            method,
            template,
            status_code,
            elapsed * 1000,
            extra={
                "method": method,
                "route": template,
                "status": status_code,
                "duration_ms": round(elapsed * 1000, 1),
            },
        )
