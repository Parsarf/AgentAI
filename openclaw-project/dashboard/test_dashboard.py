#!/usr/bin/env python3
"""Phase 8B regression tests — offline, no server, no VPS.

Covers the §1 defect fixes: dotted file names, containment (symlink/`..`/
hidden/absolute rejection, descriptor-based reads with size caps), session
lifecycle (hashed ids, idle/absolute expiry, per-session logout, revoke-all),
single-use download signatures, truthful unhealthy-container status, central
redaction, audit-on-unwritable-path. Run: python3 -m unittest test_dashboard -v
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

SPEC = importlib.util.spec_from_file_location(
    "app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)

WORKREAD = os.path.join(os.path.dirname(__file__), "workread.mjs")


def workread(mode, rel, max_bytes=2000, root=None):
    env = dict(os.environ)
    if root:
        env["WR_ROOT"] = root
    p = subprocess.run(["node", WORKREAD, mode, rel, str(max_bytes)],
                       capture_output=True, text=True, env=env, timeout=15)
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "non-json: " + p.stdout[:80] + p.stderr[:80]}


class WorkreadContainment(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="wr-")
        os.makedirs(os.path.join(self.root, "site"))
        with open(os.path.join(self.root, "site", "index.html"), "w") as f:
            f.write("<h1>hi</h1>")
        with open(os.path.join(self.root, "site", "app.test.js"), "w") as f:
            f.write("// dotted name")
        with open(os.path.join(self.root, "outside.txt"), "w") as f:
            f.write("secret")
        os.symlink(os.path.join(self.root, "outside.txt"),
                   os.path.join(self.root, "site", "sneaky.lnk"))
        with open(os.path.join(self.root, ".hidden"), "w") as f:
            f.write("nope")

    def test_dotted_names_listed_and_readable(self):
        r = workread("list", "", root=self.root)
        names = [e["name"] for e in r["entries"]]
        self.assertIn("site", names)
        r = workread("list", "site", root=self.root)
        names = [e["name"] for e in r["entries"]]
        self.assertIn("index.html", names)
        self.assertIn("app.test.js", names)
        r = workread("read", "site/index.html", root=self.root)
        self.assertTrue(r["ok"]) and self.assertIn("<h1>hi</h1>", r["content"])

    def test_traversal_forms_rejected(self):
        for bad in ("../outside.txt", "..", "site/../../outside.txt",
                    "/etc/passwd", ".hidden", "site/.hidden", "site/\x2e%2e"):
            r = workread("read", bad, root=self.root)
            self.assertFalse(r.get("ok"), f"accepted {bad!r}")

    def test_symlink_refused(self):
        r = workread("read", "site/sneaky.lnk", root=self.root)
        self.assertFalse(r["ok"])
        r = workread("list", "site", root=self.root)
        self.assertTrue(r["ok"])  # real dir still lists

    def test_size_cap_on_descriptor(self):
        with open(os.path.join(self.root, "site", "big.bin"), "wb") as f:
            f.write(b"x" * 5000)
        r = workread("read", "site/big.bin", 2000, root=self.root)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "too_large")

    def test_missing_component(self):
        self.assertFalse(workread("list", "does-not-exist", root=self.root)["ok"])


class Redaction(unittest.TestCase):
    def test_patterns(self):
        cases = {
            "Authorization: Bearer abcdef1234567890abc": "Bearer [REDACTED]",
            "key sk-abcdef1234567890abcdef": "sk-[REDACTED]",
            "api_key: supersecretvalue123": "api_key: [REDACTED]",
            "Set-Cookie: dsh=supersecretvalue123": "[REDACTED]",
        }
        for src, want in cases.items():
            out = app.redact(src)
            self.assertIn("[REDACTED]", out, src)
            self.assertNotIn(src.split()[-1], out, src)


class Sessions(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix="sess-")
        os.close(fd)
        os.unlink(self.path)
        self.store = app.SessionStore(self.path)

    def test_create_validate_logout(self):
        tok, csrf = self.store.create()
        self.assertTrue(self.store.validate(tok))
        self.store.destroy(tok)
        self.assertIsNone(self.store.validate(tok))

    def test_unique_tokens(self):
        a, _ = self.store.create()
        b, _ = self.store.create()
        self.assertNotEqual(a, b)

    def test_idle_expiry(self):
        tok, _ = self.store.create()
        h = __import__("hashlib").sha256(tok.encode()).hexdigest()
        d = json.load(open(self.path))
        d[h]["last"] -= app.SESSION_TTL_IDLE + 10
        json.dump(d, open(self.path, "w"))
        self.assertIsNone(self.store.validate(tok))

    def test_absolute_expiry(self):
        tok, _ = self.store.create()
        h = __import__("hashlib").sha256(tok.encode()).hexdigest()
        d = json.load(open(self.path))
        d[h]["created"] -= app.SESSION_TTL_ABS + 10
        json.dump(d, open(self.path, "w"))
        self.assertIsNone(self.store.validate(tok))

    def test_revoke_all(self):
        self.store.create()
        self.store.create()
        self.assertGreaterEqual(self.store.destroy_all(), 2)
        self.assertEqual(self.store._load(), {})

    def test_stored_hashes_not_tokens(self):
        tok, _ = self.store.create()
        raw = open(self.path).read()
        self.assertNotIn(tok, raw)


class DownloadClaims(unittest.TestCase):
    def test_single_use(self):
        app._used_dl.clear()
        self.assertTrue(app.claim_download("sig1", time.time() + 300))
        self.assertFalse(app.claim_download("sig1", time.time() + 300))
        self.assertTrue(app.claim_download("sig2", time.time() + 300))

    def test_expired_claims_pruned(self):
        app._used_dl.clear()
        app._used_dl["old"] = time.time() - 10
        self.assertTrue(app.claim_download("new", time.time() + 300))
        self.assertNotIn("old", app._used_dl)


class TruthfulStatus(unittest.TestCase):
    def test_unhealthy_container_marks_warn(self):
        orig = app.run
        app.run = lambda *a, **k: (0, "gw|Up 5m\nsbx-1|Up 2h (unhealthy)")
        try:
            o = app.containers()
        finally:
            app.run = orig
        self.assertEqual(o["state"], "warn")
        self.assertIn("1 unhealthy", o["label"])

    def test_observation_timestamp_preserved(self):
        o = app.obs("x", "stale", "detail", ts="2020-01-01 00:00:00Z")
        self.assertEqual(o["ts"], "2020-01-01 00:00:00Z")


class Audit(unittest.TestCase):
    def test_unwritable_path_returns_false(self):
        orig = app.AUDIT
        app.AUDIT = "/proc/definitely/not/writable/audit.jsonl"
        try:
            self.assertFalse(app.audit("x", "y", "z"))
        finally:
            app.AUDIT = orig


class FeatureSwitches(unittest.TestCase):
    """The owner UI is the only place optional features are switched; it must never bypass a gate."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.saved = {k: getattr(app, k) for k in ("SWITCH_FILE", "SWITCH_FACTS", "JEV_DIR", "AUDIT", "AUDIT_DIR", "run")}
        app.SWITCH_FILE, app.SWITCH_FACTS = os.path.join(d, "sw", "switches.json"), os.path.join(d, "sw", "facts.json")
        app.JEV_DIR, app.AUDIT_DIR = os.path.join(d, "jev"), os.path.join(d, "audit")
        app.AUDIT = os.path.join(app.AUDIT_DIR, "audit.jsonl")
        os.makedirs(app.AUDIT_DIR); os.makedirs(os.path.dirname(app.SWITCH_FILE))
        self.key_present = True
        app.run = lambda argv, timeout=25: (0 if self.key_present else 1, "")
        self.addCleanup(lambda: [setattr(app, k, v) for k, v in self.saved.items()])
        self.rec = {"csrf": "CSRF123"}

    def facts(self, **kw):
        with open(app.SWITCH_FACTS, "w") as f:
            json.dump(kw, f)

    def plugin_file(self):
        try:
            return json.load(open(os.path.join(app.JEV_DIR, "config.json")))["enabled"]
        except OSError:
            return None

    def audit_lines(self):
        return [json.loads(l) for l in open(app.AUDIT)]

    def test_everything_defaults_off_and_turn_on_is_refused_with_reasons(self):
        ok, message = app.apply_switch("research_optimization", True)
        self.assertFalse(ok)
        self.assertIn("Confirm", message)
        self.assertIsNone(self.plugin_file())                      # plugin file untouched on refusal
        self.assertIn("refused on", self.audit_lines()[-1]["result"])
        self.assertEqual(app.apply_switch("nonsense", True), (False, "unknown switch"))

    def test_full_flow_confirm_then_on_then_off_mirrors_plugin_file_and_audits(self):
        self.facts(research_provenance=True)
        app.switch_store().confirm("research_optimization", "data_handling", "owner")
        ok, message = app.apply_switch("research_optimization", True)
        self.assertTrue(ok, message)
        self.assertIs(self.plugin_file(), True)
        self.assertEqual(self.audit_lines()[-1]["action"], "switch")
        ok, _ = app.apply_switch("research_optimization", False)
        self.assertTrue(ok)
        self.assertIs(self.plugin_file(), False)
        self.assertFalse(app.switch_store().is_on("research_optimization"))

    def test_missing_server_key_blocks_turning_on(self):
        self.key_present = False
        self.facts(research_provenance=True)
        app.switch_store().confirm("research_optimization", "data_handling", "owner")
        ok, message = app.apply_switch("research_optimization", True)
        self.assertFalse(ok)
        self.assertIn("TypeSafe key", message)

    def test_plugin_file_disagreement_forces_the_switch_off(self):
        self.facts(research_provenance=True)
        app.switch_store().confirm("research_optimization", "data_handling", "owner")
        original = app.write_jev_plugin_file
        app.write_jev_plugin_file = lambda on: (False if on else original(on))   # plugin file refuses to turn on
        self.addCleanup(lambda: setattr(app, "write_jev_plugin_file", original))
        ok, message = app.apply_switch("research_optimization", True)
        self.assertFalse(ok)
        self.assertIn("switched off", message)
        self.assertFalse(app.switch_store().is_on("research_optimization"))

    def test_page_shows_plain_status_reasons_drift_and_csrf(self):
        os.makedirs(app.JEV_DIR)
        json.dump({"enabled": True}, open(os.path.join(app.JEV_DIR, "config.json"), "w"))   # the real server state on 2026-10-09
        html_page = app.switches_page(self.rec)
        self.assertIn("plugin file on the server says ON", html_page)
        self.assertIn("Turn it off everywhere", html_page)
        self.assertIn("Locked until the safety checks", html_page)           # locked switches explain themselves
        self.assertIn("Before it can be turned on", html_page)
        self.assertIn("CSRF123", html_page)
        self.assertNotIn("Turn ON</button>", html_page)                      # nothing can be switched on yet
        self.assertEqual(html_page.count("name=value value=on"), 0)

    def test_turn_it_off_everywhere_fixes_the_drift(self):
        os.makedirs(app.JEV_DIR)
        json.dump({"enabled": True}, open(os.path.join(app.JEV_DIR, "config.json"), "w"))
        ok, _ = app.apply_switch("research_optimization", False)
        self.assertTrue(ok)
        self.assertIs(self.plugin_file(), False)
        self.assertNotIn("plugin file on the server says ON", app.switches_page(self.rec))

    def test_locked_switches_have_no_on_button_even_with_every_fact_true(self):
        self.facts(**{f: True for s in app.switches.CATALOG.values() for f, _ in s.needs})
        html_page = app.switches_page(self.rec)
        for key in ("customer_schedules", "claude_code_for_customers"):
            self.assertEqual(app.apply_switch(key, True)[0], False)
        self.assertIn("Locked", html_page)

    def test_no_other_code_path_writes_the_plugin_toggle(self):
        source = open(os.path.join(os.path.dirname(__file__), "app.py")).read()
        self.assertEqual(source.count('json.dump({"enabled"'), 1)             # only write_jev_plugin_file


