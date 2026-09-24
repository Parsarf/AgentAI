"""Model calls, metered per user.

Roles (planner/worker/cheap) map to model IDs from settings. Every call
checks the user's plan hard cap BEFORE spending, logs exact token counts and
Decimal cost to the user's api_costs, and publishes usage.updated. A user at
their cap gets a clear refusal — never a silent degraded call.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

import anthropic

from core import billing, db, events, secrets_vault
from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

_client: anthropic.AsyncAnthropic | None = None


UsageCapExceeded = billing.UsageCapExceeded


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.require("anthropic_api_key"))
    return _client


@dataclass
class ModelReply:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    stop_reason: str | None = None
    raw: object = None  # full anthropic.Message when available


def _price_for(model: str) -> tuple[Decimal, Decimal]:
    prices = settings.model_prices.get(model)
    if prices is None:
        # Unknown model: fall back to the most expensive configured price so
        # metering errs on the cautious side, and say so in the log.
        top = max(
            settings.model_prices.values(),
            key=lambda p: p.input_per_mtok_usd + p.output_per_mtok_usd,
            default=None,
        )
        logger.warning("no price configured for model", extra={"model": model})
        if top is None:
            return Decimal("0"), Decimal("0")
        return top.input_per_mtok_usd, top.output_per_mtok_usd
    return prices.input_per_mtok_usd, prices.output_per_mtok_usd


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    in_price, out_price = _price_for(model)
    cost = Decimal(input_tokens) * in_price / Decimal(1_000_000) + Decimal(
        output_tokens
    ) * out_price / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))


async def _assert_within_cap(user_id) -> None:
    await billing.require_capacity(user_id)


async def call(
    user_id,
    task_id,
    role: str,
    messages: list[dict],
    *,
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    **kwargs,
) -> ModelReply:
    """One metered model call for this user. Raises UsageCapExceeded at cap."""
    from uuid import UUID as _UUID

    uid = user_id if isinstance(user_id, _UUID) else _UUID(str(user_id))
    tid = task_id if isinstance(task_id, _UUID) or task_id is None else _UUID(str(task_id))

    personal = await secrets_vault.get_model_api_key(str(uid))
    if personal is None and not settings.secrets.anthropic_api_key:
        raise secrets_vault.VaultError("No Anthropic API key is configured. Add yours in Settings.")

    model = getattr(settings.models, role, None) or settings.models.worker
    estimate = max(
        Decimal("0.01"),
        _cost_usd(model, sum(len(str(m)) for m in messages) // 3 + 1000, max_tokens),
    )
    operation_key = f"router:{uuid4()}"
    await billing.reserve(uid, tid, operation_key, estimate, allow_partial=False)
    request_kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        **kwargs,
    }
    if system:
        request_kwargs["system"] = system
    if tools:
        request_kwargs["tools"] = tools

    personal_client = False
    try:
        if personal is not None:
            client = anthropic.AsyncAnthropic(api_key=personal.reveal())
            personal_client = True
        else:
            client = _get_client()
    except BaseException:
        await db.release_unsubmitted_budget(uid, operation_key)
        raise
    reply: anthropic.Message | None = None
    last_exc: Exception | None = None
    try:
        for attempt in range(3):  # 2 retries on transient errors only
            try:
                reply = await client.messages.create(**request_kwargs)
                break
            except (
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
                anthropic.InternalServerError,
            ) as exc:
                last_exc = exc
                logger.warning(
                    "model call retry",
                    extra={"user_id": str(uid), "role": role, "attempt": attempt + 1},
                )
                if attempt < 2:
                    await asyncio.sleep(min(2**attempt, 2))
    except BaseException:
        await db.mark_budget_unknown(uid, operation_key)
        raise
    finally:
        if personal_client:
            with contextlib.suppress(Exception):
                await client.close()
    if reply is None:
        await db.mark_budget_unknown(uid, operation_key)
        raise last_exc or RuntimeError("model call failed")

    usage = getattr(reply, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cost = _cost_usd(model, input_tokens, output_tokens)
    prices = settings.model_prices.get(model)
    if prices:
        cache_write = getattr(usage, "cache_creation_input_tokens", 0)
        cache_read = getattr(usage, "cache_read_input_tokens", 0)
        cache_write = cache_write if isinstance(cache_write, int) else 0
        cache_read = cache_read if isinstance(cache_read, int) else 0
        cost += Decimal(cache_write) * prices.cache_write_per_mtok_usd / Decimal(1_000_000)
        cost += Decimal(cache_read) * prices.cache_read_per_mtok_usd / Decimal(1_000_000)
        cost = cost.quantize(Decimal("0.000001"))

    await db.settle_budget(uid, operation_key, model, input_tokens, output_tokens, cost)
    await events.publish(
        events.USAGE_UPDATED,
        {"user_id": str(uid), "task_id": str(tid) if tid else None, "cost_usd": str(cost)},
    )

    text = "".join(block.text for block in reply.content if getattr(block, "type", "") == "text")
    return ModelReply(
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        stop_reason=reply.stop_reason,
        raw=reply,
    )
