"""Redaction filter + JSON formatter + task context stamping."""

from __future__ import annotations

import io
import json
import logging

from core.logging import (
    JsonFormatter,
    RedactionFilter,
    register_secret,
    reset_task_context,
    set_task_context,
)


def _capture_logger(name: str) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, stream


def test_registered_secret_redacted():
    register_secret("hunter2-QZYXW")
    logger, stream = _capture_logger("redact-secret")
    logger.warning("my password is hunter2-QZYXW ok")
    out = stream.getvalue()
    assert "hunter2-QZYXW" not in out
    assert out.count("[REDACTED]") == 1
    payload = json.loads(out)
    assert payload["message"] == "my password is [REDACTED] ok"


def test_luhn_valid_card_redacted_but_random_numbers_survive():
    logger, stream = _capture_logger("redact-card")
    logger.info("charge 4111111111111111 from acct 1234567812345678")
    out = stream.getvalue()
    assert "4111111111111111" not in out          # luhn-valid → redacted
    assert "1234567812345678" in out              # luhn-invalid → untouched


def test_api_keys_and_password_params_redacted():
    logger, stream = _capture_logger("redact-params")
    logger.info(
        "fetched https://x.com/callback?state=ok&password=hunter2&p=1 key=sk-live-abcdefghij"
    )
    out = stream.getvalue()
    assert "hunter2" not in out
    assert "sk-live-abcdefghij" not in out
    assert "state=ok" in out  # innocent params survive


def test_task_context_stamped_on_every_line():
    logger, stream = _capture_logger("redact-context")
    tokens = set_task_context("task-1", "user-1")
    try:
        logger.info("first")
        logger.info("second")
    finally:
        reset_task_context(tokens)
    logger.info("outside")
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert all(line["task_id"] == "task-1" and line["user_id"] == "user-1" for line in lines[:2])
    assert lines[2]["task_id"] is None and lines[2]["user_id"] is None
