#!/usr/bin/env python3
"""Offline unit tests for the Jev adapter (Phase 9 build checks).

No network: transport is monkeypatched with canned responses/outcomes.
Run: python3 test_jev_adapter.py
"""
import json
import re
import unittest
import urllib.error

import jev_adapter as ja

SNAP = """[12] <a> "Pricing"
[13] <input type=email> "Email"
[14] <button> "Sign in"
garbage line that matches nothing
[99] <canvas> "chart"
[15] <input type=checkbox> "Remember me\""""

IDS = ["c12", "c13", "c14", "c15", "escalate", "stop", "no_valid_action"]


def cfg(enabled=True, **over):
    c = ja.load_config()
    c["enabled"] = enabled
    c.update(over)
    return c


def canned(model="jev-1.13.0", choice="c14", conf=0.9, probs=None,
           include_conf=True, include_noul=True):
    p = {i: round(0.2 / (len(IDS) - 1), 4) for i in IDS}
    p[choice] = round(1.0 - sum(p.values()), 4)
    if probs is not None:
        p = probs
    action = {"choice": choice, "probabilities": p}
    if include_conf:
        action["confidence"] = conf
    answers = {"action": action}
    if include_noul:
        answers["sufficient"] = {"value": True, "probability": 0.8}
    return json.dumps({"model": model, "answers": answers})


def refusing_transport(*a, **k):  # any call while disabled is a test failure
    raise AssertionError("network transport must not be called")


class Candidates(unittest.TestCase):
    def test_parses_and_skips(self):
        c = ja.build_candidates(SNAP)
        self.assertEqual([x["id"] for x in c], ["c12", "c13", "c14", "c15"])
        self.assertEqual(c[1]["action_type"], "type")
        self.assertEqual(c[2]["action_type"], "click")

    def test_empty_snapshot(self):
        self.assertEqual(ja.build_candidates("nothing here"), [])


class Decide(unittest.TestCase):
    def test_disabled_route_refuses_and_never_calls_network(self):
        r = ja.decide("s", "page", SNAP, credential="k",
                      config=cfg(enabled=False), transport=refusing_transport)
        self.assertEqual(r["outcome"], "route_disabled")

    def test_missing_credential_falls_back(self):
        r = ja.decide("s", "page", SNAP, credential=None, config=cfg(),
                      transport=refusing_transport)
        self.assertEqual(r["outcome"], "fallback")

    def test_execute_valid(self):
        r = ja.decide("sign in", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: canned())
        self.assertEqual(r["outcome"], "execute")
        self.assertEqual((r["ref"], r["action_type"]), ("14", "click"))

    def test_low_confidence_escalates(self):
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: canned(conf=0.3))
        self.assertEqual(r["outcome"], "escalate")

    def test_special_outcomes_pass_through(self):
        for sid in ("escalate", "stop", "no_valid_action"):
            r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                          transport=lambda *a, sid=sid: canned(choice=sid))
            self.assertEqual(r["outcome"], sid)

    def test_unknown_id_rejected_and_falls_back(self):
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: canned(choice="c999"))
        self.assertEqual(r["outcome"], "reject")
        self.assertTrue(r["fallback"])

    def test_model_pin_mismatch_rejected(self):
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: canned(model="jev-latest"))
        self.assertEqual(r["outcome"], "reject")

    def test_probability_sum_drift_rejected(self):
        p = {i: 0.05 for i in IDS}
        p["c14"] = 0.5
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: canned(probs=p))
        self.assertEqual(r["outcome"], "reject")

    def test_non_finite_probability_rejected(self):
        raw = re.sub(r'"c14": [0-9.]+', '"c14": NaN', canned())
        self.assertIn("NaN", raw)
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: raw)
        self.assertEqual(r["outcome"], "reject")

    def test_missing_confidence_rejected(self):
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: canned(include_conf=False))
        self.assertEqual(r["outcome"], "reject")

    def test_argmax_mismatch_rejected(self):
        raw = json.dumps({
            "model": "jev-1.13.0",
            "answers": {"action": {
                "choice": "c14",
                "probabilities": {**{i: 0.02 for i in IDS}, "c12": 0.86},
                "confidence": 0.9},
                "sufficient": {"value": True, "probability": 0.8}},
        })
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: raw)
        self.assertEqual(r["outcome"], "reject")

    def test_noul_carries_no_confidence_by_design(self):
        """Per docs: Noul has no confidence; absence must not reject."""
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=lambda *a: canned())
        self.assertEqual(r["outcome"], "execute")

    def test_budget_exhausted(self):
        b = ja.LocalBudget(1)
        self.assertTrue(b.charge())
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      budget=b, transport=refusing_transport)
        self.assertEqual(r["outcome"], "budget_exhausted")

    def test_rate_limited_falls_back_without_retry(self):
        calls = []

        def t(*a):
            calls.append(1)
            raise urllib.error.HTTPError("http://x", 429, "rc", None, None)
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=t)
        self.assertEqual(r["outcome"], "provider_rate_limited")
        self.assertEqual(len(calls), 1)

    def test_transient_then_success(self):
        state = {"n": 0}

        def t(*a):
            state["n"] += 1
            if state["n"] == 1:
                raise TimeoutError("deadline")
            return canned()
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=t)
        self.assertEqual(r["outcome"], "execute")
        self.assertEqual(state["n"], 2)

    def test_persistent_outage_falls_back(self):
        def t(*a):
            raise TimeoutError("deadline")
        r = ja.decide("s", "page", SNAP, credential="k", config=cfg(),
                      transport=t)
        self.assertEqual(r["outcome"], "provider_error")
        self.assertTrue(r["fallback"])

    def test_no_candidates(self):
        r = ja.decide("s", "page", "no elements", credential="k",
                      config=cfg(), transport=refusing_transport)
        self.assertEqual(r["outcome"], "no_valid_action")


if __name__ == "__main__":
    unittest.main(verbosity=2)
