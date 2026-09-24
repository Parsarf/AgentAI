"""Phase 5: actual SDK ledger wiring, concurrent cap, and Stripe state."""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import stripe
from claude_agent_sdk import ResultMessage

from core import billing, db, events, orchestrator, router
from core.config import settings
from gateway import web_app


async def test_concurrent_reservations_respect_one_users_cap(users_a_b):
    alice, bob = users_a_b
    await db.log_api_cost(alice.id, None, "seed", cost_usd=Decimal("9.90"))
    answers = await asyncio.gather(
        db.reserve_budget(alice.id, None, "one", Decimal("0.08"), False),
        db.reserve_budget(alice.id, None, "two", Decimal("0.08"), False),
    )
    assert sorted(answers) == [Decimal("0"), Decimal("0.08")]
    assert await db.reserve_budget(bob.id, None, "bob", Decimal("0.08"), False) == Decimal("0.08")
    key = "one" if answers[0] else "two"
    assert await db.settle_budget(alice.id, key, "model", 0, 0, Decimal("0.04"))
    assert not await db.settle_budget(alice.id, key, "model", 0, 0, Decimal("0.04"))
    assert (await db.usage_this_period(alice.id)).total_cost == Decimal("9.94")
    assert await db.reserved_this_period(alice.id) == 0
    assert (await db.usage_this_period(bob.id)).total_cost == 0


async def test_actual_sdk_loop_records_result_once(users_a_b, monkeypatch, tmp_path):
    alice, _ = users_a_b
    task = await db.create_task(alice.id, "tiny task", "user")
    async def fake_context(*_args):
        return "system", [{"role": "user", "content": "tiny task"}]
    async def fake_start(*_args):
        return Path(tmp_path)
    async def fake_query(*, prompt, options):
        assert prompt == "tiny task"
        assert options.max_budget_usd > 0
        assert options.can_use_tool is not None
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1,
            is_error=False, num_turns=1, session_id="fake", result="done",
            total_cost_usd=0.004,
            model_usage={"claude-sonnet-5": {
                "inputTokens": 100, "outputTokens": 20,
                "cacheReadInputTokens": 40, "cacheCreationInputTokens": 10,
                "costUSD": 0.004,
            }},
        )
    import claude_agent_sdk
    monkeypatch.setattr(orchestrator, "build_context", fake_context)
    monkeypatch.setattr(orchestrator.sandbox, "start_task_sandbox", fake_start)
    monkeypatch.setattr(orchestrator, "get_sdk_mcp_server", lambda: {})
    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    await orchestrator._loop(alice.id, task.id, alice, task, "user", 2)
    assert (await db.get_task(alice.id, task.id)).status == "done"
    assert await db.task_cost(alice.id, task.id) == Decimal("0.004")
    assert (await billing.usage_this_period(alice.id)).total_cost == Decimal("0.004")
    assert await db.reserved_this_period(alice.id) == 0


async def test_sdk_setup_failure_releases_unsubmitted_budget(users_a_b, monkeypatch):
    alice, _ = users_a_b
    task = await db.create_task(alice.id, "setup failure", "user")
    async def fake_context(*_args):
        return "system", [{"role": "user", "content": "setup failure"}]
    async def fail_before_model(*_args):
        raise RuntimeError("sandbox unavailable")
    monkeypatch.setattr(orchestrator, "build_context", fake_context)
    monkeypatch.setattr(orchestrator.sandbox, "start_task_sandbox", fail_before_model)
    with pytest.raises(RuntimeError, match="sandbox unavailable"):
        await orchestrator._loop(alice.id, task.id, alice, task, "user", 2)
    assert await db.reserved_this_period(alice.id) == 0


async def test_ambiguous_router_failure_keeps_budget_reserved(users_a_b, monkeypatch):
    alice, _ = users_a_b
    async def fail_after_submission(**_kwargs):
        raise RuntimeError("connection lost after send")
    client = SimpleNamespace(messages=SimpleNamespace(create=fail_after_submission))
    monkeypatch.setattr(router, "_get_client", lambda: client)
    with pytest.raises(RuntimeError, match="connection lost"):
        await router.call(alice.id, None, "cheap", [{"role": "user", "content": "hi"}], max_tokens=8)
    assert await db.reserved_this_period(alice.id) > 0
    row = await db._require_pool().fetchrow(
        "SELECT state FROM budget_reservations WHERE user_id = $1", alice.id
    )
    assert row["state"] == "unknown"


def test_sdk_cost_normalizes_cache_and_missing_usage():
    msg = SimpleNamespace(model_usage={"m": {
        "costUSD": 0.0045, "inputTokens": 10, "outputTokens": 2,
        "cacheReadInputTokens": 100, "cacheCreationInputTokens": 10,
    }}, total_cost_usd=0.9, usage={})
    assert orchestrator._sdk_result_cost(msg) == (Decimal("0.004500"), 10, 2)
    empty = SimpleNamespace(model_usage=None, total_cost_usd=None, usage=None)
    assert orchestrator._sdk_result_cost(empty)[0] is None


async def test_90_percent_warning_is_once(users_a_b):
    alice, _ = users_a_b
    seen = []
    async def on_notice(p):
        seen.append(p)
    await events.subscribe(events.NOTIFY_USER, on_notice)
    await db.log_api_cost(alice.id, None, "seed", cost_usd=Decimal("9.10"))
    await billing.require_capacity(alice.id)
    await billing.require_capacity(alice.id)
    assert len(seen) == 1
    assert seen[0]["user_id"] == str(alice.id)


