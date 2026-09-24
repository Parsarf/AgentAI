"""Router metering: cost lands on the right user; capped users are refused."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core import router
from core.router import ModelReply, UsageCapExceeded


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Replace the Anthropic client with a scripted fake."""
    calls: list[dict] = []

    def _make_reply(model: str, in_tok: int = 100, out_tok: int = 50):
        msg = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = "fake reply"
        msg.content = [block]
        usage = MagicMock()
        usage.input_tokens = in_tok
        usage.output_tokens = out_tok
        msg.usage = usage
        msg.stop_reason = "end_turn"
        return msg

    async def create(**kwargs):
        calls.append(kwargs)
        return _make_reply(kwargs.get("model", "m"))

    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=create)
    monkeypatch.setattr(router, "_get_client", lambda: client)
    return calls


async def test_cost_logged_to_right_user(users_a_b, fake_anthropic):
    alice, bob = users_a_b
    r1 = await router.call(alice.id, None, "cheap", [{"role": "user", "content": "hi"}])
    await router.call(bob.id, None, "cheap", [{"role": "user", "content": "hi"}])
    assert isinstance(r1, ModelReply) and r1.text == "fake reply"

    a_cost = await router.db.cost_today(alice.id)
    b_cost = await router.db.cost_today(bob.id)
    assert a_cost > 0 and b_cost > 0
    assert a_cost == b_cost  # identical call shape
    # …and usage summaries only see their own:
    assert (await router.db.usage_this_period(alice.id)).total_cost == a_cost


async def test_cap_blocks_with_clear_error(users_a_b, fake_anthropic):
    alice, bob = users_a_b
    plan = router.settings.plan_for("free")
    # Push alice over her plan's hard cap:
    await router.db.log_api_cost(
        alice.id, None, "claude-sonnet-4-5",
        1_000_000, 1_000_000, plan.hard_cap_usd + Decimal("1.00"),
    )
    with pytest.raises(UsageCapExceeded, match="usage cap reached"):
        await router.call(alice.id, None, "cheap", [{"role": "user", "content": "hi"}])
    # Bob is unaffected:
    reply = await router.call(bob.id, None, "cheap", [{"role": "user", "content": "hi"}])
    assert reply.text == "fake reply"
    # Alice's api_costs gained nothing new from the blocked call:
    assert len(fake_anthropic) == 1


async def test_unknown_model_uses_cautious_price(fake_anthropic, users_a_b):
    alice, _ = users_a_b
    # monkeypatching the settings model name is heavy; call _cost_usd directly:
    cautious = router._cost_usd("mystery-model", 1_000_000, 0)
    assert cautious >= Decimal("1.0")  # priced at the most expensive known input rate
