#!/usr/bin/env python3
"""Optimized browser route controller (Phase 12, DISABLED by config.json).

Owns the loop around ``jev_adapter.decide``: deadlines, action cap, loop
detection, cancellation, fresh-target re-check, budget admission for every
paid call (planner, Jev, retry, fallback), receipt-based reconciliation and the
hand-off to the baseline browser-worker route.

Invariants:
  * Jev only ever selects a code-created candidate; code executes it.
  * Nothing executes without a fresh-target re-check immediately beforehand.
  * Fallback to the baseline route happens only when no effect is outstanding:
    an uncertain effect is reconciled from observed state first and, if it
    stays unknown, the route stops for an operator instead of retrying.
  * An optimization outage never re-sends an action: every action carries an
    idempotency key and a receipt.
  * Budget denial stops paid optimization and hands off; it never evades caps.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import jev_adapter as ja

LOOP_REPEATS = 2          # same target on the same page more than twice => loop


@dataclass
class Receipt:
    effect: str            # applied | none | uncertain
    detail: str = ""


@dataclass
class RouteResult:
    status: str            # handoff | stopped | cancelled | halted | max_actions | deadline | disabled
    reason: str = ""
    executed: int = 0
    safe_to_fallback: bool = True
    steps: list = field(default_factory=list)


class OptimizedRoute:
    def __init__(self, config, *, observe, executor, admit, cancelled, credential,
                 transport=ja._http_post, clock=time.monotonic, task_id="task"):
        self.cfg, self.observe, self.executor = config, observe, executor
        self.admit, self.cancelled, self.credential = admit, cancelled, credential
        self.transport, self.clock, self.task_id = transport, clock, task_id

    def run(self, subgoal: str, *, deadline_s: float = 120.0) -> RouteResult:
        if not self.cfg.get("enabled"):
            return RouteResult("disabled", self.cfg.get("enabled_reason", "disabled"))
        started = self.clock()
        max_actions = int(self.cfg.get("budget", {}).get("max_actions_per_task", 40))
        result = RouteResult("handoff")
        seen: dict[tuple, int] = {}
        outstanding_uncertain = False

        def done(status, reason="", safe=None):
            result.status, result.reason = status, reason
            result.safe_to_fallback = (not outstanding_uncertain) if safe is None else safe
            return result

        while True:
            if self.cancelled():
                return done("cancelled", "cancellation requested", safe=False)
            if self.clock() - started > deadline_s:
                return done("deadline", "task deadline reached")
            if result.executed >= max_actions:
                return done("max_actions", "action cap reached")
            if not self.admit("jev"):
                return done("handoff", "budget admission denied for a Jev call")
            page_text, snapshot, url = self.observe()
            decision = ja.decide(subgoal, page_text, snapshot, credential=self.credential, config=self.cfg,
                                 transport=self.transport)
            outcome = decision["outcome"]
            result.steps.append({"outcome": outcome, "reason": decision.get("reason", "")})
            if outcome == "stop":
                return done("stopped", "model declared the subgoal complete; baseline must verify")
            if outcome != "execute":
                return done("handoff", f"{outcome}: {decision.get('reason', '')}".strip(": "))
            # Fresh-target check on a NEW observation, right before acting.
            _, fresh_snapshot, fresh_url = self.observe()
            if fresh_url != url or not ja.verify_fresh(decision, fresh_snapshot, self.cfg.get("max_candidates", 20)):
                return done("handoff", "stale target: page changed between decision and execution")
            key = (fresh_url, decision["fingerprint"])
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > LOOP_REPEATS:
                return done("handoff", "loop detected: same target repeated on the same page")
            if self.cancelled():
                return done("cancelled", "cancellation requested", safe=False)
            idem = f"{self.task_id}-{result.executed + 1}-{decision['fingerprint']}"
            receipt = self.executor.perform(decision["action_type"], decision["ref"], idem)
            if receipt.effect == "uncertain":
                verdict = self.executor.reconcile(idem)
                if verdict == "applied":
                    receipt = Receipt("applied", "reconciled from observed state")
                elif verdict == "none":
                    receipt = Receipt("none", "reconciled: no effect")
                else:
                    outstanding_uncertain = True
                    return done("halted", "effect unknown after reconciliation; operator review required, no retry", safe=False)
            if receipt.effect == "applied":
                result.executed += 1
            elif receipt.effect == "none":
                return done("handoff", "action had no effect; baseline continues from current page")
            else:
                return done("halted", "unrecognised receipt", safe=False)
