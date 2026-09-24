"""Agent-facing purchase tools. All gating lives in core/purchases — the one
validation + approval path — so every entry point (registry dispatch, SDK
loop, direct call_tool) is gated identically and preflight denials create
zero approval rows. Runtime purchases are DISABLED: no provider adapter
exists, so every make_purchase call denies in preflight.
"""

from __future__ import annotations

from core import purchases
from tools.base import ToolResult, tool


@tool("make_purchase", "Purchase from a merchant using the user's connected funds", risk="high")
async def make_purchase(
    merchant: str = "",
    amount: str = "",
    description: str = "",
    currency: str = "USD",
    order_ref: str | None = None,
) -> ToolResult:
    """Exact schema: merchant (bare hostname), amount ("12.34" USD),
    description (required, <=300 chars), currency (USD only),
    order_ref (optional opaque provider order/quote identity — binds replays;
    a changed purchase under one order_ref is rejected)."""
    return await purchases.purchase_flow(
        merchant=merchant,
        amount=amount,
        description=description,
        currency=currency,
        order_ref=order_ref,
    )


@tool("check_spend_status", "Check your purchase limits and recent attempts", risk="safe")
async def check_spend_status() -> dict:
    """This user's own caps, settled/reserved amounts, and sanitized recent
    receipts. Never returns connection credentials."""
    return await purchases.spend_status()
