"""THE LEAK CANARY (Phase 4's unforgivable-bug test).

Runs a full browser_login flow against the local test site with a known
password, then asserts the password appears NOWHERE: not in captured logs,
not in any model-visible message, not in task rows (result/steps_json), not
in tool results, not in any file under the browser profile dir — and the
decrypted value is registered with the log redaction filter the moment it
exists in memory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core import db, orchestrator
from core import secrets_vault as sv
from tests.browser_site import PASSWORD, USERNAME
from tests.p2_conftest import task_context  # noqa: F401
from tools.base import call_tool


async def test_password_leaks_nowhere(
    pro_users, browser_env, chromium, login_site, caplog, monkeypatch, tmp_path
):
    alice, _ = pro_users
    origin = login_site.origin

    # The credential as the user would store it via web settings:
    await sv.store_credential(
        str(alice.id), origin,
        json.dumps({"username": USERNAME, "password": PASSWORD}),
    )

    # A mocked model loop: captures everything the model would ever see.
    model_messages: list[str] = []
    tool_results: list[str] = []

    async def fake_loop(uid, tid, user, task, source, step_cap):
        from core.orchestrator import _finalize

        model_messages.append(task.request)
        result = await call_tool("browser_login", {"site": origin})
        tool_results.append(result.model_dump_json())
        model_messages.append(result.model_dump_json())
        status = "done" if result.ok else "failed"
        await _finalize(uid, tid, status, "login flow finished", parent_job_id=None)

    async def noop_start(user_id, task_id):
        return tmp_path / "ws" / str(user_id) / str(task_id)

    async def noop_stop(task_id):
        return None

    monkeypatch.setattr(orchestrator, "_loop", fake_loop)
    monkeypatch.setattr(orchestrator.sandbox, "start_task_sandbox", noop_start)
    monkeypatch.setattr(orchestrator.sandbox, "stop_task_sandbox", noop_stop)

    with caplog.at_level(logging.DEBUG):
        task = await db.create_task(alice.id, f"log into {origin}", source="user")
        await orchestrator.run_task(alice.id, task.id)

    row = await db.get_task(alice.id, task.id)
    assert row.status == "done", f"task failed: {row.result!r}; tool: {tool_results[:1]}"
    # The flow is REAL: the login actually worked (canary isn't vacuous).
    assert any("Welcome back" in r for r in tool_results)

    needles = [PASSWORD, json.dumps(PASSWORD)]  # raw + JSON-embedded forms
    haystacks = {
        "model_messages": "\n".join(model_messages),
        "tool_results": "\n".join(tool_results),
        "task_result": row.result or "",
        "steps_json": json.dumps(row.steps_json, default=str),
        "caplog": caplog.text,
    }
    for haystack_name, haystack in haystacks.items():
        for needle in needles:
            assert needle not in haystack, f"SECRET LEAKED into {haystack_name}"

    # No file under the user's browser profile contains the secret.
    profile_root = Path(browser_env.profile_root()) / str(alice.id)
    for path in profile_root.rglob("*"):
        if path.is_file():
            try:
                data = path.read_bytes()
            except OSError:
                continue
            assert PASSWORD.encode() not in data, f"SECRET LEAKED into {path}"

    # The instant the value was decrypted it became redaction-covered:
    assert any(PASSWORD in s for s in sv_export_registered())


def sv_export_registered() -> list[str]:
    from core import logging as clog

    return list(getattr(clog, "_registered_secrets", set()))
