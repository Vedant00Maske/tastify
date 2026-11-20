"""Errors from the web app (Milestone 7, spec §15 error tracking).

The browser reports uncaught rendering errors here instead of to a third-party script: no extra
origin in the content security policy, nothing sent to another company from the user's browser.
The API logs them, counts them, and forwards them to error tracking when it is configured.
Reports are anonymous (no user id), size-capped and rate limited.
"""

import logging
from typing import Literal

import sentry_sdk
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.limits import limit
from app.core import metrics
from app.core.logging import redact
from app.domains.auth import rate_limit

logger = logging.getLogger("tastify.client")

router = APIRouter(prefix="/client-errors", tags=["telemetry"])


class ClientErrorIn(BaseModel):
    kind: Literal["render", "unhandled", "chunk"] = "render"
    message: str = Field(max_length=500)
    # Route template-like path the error happened on, without the query string.
    path: str = Field(max_length=200, pattern=r"^/[^?#\s]*$")
    # Next.js error digest (links a server-rendered error to the server log), if any.
    digest: str | None = Field(default=None, max_length=64)
    release: str | None = Field(default=None, max_length=40)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[limit(rate_limit.CLIENT_ERRORS_PER_CLIENT)],
)
async def report_client_error(report: ClientErrorIn) -> None:
    message = redact(report.message)
    metrics.CLIENT_ERRORS.labels(report.kind).inc()
    logger.warning(
        "web app error kind=%s path=%s: %s",
        report.kind,
        report.path,
        message,
        extra={"client_kind": report.kind, "client_path": report.path, "digest": report.digest},
    )
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("source", "web")
        scope.set_tag("client_kind", report.kind)
        scope.set_context("client", {"path": report.path, "digest": report.digest})
        sentry_sdk.capture_message(f"web: {message}", level="error")
