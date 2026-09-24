"""Phase 6 provider-independent purchase lifecycle, driven through the real
registry dispatch seam (tools.base.call_tool) with the TEST-ONLY fake
provider. Denial tests run before success tests in this file's order; every
denial asserts ZERO provider calls and (for preflight denials) ZERO approval
rows. No money moves — the fake records charges in memory only.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

import tools.payments  # noqa: F401  (registers the purchase tools)
from core import approvals, db, purchases
from core.config import settings
from core.purchases import ProviderOutcome
from tests.fake_provider import FakePurchaseProvider
from tests.p2_conftest import task_context
from tools import base

# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
def purchase_env(monkeypatch):
    """Runtime purchases switched ON for testing, with the TEST-ONLY fake
    installed. Always resets the provider to None (the production state)."""
    monkeypatch.setattr(settings.payments, "enabled", True)
    monkeypatch.setattr(settings.payments, "provider", "fake-test-only")
    monkeypatch.setattr(settings.payments, "execution_timeout_seconds", 5.0)
    yield
    purchases.set_provider(None)


@pytest.fixture
async def fake(purchase_env):
    provider = FakePurchaseProvider()
    purchases.set_provider(provider)
    return provider


async def setup_buyer(
    user,
    *,
    plan: str = "pro",
    opted_in: bool = True,
    connected: bool = True,
    allowlist: tuple[str, ...] = ("example.com",),
    tx_cap: str = "25.00",
    month_cap: str = "50.00",
    rules: dict | None = None,
) -> None:
    await db.update_user(user.id, plan_tier=plan)
    if rules is not None:
        await db.update_user(user.id, user_limits_json=rules)
    await db.save_purchase_policy(
        user.id, Decimal(tx_cap), Decimal(month_cap), list(allowlist)
    )
    if connected:
        await db.upsert_purchase_connection(user.id, "fake-test-only", "*4242")
    if opted_in:
        await db.set_purchase_opt_in(user.id, True)


def auto_rules() -> dict:
    return {
        "rules": [
            {"match": {"tools": ["make_purchase"], "source": "user"}, "action": "auto"},
            {"match": {"tools": ["make_purchase"], "source": "job"}, "action": "auto"},
        ]
    }


async def buy(merchant: str = "example.com", amount: str = "10.00", description: str = "a thing",
              source: str = "user", order_ref: str | None = None, user_id=None):
    args = {"merchant": merchant, "amount": amount, "description": description}
    if order_ref:
        args["order_ref"] = order_ref
    with task_context(user_id, str(uuid4()), source=source):
        return await base.call_tool("make_purchase", args)


async def pending_approval(user_id) -> dict | None:
    row = await db._require_pool().fetchrow(
        "SELECT * FROM approvals WHERE user_id=$1 AND status='pending'", user_id
    )
    return dict(row) if row else None


async def wait_for_pending(user_id, timeout: float = 2.0) -> dict | None:
    deadline = datetime.now(UTC) + timedelta(seconds=timeout)
    while datetime.now(UTC) < deadline:
        row = await pending_approval(user_id)
        if row is not None:
            return row
        await asyncio.sleep(0.02)
    return None


async def purchase_rows(user_id) -> list[dict]:
    return await db.recent_purchases(user_id, limit=20)


# --------------------------------------------------------------------------- #
# denial matrix — gates beyond the kill switch (runtime enabled, fake present)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kwargs, merchant, amount",
    [
        ({"plan": "free"}, "example.com", "10.00"),  # plan entitlement
        ({"opted_in": False}, "example.com", "10.00"),  # no opt-in
        ({"connected": False}, "example.com", "10.00"),  # no connection
        ({"tx_cap": "5.00"}, "example.com", "10.00"),  # over per-transaction cap
        ({"allowlist": ("shop.example.com",)}, "example.com", "10.00"),
    ],
)
async def test_gate_denials_never_call_provider_or_prompt(fake, users_a_b, kwargs, merchant, amount):
    alice, _ = users_a_b
    await setup_buyer(alice, **kwargs)
    result = await buy(user_id=alice.id, merchant=merchant, amount=amount)
    assert not result.ok
    assert fake.executions == []  # zero provider contact
    assert await db._require_pool().fetchval(
        "SELECT count(*) FROM approvals WHERE user_id=$1", alice.id
    ) == 0  # zero approval rows for preflight denials
    row = await db._require_pool().fetchrow(
        "SELECT outcome FROM purchase_attempts WHERE user_id=$1", alice.id
    )
    assert row["outcome"] == "denied"


async def test_deceptive_registrable_domain_is_denied(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice)
    result = await buy(user_id=alice.id, merchant="example.com.evil.net", amount="10.00")
    assert not result.ok
    assert "allowlist" in result.error
    assert fake.executions == []
    # substring matching must NOT have matched example.com:
    assert result.error != ""


async def test_monthly_cap_counts_reserved_and_settled(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules(), tx_cap="50.00", month_cap="50.00")
    ok = await buy(user_id=alice.id, amount="45.00", description="first")
    assert ok.ok
    over = await buy(user_id=alice.id, amount="10.00", description="second")
    assert not over.ok
    assert "monthly cap" in over.error
    assert len(fake.charges) == 1
    assert await db._require_pool().fetchval(
        "SELECT count(*) FROM approvals WHERE user_id=$1", alice.id
    ) == 0  # the cap denial is a preflight denial: no approval row was created


@pytest.mark.parametrize(
    "merchant",
    ["co.uk", "1.2.3.4", "user@example.com", "https://example.com", "example.com/path", "localhost"],
)
async def test_malformed_merchants_are_invalid_without_provider_calls(fake, users_a_b, merchant):
    alice, _ = users_a_b
    await setup_buyer(alice)
    result = await buy(user_id=alice.id, merchant=merchant)
    assert not result.ok
    assert fake.executions == []
    row = await db._require_pool().fetchrow(
        "SELECT outcome FROM purchase_attempts WHERE user_id=$1", alice.id
    )
    assert row["outcome"] == "invalid"


async def test_kill_switch_dominates_adapter_presence(monkeypatch, fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice)
    monkeypatch.setattr(settings.payments, "enabled", False)
    result = await buy(user_id=alice.id)
    assert not result.ok
    assert "disabled" in result.error
    assert fake.executions == []


async def test_adapter_absent_denies_even_when_enabled(monkeypatch, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice)
    monkeypatch.setattr(settings.payments, "enabled", True)
    monkeypatch.setattr(settings.payments, "provider", "fake-test-only")
    with task_context(alice.id, str(uuid4())):
        result = await base.call_tool(
            "make_purchase",
            {"merchant": "example.com", "amount": "10.00", "description": "x"},
        )
    assert not result.ok
    assert "adapter" in result.error


# --------------------------------------------------------------------------- #
# success paths
# --------------------------------------------------------------------------- #


async def test_interactive_auto_executes_within_explicit_rules(fake, users_a_b, notify_log):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    with task_context(alice.id, str(uuid4())):
        result = await base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "10.00", "description": "a thing"}
        )
    assert result.ok, result.error
    assert result.data["state"] == "succeeded"
    assert len(fake.charges) == 1 and fake.charges[0]["merchant"] == "example.com"
    assert await db._require_pool().fetchval(
        "SELECT count(*) FROM approvals WHERE user_id=$1", alice.id
    ) == 0  # auto path never prompts
    totals = await db.purchase_month_totals(alice.id, datetime.now(UTC).date().replace(day=1))
    assert totals["settled"] == Decimal("10.00")
    assert totals["reserved"] == Decimal("0")
    events = await db._require_pool().fetch(
        "SELECT event FROM purchase_events WHERE user_id=$1 ORDER BY id", alice.id
    )
    kinds = [r["event"] for r in events]
    assert "created" in kinds and "claimed" in kinds and "settled" in kinds
    assert [p["user_id"] for p in notify_log] == [str(alice.id)]  # owner-only notify


async def test_interactive_approval_owner_only_single_use(fake, users_a_b):
    alice, bob = users_a_b
    await setup_buyer(alice)  # default rules: high risk => require_approval
    with task_context(alice.id, str(uuid4())):
        task = asyncio.create_task(base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "10.00", "description": "a thing"}
        ))
        row = await wait_for_pending(alice.id)
        assert row is not None
        details = row["details_json"]
        assert details["kind"] == "purchase"
        assert details["merchant"] == "example.com"
        assert details["amount"] == "10.00" and details["currency"] == "USD"
        assert details["description"] == "a thing"
        assert details["expires_at"]
        # wrong user cannot decide
        assert not await approvals.decide(str(bob.id), str(row["id"]), True)
        assert await approvals.decide(str(alice.id), str(row["id"]), True)
        result = await task
    assert result.ok, result.error
    assert len(fake.charges) == 1
    # single-use: a second decision on the same approval is refused
    assert not await approvals.decide(str(alice.id), str(row["id"]), False)
    fresh = await db.get_purchase(alice.id, UUID(details["purchase_id"]))
    assert fresh["state"] == "succeeded"


async def test_job_purchase_requires_approval_despite_auto_rules(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    with task_context(alice.id, str(uuid4()), source="job"):
        task = asyncio.create_task(base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "10.00", "description": "job buy"}
        ))
        row = await wait_for_pending(alice.id)
        assert row is not None  # code-level floor: jobs never auto-approve
        assert fake.executions == []
        assert await approvals.decide(str(alice.id), str(row["id"]), True)
        result = await task
    assert result.ok
    assert len(fake.charges) == 1


async def test_job_purchase_timeout_denies_without_charge(fake, users_a_b, monkeypatch):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    monkeypatch.setattr(settings.limits, "approval_timeout_seconds", 0.2)
    with task_context(alice.id, str(uuid4()), source="job"):
        result = await base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "10.00", "description": "job buy"}
        )
    assert not result.ok
    assert "expired" in result.error
    assert fake.executions == []
    rows = await purchase_rows(alice.id)
    assert rows[0]["state"] == "expired"
    approval_row = await db._require_pool().fetchrow(
        "SELECT status FROM approvals WHERE user_id=$1", alice.id
    )
    assert approval_row["status"] == "expired"


async def test_prechecked_flag_is_never_purchase_permission(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice)  # rules require approval
    token = base.approvals_prechecked.set(True)
    try:
        with task_context(alice.id, str(uuid4())):
            task = asyncio.create_task(base.call_tool(
                "make_purchase",
                {"merchant": "example.com", "amount": "10.00", "description": "x"},
            ))
            row = await wait_for_pending(alice.id)
            assert row is not None  # the task-wide flag created no shortcut
            assert await approvals.decide(str(alice.id), str(row["id"]), True)
            result = await task
    finally:
        base.approvals_prechecked.reset(token)
    assert result.ok
    assert len(fake.charges) == 1


async def test_ambiguous_repeat_requires_approval(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    with task_context(alice.id, str(uuid4())):
        first = await base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "5.00", "description": "book"}
        )
        assert first.ok
        # same task, different item, no order identity: must NOT auto-charge
        task = asyncio.create_task(base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "5.00", "description": "pen"}
        ))
        row = await wait_for_pending(alice.id)
        assert row is not None
        assert await approvals.decide(str(alice.id), str(row["id"]), True)
        second = await task
    assert second.ok
    assert len(fake.charges) == 2


async def test_duplicate_invocation_resumes_never_double_charges(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    with task_context(alice.id, str(uuid4())):
        args = {"merchant": "example.com", "amount": "10.00", "description": "a thing"}
        first = await base.call_tool("make_purchase", args)
        second = await base.call_tool("make_purchase", args)
    assert first.ok and not second.ok
    assert "already reached 'succeeded'" in second.error
    assert len(fake.charges) == 1
    rows = await purchase_rows(alice.id)
    assert len(rows) == 1


async def test_concurrent_cap_check_single_claim_wins(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules(), tx_cap="10.00", month_cap="10.00")
    async def one():
        return await buy(user_id=alice.id, amount="6.00", description="concurrent")
    results = await asyncio.gather(one(), one())
    oks = [r.ok for r in results]
    assert sorted(oks) == [False, True]  # exactly one claim wins
    assert len(fake.charges) == 1
    states = [row["state"] for row in await purchase_rows(alice.id)]
    # the loser is denied either at preflight (no row yet — the winner's
    # reservation already consumed the cap) or at the locked claim itself;
    # either way it never reached the provider:
    assert states.count("succeeded") == 1
    assert not ({"executing", "unknown", "failed"} & set(states))
    totals = await db.purchase_month_totals(
        alice.id, datetime.now(UTC).date().replace(day=1)
    )
    assert totals["settled"] == Decimal("6.00")


async def test_changed_details_under_one_order_ref_rejected(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    with task_context(alice.id, str(uuid4())):
        args = {"merchant": "example.com", "amount": "10.00",
                "description": "a thing", "order_ref": "order-1"}
        first = await base.call_tool("make_purchase", args)
        changed = await base.call_tool(
            "make_purchase",
            {"merchant": "example.com", "amount": "10.00",
             "description": "different item", "order_ref": "order-1"},
        )
        replay = await base.call_tool("make_purchase", args)
    assert first.ok
    assert not changed.ok and "changed details" in changed.error
    assert not replay.ok and "already reached 'succeeded'" in replay.error
    assert len(fake.charges) == 1


# --------------------------------------------------------------------------- #
# lifecycle: unknown, reconciliation, month boundaries
# --------------------------------------------------------------------------- #


async def test_timeout_becomes_unknown_and_holds_reservation(fake, users_a_b, monkeypatch):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules(), month_cap="10.00")
    monkeypatch.setattr(settings.payments, "execution_timeout_seconds", 0.05)
    fake.delay = 0.5  # provider stalls past the wall clock
    with task_context(alice.id, str(uuid4())):
        result = await base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "10.00", "description": "x"}
        )
    assert not result.ok and "UNKNOWN" in result.error
    assert fake.charges == []  # provider never confirmed
    rows = await purchase_rows(alice.id)
    assert rows[0]["state"] == "unknown"
    month = datetime.now(UTC).date().replace(day=1)
    totals = await db.purchase_month_totals(alice.id, month)
    assert totals["reserved"] == Decimal("10.00")  # budget stays reserved
    # the held reservation caps any further purchase this month:
    blocked = await buy(user_id=alice.id, amount="5.00", description="retry?")
    assert not blocked.ok
    assert "monthly cap" in blocked.error
    assert fake.charges == []


async def test_provider_success_then_db_failure_reconciles_once(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    task_id = str(uuid4())
    purchase = await db.create_purchase(
        alice.id, task_id, "user", "key-crash-1", "example.com", "example.com",
        Decimal("10.00"), "USD", "a thing", 1, None, "ready", None,
    )
    claim = await db.claim_purchase(
        alice.id, purchase["id"], "example.com", Decimal("10.00"), datetime.now(UTC)
    )
    assert claim["kind"] == "claimed"
    await fake.execute(alice.id, claim["purchase"], str(purchase["id"]))  # provider accepted
    # ...crash before persisting: the row is stuck in `executing`
    resolved = await purchases.reconcile_pending()
    assert resolved == 1
    fresh = await db.get_purchase(alice.id, purchase["id"])
    assert fresh["state"] == "succeeded" and fresh["provider_ref"]
    assert len(fake.charges) == 1  # no double charge
    assert await purchases.reconcile_pending() == 0  # idempotent second pass


async def test_unknown_resolved_by_lookup_keeps_original_month(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    month = datetime.now(UTC).date().replace(day=1)
    purchase = await db.create_purchase(
        alice.id, str(uuid4()), "user", "key-unknown-1", "example.com", "example.com",
        Decimal("7.00"), "USD", "a thing", 1, None, "executing", None,
    )
    await db._require_pool().execute(
        "UPDATE purchases SET reservation_month=$2 WHERE id=$1", purchase["id"], month
    )
    fake.remember(
        str(purchase["id"]),
        ProviderOutcome(status="succeeded", provider_ref="fake_x", recipient="example.com"),
    )
    fake.charges.append({"key": str(purchase["id"]), "user_id": str(alice.id),
                         "merchant": "example.com", "amount": "7.00"})
    assert await purchases.reconcile_pending() == 1
    fresh = await db.get_purchase(alice.id, purchase["id"])
    assert fresh["state"] == "succeeded"
    totals = await db.purchase_month_totals(alice.id, month)
    assert totals["settled"] == Decimal("7.00")


async def test_unknown_beyond_retention_stays_unresolved(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    month = datetime.now(UTC).date().replace(day=1)
    purchase = await db.create_purchase(
        alice.id, str(uuid4()), "user", "key-old", "example.com", "example.com",
        Decimal("7.00"), "USD", "a thing", 1, None, "unknown", None,
    )
    await db._require_pool().execute(
        "UPDATE purchases SET reservation_month=$2 WHERE id=$1", purchase["id"], month
    )
    fake.retention_expired = True  # provider no longer knows the key
    assert await purchases.reconcile_pending() == 0
    fresh = await db.get_purchase(alice.id, purchase["id"])
    assert fresh["state"] == "unknown"  # NOT aged away, NOT re-charged
    totals = await db.purchase_month_totals(alice.id, month)
    assert totals["reserved"] == Decimal("7.00")


async def test_month_boundary_retry_keeps_its_own_period(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules(), month_cap="10.00")
    this_month = datetime.now(UTC).date().replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    old = await db.create_purchase(
        alice.id, str(uuid4()), "user", "key-last-month", "example.com", "example.com",
        Decimal("5.00"), "USD", "old", 1, None, "unknown", None,
    )
    await db._require_pool().execute(
        "UPDATE purchases SET reservation_month=$2 WHERE id=$1", old["id"], last_month
    )
    # last month's unknown must not consume THIS month's cap:
    result = await buy(user_id=alice.id, amount="8.00", description="new month")
    assert result.ok, result.error
    fake.remember(
        str(old["id"]),
        ProviderOutcome(status="succeeded", provider_ref="old", recipient="example.com"),
    )
    assert await purchases.reconcile_pending() == 1
    settled_old = await db.get_purchase(alice.id, old["id"])
    assert settled_old["state"] == "succeeded"
    assert settled_old["reservation_month"] == last_month  # preserved, not rolled
    now_totals = await db.purchase_month_totals(alice.id, this_month)
    assert now_totals["settled"] == Decimal("8.00")
    old_totals = await db.purchase_month_totals(alice.id, last_month)
    assert old_totals["settled"] == Decimal("5.00")


# --------------------------------------------------------------------------- #
# approval-time recheck: opt-out / disconnect / recipient binding
# --------------------------------------------------------------------------- #


async def test_opt_out_during_approval_blocks_execution(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice)
    with task_context(alice.id, str(uuid4())):
        task = asyncio.create_task(base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "10.00", "description": "x"}
        ))
        row = await wait_for_pending(alice.id)
        await db.set_purchase_opt_in(alice.id, False)  # opted out while waiting
        assert await approvals.decide(str(alice.id), str(row["id"]), True)
        result = await task
    assert not result.ok
    assert fake.executions == []
    fresh = (await purchase_rows(alice.id))[0]
    assert fresh["state"] == "denied"


async def test_disconnect_during_approval_blocks_execution(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice)
    with task_context(alice.id, str(uuid4())):
        task = asyncio.create_task(base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "10.00", "description": "x"}
        ))
        row = await wait_for_pending(alice.id)
        await db.revoke_purchase_connection(alice.id)  # disconnect bumps version
        assert await approvals.decide(str(alice.id), str(row["id"]), True)
        result = await task
    assert not result.ok
    assert "connection changed" in result.error
    assert fake.executions == []


async def test_kill_switch_during_approval_blocks_execution(fake, users_a_b, monkeypatch):
    alice, _ = users_a_b
    await setup_buyer(alice)
    with task_context(alice.id, str(uuid4())):
        task = asyncio.create_task(base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "10.00", "description": "x"}
        ))
        row = await wait_for_pending(alice.id)
        monkeypatch.setattr(settings.payments, "enabled", False)
        assert await approvals.decide(str(alice.id), str(row["id"]), True)
        result = await task
    assert not result.ok
    assert fake.executions == []
    assert (await purchase_rows(alice.id))[0]["state"] == "denied"


async def test_provider_recipient_mismatch_fails_closed(fake, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    fake.script(
        "example.com",
        ProviderOutcome(status="succeeded", provider_ref="fake_evil", recipient="other.com"),
    )
    result = await buy(user_id=alice.id)
    assert not result.ok
    fresh = (await purchase_rows(alice.id))[0]
    assert fresh["state"] == "unknown"  # provider may have moved money
    month = datetime.now(UTC).date().replace(day=1)
    totals = await db.purchase_month_totals(alice.id, month)
    assert totals["settled"] == Decimal("0")
    assert totals["reserved"] == Decimal("10.00")
    assert await purchases.reconcile_pending() == 0  # mismatch cannot free budget
    assert (await purchase_rows(alice.id))[0]["state"] == "unknown"


# --------------------------------------------------------------------------- #
# status tool + tenant isolation
# --------------------------------------------------------------------------- #


async def test_status_returns_own_totals_receipts_and_no_credentials(fake, users_a_b):
    alice, bob = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    ok = await buy(user_id=alice.id, amount="10.00")
    assert ok.ok
    stuck = await db.create_purchase(
        alice.id, str(uuid4()), "user", "key-s-1", "example.com", "example.com",
        Decimal("5.00"), "USD", "stuck", 1, None, "unknown", None,
    )
    await db._require_pool().execute(
        "UPDATE purchases SET reservation_month=$2 WHERE id=$1",
        stuck["id"], datetime.now(UTC).date().replace(day=1),
    )
    with task_context(bob.id, str(uuid4())):
        bob_status = await base.call_tool("check_spend_status")
    with task_context(alice.id, str(uuid4())):
        status = await base.call_tool("check_spend_status")
    assert bob_status.ok and bob_status.data["recent_purchases"] == []
    assert bob_status.data["settled_this_month_usd"] == "0.00"
    data = status.data
    assert data["settled_this_month_usd"] == "10.00"
    assert data["reserved_or_unknown_usd"] == "5.00"
    assert data["remaining_monthly_usd"] == "35.00"
    assert {r["state"] for r in data["recent_purchases"]} == {"succeeded", "unknown"}
    blob = str(data)
    assert "4242" not in blob and "token" not in blob.lower() and "password" not in blob.lower()


# --------------------------------------------------------------------------- #
# scheduler-tick reconciliation
# --------------------------------------------------------------------------- #


async def test_scheduler_tick_reconciles_pending_purchases(fake, scheduler, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    purchase = await db.create_purchase(
        alice.id, str(uuid4()), "user", "key-tick", "example.com", "example.com",
        Decimal("3.00"), "USD", "tick", 1, None, "executing", None,
    )
    fake.remember(
        str(purchase["id"]),
        ProviderOutcome(status="succeeded", provider_ref="t", recipient="example.com"),
    )
    await scheduler.tick()
    fresh = await db.get_purchase(alice.id, purchase["id"])
    assert fresh["state"] == "succeeded"


async def test_scheduler_tick_without_provider_leaves_rows_unresolved(scheduler, users_a_b):
    alice, _ = users_a_b
    await setup_buyer(alice, rules=auto_rules())
    purchase = await db.create_purchase(
        alice.id, str(uuid4()), "user", "key-notick", "example.com", "example.com",
        Decimal("3.00"), "USD", "tick", 1, None, "executing", None,
    )
    await scheduler.tick()
    fresh = await db.get_purchase(alice.id, purchase["id"])
    assert fresh["state"] == "executing"  # flagged, never aged away or charged


# --------------------------------------------------------------------------- #
# web settings flow: opt-in / opt-out (CSRF, explicit confirmation)
# --------------------------------------------------------------------------- #


async def test_web_opt_in_requires_connection_and_confirmation(db_pool, users_a_b):
    import httpx

    from gateway.web_app import _csrf_token, app

    alice, _ = users_a_b
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        from core import auth as auth_mod

        token = await auth_mod.login("alice@example.com", "correct horse battery", ip="test")
        client.cookies.set("agent_session", token.token)
        csrf = _csrf_token(str(alice.id))

        # no connection yet → fail closed
        r = await client.post(
            "/settings/purchases/opt-in", data={"confirm": "yes", "csrf": csrf}
        )
        assert r.status_code == 409

        # connection exists but no explicit confirmation → refused
        await db.upsert_purchase_connection(alice.id, "fake-test-only", "*4242")
        r = await client.post("/settings/purchases/opt-in", data={"csrf": csrf})
        assert r.status_code == 400

        # connection + explicit confirmation → opted in
        r = await client.post(
            "/settings/purchases/opt-in", data={"confirm": "yes", "csrf": csrf}
        )
        assert r.status_code == 303
        policy = await db.get_purchase_policy(alice.id)
        assert policy["opted_in"] is True

        # bad CSRF refused
        r = await client.post(
            "/settings/purchases/opt-in", data={"confirm": "yes", "csrf": "nope"}
        )
        assert r.status_code == 403

        # opt-out revokes the connection too
        r = await client.post("/settings/purchases/opt-out", data={"csrf": csrf})
        assert r.status_code == 303
        policy = await db.get_purchase_policy(alice.id)
        connection = await db.get_purchase_connection(alice.id)
        assert policy["opted_in"] is False
        assert connection["status"] == "revoked"
