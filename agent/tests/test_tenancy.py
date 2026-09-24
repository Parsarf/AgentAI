"""The Phase 1 headline guarantee: every core.db function is tenant-isolated.

Creates two users, writes the same kind of data for both, and proves that
acting as user A never returns or mutates user B's rows. due_jobs is the one
deliberate cross-tenant function — its spanning behavior is asserted too,
and its docstring must say so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from core import db
from tests.conftest import TEST_DATABASE_URL


async def test_tasks_scoped(users_a_b):
    alice, bob = users_a_b
    a_task = await db.create_task(alice.id, "alice's task", source="user")
    b_task = await db.create_task(bob.id, "bob's task", source="user")

    assert (await db.get_task(bob.id, a_task.id)) is None
    assert (await db.get_task(alice.id, b_task.id)) is None
    assert [t.id for t in await db.list_tasks(alice.id)] == [a_task.id]
    assert [t.id for t in await db.list_tasks(bob.id)] == [b_task.id]

    # Cross-tenant update is a no-op, and the row is untouched:
    assert (await db.update_task(bob.id, a_task.id, status="done")) is None
    still = await db.get_task(alice.id, a_task.id)
    assert still.status == "pending"

    # Same-user update works:
    assert (await db.update_task(alice.id, a_task.id, status="done")).status == "done"


async def test_memories_scoped_identical_content(users_a_b):
    alice, bob = users_a_b
    content = "user prefers metric units"
    embedding = [0.1] * 384
    a_mem = await db.add_memory(alice.id, content, "preferences", embedding, 0.9)
    await db.add_memory(bob.id, content, "preferences", embedding, 0.9)

    a_results = await db.search_memories(alice.id, embedding, limit=10)
    b_results = await db.search_memories(bob.id, embedding, limit=10)

    assert [m.id for m in a_results] == [a_mem.id]
    assert all(m.user_id == alice.id for m in a_results)
    assert all(m.user_id == bob.id for m in b_results)
    # Same content+embedding for both users: each user's search surfaces only
    # their own row, and never the other's id.
    assert {m.id for m in a_results}.isdisjoint({m.id for m in b_results})


async def test_jobs_scoped_but_due_jobs_spans(users_a_b):
    alice, bob = users_a_b
    soon = datetime.now(UTC) - timedelta(minutes=1)
    a_job = await db.create_job(
        alice.id, "recurring", "*/5 * * * *", "always", "a's job", next_run_at=soon
    )
    b_job = await db.create_job(
        bob.id, "watcher", "*/5 * * * *", "on_change", "b's job", next_run_at=soon
    )

    assert [j.id for j in await db.list_jobs(alice.id)] == [a_job.id]
    assert [j.id for j in await db.list_jobs(bob.id)] == [b_job.id]
    assert (await db.get_job(bob.id, a_job.id)) is None
    assert (await db.update_job(bob.id, a_job.id, active=False)) is None
    assert (await db.get_job(alice.id, a_job.id)).active is True

    # The documented exception: due_jobs spans users BY DESIGN.
    due = await db.due_jobs(datetime.now(UTC))
    assert {j.id for j in due} == {a_job.id, b_job.id}
    assert "cross-tenant" in db.due_jobs.__doc__.lower()

    # Nothing is due before its time.
    assert await db.due_jobs(datetime.now(UTC) - timedelta(days=1)) == []


async def test_approvals_scoped(users_a_b):
    alice, bob = users_a_b
    a_ap = await db.record_approval(alice.id, None, "run http_request", {"risk": "moderate"})
    b_ap = await db.record_approval(bob.id, None, "delete file", {"risk": "moderate"})

    # Bob cannot resolve Alice's pending approval; it stays pending:
    assert (await db.update_approval(bob.id, a_ap.id, "approved")) is None
    assert (await db.get_task(alice.id, uuid4())) is None  # sanity: db up
    rows = await db._require_pool().fetch(
        "SELECT status FROM approvals WHERE id = $1", a_ap.id
    )
    assert rows[0]["status"] == "pending"

    # Alice decides her own:
    decided = await db.update_approval(alice.id, a_ap.id, "approved")
    assert decided.status == "approved" and decided.decided_at is not None
    # Double-decide (already resolved) is refused:
    assert (await db.update_approval(alice.id, a_ap.id, "denied")) is None
    assert (await db.update_approval(bob.id, b_ap.id, "denied")).status == "denied"


async def test_spend_and_api_costs_scoped(users_a_b):
    alice, bob = users_a_b
    await db.log_spend(alice.id, "example.com", Decimal("12.34"), approved_by="auto")
    await db.log_api_cost(alice.id, None, "claude-sonnet-4-5", 100, 50, Decimal("0.5"))
    await db.log_api_cost(bob.id, None, "claude-haiku-4-5", 10, 5, Decimal("0.05"))

    assert await db.spend_this_month(alice.id) == Decimal("12.34")
    assert await db.spend_this_month(bob.id) == Decimal("0")
    assert await db.cost_today(alice.id) == Decimal("0.5")
    assert await db.cost_today(bob.id) == Decimal("0.05")


async def test_usage_periods_scoped(users_a_b):
    alice, bob = users_a_b
    summary = await db.usage_this_period(alice.id)
    assert summary.total_cost == Decimal("0")
    assert summary.plan_tier == "free"
    assert summary.included_allowance == Decimal("5.00")

    start, end = summary.period_start, summary.period_end
    await db.upsert_usage_period(
        alice.id, start, end, Decimal("3.10"), Decimal("5.00"), Decimal("0")
    )
    await db.upsert_usage_period(
        bob.id, start, end, Decimal("9.99"), Decimal("5.00"), Decimal("4.99")
    )

    a_rows = await db._require_pool().fetch(
        "SELECT * FROM usage_periods WHERE user_id = $1", alice.id
    )
    assert len(a_rows) == 1 and a_rows[0]["total_cost"] == Decimal("3.10")
    # Upsert stays single-row:
    await db.upsert_usage_period(
        alice.id, start, end, Decimal("4.00"), Decimal("5.00"), Decimal("0")
    )
    a_rows = await db._require_pool().fetch(
        "SELECT * FROM usage_periods WHERE user_id = $1", alice.id
    )
    assert len(a_rows) == 1 and a_rows[0]["total_cost"] == Decimal("4.00")


async def test_vault_entries_scoped_same_site(users_a_b):
    alice, bob = users_a_b
    await db.create_vault_entry(alice.id, "example.com", b"alice-encrypted-blob")
    await db.create_vault_entry(bob.id, "example.com", b"bob-encrypted-blob")

    a_entry = await db.get_vault_entry(alice.id, "example.com")
    b_entry = await db.get_vault_entry(bob.id, "example.com")
    assert a_entry.encrypted_blob == b"alice-encrypted-blob"
    assert b_entry.encrypted_blob == b"bob-encrypted-blob"
    assert await db.list_vault_sites(alice.id) == ["example.com"]

    # Upsert overwrites the user's own value only:
    await db.create_vault_entry(alice.id, "example.com", b"alice-v2")
    assert (await db.get_vault_entry(bob.id, "example.com")).encrypted_blob == b"bob-encrypted-blob"


async def test_sessions_scoped(users_a_b, _make_session):
    alice, bob = users_a_b
    a_hash = await _make_session(alice.id)
    b_hash = await _make_session(bob.id)
    session_a, user_a = await db.get_session_by_token_hash(a_hash)
    session_b, user_b = await db.get_session_by_token_hash(b_hash)
    assert user_a.id == alice.id and user_b.id == bob.id
    assert session_a.user_id == alice.id

    # Expired sessions read as absent:
    expired_hash = await _make_session(alice.id, expires_in=-60)
    assert await db.get_session_by_token_hash(expired_hash) is None


@pytest.fixture
def _make_session(db_pool):
    from datetime import datetime, timedelta

    made: list[str] = []

    async def _make(user_id, expires_in: int = 3600) -> str:
        token_hash = uuid4().hex
        expires = datetime.now(UTC) + timedelta(seconds=expires_in)
        await db.create_session(user_id, token_hash, expires)
        made.append(token_hash)
        return token_hash

    return _make


async def test_migrations_idempotent(_test_database):
    applied = await db.apply_migrations(TEST_DATABASE_URL)
    assert applied == []  # everything already applied by the session fixture
