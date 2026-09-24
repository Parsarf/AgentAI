"""Phase 2 test helpers: tool task-context + a clean event bus per test.
(db_pool / users_a_b fixtures live in tests/conftest.py.)"""

from __future__ import annotations

import contextlib

import pytest


@contextlib.contextmanager
def task_context(user_id, task_id="t-test", source: str = "user"):
    """Put a task's tenancy context in place (what the orchestrator sets)."""
    from tools import base as tb

    tokens = tb.set_task_context_tokens(user_id, task_id)
    tb.current_task_source.set(source)
    try:
        yield
    finally:
        tb.reset_task_context(tokens)


@pytest.fixture(autouse=True)
def _clean_event_bus():
    from core import events

    events.clear_all()
    yield
    events.clear_all()
