"""The gate every non-safe action passes through, per user's own tier rules.

Rule sources, strictest wins:
1. PLAN FLOOR (capability flags in plans.yaml) — free tier can never enable
   payments/browser regardless of any rule a user sets. Hard deny.
2. MODE FLOOR — a job-sourced task (no human present) treats anything above
   "safe" as at least require_approval, no matter what rules say.
3. Per-user effective rules = the user's overrides (users.user_limits_json)
   first, then the limits.yaml defaults; first match wins; fallback applies
   otherwise.

require_approval records an approvals row, publishes approval.requested, and
awaits approval.decided for that user only; timeout defaults to deny.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import jwt  # noqa: F401  (kept imported per spec dependency list; unused yet)
from pydantic import BaseModel

from core import billing, db, events
from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

Action = Literal["auto", "auto_and_log", "require_approval", "deny"]
_STRICTNESS: dict[str, int] = {"auto": 0, "auto_and_log": 1, "require_approval": 2, "deny": 3}

#: Tools gated by plan capability flags (populated as phases land).
BROWSER_TOOLS: frozenset[str] = frozenset(
    {
        "browser_open", "browser_snapshot", "browser_click", "browser_type",
        "browser_select", "browser_scroll", "browser_screenshot", "browser_back",
        "browser_login",
    }
)
PAYMENT_TOOLS: frozenset[str] = frozenset({"make_purchase"})


class Decision(BaseModel):
    action: Action
    approval_id: str | None = None
    reason: str = ""


@dataclass
class _Rule:
    action: Action
    tools: set[str] | None
    risk: str | None
    amount_above_usd: float | None
    merchants: tuple[str, ...] | None
    source: str  # user | job | any
    origin: str  # "user" | "default" — user rules first


def _compile_rules(user_overrides: dict | None) -> list[_Rule]:
    rules: list[_Rule] = []

    def _add(rules_list: list[dict], origin: str) -> None:
        for raw in rules_list:
            match = raw.get("match") or {}
            rules.append(
                _Rule(
                    action=raw["action"],
                    tools=set(match["tools"]) if match.get("tools") else None,
                    risk=match.get("risk"),
                    amount_above_usd=(
                        float(match["amount_above_usd"])
                        if match.get("amount_above_usd") is not None
                        else None
                    ),
                    merchants=tuple(match["merchants"]) if match.get("merchants") else None,
                    source=match.get("source", "any"),
                    origin=origin,
                )
            )

    if user_overrides:
        _add(user_overrides.get("rules") or [], "user")
    _add(
        [r.model_dump() for r in settings.approval_rules.rules],
        "default",
    )
    return rules


def _matches(
    rule: _Rule, tool_name: str, risk: str, amount: float | None,
    merchants: str | None, source: str,
) -> bool:
    if rule.tools is not None and tool_name not in rule.tools:
        return False
    if rule.risk is not None and rule.risk != risk:
        return False
    if rule.amount_above_usd is not None:
        if amount is None or amount <= rule.amount_above_usd:
            return False
    if rule.merchants is not None:
        if merchants is None or not any(merchants.endswith(m) or merchants == m for m in rule.merchants):
            return False
    if rule.source not in ("any", source):
        return False
    return True


def summarize(args: dict[str, Any]) -> str:
    """Short human summary of a call for approval prompts."""
    if not args:
        return "(no arguments)"
    parts = []
    for key, value in list(args.items())[:4]:
        text = str(value).replace("\n", " ")
        parts.append(f"{key}={text[:80]}")
    more = f" (+{len(args) - 4} more)" if len(args) > 4 else ""
    return ", ".join(parts) + more


def _first_match(
    rules: list[_Rule], tool_name: str, risk: str,
    amount: float | None, merchants: str | None, source: str,
) -> tuple[Action, str]:
    for rule in rules:
        if _matches(rule, tool_name, risk, amount, merchants, source):
            return rule.action, rule.origin
    return settings.approval_rules.fallback, "fallback"


def _strictest(a: Action, b: Action) -> Action:
    return a if _STRICTNESS[a] >= _STRICTNESS[b] else b


async def check(
    user_id: str | UUID,
    tool_name: str,
    tool_args: dict[str, Any],
    risk: str,
    task_source: str,
) -> Decision:
    """Decide how a non-safe tool call proceeds for THIS user, THIS mode."""
    user = await db.get_user(user_id if isinstance(user_id, UUID) else UUID(str(user_id)))
    if user is None:
        return Decision(action="deny", reason="unknown user")
    plan = settings.plan_for(billing._effective_plan(user))

    # ---- hard plan floors (config can never weaken these)
    if tool_name in PAYMENT_TOOLS and not plan.payments_enabled:
        return Decision(action="deny", reason=f"payments not enabled on the {user.plan_tier} plan")
    if tool_name in BROWSER_TOOLS and not plan.browser_tools:
        return Decision(action="deny", reason=f"browser tools not enabled on the {user.plan_tier} plan")
    if task_source == "job" and tool_name in PAYMENT_TOOLS:
        # Hard layer #1 of 2 (the second lives in tools/payments.py, Phase 6):
        # jobs can never auto-approve payments.
        pass  # falls through to the mode floor below, which is already strict

    amount = _extract_amount(tool_args)
    merchants = _extract_merchant(tool_args)

    action, origin = _first_match(
        _compile_rules(user.user_limits_json), tool_name, risk, amount, merchants, task_source
    )

    # ---- mode floor: autonomous tasks get no looser than require_approval
    # above "safe", regardless of the user's own rules or defaults.
    if task_source == "job" and risk != "safe":
        action = _strictest(action, "require_approval")

    if action == "auto_and_log":
        logger.info(
            "approval auto_and_log",
            extra={"user_id": str(user_id), "tool": tool_name, "rule_origin": origin},
        )

    return Decision(action=action, reason=f"matched {origin} rule")


async def request_and_wait(
    user_id: str | UUID,
    task_id: str | UUID | None,
    action_summary: str,
    details_json: dict[str, Any],
) -> bool:
    """Record an approval request, deliver it, wait for THIS user's decision.

    Returns True only if the owning user approved in time. Timeout/expiry
    defaults to deny.
    """
    uid = user_id if isinstance(user_id, UUID) else UUID(str(user_id))
    approval = await db.record_approval(
        uid,
        UUID(str(task_id)) if task_id else None,
        action_summary,
        details_json,
    )
    await events.publish(
        events.APPROVAL_REQUESTED,
        {
            "user_id": str(uid),
            "approval_id": str(approval.id),
            "task_id": str(task_id) if task_id else None,
            "action_summary": action_summary,
            "details": details_json,
        },
    )
    started = time.monotonic()
    reply = await events.wait_for(
        events.APPROVAL_DECIDED,
        predicate=lambda p: p.get("user_id") == str(uid)
        and p.get("approval_id") == str(approval.id),
        timeout=settings.limits.approval_timeout_seconds,
    )
    if reply is None:
        await db.update_approval(uid, approval.id, "expired")
        logger.warning("approval timed out", extra={"user_id": str(uid), "approval_id": str(approval.id)})
        return False
    approved = bool(reply.get("approved"))
    await db.update_approval(uid, approval.id, "approved" if approved else "denied")
    logger.info(
        "approval decided",
        extra={
            "user_id": str(uid),
            "approval_id": str(approval.id),
            "approved": approved,
            "wait_ms": int((time.monotonic() - started) * 1000),
        },
    )
    return approved


async def decide(user_id: str | UUID, approval_id: str, approved: bool) -> bool:
    """Resolve a pending approval. Only the owning user can decide their own."""
    uid = user_id if isinstance(user_id, UUID) else UUID(str(user_id))
    from uuid import UUID as _UUID

    updated = await db.update_approval(uid, _UUID(approval_id), "approved" if approved else "denied")
    if updated is None:
        logger.warning(
            "approval decision refused (not owner or already resolved)",
            extra={"user_id": str(uid), "approval_id": approval_id},
        )
        return False
    await events.publish(
        events.APPROVAL_DECIDED,
        {"user_id": str(uid), "approval_id": approval_id, "approved": approved},
    )
    return True


def _extract_amount(args: dict[str, Any]) -> float | None:
    for key in ("amount", "amount_usd", "value"):
        value = args.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        # Phase 6: purchase amounts arrive as strings; amount-tiered rules
        # must apply to them too (a rule keyed on amount can't ignore the
        # only tool that carries an amount).
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def _extract_merchant(args: dict[str, Any]) -> str | None:
    for key in ("merchant", "domain", "site"):
        value = args.get(key)
        if isinstance(value, str):
            return value.lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    return None
