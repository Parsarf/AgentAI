#!/usr/bin/env python3
"""Offline tests for the optimized route controller (no network, scripted transport)."""
import json
import unittest

import jev_adapter as ja
import route as rt

PAGE = '[1] <a> "Pricing"\n[2] <a> "Docs"\n[3] <button> "Place order"'


def cfg(**over):
    c = ja.load_config()
    c["enabled"] = True
    c.update(over)
    return c


def reply(choice, ids=("c1", "c2", "c3"), conf=0.9):
    allids = list(ids) + ["escalate", "stop", "no_valid_action"]
    p = {i: round(0.2 / (len(allids) - 1), 4) for i in allids}
    p[choice] = round(1.0 - sum(v for k, v in p.items() if k != choice), 4)
    return json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 50, "output_tokens": 0},
                       "answers": {"action": {"type": "choice", "choice": choice, "probabilities": p, "confidence": conf}}})


class FakeExecutor:
    def __init__(self, effects=("applied",), reconcile="unknown"):
        self.effects, self.verdict, self.calls = list(effects), reconcile, []

    def perform(self, action_type, ref, key):
        self.calls.append((action_type, ref, key))
        effect = self.effects.pop(0) if self.effects else "applied"
        return rt.Receipt(effect)

    def reconcile(self, key):
        return self.verdict


class Harness:
    def __init__(self, replies, pages=None, **kw):
        self.replies, self.pages, self.admits, self.transport_calls = list(replies), list(pages or []), [], 0
        self.cancel_after = kw.pop("cancel_after", None)
        self.checks = 0
        self.executor = kw.pop("executor", FakeExecutor())
        self.budget_ok = kw.pop("budget_ok", lambda n: True)
        self.kw = kw

    def transport(self, *a):
        self.transport_calls += 1
        item = self.replies.pop(0) if self.replies else reply("stop")
        if isinstance(item, Exception):
            raise item
        return item

    def observe(self):
        page = self.pages.pop(0) if self.pages else PAGE
        return "text", page, "https://app.example/items"

    def admit(self, kind):
        self.admits.append(kind)
        return self.budget_ok(len(self.admits))

    def cancelled(self):
        self.checks += 1
        return self.cancel_after is not None and self.checks > self.cancel_after

    def route(self, config=None):
        return rt.OptimizedRoute(config or cfg(), observe=self.observe, executor=self.executor, admit=self.admit,
                                 cancelled=self.cancelled, credential="k", transport=self.transport, task_id="t1")


class RouteChecks(unittest.TestCase):
    def test_disabled_route_does_nothing(self):
        h = Harness([])
        r = h.route(cfg(enabled=False)).run("go")
        self.assertEqual((r.status, h.transport_calls, h.admits, h.executor.calls), ("disabled", 0, [], []))

    def test_happy_path_executes_with_idempotency_key_then_stops(self):
        h = Harness([reply("c2"), reply("stop")])
        r = h.route().run("open docs")
        self.assertEqual((r.status, r.executed), ("stopped", 1))
        self.assertEqual(len(h.executor.calls), 1)
        self.assertTrue(h.executor.calls[0][2].startswith("t1-1-"))
        self.assertEqual(h.admits, ["jev", "jev"])

    def test_budget_denial_stops_paid_calls_and_hands_off(self):
        h = Harness([reply("c2")], budget_ok=lambda n: False)
        r = h.route().run("go")
        self.assertEqual(r.status, "handoff")
        self.assertEqual((h.transport_calls, h.executor.calls), (0, []))

    def test_cancellation_before_and_after_decision(self):
        r = Harness([reply("c2")], cancel_after=0).route().run("go")
        self.assertEqual((r.status, r.safe_to_fallback), ("cancelled", False))
        h = Harness([reply("c2")], cancel_after=1)   # first check passes, second (pre-execute) cancels
        r = h.route().run("go")
        self.assertEqual((r.status, h.executor.calls), ("cancelled", []))

    def test_stale_target_executes_nothing(self):
        h = Harness([reply("c2")], pages=[PAGE, PAGE.replace('"Docs"', '"Guides"')])
        r = h.route().run("go")
        self.assertEqual((r.status, h.executor.calls), ("handoff", []))
        self.assertIn("stale", r.reason)

    def test_sensitive_control_goes_to_baseline_approval(self):
        h = Harness([reply("c3", conf=0.999)])
        r = h.route().run("go")
        self.assertEqual((r.status, h.executor.calls), ("handoff", []))
        self.assertIn("needs_approval", r.reason)

    def test_loop_detection(self):
        h = Harness([reply("c2")] * 6)
        r = h.route().run("go")
        self.assertEqual(r.status, "handoff")
        self.assertIn("loop", r.reason)
        self.assertEqual(r.executed, 2)

    def test_action_cap_and_deadline(self):
        config = cfg()
        config["budget"] = {**config["budget"], "max_actions_per_task": 1}
        h = Harness([reply("c1"), reply("c2"), reply("stop")])
        self.assertEqual(h.route(config).run("go").status, "max_actions")
        ticks = iter(range(0, 1000, 100))
        route = rt.OptimizedRoute(cfg(), observe=lambda: ("t", PAGE, "u"), executor=FakeExecutor(), admit=lambda k: True,
                                  cancelled=lambda: False, credential="k", transport=lambda *a: reply("c1"),
                                  clock=lambda: next(ticks))
        self.assertEqual(route.run("go", deadline_s=150).status, "deadline")

    def test_outage_never_resends_and_falls_back_with_nothing_executed(self):
        h = Harness([TimeoutError("deadline"), TimeoutError("deadline")])
        r = h.route().run("go")
        self.assertEqual((r.status, r.safe_to_fallback, h.executor.calls), ("handoff", True, []))

    def test_uncertain_effect_reconciles_before_any_fallback(self):
        # Applied after reconciliation: counted, not re-sent.
        h = Harness([reply("c1"), reply("stop")], executor=FakeExecutor(["uncertain"], reconcile="applied"))
        r = h.route().run("go")
        self.assertEqual((r.status, r.executed, len(h.executor.calls)), ("stopped", 1, 1))
        # Not applied after reconciliation: nothing outstanding, baseline may continue.
        h = Harness([reply("c1")], executor=FakeExecutor(["uncertain"], reconcile="none"))
        r = h.route().run("go")
        self.assertEqual((r.status, r.safe_to_fallback, len(h.executor.calls)), ("handoff", True, 1))
        # Unknown: halt for the operator, never fall back, never retry.
        h = Harness([reply("c1"), reply("c1")], executor=FakeExecutor(["uncertain", "applied"], reconcile="unknown"))
        r = h.route().run("go")
        self.assertEqual((r.status, r.safe_to_fallback, len(h.executor.calls)), ("halted", False, 1))

    def test_provider_failures_hand_off(self):
        import urllib.error
        for exc in (urllib.error.HTTPError("u", 429, "rc", None, None), urllib.error.HTTPError("u", 400, "bad", None, None)):
            r = Harness([exc]).route().run("go")
            self.assertEqual(r.status, "handoff")


if __name__ == "__main__":
    unittest.main()
