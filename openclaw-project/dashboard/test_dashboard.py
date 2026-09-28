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


if __name__ == "__main__":
    unittest.main(verbosity=2)
