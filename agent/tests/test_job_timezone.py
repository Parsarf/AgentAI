"""Cron schedules are evaluated in the USER'S OWN timezone (migration 0004):
same cron string, different timezones → different UTC instants."""

from __future__ import annotations

from datetime import UTC, datetime

from core import db
from core.scheduler_service import next_cron_run, user_timezone
from tests.p2_conftest import task_context
from tools.base import call_tool


def test_same_cron_different_timezones_different_instants():
    after = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)  # noon UTC
    ny = next_cron_run("30 9 * * *", "America/New_York", after)   # 09:30 EDT
    tokyo = next_cron_run("30 9 * * *", "Asia/Tokyo", after)      # 09:30 JST (next day)
    assert ny == datetime(2026, 9, 23, 13, 30, tzinfo=UTC)
    assert tokyo == datetime(2026, 9, 24, 0, 30, tzinfo=UTC)
    assert ny != tokyo


def test_unknown_timezone_falls_back_to_operator_default():
    assert str(user_timezone("Not/AZone")) in ("UTC", "UTC0")
    assert str(user_timezone(None)) == "UTC"
    assert str(user_timezone("Europe/Berlin")) == "Europe/Berlin"


def test_invalid_cron_raises_valueerror():
    import pytest

    after = datetime.now(UTC)
    for bad in ("nonsense", "99 * * * *", "* * * *", "60 25 * * *"):
        with pytest.raises(ValueError):
            next_cron_run(bad, "UTC", after)


async def test_create_job_seeds_next_run_in_user_timezone(pro_users):  # noqa: F811
    """The create_job tool computes the first next_run_at in the user's tz."""
    from uuid import UUID

    alice, bob = pro_users
    await db.update_user(alice.id, timezone="America/New_York")
    await db.update_user(bob.id, timezone="Asia/Tokyo")

    with task_context(str(alice.id), "t-ny"):
        a = await call_tool("create_job", {"kind": "recurring", "schedule": "30 9 * * *",
                                           "instruction": "ny morning"})
    with task_context(str(bob.id), "t-jp"):
        b = await call_tool("create_job", {"kind": "recurring", "schedule": "30 9 * * *",
                                           "instruction": "jp morning"})
    assert a.ok and b.ok

    job_a = await db.get_job(alice.id, UUID(str(a.data["job_id"])))
    job_b = await db.get_job(bob.id, UUID(str(b.data["job_id"])))
    # Same cron string, different local mornings → different UTC instants:
    # 09:30 America/New_York == 13:30Z, 09:30 Asia/Tokyo == 00:30Z.
    utc_a = job_a.next_run_at.astimezone(UTC)
    utc_b = job_b.next_run_at.astimezone(UTC)
    assert (utc_a.hour, utc_a.minute) == (13, 30)
    assert (utc_b.hour, utc_b.minute) == (0, 30)
    assert utc_a != utc_b


async def test_scheduler_claims_fire_in_user_timezone(pro_users):
    """A full claim: advanced next_run_at stays aligned to the user's local
    09:30, not the server's."""
    alice, _ = pro_users
    await db.update_user(alice.id, timezone="Asia/Tokyo")
    job = await db.create_job(
        alice.id, "recurring", "30 9 * * *", "always", "tokyo morning",
        next_run_at=datetime(2026, 9, 23, 0, 29, tzinfo=UTC),  # 09:29 JST
    )
    from core.scheduler_service import SchedulerService

    svc = SchedulerService()
    # Claim at 09:29:30 JST: next fire must be 09:30 JST == 00:30 UTC.
    ok = await svc._claim(
        job, datetime(2026, 9, 23, 0, 29, 30, tzinfo=UTC)
    )
    assert ok is True
    fresh = await db.get_job(alice.id, job.id)
    assert fresh.next_run_at == datetime(2026, 9, 23, 0, 30, tzinfo=UTC)
