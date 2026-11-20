"""Error tracking (Sentry or a compatible service; spec §15). Optional: without SENTRY_DSN nothing
is sent anywhere. Personal data is not sent: no request bodies, cookies, headers or user ids, and
messages pass through the same secret redaction as the logs."""

import logging
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger

from app import __version__
from app.core.config import get_settings
from app.core.logging import redact
from app.core.request_context import current_request_id

logger = logging.getLogger(__name__)

_DROPPED_REQUEST_FIELDS = ("cookies", "data", "headers", "query_string", "env")


def _scrub(event: Any, _hint: Any) -> Any:
    request = event.get("request")
    if isinstance(request, dict):
        for key in _DROPPED_REQUEST_FIELDS:
            request.pop(key, None)
    event.pop("user", None)
    for entry in (event.get("logentry"), event.get("message")):
        if isinstance(entry, dict) and isinstance(entry.get("message"), str):
            entry["message"] = redact(entry["message"])
    if isinstance(event.get("message"), str):
        event["message"] = redact(event["message"])
    request_id = current_request_id()
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    return event


def init_error_tracking(component: str) -> bool:
    settings = get_settings()
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=f"tastify@{__version__}",
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=_scrub,
        # Errors logged with logger.exception are reported; warnings become breadcrumbs.
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        server_name=component,
    )
    # The access log's 5xx lines repeat errors that are already reported with their exception.
    ignore_logger("tastify.access")
    logger.info("error tracking enabled component=%s", component)
    return True
