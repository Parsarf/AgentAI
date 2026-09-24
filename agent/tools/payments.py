"""Provider-independent purchase boundary. Runtime spending is disabled.

Subscription billing is not a merchant payment connection. Until a supported
user-funded, merchant-capable provider is integrated, this tool only validates
and audits denials; it must never issue a network payment.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from core import db
from core.config import settings
from tools.base import (
    ToolResult,
    current_task_id,
    current_task_source,
    current_user_id,
    tool,
)


def _amount(value: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("amount must be a positive USD amount") from None
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValueError("amount must be finite, positive, and have at most two decimals")
    if amount > Decimal("9999999999.99"):
        raise ValueError("amount is too large")
    return amount


@tool("make_purchase", "Purchase from a merchant using the user's connected funds", risk="high")
async def make_purchase(
    merchant: str = "", amount: str = "", description: str = "", currency: str = "USD"
) -> ToolResult:
    user_id = UUID(str(current_user_id.get()))
    task_id = str(current_task_id.get() or "")
    source = str(current_task_source.get() or "user")
    reason = "purchases unavailable: no supported user-funded merchant provider is configured"
    outcome = "denied"
    parsed_amount = None
    try:
        if str(currency).upper() != "USD":
            raise ValueError("only USD purchases are supported")
        parsed_amount = _amount(amount)
        merchant = str(merchant)
        description = str(description)
        if not merchant or len(merchant) > 200 or any(c in merchant for c in "/@\\?#"):
            raise ValueError("merchant must be a plain hostname")
        if not description or len(description) > 300:
            raise ValueError("description is required (300 characters max)")
        if not settings.payments.enabled:
            pass  # explicit runtime kill switch; no provider path exists
        else:
            reason = "purchases unavailable: no verified provider adapter exists"
    except ValueError as exc:
        reason = str(exc)
        outcome = "invalid"
    await db.record_purchase_denial(
        user_id,
        task_id,
        source,
        str(merchant),
        parsed_amount,
        str(description),
        outcome,
        reason,
    )
    return ToolResult(ok=False, error=reason)


@tool("check_spend_status", "Check your purchase limits and recent attempts", risk="safe")
async def check_spend_status() -> dict:
    user_id = UUID(str(current_user_id.get()))
    policy = await db.get_purchase_policy(user_id)
    attempts = await db.recent_purchase_attempts(user_id)
    spent = await db.spend_this_month(user_id)
    remaining = max(Decimal("0"), policy["monthly_cap_usd"] - spent)
    return {
        "purchases_available": False,
        "opted_in": False,
        "connection_status": "unavailable",
        "per_transaction_cap_usd": str(policy["per_transaction_cap_usd"]),
        "monthly_cap_usd": str(policy["monthly_cap_usd"]),
        "spent_this_month_usd": str(spent),
        "reserved_or_unknown_usd": "0.00",
        "remaining_monthly_usd": str(remaining),
        "recent_attempts": [
            {
                **item,
                "amount_usd": str(item["amount_usd"]) if item["amount_usd"] is not None else None,
                "created_at": item["created_at"].isoformat(),
            }
            for item in attempts
        ],
    }