async def test_queued_task_obeys_downgraded_concurrency(users_a_b):
    alice, _ = users_a_b
    await db.update_user(alice.id, plan_tier="pro")
    entered = asyncio.Event()
    release = asyncio.Event()
    async def first():
        async with orchestrator._user_slot(str(alice.id)):
            entered.set()
            await release.wait()
    first_task = asyncio.create_task(first())
    await asyncio.wait_for(entered.wait(), 2)
    await db.update_user(alice.id, plan_tier="free")
    second_entered = asyncio.Event()
    async def second():
        async with orchestrator._user_slot(str(alice.id)):
            second_entered.set()
    second_task = asyncio.create_task(second())
    await asyncio.sleep(0.05)
    assert not second_entered.is_set()
    release.set()
    await asyncio.wait_for(asyncio.gather(first_task, second_task), 2)
    assert second_entered.is_set()


async def test_verified_webhook_is_idempotent_and_downgrades(users_a_b, monkeypatch):
    alice, bob = users_a_b
    await db.set_stripe_customer(alice.id, "cus_alice")
    monkeypatch.setattr(settings.billing, "enabled", True)
    monkeypatch.setattr(settings.plans.tiers["pro"], "stripe_price_id", "price_pro")
    monkeypatch.setattr(settings.secrets, "stripe_webhook_secret", "whsec_test")
    listing = {"data": [{"id": "sub_a", "customer": "cus_alice", "status": "active",
                         "created": 1, "items": {"data": [{"price": {"id": "price_pro"}}]}}]}
    client = SimpleNamespace(v1=SimpleNamespace(subscriptions=SimpleNamespace(
        list_async=lambda *_args: asyncio.sleep(0, result=listing))))
    monkeypatch.setattr(billing, "_stripe_client", lambda: client)
    event = {"id": "evt_one", "type": "customer.subscription.updated",
             "data": {"object": {"customer": "cus_alice"}}}
    assert await billing.handle_stripe_webhook(event)
    assert not await billing.handle_stripe_webhook(event)
    assert (await db.get_user(alice.id)).plan_tier == "pro"
    assert (await db.get_user(bob.id)).plan_tier == "free"
    await db.update_user(alice.id, status="suspended")
    listing["data"][0]["status"] = "canceled"
    event["id"] = "evt_two"
    event["type"] = "customer.subscription.deleted"
    assert await billing.handle_stripe_webhook(event)
    assert (await db.get_user(alice.id)).plan_tier == "free"
    assert (await db.get_user(alice.id)).status == "suspended"


async def test_webhook_rejects_invalid_signature_before_lookup(users_a_b, monkeypatch):
    before = await db._require_pool().fetchval("SELECT COUNT(*) FROM processed_stripe_events")
    monkeypatch.setattr(settings.billing, "enabled", True)
    monkeypatch.setattr(settings.secrets, "stripe_webhook_secret", "whsec_test")
    body = json.dumps({"id": "evt_bad", "type": "customer.subscription.updated",
                       "data": {"object": {"customer": "cus_other"}}})
    transport = httpx.ASGITransport(app=web_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/webhooks/stripe", content=body,
                                     headers={"stripe-signature": "bad"})
    assert response.status_code == 400
    assert await db._require_pool().fetchval("SELECT COUNT(*) FROM processed_stripe_events") == before


async def test_signed_webhook_route_and_checkout_are_user_scoped(users_a_b, monkeypatch):
    alice, bob = users_a_b
    monkeypatch.setattr(settings.billing, "enabled", True)
    monkeypatch.setattr(settings.secrets, "stripe_webhook_secret", "whsec_test")
    monkeypatch.setattr(settings.plans.tiers["pro"], "stripe_price_id", "price_pro")
    calls = []
    async def create_customer(params, options):
        calls.append(("customer", params, options))
        return SimpleNamespace(id="cus_alice")
    async def create_checkout(params, options):
        calls.append(("checkout", params, options))
        return SimpleNamespace(id="cs_one", url="https://checkout.stripe.com/test/one")
    async def retrieve_checkout(_id):
        return SimpleNamespace(status="open", url="https://checkout.stripe.com/test/one")
    listing = {"data": [{"id": "sub_a", "customer": "cus_alice", "status": "active",
                         "created": 1, "items": {"data": [{"price": {"id": "price_pro"}}]}}]}
    async def list_subscriptions(_params):
        return listing
    fake = SimpleNamespace(v1=SimpleNamespace(
        customers=SimpleNamespace(create_async=create_customer),
        checkout=SimpleNamespace(sessions=SimpleNamespace(
            create_async=create_checkout, retrieve_async=retrieve_checkout)),
        subscriptions=SimpleNamespace(list_async=list_subscriptions),
    ))
    monkeypatch.setattr(billing, "_stripe_client", lambda: fake)
    url = await billing.start_checkout(alice.id, "pro", "op_one")
    assert url.startswith("https://checkout.stripe.com/")
    assert await billing.start_checkout(alice.id, "pro", "op_one") == url
    assert len([call for call in calls if call[0] == "checkout"]) == 1
    assert (await db.get_user(bob.id)).stripe_customer_id is None

    body = json.dumps({"id": "evt_signed", "type": "checkout.session.completed",
                       "data": {"object": {"customer": "cus_alice"}}})
    timestamp = int(time.time())
    signature = stripe.WebhookSignature._compute_signature(f"{timestamp}.{body}", "whsec_test")
    transport = httpx.ASGITransport(app=web_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/webhooks/stripe", content=body,
                                     headers={"stripe-signature": f"t={timestamp},v1={signature}"})
    assert response.status_code == 200
    assert (await db.get_user(alice.id)).plan_tier == "pro"
    assert (await db.get_user(bob.id)).plan_tier == "free"
