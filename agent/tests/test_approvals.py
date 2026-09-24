"""The approvals matrix: same call, different users → different decisions;
mode floor; plan floor; decisions only by the owner; timeout denies."""

from __future__ import annotations

import pytest

from core import approvals
from tests.p2_conftest import task_context  # noqa: F401


async def _override_rules(user_id, rules: list[dict], fallback: str | None = None):
    doc: dict = {"rules": rules}
    if fallback:
        doc["fallback"] = fallback
    from core import db

    await db.update_user(user_id, user_limits_json=doc)


@pytest.fixture
def tool_registered():
    from tools import base as tb

    if "p2_app_gate" not in tb.registry.all():

        @tb.tool("p2_app_gate", "gated tool", risk="moderate")
        async def p2_app_gate(action: str) -> str:
            return f"did {action}"


async def test_stricter_user_requires_approval_while_looser_auto(users_a_b, tool_registered):
    alice, bob = users_a_b
    # Bob tightens: everything requires approval.
    await _override_rules(
        bob.id, [{"match": {"risk": "moderate", "source": "any"}, "action": "require_approval"}]
    )

    d_alice = await approvals.check(alice.id, "p2_app_gate", {"action": "x"}, "moderate", "user")
    d_bob = await approvals.check(bob.id, "p2_app_gate", {"action": "x"}, "moderate", "user")
    assert d_alice.action == "auto_and_log"   # default rules
    assert d_bob.action == "require_approval"  # his own override


async def test_mode_floor_job_cannot_loosen(users_a_b):
    alice, _ = users_a_b
    # Alice tries to auto-approve moderate tools even from jobs:
    await _override_rules(alice.id, [{"match": {"risk": "moderate", "source": "job"}, "action": "auto"}])
    d = await approvals.check(alice.id, "p2_app_gate", {"action": "x"}, "moderate", "job")
    assert d.action == "require_approval"  # floor wins


async def test_plan_floor_browser_denied_on_free(users_a_b):
    alice, _ = users_a_b  # free tier
    d = await approvals.check(alice.id, "browser_open", {"url": "https://x.com"}, "moderate", "user")
    assert d.action == "deny"
    assert "plan" in d.reason


async def test_high_risk_from_job_denied_by_default_rules(users_a_b):
    alice, _ = users_a_b
    d = await approvals.check(alice.id, "p2_app_gate", {}, "high", "job")
    assert d.action == "deny"


async def test_wrong_user_cannot_decide_and_timeout_denies(users_a_b):
    import asyncio
    from uuid import UUID

    from core import db

    alice, bob = users_a_b

    class _Waiter:
        def __init__(self):
            self.approved = None

    waiter = _Waiter()

    async def wait_for_decision():
        waiter.approved = await approvals.request_and_wait(
            alice.id, None, "p2_app_gate: do a thing", {"tool": "p2_app_gate"}
        )

    task = asyncio.get_running_loop().create_task(wait_for_decision())
    await asyncio.sleep(0.05)

    # Bob (wrong user) attempts to approve Alice's request:
    rows = await db._require_pool().fetch(
        "SELECT id FROM approvals WHERE user_id = $1 AND status='pending'", alice.id
    )
    approval_id = str(rows[0]["id"])
    ok = await approvals.decide(bob.id, approval_id, True)
    assert ok is False  # refused
    row = await db._require_pool().fetchrow("SELECT status FROM approvals WHERE id=$1", UUID(approval_id))
    assert row["status"] == "pending"  # unchanged

    # Alice approves her own:
    ok = await approvals.decide(alice.id, approval_id, True)
    assert ok is True
    await asyncio.wait_for(task, timeout=5)
    assert waiter.approved is True


async def test_timeout_defaults_to_deny(users_a_b, monkeypatch):
    alice, _ = users_a_b
    from core.config import settings

    monkeypatch.setattr(settings.limits, "approval_timeout_seconds", 1)
    approved = await approvals.request_and_wait(
        alice.id, None, "p2_app_gate: slow thing", {}
    )
    assert approved is False
    rows = await db._require_pool().fetch(
        "SELECT status FROM approvals WHERE user_id = $1", alice.id
    )
    assert rows[0]["status"] == "expired"


async def test_unknown_amount_rules_do_not_block_safe_free_tools(users_a_b):
    alice, _ = users_a_b
    d = await approvals.check(alice.id, "web_search", {"query": "x"}, "safe", "job")
    # safe tools aren't gated at all by callers, but check() still answers:
    assert d.action in ("auto", "auto_and_log")


from core import db  # noqa: E402
