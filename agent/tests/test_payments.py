"""Phase 6 fail-closed purchase boundary while no merchant provider is configured."""

from __future__ import annotations

import pytest

import tools.payments  # noqa: F401
from core import db
from core.config import settings
from tests.p2_conftest import task_context
from tools import base


@pytest.mark.parametrize("amount", ["0", "-1", "nan", "Infinity", "1.001", "oops"])
async def test_invalid_amount_never_prompts_or_purchases(pro_users, amount):
    alice, _ = pro_users
    with task_context(alice.id):
        result = await base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": amount, "description": "thing"}
        )
    assert not result.ok
    assert await db._require_pool().fetchval("SELECT count(*) FROM approvals WHERE user_id=$1", alice.id) == 0


@pytest.mark.parametrize("plan", ["free", "pro"])
async def test_purchase_provider_disabled_and_audited_for_each_user(users_a_b, plan):
    assert not settings.payments.enabled
    alice, bob = users_a_b
    await db.update_user(alice.id, plan_tier=plan)
    for user in (alice, bob):
        with task_context(user.id):
            result = await base.call_tool(
                "make_purchase", {"merchant": "example.com", "amount": "1.00", "description": "thing"}
            )
        assert not result.ok
        assert (
            await db._require_pool().fetchval("SELECT count(*) FROM approvals WHERE user_id=$1", user.id) == 0
        )
        assert (
            await db._require_pool().fetchval(
                "SELECT count(*) FROM purchase_attempts WHERE user_id=$1", user.id
            )
            == 1
        )


async def test_status_is_tenant_scoped(users_a_b):
    alice, bob = users_a_b
    with task_context(alice.id):
        await base.call_tool(
            "make_purchase", {"merchant": "example.com", "amount": "1.00", "description": "thing"}
        )
    with task_context(bob.id):
        status = await base.call_tool("check_spend_status")
    assert status.ok
    assert status.data["recent_attempts"] == []
    assert status.data["purchases_available"] is False


@pytest.mark.parametrize("merchant", ["https://example.com", "user@example.com", "example.com/path"])
async def test_deceptive_merchant_is_invalid_without_approval(pro_users, merchant):
    alice, _ = pro_users
    with task_context(alice.id):
        result = await base.call_tool(
            "make_purchase", {"merchant": merchant, "amount": "1.00", "description": "thing"}
        )
    assert not result.ok
    assert await db._require_pool().fetchval("SELECT count(*) FROM approvals WHERE user_id=$1", alice.id) == 0
    row = await db._require_pool().fetchrow(
        "SELECT outcome FROM purchase_attempts WHERE user_id=$1", alice.id
    )
    assert row["outcome"] == "invalid"


async def test_unsupported_currency_and_job_mode_never_prompt(pro_users):
    alice, _ = pro_users
    with task_context(alice.id, source="job"):
        result = await base.call_tool(
            "make_purchase",
            {"merchant": "example.com", "amount": "1.00", "description": "thing", "currency": "EUR"},
        )
    assert not result.ok
    assert "USD" in result.error
    assert await db._require_pool().fetchval("SELECT count(*) FROM approvals WHERE user_id=$1", alice.id) == 0


async def test_prechecked_flag_does_not_enable_payment(pro_users):
    alice, _ = pro_users
    token = base.approvals_prechecked.set(True)
    try:
        with task_context(alice.id):
            result = await base.call_tool(
                "make_purchase", {"merchant": "example.com", "amount": "1.00", "description": "thing"}
            )
    finally:
        base.approvals_prechecked.reset(token)
    assert not result.ok
    assert await db._require_pool().fetchval("SELECT count(*) FROM approvals WHERE user_id=$1", alice.id) == 0
