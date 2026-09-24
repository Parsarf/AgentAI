"""THE one purchase path — validation, preflight, approval, durable ledger.

Runtime purchases are DISABLED by recorded operator decision: no provider or
charging adapter ships, so ``get_provider()`` returns None in production and
every request denies before any approval row is created. The full lifecycle
below is exercised only against a clearly labeled TEST-ONLY fake installed
via :func:`set_provider` (see ``tests/fake_provider.py``).

Design contract (phase-prompts/phase-6-lean-payments.md):
- ONE validation + approval path. ``tools.base.call_tool`` routes payment
  tools here instead of the generic approval gate, so preflight denials create
  ZERO approval rows no matter what — including when the loop's task-wide
  ``approvals_prechecked`` flag is set. Permission is never inferred from that
  flag: it is bound to this user/task/invocation/purchase via the purchases
  row and its single approval record.
- Preflight order: enabled/provider → plan entitlement → opt-in → live
  connection → merchant allowlist (canonical registrable domains) → caps.
  Hard cap/allowlist failures are denials, never overridable by approval.
- Durable identity: the server derives the invocation key from trusted
  context + validated immutable details; the model cannot invent IDs. Same
  invocation resumes the same purchase; changed details under one order_ref
  are rejected; an ambiguous repeat (new purchase without order identity in a
  task that already bought something) can never auto-charge.
- Lifecycle: awaiting_approval → ready → executing → succeeded|failed|unknown
  (+ denied/expired before execution). ``TRANSITIONS`` below is the single
  source of truth; every state write goes through :func:`_move` (derived from
  it) or the guarded per-user claim transaction.
- Claim+reserve: one short per-user-locked transaction re-reads every gate
  FRESH and flips ready→executing — that flip IS the reservation. Settling,
  releasing and unknown-marking are guarded, idempotent updates.
- A timeout/crash after submission is `unknown`, budget stays reserved, and
  only a provider lookup (never age, never a retry) resolves it. Reconciliation
  preserves the reservation's original UTC month.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import UUID

from core import approvals as approvals_mod
from core import db, events
from core.config import settings
from core.logging import get_logger
from core.publicsuffix import canonical_merchant
from tools.base import ToolResult, current_task_id, current_task_source, current_user_id

logger = get_logger(__name__)

CURRENCY = "USD"
_MAX_AMOUNT = Decimal("9999999999.99")

#: The whole lifecycle. Terminal states have no outgoing edges; `unknown` can
#: only be resolved by a provider lookup (reconciliation), never by retry.
TRANSITIONS: dict[str, frozenset[str]] = {
    "awaiting_approval": frozenset({"ready", "denied", "expired"}),
    "ready": frozenset({"executing", "denied", "expired"}),
    "executing": frozenset({"succeeded", "failed", "unknown"}),
    "unknown": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "denied": frozenset(),
    "expired": frozenset(),
}

#: Unfinished states that hold their budget reservation.
RESERVING_STATES = ("executing", "unknown")


def _from_states(new_state: str) -> tuple[str, ...]:
    """States allowed to transition INTO new_state — derived from TRANSITIONS,
    which is the single source of truth for the lifecycle."""
    return tuple(state for state, outs in TRANSITIONS.items() if new_state in outs)


async def _move(user_id: UUID, purchase_id: Any, new_state: str, **fields: Any) -> dict[str, Any] | None:
    """The only way purchases.py changes lifecycle state. Returns the updated
    row, or None when the purchase already moved elsewhere."""
    return await db.transition_purchase(
        user_id, purchase_id, new_state, _from_states(new_state), **fields
    )


# --------------------------------------------------------------------------- #
# Provider seam — None in production; TEST-ONLY fake in tests, never shipped
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProviderOutcome:
    status: Literal["succeeded", "failed", "unknown"]
    provider_ref: str | None = None
    #: Canonical merchant domain the provider actually charged/bound. A
    #: mismatch with the approved merchant fails the purchase fail-closed.
    recipient: str | None = None
    detail: str = ""


class PurchaseProvider(Protocol):
    """Minimal adapter interface (one adapter when a real provider exists):
    connection status, idempotent execute, lookup by durable reference."""

    name: str
    #: How long the provider honors an idempotency key. Unresolved operations
    #: older than this require manual reconciliation — never a new key.
    idempotency_retention: timedelta

    async def execute(
        self, user_id: UUID, purchase: dict[str, Any], idempotency_key: str
    ) -> ProviderOutcome: ...

    async def lookup(self, user_id: UUID, idempotency_key: str) -> ProviderOutcome | None: ...


_provider: PurchaseProvider | None = None


def set_provider(provider: PurchaseProvider | None) -> None:
    """Install the adapter. Production never calls this; tests install the
    TEST-ONLY fake and must reset it to None afterwards."""
    global _provider
    _provider = provider


def get_provider() -> PurchaseProvider | None:
    return _provider


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, ValueError):
        raise ValueError("amount must be a positive USD amount") from None
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValueError("amount must be finite, positive, and have at most two decimals")
    if amount > _MAX_AMOUNT:
        raise ValueError("amount is too large")
    return amount


def validate_request(
    merchant: Any, amount: Any, description: Any, currency: Any, order_ref: Any
) -> dict[str, Any]:
    """Hard input validation BEFORE any gate or provider contact."""
    if str(currency or CURRENCY).upper() != CURRENCY:
        raise ValueError(f"only {CURRENCY} purchases are supported")
    parsed = _amount(amount)
    canonical = canonical_merchant(str(merchant or ""))
    text = str(description or "")
    if not text or len(text) > 300:
        raise ValueError("description is required (300 characters max)")
    ref = str(order_ref).strip() if order_ref else None
    if ref and (len(ref) > 200 or any(c.isspace() for c in ref)):
        raise ValueError("order_ref must be a single opaque token (200 characters max)")
    return {
        "merchant": canonical,
        "merchant_input": str(merchant),
        "amount": parsed,
        "currency": CURRENCY,
        "description": text,
        "order_ref": ref,
    }


# --------------------------------------------------------------------------- #
# Preflight — the gates, in order. Returns a denial reason or None.
# --------------------------------------------------------------------------- #


def _runtime_ready() -> bool:
    """The runtime kill switch: enabled AND a named provider AND an installed
    adapter. Enabling the flag alone can never arm a charge."""
    provider = get_provider()
    return bool(
        settings.payments.enabled and provider and settings.payments.provider == provider.name
    )


async def run_preflight(user_id: UUID, validated: dict[str, Any]) -> str | None:
    if not settings.payments.enabled:
        return "purchases are disabled"
    if not settings.payments.provider:
        return "purchases unavailable: no payment provider is configured"
    provider = get_provider()
    if provider is None or provider.name != settings.payments.provider:
        return "purchases unavailable: no verified provider adapter exists"
    user = await db.get_user(user_id)
    if user is None or user.status != "active":
        return "account is not active"
    plan = settings.plan_for(user.plan_tier)
    if not plan.payments_enabled:
        return f"payments not enabled on the {user.plan_tier} plan"
    policy = await db.get_purchase_policy(user_id)
    if not policy["opted_in"]:
        return "purchases are opted out for this account"
    connection = await db.get_purchase_connection(user_id)
    if (connection is None or connection["status"] != "active"
            or connection["provider"] != settings.payments.provider):
        return "no active payment connection — connect one in settings first"
    allowlist = set(policy["merchant_allowlist"] or [])
    if validated["merchant"] not in allowlist:
        return "merchant is not on your allowlist"
    if validated["amount"] > policy["per_transaction_cap_usd"]:
        return "amount exceeds your per-transaction cap"
    month = _month_of(datetime.now(UTC))
    totals = await db.purchase_month_totals(user_id, month)
    committed = totals["settled"] + totals["reserved"]
    if committed + validated["amount"] > policy["monthly_cap_usd"]:
        return "amount exceeds your remaining monthly cap"
    return None


# --------------------------------------------------------------------------- #
# Audit + notification helpers (sanitized; never credentials)
# --------------------------------------------------------------------------- #


async def _audit_attempt(
    user_id: UUID,
    task_id: str,
    source: str,
    merchant: str | None,
    amount: Decimal | None,
    description: str | None,
    outcome: str,
    reason: str,
) -> None:
    try:
        await db.record_purchase_denial(
            user_id, task_id, source, merchant, amount, description, outcome, reason
        )
    except Exception:
        logger.exception("purchase attempt audit failed", extra={"user_id": str(user_id)})


async def _event(user_id: UUID, purchase_id: Any, event: str, detail: dict[str, Any] | None = None) -> None:
    try:
        await db.record_purchase_event(user_id, purchase_id, event, detail)
    except Exception:
        logger.exception("purchase event audit failed", extra={"user_id": str(user_id)})


async def _notify(user_id: UUID, message: str, urgent: bool = False) -> None:
    """Outcome notification. A failed notify never rolls back a purchase."""
    try:
        await events.publish(
            events.NOTIFY_USER,
            {"user_id": str(user_id), "message": message[:500], "urgent": urgent},
        )
    except Exception:
        logger.exception("purchase notification failed", extra={"user_id": str(user_id)})


def _month_of(now: datetime) -> date:
    return now.date().replace(day=1)


def _invocation_key(user_id: str, task_id: str, validated: dict[str, Any]) -> str:
    material = "|".join(
        [
            user_id,
            task_id,
            validated["merchant"],
            str(validated["amount"]),
            validated["currency"],
            validated["description"],
            validated["order_ref"] or "",
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()[:64]


def _receipt(purchase: dict[str, Any]) -> dict[str, Any]:
    return {
        "purchase_id": str(purchase["id"]),
        "merchant": purchase["merchant"],
        "amount_usd": str(purchase["amount"]),
        "currency": purchase["currency"],
        "description": purchase["description"],
        "state": purchase["state"],
        "provider_ref": (purchase.get("provider_ref") or "")[:40] or None,
    }


def _denied(validated: dict[str, Any], reason: str, outcome: str = "denied") -> ToolResult:
    return ToolResult(ok=False, error=f"purchase denied: {reason}" if outcome == "denied" else reason)


# --------------------------------------------------------------------------- #
# The one flow
# --------------------------------------------------------------------------- #


async def purchase_flow(
    merchant: Any = "", amount: Any = "", description: Any = "",
    currency: Any = CURRENCY, order_ref: Any = None,
) -> ToolResult:
    user_raw = current_user_id.get()
    task_id = str(current_task_id.get() or "")
    source = str(current_task_source.get() or "user")
    if not user_raw or not task_id:  # call_tool guarantees context; be defensive
        return ToolResult(ok=False, error="internal: no task context for purchases")
    user_id = UUID(str(user_raw))

    # 1. Input validation — invalid attempts never touch gates or providers.
    try:
        validated = validate_request(merchant, amount, description, currency, order_ref)
    except ValueError as exc:
        raw = str(merchant) if isinstance(merchant, str) else None
        await _audit_attempt(user_id, task_id, source, raw, None, None, "invalid", str(exc))
        await _notify(user_id, f"Purchase request refused: {exc}")
        return ToolResult(ok=False, error=str(exc))

    # 2. Preflight gates — denials create ZERO approval rows.
    reason = await run_preflight(user_id, validated)
    if reason is not None:
        await _audit_attempt(
            user_id, task_id, source, validated["merchant"], validated["amount"],
            validated["description"], "denied", reason,
        )
        await _notify(user_id, f"Purchase denied ({validated['merchant']}, ${validated['amount']}): {reason}")
        return ToolResult(ok=False, error=f"purchase denied: {reason}")

    # 3. Durable identity — the server owns it; the model cannot invent it.
    key = _invocation_key(str(user_id), task_id, validated)
    existing = await db.get_purchase_by_invocation(user_id, key)
    if existing is not None:
        return await _resume(user_id, task_id, source, existing)

    if validated["order_ref"]:
        clash = await db.get_purchase_by_order(user_id, validated["order_ref"])
        if clash is not None:
            reason = (
                "this order_ref is already bound to a purchase with different details — "
                "changed details require a new order"
            )
            await _audit_attempt(
                user_id, task_id, source, validated["merchant"], validated["amount"],
                validated["description"], "invalid", reason,
            )
            await _notify(user_id, f"Purchase refused: {reason}")
            return ToolResult(ok=False, error=reason)

    # 4. Approval decision — the shared rule engine, plus code-level floors.
    raw_args = {"merchant": validated["merchant_input"], "amount": str(validated["amount"]),
                "description": validated["description"]}
    decision = await approvals_mod.check(
        user_id=user_id, tool_name="make_purchase", tool_args=raw_args,
        risk="high", task_source=source,
    )
    action = decision.action
    if source == "job":
        # Hard layer #2 (approvals.check's mode floor is #1): jobs can never
        # auto-approve purchases, whatever any config says.
        action = _strictest(action, "require_approval")
    prior_in_task = await db.count_purchases_for_task(user_id, task_id)
    ambiguous = prior_in_task > 0 and validated["order_ref"] is None
    if ambiguous:
        # A repeat without provider order identity in a task that already
        # bought something: ambiguous new intent — never auto-charge.
        action = _strictest(action, "require_approval")

    now = datetime.now(UTC)
    expires = now + timedelta(seconds=settings.limits.approval_timeout_seconds)

    if action == "deny":
        deny_reason = decision.reason or "denied by your approval rules"
        await _audit_attempt(
            user_id, task_id, source, validated["merchant"], validated["amount"],
            validated["description"], "denied", deny_reason,
        )
        await _notify(
            user_id,
            f"Purchase denied ({validated['merchant']}, ${validated['amount']}): {deny_reason}",
        )
        return ToolResult(ok=False, error=f"purchase denied: {deny_reason}")

    initial_state = "awaiting_approval" if action == "require_approval" else "ready"
    purchase = await db.create_purchase(
        user_id,
        task_id,
        source,
        key,
        validated["merchant"],
        validated["merchant_input"],
        validated["amount"],
        validated["currency"],
        validated["description"],
        (await db.get_purchase_connection(user_id) or {})["connection_version"],
        validated["order_ref"],
        initial_state,
        expires if initial_state == "awaiting_approval" else None,
    )
    await _event(user_id, purchase["id"], "created", {"state": initial_state, "source": source})

    if action == "require_approval":
        approved = await _wait_for_purchase_approval(user_id, task_id, purchase)
        if not approved:
            fresh = await db.get_purchase(user_id, purchase["id"])
            state = fresh["state"] if fresh else "denied"
            message = (
                "the approval for this purchase expired unused"
                if state == "expired"
                else "you declined this purchase"
            )
            await _notify(
                user_id,
                f"Purchase not executed ({validated['merchant']}, ${validated['amount']}): {message}",
            )
            return ToolResult(ok=False, error=f"purchase {state}: {message}")
        purchase = (await db.get_purchase(user_id, purchase["id"])) or purchase

    # 5. Claim + reserve + execute + settle.
    return await _execute(user_id, purchase)


async def _resume(user_id: UUID, task_id: str, source: str, purchase: dict[str, Any]) -> ToolResult:
    """Same invocation seen again: resume the SAME purchase — never a new
    charge. Terminal states stay terminal; a deliberate repeat needs a new
    order_ref (or a new task)."""
    state = purchase["state"]
    if state in ("succeeded", "failed", "denied", "expired"):
        await _audit_attempt(
            user_id, task_id, source,
            purchase["merchant"], Decimal(str(purchase["amount"])), purchase["description"],
            "denied",
            f"this exact purchase already reached '{state}'; a repeat needs new confirmation",
        )
        return ToolResult(
            ok=False,
            error=(
                f"this purchase already reached '{state}' — repeating the identical request "
                "is refused; a deliberate new purchase needs a new order_ref"
            ),
        )
    if state == "executing":
        return ToolResult(ok=False, error="this purchase is already executing — do not retry; check status")
    if state == "unknown":
        await _reconcile_one(user_id, purchase, get_provider())
        fresh = await db.get_purchase(user_id, purchase["id"])
        if fresh and fresh["state"] in ("succeeded", "failed"):
            return await _resume(user_id, task_id, source, fresh)
        return ToolResult(
            ok=False,
            error=(
                "this purchase has an unresolved provider outcome (unknown) — its budget stays "
                "reserved until reconciliation; do not issue a new payment for it"
            ),
        )
    if state == "ready":
        return await _execute(user_id, purchase)
    if state == "awaiting_approval":
        approved = await _wait_for_purchase_approval(user_id, task_id, purchase)
        if not approved:
            fresh = await db.get_purchase(user_id, purchase["id"])
            state = fresh["state"] if fresh else "denied"
            return ToolResult(ok=False, error=f"purchase {state}: not approved")
        purchase = (await db.get_purchase(user_id, purchase["id"])) or purchase
        return await _execute(user_id, purchase)
    return ToolResult(ok=False, error=f"purchase is in state {state}")


async def _wait_for_purchase_approval(user_id: UUID, task_id: str, purchase: dict[str, Any]) -> bool:
    """Owner-only, single-use decision bound to THIS purchase's immutable
    details. Re-waiting (resume) reuses the SAME approval row."""
    approval_id = purchase.get("approval_id")
    expires: datetime = purchase.get("approval_expires_at") or (
        datetime.now(UTC) + timedelta(seconds=settings.limits.approval_timeout_seconds)
    )
    details = {
        "tool": "make_purchase",
        "purchase_id": str(purchase["id"]),
        "kind": "purchase",
        "merchant": purchase["merchant"],
        "recipient": purchase.get("recipient") or purchase["merchant"],
        "amount": str(purchase["amount"]),
        "currency": purchase["currency"],
        "description": purchase["description"],
        "expires_at": expires.isoformat(),
    }
    summary = (
        f"make_purchase: {purchase['merchant']} — ${purchase['amount']} {purchase['currency']} "
        f"({purchase['description'][:80]})"
    )
    if approval_id is None:
        try:
            linked_task = UUID(task_id)
        except ValueError:
            linked_task = None
        approval = await db.record_approval(user_id, linked_task, summary, details)
        approval_id = approval.id
        await db.update_purchase(user_id, purchase["id"], approval_id=approval_id)
    # Subscribe BEFORE announcing the request: a decision that lands between
    # the announcement and the wait must never be missed (it would otherwise
    # stall until the approval timeout and wrongly expire the purchase).
    loop = asyncio.get_running_loop()
    decided: asyncio.Future[dict] = loop.create_future()

    async def _on_decided(payload: dict) -> None:
        if (
            not decided.done()
            and payload.get("user_id") == str(user_id)
            and payload.get("approval_id") == str(approval_id)
        ):
            decided.set_result(payload)

    await events.subscribe(events.APPROVAL_DECIDED, _on_decided)
    try:
        await events.publish(
            events.APPROVAL_REQUESTED,
            {
                "user_id": str(user_id),
                "approval_id": str(approval_id),
                "task_id": task_id if task_id else None,
                "action_summary": summary,
                "details": details,
            },
        )
        remaining = (expires - datetime.now(UTC)).total_seconds()
        try:
            reply = await asyncio.wait_for(decided, timeout=max(remaining, 0.1))
        except TimeoutError:
            reply = None
    finally:
        await events.unsubscribe(events.APPROVAL_DECIDED, _on_decided)
    fresh = await db.get_purchase(user_id, purchase["id"])
    if fresh is not None and fresh["approval_id"] is None:
        await db.update_purchase(user_id, purchase["id"], approval_id=approval_id)
    if reply is None:
        await db.update_approval(user_id, approval_id, "expired")
        await _move(user_id, purchase["id"], "expired", failure_reason="approval timed out")
        await _event(user_id, purchase["id"], "approval_expired")
        return False
    approved = bool(reply.get("approved"))
    if approved:
        updated = await _move(user_id, purchase["id"], "ready", failure_reason=None)
        if updated is None:
            return False  # someone else already resolved the purchase
        await db.update_approval(user_id, approval_id, "approved")
        await _event(user_id, purchase["id"], "approved")
        return True
    await db.update_approval(user_id, approval_id, "denied")
    await _move(user_id, purchase["id"], "denied", failure_reason="declined by owner")
    await _event(user_id, purchase["id"], "declined")
    return False


def _strictest(a: str, b: str) -> str:
    order = {"auto": 0, "auto_and_log": 1, "require_approval": 2, "deny": 3}
    return a if order.get(a, 0) >= order.get(b, 0) else b


# --------------------------------------------------------------------------- #
# Claim → execute → settle
# --------------------------------------------------------------------------- #


async def _execute(user_id: UUID, purchase: dict[str, Any]) -> ToolResult:
    provider = get_provider()
    if provider is None or not _runtime_ready():
        # Preflight passed but the adapter vanished (operator teardown between
        # approval and execution) — fail closed, never charge.
        await _move(user_id, purchase["id"], "denied", failure_reason="provider adapter disappeared")
        await _event(user_id, purchase["id"], "denied", {"reason": "no provider adapter"})
        return ToolResult(ok=False, error="purchase denied: no verified provider adapter exists")

    now = datetime.now(UTC)
    claim = await db.claim_purchase(
        user_id, purchase["id"], purchase["merchant"], Decimal(str(purchase["amount"])), now
    )
    if claim["kind"] != "claimed":
        reason = claim["reason"] or claim["kind"]
        new_state = "expired" if claim["kind"] == "expired" else "denied"
        await _move(user_id, purchase["id"], new_state, failure_reason=reason[:200])
        await _event(user_id, purchase["id"], claim["kind"], {"reason": reason[:200]})
        await _notify(
            user_id, f"Purchase not executed ({purchase['merchant']}, ${purchase['amount']}): {reason}"
        )
        return ToolResult(ok=False, error=f"purchase {new_state}: {reason}")

    claimed = claim["purchase"]
    await _event(
        user_id, purchase["id"], "claimed", {"reservation_month": str(claimed["reservation_month"])}
    )

    # Network execution happens OUTSIDE any DB transaction, bounded by a wall
    # clock. Timeout ⇒ unknown: budget stays reserved, only a lookup resolves.
    try:
        outcome = await asyncio.wait_for(
            provider.execute(user_id, claimed, idempotency_key=str(purchase["id"])),
            timeout=settings.payments.execution_timeout_seconds,
        )
    except TimeoutError:
        await _finish_transition(user_id, purchase["id"], "unknown", None, "provider call timed out")
        return ToolResult(
            ok=False,
            error="the payment outcome is UNKNOWN (timed out after submission) — budget stays "
            "reserved and the purchase will be reconciled; do NOT retry it as a new purchase",
        )
    except asyncio.CancelledError:
        await _finish_transition(
            user_id, purchase["id"], "unknown", None, "task interrupted after submission"
        )
        raise
    except Exception as exc:
        await _finish_transition(
            user_id, purchase["id"], "unknown", None, f"provider error: {str(exc)[:150]}"
        )
        return ToolResult(
            ok=False,
            error="the payment outcome is UNKNOWN (provider error after submission) — budget stays "
            "reserved and the purchase will be reconciled; do NOT retry it as a new purchase",
        )

    if outcome.status == "succeeded" and outcome.recipient != purchase["merchant"]:
        # The provider may already have moved money. Never report a failure
        # or release the reservation; hold it for manual reconciliation.
        outcome = ProviderOutcome(
            status="unknown", provider_ref=outcome.provider_ref,
            detail=f"recipient mismatch: {outcome.recipient!r} is not {purchase['merchant']!r}",
        )

    final = await _finish_transition(
        user_id, purchase["id"], outcome.status, outcome.provider_ref, outcome.detail
    )
    state = outcome.status
    if state == "succeeded":
        await _notify(
            user_id,
            f"Purchase succeeded: {purchase['merchant']} — "
            f"${purchase['amount']} {purchase['currency']}",
        )
        settled = final or {
            **purchase, "state": "succeeded", "provider_ref": outcome.provider_ref,
        }
        return ToolResult(ok=True, data=_receipt(settled))
    if state == "failed":
        await _notify(
            user_id,
            f"Purchase failed ({purchase['merchant']}, ${purchase['amount']}): "
            f"{outcome.detail or 'declined by provider'}",
        )
        return ToolResult(ok=False, error=f"purchase failed: {outcome.detail or 'declined by provider'}")
    await _notify(
        user_id,
        f"Purchase outcome UNKNOWN ({purchase['merchant']}, ${purchase['amount']}) — "
        "budget stays reserved pending reconciliation",
    )
    return ToolResult(
        ok=False,
        error="the payment outcome is UNKNOWN — budget stays reserved pending reconciliation; "
        "do NOT retry as a new purchase",
    )


async def _finish_transition(
    user_id: UUID, purchase_id: Any, status: str, provider_ref: str | None, detail: str
) -> dict[str, Any] | None:
    """executing → succeeded | failed | unknown. Guarded + idempotent: a row
    already resolved keeps its outcome and returns None."""
    fields: dict[str, Any] = {"provider_ref": provider_ref}
    if detail:
        fields["failure_reason"] = detail[:200]
    if status == "succeeded":
        updated = await _move(user_id, purchase_id, "succeeded", provider_ref=provider_ref)
        event = "settled"
    elif status == "failed":
        updated = await _move(user_id, purchase_id, "failed", **fields)
        event = "released"  # failed: the reservation is released
    else:
        updated = await _move(user_id, purchase_id, "unknown", **fields)
        event = "marked_unknown"
    await _event(
        user_id, purchase_id, event,
        {"provider_ref": (provider_ref or "")[:40], "detail": detail[:200] if detail else ""},
    )
    return updated


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #


async def _reconcile_one(user_id: UUID, purchase: dict[str, Any], provider: PurchaseProvider | None) -> bool:
    """One lookup-driven resolution. Age never resolves anything and no new
    payment is ever issued here."""
    if provider is None:
        return False
    try:
        outcome = await provider.lookup(user_id, str(purchase["id"]))
    except Exception:
        logger.exception("provider lookup failed", extra={"user_id": str(user_id)})
        return False
    if outcome is None:
        return False  # still pending, or beyond idempotency retention
    if outcome.status == "succeeded" and outcome.recipient != purchase["merchant"]:
        outcome = ProviderOutcome(
            status="unknown", provider_ref=outcome.provider_ref, detail="recipient mismatch at lookup"
        )
    if outcome.status == "unknown":
        if purchase["state"] == "executing":
            await _finish_transition(
                user_id, purchase["id"], "unknown",
                outcome.provider_ref, outcome.detail or "provider reports unknown",
            )
        return False
    updated = await _finish_transition(
        user_id, purchase["id"], outcome.status, outcome.provider_ref, outcome.detail
    )
    if updated is not None:
        await _event(user_id, purchase["id"], "reconciled", {"to": outcome.status})
        if outcome.status == "succeeded":
            await _notify(
                user_id, f"Reconciled purchase {purchase['merchant']} (${purchase['amount']}): succeeded"
            )
        else:
            await _notify(
                user_id,
                f"Reconciled purchase {purchase['merchant']} (${purchase['amount']}): "
                "failed; reserved budget released",
            )
    return updated is not None


async def reconcile_pending(limit: int = 10) -> int:
    """Startup + bounded scheduler-tick reconciliation of executing/unknown
    purchases. Provider-less (the permanent runtime case) this resolves
    nothing and leaves rows untouched for manual reconciliation."""
    rows = await db.unresolved_purchases(limit)
    if not rows:
        return 0
    provider = get_provider()
    if provider is None:
        logger.warning(
            "unresolved purchases need reconciliation but no provider adapter is installed",
            extra={"count": len(rows)},
        )
        return 0
    resolved = 0
    for row in rows:
        try:
            if await _reconcile_one(UUID(str(row["user_id"])), row, provider):
                resolved += 1
        except Exception:
            logger.exception("reconciliation failed", extra={"purchase_id": str(row.get("id"))})
    return resolved


# --------------------------------------------------------------------------- #
# check_spend_status payload
# --------------------------------------------------------------------------- #


async def spend_status() -> dict[str, Any]:
    user_raw = current_user_id.get()
    if not user_raw:
        return {"error": "no task context"}
    user_id = UUID(str(user_raw))
    policy = await db.get_purchase_policy(user_id)
    connection = await db.get_purchase_connection(user_id)
    attempts = await db.recent_purchase_attempts(user_id)
    receipts = await db.recent_purchases(user_id)
    month = _month_of(datetime.now(UTC))
    totals = await db.purchase_month_totals(user_id, month)
    monthly_cap = policy["monthly_cap_usd"]
    committed = totals["settled"] + totals["reserved"]

    def money(value: Decimal) -> str:
        return str(Decimal(value).quantize(Decimal("0.01")))

    return {
        "purchases_available": bool(_runtime_ready()),
        "provider": settings.payments.provider or "none",
        "opted_in": bool(policy["opted_in"]),
        "connection_status": (connection["status"] if connection else "unavailable"),
        "per_transaction_cap_usd": str(policy["per_transaction_cap_usd"]),
        "monthly_cap_usd": str(monthly_cap),
        "settled_this_month_usd": money(totals["settled"]),
        "reserved_or_unknown_usd": money(totals["reserved"]),
        "remaining_monthly_usd": money(max(Decimal("0"), monthly_cap - committed)),
        "reservation_month": month.isoformat(),
        "recent_purchases": [
            {
                "merchant": item["merchant"],
                "amount_usd": str(item["amount"]),
                "currency": item["currency"],
                "state": item["state"],
                "created_at": item["created_at"].isoformat(),
            }
            for item in receipts
        ],
        "recent_attempts": [
            {
                **item,
                "amount_usd": str(item["amount_usd"]) if item["amount_usd"] is not None else None,
                "created_at": item["created_at"].isoformat(),
            }
            for item in attempts
        ],
    }
