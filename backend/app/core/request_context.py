"""Per-request context shared with logging, metrics and error tracking."""

import re
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Accept a caller's (the proxy's or the browser's) request id only if it is short and plain, so
# it cannot inject anything into logs or headers.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def new_request_id(incoming: str | None = None) -> str:
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


def current_request_id() -> str | None:
    return request_id_var.get()
