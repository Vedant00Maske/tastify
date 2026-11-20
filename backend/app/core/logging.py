"""Process-wide logging configuration (spec §15: structured logs).

Every record carries the current request id. Secrets that might reach a message by accident
(bearer tokens, OAuth codes, passwords, session cookies) are masked before anything is written,
and uvicorn's own access log, which prints full URLs including OAuth callback codes, is replaced
by the request middleware's access line (route templates only).
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Literal

from app.core.request_context import current_request_id

_SECRET_PATTERNS = [
    # Authorization: Bearer xxx, Basic xxx
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [redacted]"),
    # key=value pairs in URLs, forms and messages
    (
        re.compile(
            r"(?i)\b(access_token|refresh_token|id_token|token|code|state|password|secret"
            r"|client_secret|api_key|soniqueo_session)=([^&\s\"',;]+)"
        ),
        r"\1=[redacted]",
    ),
    # JSON-ish "password": "..."
    (
        re.compile(
            r"(?i)([\"'](?:password|current_password|new_password|token|access_token"
            r"|refresh_token|secret)[\"']\s*:\s*)[\"'][^\"']*[\"']"
        ),
        r'\1"[redacted]"',
    ),
]

# Standard LogRecord attributes; anything else passed via `extra=` is emitted as a field.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "request_id"}


def redact(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class ContextFilter(logging.Filter):
    """Adds the request id and masks secrets in the rendered message."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id() or "-"
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value if isinstance(value, str | int | float | bool) else str(value)
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s [%(name)s] [%(request_id)s] %(message)s")

    def formatException(self, ei: object) -> str:  # noqa: N802 - logging API name
        return redact(super().formatException(ei))  # type: ignore[arg-type]


def configure_logging(level: str, fmt: Literal["text", "json"] = "text") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # uvicorn's loggers: errors go through ours; its access log is replaced (see module doc).
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs every request URL at INFO (provider calls include query strings).
    logging.getLogger("httpx").setLevel(logging.WARNING)
