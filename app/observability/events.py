"""Structured JSON event logging and request-ID context propagation."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

REQUEST_ID = contextvars.ContextVar("learning_pathway_request_id", default="standalone")
LOGGER_NAME = "learning_pathway"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class JsonLogFormatter(logging.Formatter):
    """Format structured event dictionaries as one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "event_data", None)
        if not isinstance(payload, dict):
            payload = {"event": record.getMessage()}
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            **payload,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> logging.Logger:
    """Configure one JSON stream handler for application events."""
    logger = logging.getLogger(LOGGER_NAME)
    if not getattr(logger, "_json_configured", False):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger._json_configured = True  # type: ignore[attr-defined]
    return logger


def set_request_id(value: str | None) -> contextvars.Token[str]:
    """Set a validated client request ID or generate a fresh opaque identifier."""
    import uuid

    request_id = value if value and REQUEST_ID_PATTERN.fullmatch(value) else str(uuid.uuid4())
    return REQUEST_ID.set(request_id)


def emit_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Write a structured event without logging user goal text or secrets."""
    configure_logging().log(
        level,
        event,
        extra={"event_data": {"event": event, "request_id": REQUEST_ID.get(), **fields}},
    )


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Restore the prior request ID after the current request is complete."""
    REQUEST_ID.reset(token)


def estimate_tokens(text: str) -> int:
    """Return a conservative four-characters-per-token estimate."""
    return (len(text) + 3) // 4