class RoutingControls(FeatureSwitches):
    """Routing settings: validated, audited, and always switch-offable."""

    def setUp(self):
        super().setUp()
        self.saved.update({k: getattr(app, k) for k in ("ROUTING_DIR", "ROUTING_FILE", "ROUTING_KEY")})
        d = self.tmp.name
        app.ROUTING_DIR = os.path.join(d, "routing"); app.ROUTING_FILE = os.path.join(app.ROUTING_DIR, "routing.json")
        app.ROUTING_KEY = os.path.join(app.ROUTING_DIR, "typesafe.key")

    def test_save_validates_audits_and_never_enables_canary(self):
        ok, msg = app.routing_save({"enabled": "on", "automatic": "0.9", "review": "0.7", "route_claude": "on", "route_deterministic": "on"})
        self.assertTrue(ok, msg)
        cfg = json.load(open(app.ROUTING_FILE))
        self.assertEqual((cfg["enabled"], cfg["mode"], cfg["canary_percent"], cfg["confidence"]["automatic"]), (True, "shadow", 0, 0.9))
        self.assertEqual(oct(os.stat(app.ROUTING_FILE).st_mode & 0o777), "0o600")
        self.assertEqual(self.audit_lines()[-1]["action"], "routing-save")

    def test_bad_values_are_refused_and_leave_the_file_alone(self):
        app.routing_save({"enabled": "on", "route_claude": "on"})
        before = open(app.ROUTING_FILE).read()
        for bad in ({"automatic": "0.5", "review": "0.9"}, {"max_task_cost_usd": "50"}, {"automatic": "abc"}, {"max_escalations": "-1"}):
            ok, _ = app.routing_save({"enabled": "on", "route_claude": "on", **bad})
            self.assertFalse(ok)
        self.assertEqual(open(app.ROUTING_FILE).read(), before)

    def test_rollback_turns_config_and_switch_off_and_page_renders(self):
        self.facts(routing_key_present=True)
        open(app.ROUTING_KEY, "w").close() if os.path.isdir(app.ROUTING_DIR) else None
        app.routing_save({"enabled": "on", "route_claude": "on"})
        sw = app.switch_store(); sw.facts = lambda: {"routing_key_present": True}
        sw.confirm("jev_routing", "data_handling", "owner"); sw.set("jev_routing", True, "owner")
        ok, _ = app.routing_rollback()
        self.assertTrue(ok)
        self.assertFalse(json.load(open(app.ROUTING_FILE))["enabled"])
        self.assertFalse(app.switch_store().describe("jev_routing")["recorded_on"])
        app.routing_report = lambda: {"total_routed": 0, "classified": 0, "unavailable_or_rejected": 0, "jev_selected_percent": None,
            "claude_escalation_percent": None, "would_change_route_percent": None, "success_percent": None, "failed_count": 0,
            "avg_task_cost_usd": None, "avg_task_seconds": None, "avg_classifier_latency_ms": None,
            "confidence_distribution": {"<0.65": 0}, "by_recommended_route": {}, "classifier_cost_usd_estimated": 0, "estimated_monthly_savings_usd": None}
        html = app.routing_page(self.rec)
        self.assertIn("Emergency rollback", html); self.assertIn("not measured yet", html); self.assertNotIn("typesafe.key", html)


