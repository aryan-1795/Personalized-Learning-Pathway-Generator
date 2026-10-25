from __future__ import annotations

import json
import logging

from app.observability.events import (
    JsonLogFormatter,
    estimate_tokens,
    reset_request_id,
    set_request_id,
)


def test_json_formatter_serializes_structured_fields() -> None:
    record = logging.LogRecord("test", logging.INFO, "", 1, "llm_call", (), None)
    record.event_data = {
        "event": "llm_call",
        "request_id": "req-123",
        "prompt_version": "pathway_v2",
        "model": "mock",
        "input_tokens_estimated": 80,
        "output_tokens_estimated": 25,
        "latency_ms": 12.5,
        "validation_outcome": "accepted",
        "retries": 0,
    }
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["event"] == "llm_call"
    assert payload["request_id"] == "req-123"
    assert payload["model"] == "mock"
    assert payload["validation_outcome"] == "accepted"
    assert payload["timestamp"]


def test_request_ids_reject_unsafe_or_oversized_values() -> None:
    valid_token = set_request_id("request-123")
    try:
        from app.observability.events import REQUEST_ID

        assert REQUEST_ID.get() == "request-123"
    finally:
        reset_request_id(valid_token)
    invalid_token = set_request_id("bad request id")
    try:
        from app.observability.events import REQUEST_ID

        assert REQUEST_ID.get() != "bad request id"
        assert len(REQUEST_ID.get()) == 36
    finally:
        reset_request_id(invalid_token)


def test_token_estimate_is_conservative() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
