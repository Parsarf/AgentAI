"""Phase 7 process lifecycle: no duplicate web tasks or side-effect replay."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core import db, orchestrator


async def test_web_event_runs_existing_task_once(users_a_b, monkeypatch):
    alice, _ = users_a_b
    task = await db.create_task(alice.id, "hello", "user")
    seen = []
    monkeypatch.setattr(orchestrator, "_spawn_task", lambda uid, tid: seen.append((uid, tid)))
    orchestrator.subscribe()
    try:
        await orchestrator.handle_task_requested(
            {
                "user_id": str(alice.id),
                "task_id": str(task.id),
                "request": "hello",
                "source": "user",
            }
        )
    finally:
        await orchestrator.unsubscribe_all()
    assert seen == [(str(alice.id), task.id)]
    assert len(await db.list_tasks(alice.id)) == 1


async def test_startup_marks_interrupted_tasks_and_approvals_terminal(users_a_b):
    alice, bob = users_a_b
    a = await db.create_task(alice.id, "first", "user")
    b = await db.create_task(bob.id, "second", "user")
    await db.update_task(alice.id, a.id, status="running")
    approval = await db.record_approval(alice.id, a.id, "test", {})
    affected = await db.recover_interrupted_tasks()
    assert set(affected) == {(alice.id, a.id), (bob.id, b.id)}
    assert (await db.get_task(alice.id, a.id)).status == "failed"
    assert (await db.get_task(bob.id, b.id)).status == "failed"
    row = await db._require_pool().fetchrow("SELECT status FROM approvals WHERE id=$1", approval.id)
    assert row["status"] == "expired"
    assert await db.recover_interrupted_tasks() == []


async def test_bounded_drain_cancels_inflight_task():
    started = asyncio.Event()

    async def slow():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(slow())
    orchestrator._running_tasks.add(task)
    task.add_done_callback(orchestrator._running_tasks.discard)
    await started.wait()
    await orchestrator.stop_and_drain(timeout=0.01)
    assert task.cancelled()
    assert not orchestrator.accepting()
    orchestrator.subscribe()


async def test_shutdown_stops_telegram_before_waiting_on_its_task(monkeypatch):
    import main
    from core import events, scheduler_service
    from gateway import telegram_bot

    stopped = asyncio.Event()
    order = []

    async def telegram_start():
        await stopped.wait()
        order.append("telegram task done")

    async def telegram_stop():
        order.append("telegram stop")
        stopped.set()

    async def noop(*_args, **_kwargs):
        return []

    monkeypatch.setattr(telegram_bot, "stop", telegram_stop)
    monkeypatch.setattr(orchestrator, "stop_and_drain", noop)
    monkeypatch.setattr(orchestrator, "unsubscribe_all", noop)
    monkeypatch.setattr(scheduler_service, "stop", noop)
    monkeypatch.setattr(db, "recover_interrupted_tasks", noop)
    monkeypatch.setattr(db, "close_pool", noop)
    monkeypatch.setattr(events, "publish", noop)
    web_task = asyncio.create_task(asyncio.sleep(0))
    telegram_task = asyncio.create_task(telegram_start())
    server = SimpleNamespace(should_exit=False)
    await main._shutdown(server, web_task, telegram_task)
    assert server.should_exit
    assert order == ["telegram stop", "telegram task done"]
