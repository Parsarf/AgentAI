"""Tenant-scoped platform cost limits and flat Stripe subscriptions.

The api_costs table is the cost ledger. Stripe charges flat subscription
prices; internal allowance/overage values are informational only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import stripe

from core import db, events
from core.config import ConfigError, settings


class UsageCapExceeded(Exception):
    pass


@dataclass(frozen=True)
class LimitCheck:
    ok: bool
    reason: str | None
    pct_used: float
    settled_usd: Decimal
    reserved_usd: Decimal
    cap_usd: Decimal


def _cap_reason(tier: str, used: Decimal, cap: Decimal) -> str:
    return (
        f"usage cap reached for your {tier} plan (${used}/${cap}) — "
        f"manage your plan at {settings.secrets.base_url}/usage"
    )


def _effective_plan(user: db.User) -> str:
    if user.billing_state == "past_due" and (
        user.billing_grace_until is None or user.billing_grace_until <= datetime.now(UTC)
    ):
        return "free"
    if user.billing_state in ("unpaid", "canceled"):
        return "free"
    return user.plan_tier


async def usage_this_period(user_id: UUID) -> db.UsageSummary:
    user = await db.get_user(user_id)
    if user is None:
        raise ValueError("unknown user")
    summary = await db.usage_this_period(user_id)
    tier = _effective_plan(user)
    if tier == summary.plan_tier:
        return summary
    plan = settings.plan_for(tier)
    return summary.model_copy(update={
        "plan_tier": tier,
        "included_allowance": plan.monthly_included_usage_usd,
        "overage": max(Decimal("0"), summary.total_cost - plan.monthly_included_usage_usd),
    })


async def check_within_limit(user_id: UUID) -> LimitCheck:
    summary = await usage_this_period(user_id)
    reserved = await db.reserved_this_period(user_id)
    cap = settings.plan_for(summary.plan_tier).hard_cap_usd
    used = summary.total_cost + reserved
    pct = float(used / cap * 100) if cap > 0 else 100.0
    return LimitCheck(
        ok=used < cap,
        reason=_cap_reason(summary.plan_tier, used, cap) if used >= cap else None,
        pct_used=pct, settled_usd=summary.total_cost,
        reserved_usd=reserved, cap_usd=cap,
    )


async def require_capacity(user_id: UUID) -> LimitCheck:
    check = await check_within_limit(user_id)
    if not check.ok:
        raise UsageCapExceeded(check.reason or "usage cap reached")
    if check.pct_used >= 90:
        summary = await usage_this_period(user_id)
        if await db.record_billing_warning(user_id, summary.period_start, 90):
            await events.publish(events.NOTIFY_USER, {
                "user_id": str(user_id),
                "message": f"You have used {check.pct_used:.0f}% of your {summary.plan_tier} usage cap. "
                           f"Manage your plan at {settings.secrets.base_url}/usage",
                "urgent": False,
            })
    return check


async def reserve(
    user_id: UUID, task_id: UUID | None, key: str, maximum: Decimal,
    allow_partial: bool = True,
) -> Decimal:
    await require_capacity(user_id)
    amount = await db.reserve_budget(user_id, task_id, key, maximum, allow_partial)
    if amount <= 0:
        check = await check_within_limit(user_id)
        raise UsageCapExceeded(check.reason or "usage cap reached")
    return amount


async def rollup(user_id: UUID) -> db.UsagePeriod:
    summary = await usage_this_period(user_id)
    result = await db.upsert_usage_period(
        user_id, summary.period_start, summary.period_end, summary.total_cost,
        summary.included_allowance, summary.overage,
    )
    await events.publish(events.USAGE_UPDATED, {
        "user_id": str(user_id), "total_cost": str(summary.total_cost),
        "cap": str(settings.plan_for(summary.plan_tier).hard_cap_usd),
    })
    return result


async def rollup_active_users() -> int:
    """Hourly reporting refresh; live cap checks still query the ledger."""
    ids = await db.active_usage_user_ids()
    for user_id in ids:
        await rollup(user_id)
    return len(ids)


def _stripe_client() -> stripe.StripeClient:
    if not settings.billing.enabled:
        raise ConfigError("billing.enabled is false; Stripe flows are disabled")
    key = settings.require("stripe_secret_key")
    settings.require("stripe_webhook_secret")
    if key.startswith("sk_live_"):
        if not settings.billing.allow_live or not settings.secrets.base_url.startswith("https://"):
            raise ConfigError("live Stripe billing requires billing.allow_live and HTTPS BASE_URL")
    elif not key.startswith("sk_test_"):
        raise ConfigError("STRIPE_SECRET_KEY must be a Stripe test key or explicitly enabled live key")
    return stripe.StripeClient(key)


def validate_startup() -> None:
    for role in (settings.models.planner, settings.models.worker, settings.models.cheap):
        prices = settings.model_prices.get(role)
        if not prices or prices.input_per_mtok_usd <= 0 or prices.output_per_mtok_usd <= 0:
            raise ConfigError(f"settings.yaml: missing positive model_prices for {role}")
    if settings.billing.sdk_task_budget_usd <= 0:
        raise ConfigError("settings.yaml: billing.sdk_task_budget_usd must be positive")
    if settings.billing.enabled:
        _stripe_client()
        if not any(t.stripe_price_id for n, t in settings.plans.tiers.items() if n != "free"):
            raise ConfigError("billing enabled but no paid stripe_price_id configured")


async def create_stripe_customer(user_id: UUID) -> str:
    user = await db.get_user(user_id)
    if user is None:
        raise ValueError("unknown user")
    if user.stripe_customer_id:
        return user.stripe_customer_id
    client = _stripe_client()
    customer = await client.v1.customers.create_async(
        {"email": user.email, "metadata": {"user_id": str(user_id)}},
        {"idempotency_key": f"customer:{user_id}"},
    )
    current = await db.set_stripe_customer(user_id, customer.id)
    return current.stripe_customer_id or customer.id


async def start_checkout(user_id: UUID, plan_tier: str, operation_key: str) -> str:
    plan = settings.plan_for(plan_tier)
    if plan_tier == "free" or not plan.stripe_price_id:
        raise ValueError("plan is not available for checkout")
    user = await db.get_user(user_id)
    if user is None:
        raise ValueError("unknown user")
    if user.plan_tier == plan_tier and user.billing_state in ("active", "trialing"):
        raise ValueError("plan is already active; use Manage billing")
    customer_id = await create_stripe_customer(user_id)
    client = _stripe_client()
    checkout_key = f"{plan_tier}:{operation_key}"
    previous = await db.get_billing_operation(user_id, "checkout", checkout_key)
    if previous:
        old_session = await client.v1.checkout.sessions.retrieve_async(previous)
        if _attr(old_session, "status") != "open":
            raise ValueError("checkout session expired; reload Usage to try again")
        old_url = _attr(old_session, "url")
        if old_url and old_url.startswith("https://checkout.stripe.com/"):
            return old_url
        raise ValueError("Stripe did not return a hosted checkout URL")
    session = await client.v1.checkout.sessions.create_async(
        {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": plan.stripe_price_id, "quantity": 1}],
            "client_reference_id": str(user_id),
            "success_url": f"{settings.secrets.base_url}/usage/success",
            "cancel_url": f"{settings.secrets.base_url}/usage",
        },
        {"idempotency_key": f"checkout:{user_id}:{checkout_key}"},
    )
    await db.save_billing_operation(user_id, "checkout", checkout_key, session.id)
    if not session.url or not session.url.startswith("https://checkout.stripe.com/"):
        raise ValueError("Stripe did not return a hosted checkout URL")
    return session.url


async def create_portal_session(user_id: UUID) -> str:
    user = await db.get_user(user_id)
    if user is None or not user.stripe_customer_id:
        raise ValueError("no billing account to manage")
    client = _stripe_client()
    session = await client.v1.billing_portal.sessions.create_async({
        "customer": user.stripe_customer_id,
        "return_url": f"{settings.secrets.base_url}/usage",
    })
    if not session.url or not session.url.startswith("https://billing.stripe.com/"):
        raise ValueError("Stripe did not return a hosted portal URL")
    return session.url


def _attr(value: object, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


async def handle_stripe_webhook(event: object) -> bool:
    """Apply a signature-verified event using the provider's current state.

    The route verifies the signature. Looking up current subscriptions makes
    old delivery order harmless; event id insertion and updates are atomic.
    """
    event_type = _attr(event, "type", "")
    event_id = _attr(event, "id", "")
    handled = {
        "checkout.session.completed", "customer.subscription.updated",
        "customer.subscription.deleted", "invoice.payment_failed", "invoice.paid",
    }
    if event_type not in handled:
        return False
    obj = _attr(_attr(event, "data"), "object")
    customer_id = _attr(obj, "customer")
    if not event_id or not isinstance(customer_id, str):
        raise ValueError("Stripe event missing id/customer")
    user = await db.get_user_by_stripe_customer(customer_id)
    if user is None:
        return False
    client = _stripe_client()
    listing = await client.v1.subscriptions.list_async({
        "customer": customer_id, "status": "all", "limit": 20,
    })
    subscriptions = list(_attr(listing, "data", []))
    price_to_tier = {
        plan.stripe_price_id: tier for tier, plan in settings.plans.tiers.items()
        if plan.stripe_price_id
    }
    candidates: list[tuple[int, int, object, str, str]] = []
    for sub in subscriptions:
        items = _attr(_attr(sub, "items"), "data", [])
        tiers = [price_to_tier.get(_attr(_attr(item, "price"), "id")) for item in items]
        tier = next((t for t in tiers if t), None)
        if tier is None:
            continue
        state = str(_attr(sub, "status", "canceled"))
        priority = {"active": 3, "trialing": 3, "past_due": 2, "unpaid": 1}.get(state, 0)
        candidates.append((priority, int(_attr(sub, "created", 0)), sub, tier, state))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = candidates[0] if candidates else None
    sub_id = str(_attr(selected[2], "id")) if selected else None
    state = selected[4] if selected else "canceled"
    tier = selected[3] if selected and state in ("active", "trialing", "past_due") else "free"
    grace: datetime | None = None
    if state == "past_due":
        if user.billing_state == "past_due" and user.billing_grace_until:
            grace = user.billing_grace_until
        else:
            grace = datetime.now(UTC) + timedelta(days=settings.billing.past_due_grace_days)
        if grace <= datetime.now(UTC):
            tier = "free"
    applied = await db.apply_stripe_event(user.id, event_id, event_type, sub_id, state, tier, grace)
    if applied:
        await events.publish(events.USAGE_UPDATED, {"user_id": str(user.id)})
        await events.publish(events.NOTIFY_USER, {
            "user_id": str(user.id), "message": f"Billing status: {state}; plan: {tier}.",
            "urgent": False,
        })
    return applied
