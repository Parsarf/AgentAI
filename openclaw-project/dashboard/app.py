#!/usr/bin/env python3
"""OpenClaw private owner dashboard v2 (Phase 8B).

Owner-only, loopback-only. stdlib Python. Browser ⇄ dashboard ⇄ fixed native
operations; no credential reaches the browser. All rendered agent/web content
is escaped text passed through redact(). Fail-open everywhere: any native
source that is missing or misshapen renders as "unknown"/"unavailable", never
as a healthy default. The Jev research layer toggle flips the plugin's
documented config file with readback; the browser layer is not deployed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http import cookies as http_cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "/opt/openclaw-production"
DIR = os.path.join(BASE, "dashboard")
AUDIT_DIR = os.path.join(DIR, "audit")
AUDIT = os.path.join(AUDIT_DIR, "audit.jsonl")
OWNER_SECRET = os.path.join(DIR, "owner-secret")
SESSION_SECRET = os.path.join(DIR, "session-secret")
STATIC = os.path.join(DIR, "static")
GATEWAY = "openclaw-production-openclaw-gateway-1"
POSTGRES = "openclaw-production-postgres-1"
LITELLM = "openclaw-production-litellm-1"
HOST_STATE = os.path.join(BASE, "openclaw-state")  # = container /home/node/.openclaw
JEV_DIR = os.path.join(HOST_STATE, "jev-research")
PORT, BIND = 18795, "127.0.0.1"
SESSION_TTL_IDLE, SESSION_TTL_ABS = 2 * 3600, 24 * 3600
DOWNLOAD_TTL, MAX_FILE_BYTES = 300, 2_000_000
WORK_ROOT = "/home/node/.openclaw/work"
WORKREAD = WORK_ROOT + "/.dashread.mjs"
CAPS = {"daily_usd": 2.0, "monthly_usd": 25.0}
MAX_STREAMS = 5
ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}
_login_fails: dict[str, list[float]] = {}
_streams = 0
_used_dl: dict[str, float] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def redact(text: str) -> str:
    """Central redaction applied before render/log/audit."""
    t = str(text)
    t = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{10,}", "Bearer [REDACTED]", t)
    t = re.sub(r"\bsk-[A-Za-z0-9_-]{10,}", "sk-[REDACTED]", t)
    t = re.sub(r"(?i)((?:api[_-]?key|token|password|secret|authorization)\s*[=:]\s*)(\S{6,})",
               r"\1[REDACTED]", t)
    t = re.sub(r"(?i)(set-cookie\s*:\s*)\S{6,}", r"\1[REDACTED]", t)
    return t


def run(argv: list[str], timeout: int = 25) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        out = p.stdout or ""
        if p.returncode != 0 and p.stderr:
            out += "\n" + p.stderr
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except FileNotFoundError:
        return 127, "command not found"
    except Exception as e:  # noqa: BLE001
        return 125, f"error: {type(e).__name__}"


def cached(key: str, ttl: int, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], hit[0]
    value = fn()
    _cache[key] = (now, value)
    return value, now


# ---------- secrets / sessions ----------

def _session_key() -> bytes:
    try:
        with open(SESSION_SECRET, "rb") as f:
            return f.read().strip()
    except FileNotFoundError:
        raw = secrets.token_hex(32).encode()
        fd = os.open(SESSION_SECRET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        return raw


def _sign(payload: str) -> str:
    return hmac.new(_session_key(), payload.encode(), hashlib.sha256).hexdigest()


def check_password(supplied: str) -> bool:
    try:
        with open(OWNER_SECRET, "rb") as f:
            want = f.read().strip()
    except OSError:
        return False
    return hmac.compare_digest(want, supplied.encode())


class SessionStore:
    """Random server-side session IDs; only SHA-256 hashes are stored."""

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()

    def _load(self) -> dict:
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict) -> None:
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(d, f)

    def create(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        h = hashlib.sha256(token.encode()).hexdigest()
        with _lock, self.lock:
            d = self._load()
            d[h] = {"created": time.time(), "last": time.time(),
                    "csrf": secrets.token_hex(16)}
            self._save(d)
        return token, d[h]["csrf"]

    def validate(self, token: str) -> dict | None:
        if not token:
            return None
        h = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            d = self._load()
            rec = d.get(h)
            if not rec:
                return None
            now = time.time()
            if now - rec["created"] > SESSION_TTL_ABS or now - rec["last"] > SESSION_TTL_IDLE:
                del d[h]
                self._save(d)
                return None
            rec["last"] = now
            self._save(d)
            return rec

    def destroy(self, token: str) -> None:
        h = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            d = self._load()
            if h in d:
                del d[h]
                self._save(d)

    def destroy_all(self) -> int:
        with self.lock:
            d = self._load()
            n = len(d)
            self._save({})
            return n


SESSIONS = SessionStore(os.path.join(DIR, "sessions.json"))


def audit(action: str, target: str, result: str) -> bool:
    rec = {"ts": now_iso(), "actor": "owner", "role": "owner",
           "action": action, "target": str(target)[:120], "result": result}
    try:
        with open(AUDIT, "a") as f:
            f.write(json.dumps(rec) + "\n")
        return True
    except OSError:
        return False


def audit_tail(n: int = 25) -> list[str]:
    try:
        with open(AUDIT) as f:
            return f.readlines()[-n:]
    except OSError:
        return []


# ---------- fixed native observations ----------

def obs(label: str, state: str, detail, ts: str | None = None) -> dict:
    return {"label": label, "state": state, "detail": detail, "ts": ts or now_iso()}


def gw_health() -> dict:
    ts = now_iso()
    try:
        with urllib.request.urlopen("http://127.0.0.1:18789/healthz", timeout=5) as r:
            ok = r.status == 200
        return obs("gateway /healthz", "ok" if ok else "down", f"HTTP {r.status}", ts)
    except Exception as e:  # noqa: BLE001
        return obs("gateway /healthz", "down", f"unavailable: {type(e).__name__}", ts)


def gw_version() -> dict:
    ts = now_iso()
    (rc, out), _ = cached("gwver", 300,
                          lambda: run(["docker", "exec", GATEWAY, "node", "dist/index.js", "--version"]))
    first = out.splitlines()[0][:120] if out else f"rc={rc}"
    return obs("gateway release", "ok" if rc == 0 else "unknown", first, ts)


def postgres() -> dict:
    ts = now_iso()
    rc, out = run(["docker", "exec", POSTGRES, "pg_isready", "-U", "litellm", "-d", "litellm"])
    return obs("postgres", "ok" if rc == 0 else "down", out.splitlines()[0][:120], ts)


def containers() -> dict:
    ts = now_iso()
    rc, out = run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"])
    if rc != 0:
        return obs("containers", "unknown", f"rc={rc}", ts)
    rows, unhealthy = [], 0
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, status = line.split("|", 1)
        if "sbx" not in name and "gateway" not in name and "litellm" not in name and "postgres" not in name:
            continue
        if "unhealthy" in status:
            unhealthy += 1
        rows.append((name.replace("openclaw-production-", "").replace("openclaw-", ""),
                     status))
    state = "warn" if unhealthy else "ok"
    return obs(f"containers ({len(rows)}, {unhealthy} unhealthy)", state, rows, ts)


SPEND_SQL = (
    "SELECT 'today', COALESCE(SUM(spend),0) FROM \"LiteLLM_SpendLogs\" "
    "WHERE \"startTime\" >= date_trunc('day', now() at time zone 'utc') "
    "UNION ALL SELECT '30d', COALESCE(SUM(spend),0) FROM \"LiteLLM_SpendLogs\" "
    "WHERE \"startTime\" >= now() - interval '30 days' "
    "UNION ALL SELECT 'phase4a', COALESCE(SUM(spend),0) FROM \"LiteLLM_SpendLogs\" "
    "WHERE key_alias = 'phase4a-jev-eval'")


def spend() -> dict:
    ts = now_iso()

    def q():
        return run(["docker", "exec", POSTGRES, "psql", "-U", "litellm", "-d", "litellm",
                    "-t", "-A", "-c", SPEND_SQL])
    (rc, out), _ = cached("spend", 60, q)
    vals = {}
    for line in (out or "").splitlines():
        if "|" in line:
            k, v = line.split("|", 1)
            try:
                vals[k] = float(v)
            except ValueError:
                pass
    if rc != 0 or "today" not in vals:
        return obs("spend (proxy ledger)", "unknown", f"query rc={rc}", ts)
    jev = vals.get("phase4a", 0.0)
    detail = {
        "today": f"${vals.get('today', 0):.4f} / ${CAPS['daily_usd']:.2f} (cap)",
        "30d": f"${vals.get('30d', 0):.2f} / ${CAPS['monthly_usd']:.2f} (cap)",
        "jev_eval_key": f"${jev:.6f} (disposable probe key)",
        "codex_chatgpt": "unknown (no attribution on this route)",
    }
    state = "warn" if (vals.get("today", 0) >= CAPS["daily_usd"]
                       or vals.get("30d", 0) >= CAPS["monthly_usd"]) else "ok"
    return obs("spend vs configured caps", state, detail, ts)


def backups() -> dict:
    ts = now_iso()
    ops_dir = os.path.join(BASE, "backups", "ops")
    try:
        newest = max((os.path.join(ops_dir, f) for f in os.listdir(ops_dir)
                      if f.startswith("oc-ops-")), key=os.path.getmtime)
        age_h = int((time.time() - os.path.getmtime(newest)) / 3600)
        state = "ok" if age_h <= 24 else "stale"
        return obs("operator backup", state,
                   f"{os.path.basename(newest)} age={age_h}h (RPO 24h)", ts)
    except (OSError, ValueError):
        return obs("operator backup", "unknown", "no ops archive found", ts)


def approvals_data() -> dict:
    def q():
        return run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                    "approvals", "pending", "--json"], timeout=30)
    (rc, out), _ = cached("approvals", 15, q)
    if rc != 0:
        return {"state": "unknown", "items": [], "count": 0, "raw": f"rc={rc}"}
    try:
        data = json.loads(out)
        if isinstance(data, list):
            items = data
        else:
            items = data.get("requests") or data.get("items") or data.get("pending") or []
        return {"state": "ok", "count": len(items), "items": items}
    except json.JSONDecodeError:
        return {"state": "ok", "count": 0, "items": [], "raw": out[:1500]}


def sessions_data() -> dict:
    def q():
        return run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                    "sessions", "list", "--json", "--all-agents"], timeout=30)
    (rc, out), _ = cached("sessions", 20, q)
    if rc != 0:
        return {"state": "unknown", "rows": []}
    try:
        data = json.loads(out)
        items = data.get("sessions") or data.get("list") or []
        rows = []
        for s in items:
            key = str(s.get("key", "?"))
            updated = s.get("updatedAtMs")
            try:
                when = datetime.fromtimestamp(int(updated) / 1000, timezone.utc)\
                    .strftime("%m-%d %H:%M") if updated else None
            except (TypeError, ValueError, OverflowError):
                when = None
            rows.append({"key": key[:90], "agent": key.split(":")[1] if ":" in key else "?",
                         "when": when or "unknown"})
        rows.sort(key=lambda r: r["when"] == "unknown")
        return {"state": "ok", "rows": rows}
    except json.JSONDecodeError:
        return {"state": "unknown", "rows": []}


def connectors() -> dict:
    def q():
        return run(["python3", os.path.join(BASE, "integrations", "manage-connectors.py"),
                    "list"], timeout=30)
    (rc, out), _ = cached("connectors", 60, q)
    return {"state": "ok" if rc == 0 else "unknown", "text": (out or f"rc={rc}")[:2000]}


def now_running() -> list[str]:
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def q():
        return run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                    "audit", "--after", since, "--json"], timeout=20)
    (rc, out), _ = cached("nowrun", 20, q)
    active: dict[str, str] = {}
    if rc == 0:
        try:
            recs = json.loads(out)
            recs = recs.get("records") if isinstance(recs, dict) else recs
            for r in recs or []:
                if r.get("action") == "agent.run.started":
                    active[str(r.get("runId"))[:8]] = r.get("agentId", "?")
                if r.get("action") == "agent.run.finished":
                    active.pop(str(r.get("runId"))[:8], None)
        except json.JSONDecodeError:
            pass
    return [f"{agent} ({rid})" for rid, agent in sorted(active.items())]


# ---------- files via fixed container helper ----------

def workread(mode: str, rel: str, max_bytes: int = MAX_FILE_BYTES) -> dict:
    rc, out = run(["docker", "exec", GATEWAY, "node", WORKREAD, mode, rel, str(max_bytes)])
    if rc != 0:
        return {"ok": False, "reason": f"helper rc={rc}"}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "helper returned non-JSON"}


def file_version(rel: str) -> str:
    e = workread("stat", rel)  # helper: stat returns size+mtimeMs without content
    if e.get("ok"):
        return f"{e.get('size', 0)}:{e.get('mtimeMs', 0)}"
    return "missing"


def claim_download(sig: str, exp: float) -> bool:
    """Single-use claims: True on first use, False on replay. Expired links
    are rejected before this is called; claimed sigs are garbage-collected."""
    now = time.time()
    with _lock:
        for s in [s for s, e in _used_dl.items() if e < now]:
            del _used_dl[s]
        if sig in _used_dl:
            return False
        _used_dl[sig] = exp + 60
        return True


# ---------- live work viewer ----------

def live_backend() -> str:
    try:
        with open(os.path.join(DIR, "state", "live-backend.json")) as f:
            return json.load(f).get("backend", "cli-audit")
    except (OSError, ValueError):
        return "cli-audit"


_audit_cursor = {"ts": (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime(
    "%Y-%m-%dT%H:%M:%SZ")}


def cli_events() -> list[dict]:
    """Poll the native audit trail with a moving cursor (overlap 1 s)."""
    global _audit_cursor
    since = _audit_cursor["ts"]

    def _cli_query(since):
        return run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                    "audit", "--after", since, "--json"], timeout=20)
    (rc, out), _ = cached("live-audit", 2, lambda: _cli_query(since))
    rows: list[dict] = []
    if rc != 0:
        return rows
    try:
        recs = json.loads(out)
        recs = recs.get("records") if isinstance(recs, dict) else recs
        for r in recs or []:
            action = str(r.get("action", ""))
            tool = ""
            if "tool.action" in action:
                tool = action.split(":")[-1]
            cls = "err" if "error" in action or r.get("status") == "failed" else \
                  ("tool" if tool else "")
            rows.append({"ts": str(r.get("ts", ""))[:19], "agent": r.get("agentId", "?"),
                         "tool": tool, "cls": cls,
                         "text": redact(action + " → " + str(r.get("status", ""))),
                         "agent_key": r.get("sessionId", "")})
        if rows:
            _audit_cursor["ts"] = max(rows, key=lambda r: r["ts"])["ts"]
    except json.JSONDecodeError:
        pass
    return rows


def gw_history_events(key: str) -> list[dict]:
    """Documented-native path, only used when the deploy-time probe verified
    the endpoint and wrote dashboard/gateway-token. Defensive parsing:
    unknown shapes render as one unparsed row, never invented fields."""
    try:
        with open(os.path.join(DIR, "gateway-token")) as f:
            token = f.read().strip()
    except OSError:
        return []
    q = urllib.parse.urlencode({"includeTools": "1"})
    url = (f"http://127.0.0.1:18789/sessions/{urllib.parse.quote(key, safe='')}"
           f"/history?{q}")
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode() or "{}")
    except Exception:  # noqa: BLE001
        return []
    rows = []
    events = data.get("events") or data.get("messages") or []
    for ev in events:
        role = str(ev.get("role") or ev.get("type") or "?")
        tool = str(ev.get("toolName") or ev.get("tool") or "")
        content = ev.get("text") or ev.get("content") or ev.get("summary") or ""
        if not isinstance(content, str):
            content = json.dumps(content)[:400]
        rows.append({"ts": str(ev.get("ts") or ev.get("timestamp") or "")[:19],
                     "agent": key.split(":")[1] if ":" in key else "?", "tool": tool,
                     "cls": "err" if role == "error" else ("tool" if tool else ""),
                     "text": redact(content[:500]),
                     "detail": redact(content[500:2500])})
    return rows


def timeline_events() -> tuple[list[dict], str]:
    backend = live_backend()
    if backend == "gateway-http" and os.path.exists(os.path.join(DIR, "gateway-token")):
        s = sessions_data()
        rows: list[dict] = []
        for r in s.get("rows", [])[:12]:
            rows.extend(gw_history_events(r["key"]))
        rows.sort(key=lambda e: e.get("ts", ""))
        return rows, backend
    return cli_events(), "cli-audit"


# ---------- html ----------

def esc(v) -> str:
    return html.escape(redact(v), quote=True)


def page(title: str, body: str, rec: dict | None, flash: str = "") -> str:
    nav = logout = ""
    if rec:
        nav = ("<nav><a href=/>Overview</a><a href=/live>Live</a>"
               "<a href=/sessions>Sessions</a><a href=/files>Files</a>"
               "<a href=/approvals>Approvals</a><a href=/schedules>Schedules</a>"
               "<a href=/memory>Memory</a><a href=/integrations>Integrations</a>"
               "<a href=/costs>Costs</a><a href=/audit>Audit</a></nav>")
        logout = (f"<form method=post action=/logout class=inline>"
                  f"<input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
                  f"<button type=submit>Logout</button>"
                  f"</form><form method=post action=/revoke-all class=inline>"
                  f"<input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
                  f"<button type=submit>Revoke all sessions</button></form>")
    fl = f"<p class=warn>{esc(flash)}</p>" if flash else ""
    return (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} — OpenClaw ops</title>"
            f"<link rel=stylesheet href=/static/app.css>"
            f"</head><body><header><h1>OpenClaw ops</h1>{nav}{logout}</header>"
            f"<main>{fl}{body}</main>"
            f"<script src=/static/app.js></script></body></html>")


def obs_table(items: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{esc(o['label'])}</td><td class={esc(o['state'])}>{esc(o['state'])}</td>"
        f"<td>{esc(o['detail'] if not isinstance(o['detail'], list) else chr(10).join(str(x) for x in o['detail']))}</td>"
        f"<td class=muted>{esc(o['ts'])}</td></tr>" for o in items)
    return (f"<table><tr><th>Check</th><th>State</th><th>Detail</th><th>Observed (UTC)</th>"
            f"</tr>{rows}</table>")


def gate(text: str) -> str:
    return f"<div class=gate>{esc(text)}</div>"


def table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    if not rows:
        body = f"<tr><td colspan={len(headers)} class=muted>{esc(empty)}</td></tr>"
    return (f"<table><tr>" + "".join(f"<th>{esc(h)}</th>" for h in headers) +
            f"</tr>{body}</table>")


# ---------- request handler ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _headers(self, code: int, ctype: str, extra: list[tuple[str, str]]) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'self'; script-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
                         "frame-ancestors 'none'")
        for k, v in extra:
            self.send_header(k, v)

    def _send(self, code: int, body: str | bytes, ctype="text/html; charset=utf-8",
              extra: list[tuple[str, str]] | None = None) -> None:
        raw = body.encode() if isinstance(body, str) else body
        self._headers(code, ctype, extra or [])
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _cookie(self, name: str) -> str:
        jar = http_cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http_cookies.CookieError:
            return ""
        return jar.get(name).value if jar.get(name) else ""

    def _auth(self) -> tuple[dict | None, str]:
        tok = self._cookie("dsh")
        rec = SESSIONS.validate(tok)
        return (rec, tok) if rec else (None, "")

    def _redirect(self, loc: str, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", loc)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _deny(self, code: int, msg: str) -> None:
        body = (f"<div class=login><p class=error>{esc(msg)}</p>"
                f"<p><a href=/>back</a></p></div>")
        self._send(code, page("denied", body, None))

    def _form(self) -> dict:
        n = min(int(self.headers.get("Content-Length") or 0), 8192)
        return {k: v[0] for k, v in urllib.parse.parse_qs(
            self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}

    # ---- GET ----
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path, q = parsed.path, urllib.parse.parse_qs(parsed.query)
        rec, tok = self._auth()

        if path == "/static/app.css":
            return self._static("app.css", "text/css; charset=utf-8")
        if path == "/static/app.js":
            return self._static("app.js", "text/javascript; charset=utf-8")
        if path == "/login" or (path == "/" and not rec):
            return self._send(200, page("sign in",
                    "<div class=login><h2>Owner sign-in</h2>"
                    "<form method=post action=/login>"
                    "<input type=password name=password placeholder='app password' "
                    "autocomplete=current-password required> "
                    "<button type=submit>Sign in</button></form></div>", None))
        if not rec:
            return self._redirect("/login")

        if path == "/":
            items = [gw_health(), gw_version(), postgres(), spend(), backups(),
                     containers()]
            strip = now_running()
            ap = approvals_data()
            strip_html = ("<h2>Now running</h2>" + ("<div class=strip>" + "".join(
                f"<span class=chip>{esc(x)}</span>" for x in strip) + "</div>"
                if strip else "<p class=muted>nothing running</p>"))
            gates = ("<h2>Disabled / scoped controls</h2>" +
                     gate("session cancel: no owner-scoped native abort verified on "
                          "this build — use the Control UI") +
                     gate("approval resolution: read-only here; resolve via "
                          "Telegram/Control UI (native policy authoritative)") +
                     gate("new chat: Control UI / Telegram"))
            body = ("<h2>Overview</h2>" + obs_table(items) + strip_html +
                    f"<h2>Pending approvals: {esc(ap.get('count', 0))}</h2>" + gates)
            return self._send(200, page("overview", body, rec))

        if path == "/sessions":
            s = sessions_data()
            rows = [(esc(r["key"]), esc(r["agent"]), esc(r["when"])) for r in s["rows"]]
            body = ("<h2>Sessions (main + worker runs)</h2>" +
                    table(["Session", "Agent", "Updated (UTC)"], rows,
                          "no sessions") +
                    gate("cancel/reset: not available from the dashboard on this "
                         "build — no verified owner-scoped native abort path"))
            return self._send(200, page("sessions", body, rec))

        if path == "/live":
            backend = live_backend()
            try:
                with open(os.path.join(JEV_DIR, "config.json")) as f:
                    jev = "on" if json.load(f).get("enabled") else "off"
            except (OSError, ValueError):
                jev = "unknown"
            body = (f"<h2>Live work viewer <span class=muted>({esc(backend)} backend)"
                    f"</span></h2>"
                    f"<p><button id=pause type=button>Pause</button> "
                    f"<select id=filter-agent><option value=''>all agents</option></select> "
                    f"<select id=filter-tool><option value=''>all tools</option>"
                    f"<option>web_fetch</option><option>brave_web_search</option>"
                    f"<option>browser</option><option>exec</option></select> "
                    f"<span id=live-status class=muted>connecting…</span></p>"
                    f"<div id=timeline></div>"
                    f"<h2>Jev research layer: {esc(jev)}</h2>"
                    f"<form method=post action=/jev-toggle>"
                    f"<input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
                    f"<input type=hidden name=layer value=research>"
                    f"<select name=value><option value='off'>off</option>"
                    f"<option value='on'>on</option></select> "
                    f"<button type=submit>Apply (read back + audit)</button></form>"
                    f"<p class=muted>All content is escaped, redacted attributed "
                    f"data. Model reasoning is not shown (not exposed by the "
                    f"runtime).</p>")
            return self._send(200, page("live", body, rec))

        if path == "/live/stream":
            if self.headers.get("Origin") not in {None, *ORIGINS}:
                return self._deny(403, "origin not allowed")
            if not rec:
                return self._deny(403, "session required")
            global _streams
            with _lock:
                if _streams >= MAX_STREAMS:
                    return self._deny(429, "too many live streams")
                _streams += 1
            cursor = int(q.get("cursor", ["0"])[0] or 0)
            seq = cursor
            try:
                # Raw status+headers for this route: some callers reject the
                # send_response() path's buffering for event streams.
                self.wfile.write(b"HTTP/1.0 200 OK\r\n"
                                 b"Content-Type: text/event-stream\r\n"
                                 b"Cache-Control: no-store\r\n"
                                 b"Connection: close\r\n\r\n")
                self.wfile.write(b": stream\n\n")
                self.wfile.flush()
                idle = 0
                while _streams and idle < 150:  # ~5 min without events then re-probe
                    events, backend = timeline_events()
                    for e in events:
                        seq += 1
                        e["seq"] = seq
                        self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())
                    self.wfile.write(f"data: {json.dumps({'cursor': seq})}\n\n".encode())
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    time.sleep(2)
                    idle += 1
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with _lock:
                    _streams -= 1
            return

        if path == "/files":
            rel = q.get("dir", [""])[0]
            res = workread("list", rel)
            if not res.get("ok"):
                reason = res.get("reason", "unavailable")
                body = (f"<h2>Files — allowlisted root <code>work/</code></h2>"
                        f"<p class={'denied' if reason == 'path_rejected' else 'unknown'}>"
                        f"{esc(reason)}</p>")
            else:
                rows = []
                for e in res["entries"]:
                    name = e["name"]
                    if e["dir"]:
                        link = f"<a href='/files?dir={urllib.parse.quote(e['name'])}'>{esc(name)}/</a>"
                        dl = ""
                    elif e["link"]:
                        link, dl = f"{esc(name)} (symlink — refused)", ""
                    else:
                        exp = int(time.time()) + DOWNLOAD_TTL
                        ver = f"{e['size']}:{e['mtimeMs']}"
                        sig = _sign(f"dl|{rec['csrf']}|{rel}/{name}|{ver}|{exp}")
                        qs = urllib.parse.urlencode({"path": f"{rel}/{name}".lstrip("/"),
                                                     "ver": ver, "exp": exp, "sig": sig})
                        link, dl = esc(name), f"<a href='/files/dl?{qs}'>download</a>"
                    rows.append([link, "—" if e["dir"] else f"{int(e.get('size') or 0):,} B",
                                 time.strftime("%m-%d %H:%M", time.gmtime(e.get("mtimeMs", 0)/1000)),
                                 dl])
                body = ("<h2>Files — allowlisted root <code>work/</code></h2>" +
                        table(["Name", "Size", "Modified (UTC)", ""], rows, "empty") +
                        gate("file_upload disabled: requires enforced permissions, "
                             "size/type limits and malware scanning — unavailable"))
            return self._send(200, page("files", body, rec))

        if path == "/files/dl":
            if not rec:
                return self._deny(403, "session required")
            rel, ver = q.get("path", [""])[0], q.get("ver", [""])[0]
            try:
                exp = int(q.get("exp", ["0"])[0])
            except ValueError:
                exp = 0
            sig = q.get("sig", [""])[0]
            now = time.time()
            bound = _sign(f"dl|{rec['csrf']}|{rel}|{ver}|{exp}")
            if exp < now or not hmac.compare_digest(bound, sig):
                return self._deny(403, "download link expired, replayed, or invalid")
            if not claim_download(sig, exp):
                return self._deny(403, "download link already used (replay)")
            res = workread("read", rel, MAX_FILE_BYTES)
            if not res.get("ok"):
                return self._deny(403, str(res.get("reason", "read refused")))
            if not audit("download", rel, "ok"):
                return self._deny(500, "audit write failed — download refused")
            name = os.path.basename(rel.replace("\\", "/"))
            return self._send(200, res["content"], "application/octet-stream",
                              [("Content-Disposition", f"attachment; filename=\"{name}\"")])

        if path == "/approvals":
            a = approvals_data()
            if a.get("state") != "ok":
                body = "<h2>Approvals (pending)</h2><p class=unknown>unavailable</p>"
            elif not a["items"]:
                body = "<h2>Approvals (pending)</h2><p class=ok>no pending approvals</p>"
            else:
                text = json.dumps(a["items"], indent=1)[:3000]
                body = f"<h2>Approvals (pending)</h2><pre>{esc(text)}</pre>"
            body += gate("resolution is read-only here: resolve via Telegram/Control "
                         "UI — native policy stays authoritative")
            return self._send(200, page("approvals", body, rec))

        if path == "/schedules":
            def q2():
                return run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                            "cron", "list", "--json"], timeout=30)
            (rc, out), _ = cached("cron", 30, q2)
            rows = []
            if rc == 0:
                try:
                    for j in json.loads(out).get("jobs", []):
                        sch = j.get("schedule", {})
                        when = (time.strftime("%m-%d %H:%M", time.gmtime(j["nextRunAtMs"]/1000))
                                if j.get("nextRunAtMs") else "?")
                        rows.append([esc(j.get("name", "?")), esc(str(j.get("enabled"))),
                                     esc(json.dumps(sch)[:60]), esc(when)])
                except json.JSONDecodeError:
                    rows = [["parse error", "?", "?", "?"]]
            body = ("<h2>Schedules (native automations)</h2>" +
                    table(["Name", "Enabled", "Schedule", "Next run (UTC)"], rows,
                          "no jobs"))
            return self._send(200, page("schedules", body, rec))

        if path == "/memory":
            mem = os.path.join(HOST_STATE, "workspace", "memory")
            rows = []
            try:
                for f in sorted(os.listdir(mem)):
                    if f.endswith(".md"):
                        with open(os.path.join(mem, f), errors="replace") as fh:
                            excerpt = fh.read(300)
                        rows.append([esc(f), f"<pre>{esc(excerpt)}…</pre>"])
            except OSError:
                pass
            body = ("<h2>Memory (read-only view)</h2>" +
                    table(["File", "Excerpt"], rows, "no memory files") +
                    gate("correction/deletion happens through the agent's native "
                         "memory tools; this page is read-only"))
            return self._send(200, page("memory", body, rec))

        if path == "/integrations":
            c = connectors()
            body = (f"<h2>Integrations</h2><pre>{esc(c['text'])}</pre>"
                    f"<p class=muted>Sign-in is owner-only via bin/connect-tool "
                    f"(protected flows; no credentials here).</p>")
            return self._send(200, page("integrations", body, rec))

        if path == "/costs":
            def q2():
                return run(["docker", "exec", POSTGRES, "psql", "-U", "litellm", "-d",
                            "litellm", "-t", "-A", "-c",
                            "SELECT date(\"startTime\"), key_alias, ROUND(SUM(spend),6) "
                            "FROM \"LiteLLM_SpendLogs\" WHERE \"startTime\" >= now() - "
                            "interval '7 days' GROUP BY 1,2 ORDER BY 1 DESC LIMIT 40"])
            (rc, out), _ = cached("costs", 120, q2)
            rows = [[esc(p[0]), esc(p[1]), esc("$" + p[2])] for p in
                    (line.split("|") for line in (out or "").splitlines() if "|" in line)]
            body = ("<h2>Costs — LiteLLM ledger, last 7 days</h2>" +
                    table(["Day (UTC)", "Key alias", "Spend"], rows, "no spend recorded") +
                    f"<p class=muted>Jev decisions: {esc(jev_cost_line())} · "
                    f"Codex/ChatGPT spend: unknown (no attribution on that route)</p>")
            return self._send(200, page("costs", body, rec))

        if path == "/audit":
            rows = [[esc(l.strip())] for l in audit_tail()] or \
                [["no audit records yet"]]
            return self._send(200, page("audit",
                    "<h2>Application audit (append-only JSONL)</h2>" +
                    table(["Record"], rows, ""), rec))

        if path == "/logout":
            SESSIONS.destroy(tok)
            return self._redirect("/", cookie="dsh=; HttpOnly; Max-Age=0; Path=/")

        self._deny(404, "not found")

    # ---- POST ----
    def do_POST(self):  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path == "/login":
            ip = self.client_address[0]
            now = time.time()
            fails = [t for t in _login_fails.get(ip, []) if now - t < 3600]
            if len(fails) >= 5:
                return self._deny(429, "too many failed attempts; wait an hour")
            form = self._form()
            if not check_password(form.get("password", "")):
                _login_fails.setdefault(ip, []).append(now)
                if not audit("login", ip, "failed"):
                    return self._deny(500, "audit write failed")
                return self._deny(403, "wrong password")
            _login_fails[ip] = []
            if not audit("login", ip, "ok"):
                return self._deny(500, "audit write failed — login refused")
            token, _ = SESSIONS.create()  # rotation: fresh id every login
            cookie = (f"dsh={token}; HttpOnly; SameSite=Strict; Path=/; "
                      f"Max-Age={SESSION_TTL_ABS}")
            return self._redirect("/", cookie=cookie)

        rec, tok = self._auth()
        form = self._form()
        if not rec or not hmac.compare_digest(rec["csrf"], form.get("csrf", "")):
            return self._deny(403, "bad session or csrf")
        if path == "/logout":
            if not audit("logout", ip := self.client_address[0], "ok"):
                return self._deny(500, "audit write failed")
            SESSIONS.destroy(tok)
            return self._redirect("/", cookie="dsh=; HttpOnly; Max-Age=0; Path=/")
        if path == "/revoke-all":
            n = SESSIONS.destroy_all()
            try:
                os.remove(SESSION_SECRET)
            except FileNotFoundError:
                pass
            _session_key()
            if not audit("revoke-all-sessions", "all", f"revoked={n}"):
                return self._deny(500, "audit write failed — action refused")
            return self._redirect("/login", cookie="dsh=; HttpOnly; Max-Age=0; Path=/")
        if path == "/jev-toggle":
            layer = form.get("layer", "")
            value = form.get("value", "")
            if layer != "research" or value not in ("on", "off"):
                return self._deny(400, "unsupported layer or value")
            target = os.path.join(JEV_DIR, "config.json")
            try:
                os.makedirs(JEV_DIR, exist_ok=True)
                with open(target, "w") as f:
                    json.dump({"enabled": value == "on"}, f)
                os.chmod(target, 0o600)
                with open(target) as f:
                    readback = json.load(f)
            except OSError as e:
                return self._deny(500, f"toggle failed: {type(e).__name__}")
            if not audit("jev-toggle", layer, f"{value}; readback={readback}"):
                return self._deny(500, "audit write failed — change refused")
            body = (f"<h2>Jev research layer</h2>"
                    f"<p>Requested <b>{esc(value)}</b>; read back "
                    f"<b>{esc(json.dumps(readback))}</b>.</p>"
                    f"<p><a href=/live>back to live viewer</a></p>")
            return self._send(200, page("jev toggle", body, rec))
        self._deny(404, "not found")

    def _static(self, name: str, ctype: str) -> None:
        try:
            with open(os.path.join(STATIC, name), "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError:
            self._deny(404, "missing asset")


def jev_cost_line() -> str:
    try:
        total = 0.0
        path = os.path.join(JEV_DIR, "decisions.jsonl")
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    try:
                        c = json.loads(line).get("cost_usd")
                        if isinstance(c, (int, float)):
                            total += c
                    except ValueError:
                        continue
        return f"${total:.6f} across logged decisions"
    except OSError:
        return "unknown"


def main() -> None:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    os.makedirs(STATIC, exist_ok=True)
    os.makedirs(os.path.join(HOST_STATE, "jev-research"), exist_ok=True)
    os.chmod(DIR, 0o700)
    _session_key()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    server.daemon_threads = True
    print(f"dashboard listening on {BIND}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
