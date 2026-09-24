"""Structured, per-tenant-traceable logging.

Every log line is JSON and carries ``task_id`` and ``user_id`` from context
variables (set by the orchestrator via :func:`set_task_context`). A
redaction filter replaces any registered secret value — plus card numbers,
API keys, JWTs and credentials-in-URLs — with ``[REDACTED]`` before the line
ever leaves the process. Secrets are registered at settings load time and,
from Phase 4 on, whenever a vault value is decrypted.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "agent.log"

_REDACTED = "[REDACTED]"

task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "task_id", default=None
)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id", default=None
)

_registered_secrets: set[str] = set()
_registered_lock = threading.Lock()

# 13-19 digit runs, with optional separators — validated against Luhn before
# redacting so ordinary numbers survive.
_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,19}\d\b")
# Anthropic/OpenAI-style API keys.
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
# JWTs (three base64url segments).
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b")
# Credentials embedded in URLs/strings: password=... / api_key: ...
_CRED_PARAM_RE = re.compile(
    r"\b((?:password|passwd|pwd|secret|token|api_key|apikey|access_token)\s*[=:]\s*)(\S+)",
    re.IGNORECASE,
)


def register_secret(value: str) -> None:
    """Register an exact secret value for redaction in every future log line.

    Short values (< 6 chars) are ignored — the redaction cost/benefit flips
    at that length.
    """
    if value and len(value) >= 6:
        with _registered_lock:
            _registered_secrets.add(value)


def set_task_context(task_id: str, user_id: str) -> tuple[Any, Any]:
    """Attach task_id/user_id to everything logged in this context.

    Returns reset tokens — pass to :func:`reset_task_context` when the task
    ends so stale ids don't leak into unrelated work on the same thread/loop.
    """
    t = task_id_var.set(str(task_id))
    u = user_id_var.set(str(user_id))
    return (t, u)


def set_task_context_tokens(user_id: str, task_id: str) -> tuple[Any, Any]:
    """Alias with (user_id, task_id) argument order for orchestrator callers."""
    return set_task_context(task_id, user_id)


def reset_task_context(tokens: Sequence[Any]) -> None:
    task_id_var.reset(tokens[0])
    user_id_var.reset(tokens[1])


def _luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _redact(text: str) -> str:
    with _registered_lock:
        secrets = sorted(_registered_secrets, key=len, reverse=True)
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, _REDACTED)

    text = _SK_KEY_RE.sub(_REDACTED, text)
    text = _JWT_RE.sub(_REDACTED, text)
    text = _CRED_PARAM_RE.sub(lambda m: m.group(1) + _REDACTED, text)

    def _card_sub(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return _REDACTED if _luhn_ok(digits) else m.group(0)

    text = _CARD_RE.sub(_card_sub, text)
    return text


class RedactionFilter(logging.Filter):
    """Redact secrets in the rendered message before any formatter sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = _redact(message)
        record.args = ()
        return True


_RESERVED_ATTRS = frozenset(
    vars(logging.LogRecord("x", 0, "x", 1, "x", (), None)).keys()
    | {"message", "asctime", "taskName", "task_id", "user_id"}
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "task_id": task_id_var.get(),
            "user_id": user_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(force: bool = False) -> None:
    """Attach the JSON + redaction handlers to the root logger (once)."""
    root = logging.getLogger()
    if getattr(root, "_agent_json_configured", False) and not force:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = JsonFormatter()
    redact = RedactionFilter()
    stdout_handler = logging.StreamHandler()
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    for handler in (stdout_handler, file_handler):
        handler.setFormatter(fmt)
        handler.addFilter(redact)
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    root._agent_json_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
