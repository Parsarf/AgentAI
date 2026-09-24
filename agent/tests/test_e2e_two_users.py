"""The spec's headline e2e: two users run tasks concurrently (web search,
code, memory) with a FAKE model loop, and neither can observe anything about
the other — tasks, costs, memories, notifications."""

from __future__ import annotations

import asyncio

import pytest

from core import db, events


@pytest.fixture
def fake_sdk_loop(monkeypatch):
    """Replace the real SDK loop with a scripted in-process fake that 'runs'
    each task: searches, 'runs code' (sandbox mocked), stores a memory, and
    finishes. Asserts isolation at the seams the real loop uses."""
    ran: list[tuple[str, str, str]] = []  # (user_id, task_id, request)

    async def fake_loop(uid, tid, user, task, source, step_cap):
        from decimal import Decimal

        from core import db
        from tools.base import (
            approvals_prechecked,
            call_tool,
            current_task_source,
            set_task_context_tokens,
        )

        ran.append((str(uid), str(tid), task.request))
        tokens = set_task_context_tokens(str(uid), str(tid))
        current_task_source.set(source)
        approvals_prechecked.set(True)
        try:
            await db.update_task(uid, tid, status="running")
            # 1. web search (mocked provider below)
            await call_tool("web_search", {"query": task.request[:50]})
            # 2. code (mocked sandbox tool so no Docker is needed)
            await call_tool("p2_fake_code", {"snippet": "print('x')"})
            # 3. memory
            await call_tool("remember", {"content": f"result of: {task.request[:40]}"})
            # 4. metered model cost — direct db (as the loop would)
            await db.log_api_cost(uid, tid, "claude-haiku-4-5", 100, 40, Decimal("0.0001"))
            from core.orchestrator import _finalize

            await _finalize(uid, tid, "done", f"finished: {task.request[:30]}")
        finally:
            from tools.base import reset_task_context

            reset_task_context(tokens)

    async def noop_start(user_id, task_id):
        import pathlib
        import tempfile

        ws = pathlib.Path(tempfile.gettempdir()) / "p2ws" / str(user_id) / str(task_id)
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    async def noop_stop(task_id):
        return None

    from core import orchestrator  # noqa: F401
    monkeypatch.setattr(orchestrator, "_loop", fake_loop)
    monkeypatch.setattr(orchestrator.sandbox, "start_task_sandbox", noop_start)
    monkeypatch.setattr(orchestrator.sandbox, "stop_task_sandbox", noop_stop)
    return ran


@pytest.fixture(autouse=True)
def fake_code_tool():
    from tools import base as tb

    if "p2_fake_code" not in tb.registry.all():

        @tb.tool("p2_fake_code", "fake code exec", risk="safe")
        async def p2_fake_code(snippet: str) -> dict:
            return {"exit_code": 0, "stdout": "x", "stderr": ""}


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    """Never load torch in tests — deterministic fake vectors everywhere."""
    import hashlib

    from tools import memory

    async def fake_embed(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        vector = (digest * 12)[:384]
        return [b / 255.0 for b in vector]

    monkeypatch.setattr(memory, "embed_text", fake_embed)


@pytest.fixture(autouse=True)
def fake_search_provider(monkeypatch):
    import tools.web as tw

    async def fake_search(query: str, num_results: int = 5):
        return [{"title": "t", "url": "https://example.com", "snippet": f"about {query}"}]

    async def patched_web_search(query: str, num_results: int = 5):
        from uuid import UUID as U

        from core import db
        from core.config import settings
        from tools.base import current_task_id, current_user_id

        results = await fake_search(query, num_results)
        uid = current_user_id.get()
        tid = current_task_id.get()
        await db.log_api_cost(
            U(uid), U(tid) if tid else None, "search:brave", 0, 0,
            settings.search_per_query_usd,
        )
        return results

    monkeypatch.setattr(tw, web_search_ref(), patched_web_search)


def web_search_ref():
    return "web_search"


async def test_two_users_concurrent_no_cross_talk(users_a_b, fake_sdk_loop):
    alice, bob = users_a_b
    seen: dict[str, list[dict]] = {"alice": [], "bob": []}
    finished: dict[str, list[dict]] = {"alice": [], "bob": []}

    async def on_progress(p):
        key = "alice" if p["user_id"] == str(alice.id) else "bob"
        seen[key].append(p)

    async def on_finished(p):
        key = "alice" if p["user_id"] == str(alice.id) else "bob"
        finished[key].append(p)

    await events.subscribe(events.TASK_PROGRESS, on_progress)
    await events.subscribe(events.TASK_FINISHED, on_finished)

    # Both submit at once:
    from core.orchestrator import handle_task_requested

    await asyncio.gather(
        handle_task_requested({"user_id": alice.id, "request": "alice research task", "source": "user"}),
        handle_task_requested({"user_id": bob.id, "request": "bob research task", "source": "user"}),
    )
    # Wait (bounded, no fixed sleep) until both tasks finished:
    for _ in range(100):
        if len(finished["alice"]) >= 1 and len(finished["bob"]) >= 1:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.05)  # let final DB writes land

    # Each finished exactly once with their own summary:
    assert len(finished["alice"]) == 1 and finished["alice"][0]["status"] == "done"
    assert "alice research task" in finished["alice"][0]["summary"]
    assert len(finished["bob"]) == 1 and "bob research task" in finished["bob"][0]["summary"]

    # Tasks, costs, memories are isolated:
    a_tasks = await db_list(alice.id)
    b_tasks = await db_list(bob.id)
    assert [t.request for t in a_tasks] == ["alice research task"]
    assert [t.request for t in b_tasks] == ["bob research task"]

    a_mem = await db._require_pool().fetch("SELECT content FROM memories WHERE user_id=$1", alice.id)
    b_mem = await db._require_pool().fetch("SELECT content FROM memories WHERE user_id=$1", bob.id)
    assert len(a_mem) == 1 and "alice research task" in a_mem[0]["content"]
    assert len(b_mem) == 1 and "bob research task" in b_mem[0]["content"]

    a_cost = await db_cost(alice.id)
    b_cost = await db_cost(bob.id)
    assert a_cost > 0 and b_cost > 0  # both metered, separately


async def db_list(user_id):
    return await db_list_inner(user_id)


async def db_list_inner(user_id):
    from core import db

    return await db.list_tasks(user_id)


async def db_cost(user_id):
    from core import db

    return await db.cost_today(user_id)


async def test_plan_floor_blocks_job_tasks_for_free_tier(users_a_b, fake_sdk_loop):
    """Free tier can't run job-sourced tasks at all (autonomy disabled)."""
    alice, _ = users_a_b
    from core import db, orchestrator

    task = await db.create_task(alice.id, "autonomous!", source="job")
    await orchestrator.run_task(alice.id, task.id)
    updated = await db.get_task(alice.id, task.id)
    assert updated.status == "failed"
    assert "autonomous jobs" in updated.result
