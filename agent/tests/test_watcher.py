"""Watcher behavior: check runs in the user's own sandbox; escalate only on
change; a check that cannot run is a FAILED run; fired jobs become
source="job" tasks with the check output in context (untrusted-wrapped)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from core import db, orchestrator, skills


def _past(minutes: int = 1) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def _watcher(user, output: str, fake_sandbox, instruction: str = "watch the feed") -> db.Job:
    """A watcher job whose check script prints `output` (via the fake sandbox)."""
    job = await db.create_job(
        user.id, "watcher", "*/5 * * * *", "on_change", instruction, next_run_at=_past()
    )
    path = skills.write_check_script(str(user.id), str(job.id), f"print({output!r})")
    await db.update_job(user.id, job.id, check_script_path=str(path))
    fake_sandbox.script_outputs[f"check-{job.id}"] = (0, output, "")
    return job


async def test_watcher_escalates_only_on_change(pro_users, scheduler, fired, fake_sandbox):  # noqa: F811
    alice, _ = pro_users
    job = await _watcher(alice, "state-v1", fake_sandbox)

    t0 = datetime.now(UTC)
    await scheduler.tick(t0)
    await scheduler.drain()
    # First observation: no baseline hash yet → escalates, output carried.
    assert len(fired) == 1
    assert fired[0]["kind"] == "watcher"
    assert fired[0]["check_output"] == "state-v1"
    assert fired[0]["user_id"] == str(alice.id)

    # Unchanged output → watcher.quiet: no task, no usage.
    await scheduler.tick(t0 + timedelta(minutes=6))
    await scheduler.drain()
    assert len(fired) == 1

    # Changed output → escalates again with the new output.
    fake_sandbox.script_outputs[f"check-{job.id}"] = (0, "state-v2", "")
    await scheduler.tick(t0 + timedelta(minutes=11))
    await scheduler.drain()
    assert len(fired) == 2
    assert fired[1]["check_output"] == "state-v2"

    # Every check ran inside THIS user's own sandbox container slot.
    assert {c["task_id"] for c in fake_sandbox.calls} == {f"check-{job.id}"}
    assert fake_sandbox.started == fake_sandbox.stopped  # no container leaks


async def test_unchanged_check_logs_quiet_and_advances_schedule(
    pro_users, scheduler, fired, fake_sandbox  # noqa: F811
):
    alice, _ = pro_users
    job = await _watcher(alice, "same", fake_sandbox)
    t0 = datetime.now(UTC)
    await scheduler.tick(t0)
    await scheduler.drain()

    refreshed = await db.get_job(alice.id, job.id)
    assert refreshed.state_json["last_hash"]  # baseline stored
    next_before = refreshed.next_run_at
    assert next_before > t0
    assert refreshed.state_json["consecutive_failures"] == 0


async def test_failed_check_is_a_failure_not_a_skip(
    pro_users, scheduler, fired, fake_sandbox  # noqa: F811
):
    alice, _ = pro_users
    job = await _watcher(alice, "will explode", fake_sandbox)
    fake_sandbox.fail_task_ids = {f"check-{job.id}"}

    await scheduler.tick(datetime.now(UTC))
    await scheduler.drain()

    assert fired == []  # nothing escalated
    state = (await db.get_job(alice.id, job.id)).state_json
    assert state["consecutive_failures"] == 1
    assert state["last_status"] == "failed"
    assert "exit code 1" in state["last_error"]

    # A job whose check script vanished also fails — never silently skips.
    job2 = await db.create_job(
        alice.id, "watcher", "*/5 * * * *", "on_change", "no script",
        next_run_at=_past(), check_script_path="/nonexistent/check.py",
    )
    await scheduler.tick(datetime.now(UTC) + timedelta(minutes=10))
    await scheduler.drain()
    state2 = (await db.get_job(alice.id, job2.id)).state_json
    assert state2["consecutive_failures"] == 1
    assert "check script missing" in state2["last_error"]


async def test_job_fired_becomes_job_source_task_with_check_output(
    pro_users, monkeypatch, tmp_path, fired  # noqa: F811
):
    """The full hand-off: scheduler → job.fired → orchestrator task."""
    alice, _ = pro_users

    ran: list[tuple[str, str]] = []

    async def fake_loop(uid, tid, user, task, source, step_cap):
        from core.orchestrator import _finalize

        ran.append((str(uid), task.request))
        await _finalize(uid, tid, "done", "job task finished", parent_job_id=task.parent_job_id)

    async def noop_start(user_id, task_id):
        ws = tmp_path / "ws" / str(user_id) / str(task_id)
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    async def noop_stop(task_id):
        return None

    monkeypatch.setattr(orchestrator, "_loop", fake_loop)
    monkeypatch.setattr(orchestrator.sandbox, "start_task_sandbox", noop_start)
    monkeypatch.setattr(orchestrator.sandbox, "stop_task_sandbox", noop_stop)

    job = await db.create_job(
        alice.id, "watcher", "*/5 * * * *", "on_change", "summarize the feed changes",
        next_run_at=_past(),
    )
    await orchestrator.handle_job_fired(
        {
            "user_id": str(alice.id),
            "job_id": str(job.id),
            "instruction": "summarize the feed changes",
            "kind": "watcher",
            "check_mode": "on_change",
            "check_script_path": None,
            "check_output": "NEW POST: hello world",
        }
    )

    for _ in range(100):
        task = (await db.list_tasks(alice.id, limit=1))
        if task and task[0].status in ("done", "failed"):
            break
        await asyncio.sleep(0.02)
    task = (await db.list_tasks(alice.id, limit=1))[0]
    assert task.status == "done"
    assert task.source == "job"                      # autonomous mode
    assert str(task.parent_job_id) == str(job.id)    # linked to its job
    assert "summarize the feed changes" in task.request
    # Check output is context, wrapped as untrusted — never instructions.
    assert '<untrusted_content source="watcher check script">' in task.request
    assert "NEW POST: hello world" in task.request
    assert ran and ran[0][0] == str(alice.id)


async def test_recurring_job_fires_without_check_output(
    pro_users, scheduler, fired, fake_sandbox  # noqa: F811
):
    alice, _ = pro_users
    await db.create_job(
        alice.id, "recurring", "*/5 * * * *", "always", "morning digest",
        next_run_at=_past(),
    )
    await scheduler.tick(datetime.now(UTC))
    await scheduler.drain()
    assert len(fired) == 1
    assert fired[0]["check_output"] is None
    assert fake_sandbox.calls == []  # no sandbox run for a plain recurring job