class FeatureSwitchesOverHttp(FeatureSwitches):
    """Drives the real request handler: login, page, CSRF, refused turn-on, turn-off."""

    def setUp(self):
        super().setUp()
        import http.cookiejar, threading, urllib.request
        from http.server import ThreadingHTTPServer
        d = self.tmp.name
        self.saved2 = {k: getattr(app, k) for k in ("DIR", "OWNER_SECRET", "SESSION_SECRET", "SESSIONS", "gw_health")}
        app.DIR = d
        app.OWNER_SECRET, app.SESSION_SECRET = os.path.join(d, "owner-secret"), os.path.join(d, "session-secret")
        open(app.OWNER_SECRET, "w").write("correct horse battery"); os.chmod(app.OWNER_SECRET, 0o600)
        open(app.SESSION_SECRET, "w").write("s" * 64); os.chmod(app.SESSION_SECRET, 0o600)
        app.SESSIONS = app.SessionStore(os.path.join(d, "sessions.json"))
        self.addCleanup(lambda: [setattr(app, k, v) for k, v in self.saved2.items()])
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.jar = http.cookiejar.CookieJar()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def call(self, path, data=None):
        import urllib.error, urllib.parse, urllib.request
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        try:
            r = self.opener.open(urllib.request.Request(self.base + path, data=body), timeout=10)
            return r.status, r.read().decode(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), e.headers

    def login(self):
        self.call("/login", {"password": "correct horse battery"})
        status, page_html, _ = self.call("/switches")
        self.assertEqual(status, 200)
        import re
        return re.search(r"name=csrf value='([^']+)'", page_html).group(1), page_html

    def test_requires_login(self):
        self.assertEqual(self.call("/switches")[0], 303)
        self.assertEqual(self.call("/switch", {"name": "research_optimization", "value": "off"})[0], 403)

    def test_page_post_flow_through_the_real_handler(self):
        csrf, page_html = self.login()
        self.assertIn("Feature switches", page_html)
        self.assertEqual(self.call("/switch", {"csrf": "wrong", "name": "research_optimization", "value": "off"})[0], 403)
        status, _, headers = self.call("/switch", {"csrf": csrf, "name": "research_optimization", "value": "on"})
        self.assertEqual(status, 303)
        self.assertIn("Confirm", headers["Location"])                       # refused with a plain reason
        self.assertFalse(app.switch_store().is_on("research_optimization"))
        self.assertEqual(self.call("/switch", {"csrf": csrf, "name": "research_optimization", "value": "banana"})[0], 400)
        status, _, headers = self.call("/switch-confirm", {"csrf": csrf, "name": "research_optimization", "id": "data_handling"})
        self.assertEqual(status, 303)
        self.assertEqual(self.call("/switch-confirm", {"csrf": csrf, "name": "research_optimization", "id": "bogus"})[0], 400)
        os.makedirs(app.JEV_DIR, exist_ok=True)
        json.dump({"enabled": True}, open(os.path.join(app.JEV_DIR, "config.json"), "w"))
        self.call("/switch", {"csrf": csrf, "name": "research_optimization", "value": "off"})
        self.assertIs(self.plugin_file(), False)
        status, page_html, _ = self.call("/switches?msg=hello")
        self.assertIn("hello", page_html)
        # the old toggle endpoints now go through the same checks
        status, _, headers = self.call("/toggle", {"csrf": csrf, "name": "jev_research", "value": "on"})
        self.assertIn("/switches", headers["Location"])
        self.assertIs(self.plugin_file(), False)
        status, _, headers = self.call("/jev-toggle", {"csrf": csrf, "layer": "research", "value": "on"})
        self.assertIs(self.plugin_file(), False)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class CustomersPage(unittest.TestCase):
    """Approving people is the owner's call: only fixed actions and validated ids ever reach the host command."""

    def setUp(self):
        self.saved = app.run
        self.calls = []
        self.listing = {"limit": 2, "assistants": 1, "customers": [
            {"account": "su1", "status": "suspended", "email": "wait@example.test", "signup": "pending", "created_epoch": 1791900000, "decided_epoch": None, "assistant": None},
            {"account": "acc2", "status": "active", "email": "cust@example.test", "signup": "approved", "created_epoch": 1791800000, "decided_epoch": 1791800500, "assistant": "ready"},
            {"account": "su3", "status": "suspended", "email": "new@example.test", "signup": "unverified", "created_epoch": 1791900100, "decided_epoch": None, "assistant": None}]}

        def fake(argv, timeout=25):
            self.calls.append(argv)
            if argv[-1] == "list":
                return 0, "noise\n" + json.dumps(self.listing)
            return 0, json.dumps({"ok": True})
        app.run = fake
        self.addCleanup(lambda: setattr(app, "run", self.saved))
        self.rec = {"csrf": "CSRF123"}

    def test_page_lists_waiting_people_with_approve_and_decline(self):
        html_page = app.customers_page(self.rec)
        self.assertIn("wait@example.test", html_page)
        self.assertIn("Waiting for your approval (1)", html_page)
        self.assertIn("value='approve'", html_page); self.assertIn("value='decline'", html_page)
        self.assertIn("Assistants: <b>1 of 2</b>", html_page)
        self.assertIn("email not confirmed", html_page)
        self.assertEqual(html_page.count("value='suspend'"), 1)             # only the active customer can be suspended
        self.assertNotIn("<b>OPEN</b>", html_page)

    def test_actions_use_fixed_words_and_validated_ids_only(self):
        ok, msg = app.customer_action("approve", "su1")
        self.assertTrue(ok); self.assertEqual(self.calls[-1][-3:], ["approve", "--account", "su1"])
        self.assertTrue(all(isinstance(a, str) for a in self.calls[-1]))
        for action, account in (("delete", "su1"), ("approve", "x; rm -rf /"), ("approve", ""), ("approve", "a" * 65), ("resume", "../../etc")):
            before = len(self.calls)
            ok, _ = app.customer_action(action, account)
            self.assertFalse(ok); self.assertEqual(len(self.calls), before)  # nothing reached the host

    def test_limit_validation_and_failed_listing_is_honest(self):
        self.assertTrue(app.customer_limit("5")[0]); self.assertEqual(self.calls[-1][-3:], ["limit", "--count", "5"])
        for bad in ("0", "201", "-1", "ten", "5; ls"):
            self.assertFalse(app.customer_limit(bad)[0])
        app.run = lambda argv, timeout=25: (1, "boom")
        self.assertIn("Could not read the customer list", app.customers_page(self.rec))

    def test_a_refusal_is_reported_not_hidden(self):
        app.run = lambda argv, timeout=25: (1, "CommandError: Customer limit reached (2). Raise the limit first.")
        ok, msg = app.customer_action("approve", "su1")
        self.assertFalse(ok); self.assertIn("limit reached", msg)
