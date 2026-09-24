"""Scheduler tenancy (spec accept): B cannot list/pause/delete A's job by id;
A's and B's jobs fire independently; B's pathologically failing job never
blocks A's firing; auto-pause after 3 failures notifies ONLY the owner;
catch-up fires once and concurrent ticks never double-fire."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from core import approvals, db, skills
from tests.p2_conftest import task_context
from tools.base import call_tool


def _past(minutes: int = 1) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def _recurring(user, instruction: str, **kwargs) -> db.Job:
    return await db.create_job(
        user.id, "recurring", "*/5 * * * *", "always", instruction,
        next_run_at=_past(), **kwargs,
    )


async def test_b_cannot_list_pause_or_delete_a_job(pro_users, fired):  # noqa: F811
    alice, bob = pro_users
    job_a = await _recurring(alice, "alice private job")

    with task_context(str(bob.id), "t-bob"):
        listed = await call_tool("list_jobs", {})
        assert listed.ok
        assert listed.data == []  # A's job is not even visible
        paused = await call_tool("pause_job", {"job_id": str(job_a.id)})
        assert not paused.ok and paused.error == "job not found"
        deleted = await call_tool("delete_job", {"job_id": str(job_a.id)})
        assert not deleted.ok and deleted.error == "job not found"
        # A garbage id reads exactly the same (existence never leaked):
        garbage = await call_tool("pause_job", {"job_id": "not-even-a-uuid"})
        assert not garbage.ok and garbage.error == "job not found"

    still = await db.get_job(alice.id, job_a.id)
    assert still is not None and still.active  # untouched
    assert fired == []


async def test_jobs_of_different_users_fire_independently(pro_users, scheduler, fired):  # noqa: F811
    alice, bob = pro_users
    await _recurring(alice, "alice thing")
    await _recurring(bob, "bob thing")

    await scheduler.tick(datetime.now(UTC) + timedelta(minutes=10))
    await scheduler.drain()

    assert {(p["user_id"], p["instruction"]) for p in fired} == {
        (str(alice.id), "alice thing"),
        (str(bob.id), "bob thing"),
    }


async def test_failing_job_never_blocks_other_users(
    pro_users, scheduler, fired, fake_sandbox  # noqa: F811
):
    alice, bob = pro_users
    await _recurring(alice, "alice fine")

    # Bob's watcher: its check script explodes every single time.
    jb = await db.create_job(
        bob.id, "watcher", "*/5 * * * *", "on_change", "bob broken watcher",
        next_run_at=_past(),
    )
    path = skills.write_check_script(str(bob.id), str(jb.id), "print('doomed')")
    await db.update_job(bob.id, jb.id, check_script_path=str(path))
    fake_sandbox.fail_task_ids = {f"check-{jb.id}"}

    await scheduler.tick(datetime.now(UTC) + timedelta(minutes=10))
    await scheduler.drain()

    # Alice fired normally; Bob's failure was recorded as a failure.
    assert [p["instruction"] for p in fired] == ["alice fine"]
    broken = await db.get_job(bob.id, jb.id)
    assert broken.state_json["consecutive_failures"] == 1
    assert broken.active

    # The loop is alive: a second tick still fires Alice's job.
    await db.update_job(alice.id, (await db.list_jobs(alice.id))[0].id,
                        next_run_at=_past())
    await scheduler.tick(datetime.now(UTC) + timedelta(minutes=20))
    await scheduler.drain()
    assert len(fired) == 2


async def test_auto_pause_after_three_failures_notifies_owner_only(
    pro_users, scheduler, fired, notify_log, fake_sandbox  # noqa: F811
):
    alice, bob = pro_users
    ja = await _recurring(alice, "alice healthy")

    jb = await db.create_job(
        bob.id, "watcher", "*/5 * * * *", "on_change", "bob doomed watcher",
        next_run_at=_past(),
    )
    path = skills.write_check_script(str(bob.id), str(jb.id), "raise SystemExit(1)")
    await db.update_job(bob.id, jb.id, check_script_path=str(path))
    fake_sandbox.fail_task_ids = {f"check-{jb.id}"}

    t0 = datetime.now(UTC) + timedelta(minutes=10)
    for offset in (0, 6, 12):  # cron */5 → due again on each tick
        await scheduler.tick(t0 + timedelta(minutes=offset))
        await scheduler.drain()

    # Bob's job auto-paused; alice's job is untouched and fired every tick.
    paused = await db.get_job(bob.id, jb.id)
    assert paused.active is False
    healthy = await db.get_job(alice.id, ja.id)
    assert healthy.active is True
    assert len(fired) == 3 and all(p["user_id"] == str(alice.id) for p in fired)

    # Exactly one notification, to the OWNER only.
    assert len(notify_log) == 1
    assert notify_log[0]["user_id"] == str(bob.id)
    assert "auto-paused" in notify_log[0]["message"]


async def test_catchup_fires_once_and_concurrent_ticks_never_double_fire(
    pro_users, scheduler, fired  # noqa: F811
):
    alice, _ = pro_users
    # next_run_at three days in the past: the service was "down".
    job = await db.create_job(
        alice.id, "recurring", "* * * * *", "always", "catch-up job",
        next_run_at=datetime.now(UTC) - timedelta(days=3),
    )
    now = datetime.now(UTC)

    await asyncio.gather(scheduler.tick(now), scheduler.tick(now))
    await scheduler.drain()
    assert len([p for p in fired if p["job_id"] == str(job.id)]) == 1

    # A further tick at the same instant finds nothing due.
    await scheduler.tick(now)
    await scheduler.drain()
    assert len([p for p in fired if p["job_id"] == str(job.id)]) == 1

    refreshed = await db.get_job(alice.id, job.id)
    assert refreshed.next_run_at is not None and refreshed.next_run_at > now


async def test_job_source_tasks_hit_the_autonomous_mode_floor(pro_users):
    """Job-sourced tasks never get a looser gate than require_approval above
    'safe' — regardless of the (default) rules that auto-log interactive use."""
    alice, _ = pro_users
    for tool_name in ("pause_job", "delete_job", "create_job"):
        decision = await approvals.check(
            alice.id, tool_name, {"job_id": "x"}, "moderate", task_source="user"
        )
        assert decision.action == "auto_and_log"  # interactive: logged, proceeds
        decision = await approvals.check(
            alice.id, tool_name, {"job_id": "x"}, "moderate", task_source="job"
        )
        assert decision.action == "require_approval"  # autonomous floor
