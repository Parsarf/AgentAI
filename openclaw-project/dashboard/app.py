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
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http import cookies as http_cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def _load_switches():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, "switches.py"),
                      os.path.join(here, "..", "platform", "agentai_platform", "switches.py")):
        if os.path.exists(candidate):
            spec = importlib.util.spec_from_file_location("owner_switches", candidate)
            module = importlib.util.module_from_spec(spec)
            sys.modules["owner_switches"] = module  # dataclasses look the module up by name
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("switches.py not found next to the dashboard")


switches = _load_switches()


def _load_routing_config():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, "routing_config.py"),
                      os.path.join(here, "..", "platform", "agentai_platform", "routing", "config.py")):
        if os.path.exists(candidate):
            spec = importlib.util.spec_from_file_location("owner_routing_config", candidate)
            module = importlib.util.module_from_spec(spec)
            sys.modules["owner_routing_config"] = module
            spec.loader.exec_module(module)
            return module
    return None


routing_config = _load_routing_config()
ROUTING_DIR = "/var/lib/agentai-platform/routing"
ROUTING_FILE = os.path.join(ROUTING_DIR, "routing.json")
ROUTING_KEY = os.path.join(ROUTING_DIR, "typesafe.key")

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
SWITCH_DIR = os.path.join(BASE, "feature-switches")
SWITCH_FILE = os.path.join(SWITCH_DIR, "switches.json")
SWITCH_FACTS = os.path.join(SWITCH_DIR, "facts.json")
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
    "WHERE \"startTime\" >= now() - interval '30 days'")


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
    jev = jev_cost_line()
    detail = {
        "today": f"${vals.get('today', 0):.4f} / ${CAPS['daily_usd']:.2f} (cap)",
        "30d": f"${vals.get('30d', 0):.2f} / ${CAPS['monthly_usd']:.2f} (cap)",
        "jev_eval_key": jev,
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


def _svg(d: str) -> str:
    return (f"<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' "
            f"stroke-linejoin='round' aria-hidden='true'>{d}</svg>")


ICONS = {
    "home": _svg("<path d='M3 11l9-8 9 8'/><path d='M5 10v10h14V10'/>"),
    "users": _svg("<circle cx='9' cy='8' r='3.5'/><path d='M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5'/><path d='M16 4.6a3.5 3.5 0 010 6.8M18 14.8c2 .6 3.2 2.3 3.5 5.2'/>"),
    "toggle": _svg("<rect x='2.5' y='7' width='19' height='10' rx='5'/><circle cx='16' cy='12' r='2.6'/>"),
    "wallet": _svg("<path d='M3 7.5A2.5 2.5 0 015.5 5H19v3'/><path d='M3 7.5V18a2 2 0 002 2h15V8H5.5A2.5 2.5 0 013 7.5z'/><circle cx='16.5' cy='14' r='1.2'/>"),
    "pulse": _svg("<path d='M3 12h4l2.5-6 4 12 2.5-6H21'/>"),
    "log": _svg("<path d='M6 3h9l4 4v14H6z'/><path d='M14 3v5h5M9 13h7M9 17h7'/>"),
    "dots": _svg("<circle cx='5' cy='12' r='1.5'/><circle cx='12' cy='12' r='1.5'/><circle cx='19' cy='12' r='1.5'/>"),
    "spark": _svg("<path d='M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z'/>"),
    "link": _svg("<path d='M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1'/><path d='M14 10a4 4 0 00-5.7 0l-3 3A4 4 0 0011 18.7l1-1'/>"),
}
NAV = [
    ("", [("Overview", "/", "home"), ("Customers", "/customers", "users"), ("Features", "/switches", "toggle"), ("Money", "/costs", "wallet")]),
    ("Activity", [("Live", "/live", "pulse"), ("Audit log", "/audit", "log")]),
    ("Advanced", [("Sessions", "/sessions", "dots"), ("Files", "/files", "dots"), ("Approvals", "/approvals", "dots"), ("Schedules", "/schedules", "dots"),
                  ("Memory", "/memory", "dots"), ("Integrations", "/integrations", "dots"), ("Routing", "/routing", "dots"), ("System details", "/system", "dots")]),
]


def waiting_badge() -> int:
    ov = overview_data()
    try:
        return int((ov or {}).get("customers", {}).get("pending", 0))
    except (TypeError, ValueError):
        return 0


def page(title: str, body: str, rec: dict | None, flash: str = "", sub: str = "") -> str:
    fl = f"<div class=flash role=status>{esc(flash)}</div>" if flash else ""
    head = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} — Lumina owner</title><link rel=stylesheet href=/static/app.css></head>")
    if not rec:                                   # signed-out pages: no navigation, no data
        return head + f"<body><main class='content solo'>{fl}{body}</main><script src=/static/app.js></script></body></html>"
    badge = waiting_badge()
    groups = ""
    for group, links in NAV:
        groups += f"<div class=navgroup>{esc(group)}</div>" if group else ""
        groups += "<nav class=sidenav>" + "".join(
            f"<a href='{href}'>{ICONS[icon]}<span>{esc(label)}</span>"
            + (f"<span class=badge title='Waiting for your approval'>{badge}</span>" if href == "/customers" and badge else "") + "</a>"
            for label, href, icon in links) + "</nav>"
    side = (f"<aside class=side id=side><div class=brand><span class=logo>{ICONS['spark']}</span><span>LUMINA<small>Owner dashboard</small></span></div>{groups}"
            f"<div class=sidefoot><a href='http://127.0.0.1:18790/' title='Switch between every owner view'>{ICONS['link']} Owner console</a>"
            f"<a href='https://getlumina.pro/app/' target=_blank rel=noopener>Open the Lumina app ↗</a>"
            f"<div><button id=theme-toggle type=button class=small>Theme</button> "
            f"<form method=post action=/logout class=inline><input type=hidden name=csrf value='{esc(rec['csrf'])}'><button type=submit class=small>Log out</button></form> "
            f"<form method=post action=/revoke-all class=inline title='Sign out everywhere'><input type=hidden name=csrf value='{esc(rec['csrf'])}'><button type=submit class='small danger'>Revoke all</button></form></div></div></aside>")
    top = (f"<div class=topbar><button class=menu-btn id=menu-btn type=button aria-label='Menu'>{ICONS['dots']}</button>"
           f"<div><h1>{esc(title[:1].upper() + title[1:])}</h1>{f'<p class=sub>{esc(sub)}</p>' if sub else ''}</div><div class=sp></div></div>")
    return head + f"<body><div class=shell>{side}<main class=content>{top}{fl}{body}</main></div><script src=/static/app.js></script></body></html>"


def pill(state: str) -> str:
    return f"<span class='pill {esc(state)}'>{esc(state)}</span>"


def toggle_row(name: str, label: str, on: bool | None, enabled: bool,
               note: str = "") -> str:
    """Controls row. on=None → unknown state. enabled=False → read-only."""
    if on is None:
        state = "<span class='pill unknown'>unknown</span>"
    else:
        state = pill("ok" if on else "warn") + f" <b>{'on' if on else 'off'}</b>"
    if enabled:
        ctl = (f"<form method=post action=/toggle class=inline>"
               f"<input type=hidden name=csrf value='{{CSRF}}'>"
               f"<input type=hidden name=name value='{esc(name)}'>"
               f"<input type=hidden name=value value='{'off' if on else 'on'}'>"
               f"<button type=submit class=small>Turn {'off' if on else 'on'}</button>"
               f"</form>")
    else:
        ctl = "<span class=muted>read-only</span>"
    note_html = f"<div class='small mut'>{esc(note)}</div>" if note else ""
    return (f"<div class=card style='display:flex;justify-content:space-between;"
            f"align-items:center;gap:1rem'>"
            f"<div><b>{esc(label)}</b> {state}{note_html}</div><div>{ctl}</div>")


def spend_bars(detail) -> str:
    def bar(label: str, val: float, cap: float) -> str:
        pct = min(100.0, (val / cap * 100.0) if cap else 0)
        hot = " hot" if pct >= 80 else ""
        return (f"<div class=kv><span>{esc(label)}</span>"
                f"<span>${val:,.4f} / ${cap:,.2f}</span></div>"
                f"<div class=bar><i class='{hot}' style='width:{pct:.1f}%'></i></div>")
    d = detail if isinstance(detail, dict) else {}
    try:
        today = float(str(d.get("today", "0")).replace("$", "").split("/")[0].strip())
        month = float(str(d.get("30d", "0")).replace("$", "").split("/")[0].strip())
    except (ValueError, IndexError):
        return "<p class=unknown>spend unavailable</p>"
    return (bar("Today (24h cap)", today, CAPS["daily_usd"]) +
            "<div style=height:.45rem></div>" +
            bar("30 days (monthly cap)", month, CAPS["monthly_usd"]) +
            f"<div class='small mut' style=margin-top:.45rem>Jev eval key: "
            f"{esc(d.get('jev_eval_key', 'unknown'))} · Codex/ChatGPT: "
            f"{esc(d.get('codex_chatgpt', 'unknown'))}</div>")


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
            flash = q.get("msg", [""])[0][:200]
            return self._send(200, page("Overview", home_page(rec), rec, flash, "How Lumina is doing right now"))
        if path == "/system":
            return self._send(200, page("System details", system_page(), rec, "", "The underlying runtime"))

        if path == "/switches":
            flash = q.get("msg", [""])[0][:200]
            return self._send(200, page("Features", switches_page(rec), rec, flash, "Turn parts of Lumina on or off, in plain words"))

        if path == "/routing":
            flash = q.get("msg", [""])[0][:200]
            return self._send(200, page("Routing", routing_page(rec), rec, flash, "Smart routing (JEV) settings and what it recommended"))

        if path == "/customers":
            flash = q.get("msg", [""])[0][:200]
            return self._send(200, page("Customers", customers_page(rec), rec, flash, "Approve sign-ups, pause customers, set how many the server can carry"))

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
                    f"<form method=post action=/toggle>"
                    f"<input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
                    f"<input type=hidden name=name value=jev_research>"
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
        if path == "/switch":
            name, value = form.get("name", ""), form.get("value", "")
            if value not in ("on", "off"):
                return self._deny(400, "bad value")
            ok, message = apply_switch(name, value == "on")
            back = form.get("back", "/switches")
            back = back if back in BACK_PATHS else "/switches"
            return self._redirect(back + "?msg=" + urllib.parse.quote(message))
        if path == "/switch-confirm":
            name, cid = form.get("name", ""), form.get("id", "")
            try:
                switch_store().confirm(name, cid, "owner")
            except switches.SwitchError as e:
                return self._deny(400, "; ".join(e.reasons))
            if not audit("switch-confirm", f"{name}:{cid}", "recorded"):
                return self._deny(500, "audit write failed — confirmation not trusted")
            return self._redirect("/switches?msg=" + urllib.parse.quote("Confirmation recorded"))
        if path == "/toggle":
            name = form.get("name", "")
            value = form.get("value", "")
            if value not in ("on", "off"):
                return self._deny(400, "bad value")
            if name == "jev_research":
                ok, message = apply_switch("research_optimization", value == "on")
                return self._redirect("/switches?msg=" + urllib.parse.quote(message))
            if name == "sandbox_browser":
                rc, out = run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                               "config", "set",
                               "agents.defaults.sandbox.browser.enabled",
                               "true" if value == "on" else "false"], timeout=40)
                vrc, tout = run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                                 "config", "validate", "--json"], timeout=60)
                if rc != 0 or vrc != 0:
                    return self._deny(500, f"config change failed: {out[:120]}")
                state = sandbox_browser_enabled()
            else:
                return self._deny(400, "unsupported toggle")
            if state is None or (value == "on") != bool(state):
                return self._deny(500, "readback mismatch — change not confirmed")
            if not audit("toggle", name, value):
                return self._deny(500, "audit write failed — change refused")
            return self._redirect("/")
        if path == "/jev-toggle":
            layer = form.get("layer", "")
            value = form.get("value", "")
            if layer != "research" or value not in ("on", "off"):
                return self._deny(400, "unsupported layer or value")
            ok, message = apply_switch("research_optimization", value == "on")
            return self._redirect("/switches?msg=" + urllib.parse.quote(message))
        if path == "/customer-action":
            ok, message = customer_action(form.get("action", ""), form.get("account", ""))
            if not audit("customer-" + form.get("action", "?"), form.get("account", "?")[:64], "ok" if ok else "refused"):
                return self._deny(500, "audit write failed")
            return self._redirect("/customers?msg=" + urllib.parse.quote(message))
        if path == "/customer-limit":
            ok, message = customer_limit(form.get("count", ""))
            if not audit("customer-limit", form.get("count", "?")[:8], "ok" if ok else "refused"):
                return self._deny(500, "audit write failed")
            return self._redirect("/customers?msg=" + urllib.parse.quote(message))
        if path == "/routing-save":
            ok, message = routing_save(form)
            return self._redirect("/routing?msg=" + urllib.parse.quote(message))
        if path == "/routing-rollback":
            ok, message = routing_rollback()
            return self._redirect("/routing?msg=" + urllib.parse.quote(message))
        self._deny(404, "not found")

    def _static(self, name: str, ctype: str) -> None:
        try:
            with open(os.path.join(STATIC, name), "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError:
            self._deny(404, "missing asset")



def switch_store():
    return switches.SwitchStore(SWITCH_FILE, facts_path=SWITCH_FACTS)


def live_facts() -> dict:
    """Facts written by deployment tooling, plus the few the dashboard can verify itself."""
    facts = switches.load_facts(SWITCH_FACTS)
    rc, _ = run(["docker", "exec", GATEWAY, "test", "-e", "/run/secrets/phase4a-jev-eval.key"], timeout=15)
    facts["typesafe_key_present"] = rc == 0
    facts["routing_key_present"] = os.path.isfile(ROUTING_KEY)
    return facts


def write_jev_plugin_file(on: bool) -> bool | None:
    """Mirror the research switch into the plugin's documented config file, with readback."""
    target = os.path.join(JEV_DIR, "config.json")
    try:
        os.makedirs(JEV_DIR, exist_ok=True)
        with open(target, "w") as f:
            json.dump({"enabled": bool(on)}, f)
        os.chmod(target, 0o600)
    except OSError:
        return None
    return jev_research_enabled()


def apply_switch(key: str, on: bool) -> tuple[bool, str]:
    """One code path for every feature switch: checks, save, mirror, readback, audit.
    Turning OFF always works; turning ON needs every confirmation and fact."""
    store = switch_store()
    if key not in store.catalog:
        return False, "unknown switch"
    store.facts = lambda f=live_facts(): f  # one consistent fact snapshot for this change
    try:
        result = store.set(key, on, "owner")
    except switches.SwitchError as e:
        audit("switch", key, f"refused {'on' if on else 'off'}: {'; '.join(e.reasons)[:200]}")
        return False, "; ".join(e.reasons)
    if key == "research_optimization":
        actual = write_jev_plugin_file(on)
        if actual is None or actual != bool(on):
            try:
                store.set(key, False, "owner")      # never leave the switch on if the plugin file disagrees
                write_jev_plugin_file(False)
            except switches.SwitchError:
                pass
            audit("switch", key, "plugin file readback mismatch; forced off")
            return False, "the research plugin file did not confirm the change, so it was switched off"
    if not audit("switch", key, "on" if on else "off"):
        return False, "audit write failed — change not recorded as confirmed"
    return True, f"{result['title']} is now {'ON' if on else 'OFF'}"


def switches_page(rec: dict, flash: str = "") -> str:
    store = switch_store()
    facts = live_facts()
    store.facts = lambda f=facts: f
    plugin = jev_research_enabled()
    cards = []
    drift = ""
    research = store.describe("research_optimization")
    if plugin is True and not research["effective_on"]:
        drift = ("<div class='card'><span class='pill warn'>needs attention</span> "
                 "<b>The research plugin file on the server says ON, but its switch here is OFF or blocked.</b>"
                 "<div class='small mut'>Nothing is eligible right now so it is not spending, but it should match. "
                 "Press the button to switch it off everywhere.</div>"
                 f"<form method=post action=/switch class=inline><input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
                 "<input type=hidden name=name value=research_optimization><input type=hidden name=value value=off>"
                 "<button type=submit class=small>Turn it off everywhere</button></form></div>")
    for d in store.all():
        status = {"on": ("ok", "ON"), "off": ("warn", "OFF"), "locked": ("unknown", "LOCKED"),
                  "on_but_blocked": ("down", "ON but blocked")}[d["status"]]
        key = esc(d["key"])
        blockers = "".join(f"<li>{esc(b)}</li>" for b in d["blockers"] if not b.startswith("Confirm:"))
        confirms = ""
        for c in d["confirmations"]:
            if c["at"]:
                confirms += f"<div class='small'>✓ {esc(c['text'])} <span class=mut>(recorded)</span></div>"
            elif not d["locked"]:
                confirms += (f"<form method=post action=/switch-confirm class=inline>"
                             f"<input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
                             f"<input type=hidden name=name value='{key}'><input type=hidden name=id value='{esc(c['id'])}'>"
                             f"<label class=small><input type=checkbox required> {esc(c['text'])}</label> "
                             f"<button type=submit class=small>Record</button></form>")
        if d["locked"]:
            action = f"<span class=muted>{esc(d['locked'])}</span>"
        elif d["recorded_on"]:
            action = (f"<form method=post action=/switch class=inline><input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
                      f"<input type=hidden name=name value='{key}'><input type=hidden name=value value=off>"
                      f"<button type=submit>Turn OFF</button></form>")
        elif d["can_turn_on"]:
            action = (f"<form method=post action=/switch class=inline><input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
                      f"<input type=hidden name=name value='{key}'><input type=hidden name=value value=on>"
                      f"<button type=submit>Turn ON</button></form>")
        else:
            action = "<span class=muted>Can't be turned on yet — see below</span>"
        todo = (f"<div class='small'><b>Before it can be turned on:</b><ul>{blockers}</ul></div>" if blockers and not d["locked"] else "")
        label = FRIENDLY.get(d["key"], d["title"])
        cards.append((d["key"],
            f"<div class='card feature'><div><b style='font-size:1.02rem'>{esc(label)}</b> {pill(status[0]).replace(esc(status[0]) + '</span>', esc(status[1]) + '</span>')}"
            f"<p style='margin:6px 0 0'>{esc(d['plain'])}</p></div><div style='align-self:start'>{action}</div>"
            f"<div class=meta><div><b>When on:</b> {esc(d['when_on'])}</div><div><b>Cost:</b> {esc(d['cost_note'])}</div>{confirms}{todo}"
            + (f"<div>last changed by {esc(d['changed_by'])}</div>" if d["changed_by"] else "") + "</div></div>"))
    groups = [("Customers and access", ["open_signups", "open_access", "billing_checkout", "customer_execution"]),
              ("What assistants can do", ["browse_tasks", "credentialed_browsing", "customer_schedules", "connectors"]),
              ("Smart routing and research", ["jev_routing", "research_optimization"])]
    used, sections = set(), ""
    for title, keys in groups + [("More", [])]:
        members = [h for k, h in cards if (k in keys if keys else k not in {x for _, ks in groups for x in ks})]
        if members:
            sections += f"<h2>{esc(title)}</h2>" + "".join(members)
    note = ("<p class=muted>Each switch is the on/off control for one feature. A switch never overrides a safety check: turning one ON only works "
            "when its confirmations are ticked and its setup is really finished, and turning one OFF always works immediately. Every change "
            "is read back and written to the audit log.</p>")
    return note + drift + sections


def routing_load() -> dict:
    try:
        return routing_config.load(ROUTING_FILE)
    except Exception:
        return routing_config.validate(routing_config._merge(routing_config.DEFAULTS, {}))


def routing_write(cfg: dict) -> bool:
    """Atomic write, readable by the app user only; returns whether the readback matches."""
    import pwd
    try:
        os.makedirs(ROUTING_DIR, exist_ok=True)
        try:
            app = pwd.getpwnam("agentai-platform") if os.geteuid() == 0 else None
        except KeyError:
            app = None
        if app:
            os.chown(ROUTING_DIR, app.pw_uid, app.pw_gid)
        os.chmod(ROUTING_DIR, 0o700)
        tmp = ROUTING_FILE + ".new"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=1, sort_keys=True)
        if app:
            os.chown(tmp, app.pw_uid, app.pw_gid)
        os.chmod(tmp, 0o600)
        os.replace(tmp, ROUTING_FILE)
        return routing_config.load(ROUTING_FILE) == cfg
    except (OSError, KeyError, ValueError):
        return False


def routing_save(form: dict) -> tuple[bool, str]:
    def flag(name): return form.get(name) == "on"
    try:
        override = {
            "enabled": flag("enabled"), "mode": "shadow", "canary_percent": 0,
            "confidence": {"automatic": float(form.get("automatic", "0.85")), "review": float(form.get("review", "0.65"))},
            "escalation": {"enabled": True, "max_escalations": int(form.get("max_escalations", "2")),
                           "max_retries_per_step": int(form.get("max_retries_per_step", "2"))},
            "limits": {"max_task_duration_seconds": int(form.get("max_task_duration_seconds", "1800")),
                       "max_task_cost_usd": float(form.get("max_task_cost_usd", "1.0"))},
            "routes": {r: flag("route_" + r) for r in routing_config.ROUTES if r != "abstain"},
        }
        cfg = routing_config.validate(routing_config._merge(routing_config.DEFAULTS, override))
    except (ValueError, routing_config.ConfigError) as e:
        audit("routing-save", "settings", "refused")
        return False, "not saved: " + str(e)[:150]
    if not routing_write(cfg):
        return False, "the settings file did not confirm the change"
    if not audit("routing-save", "settings", json.dumps({"enabled": cfg["enabled"], "mode": cfg["mode"]})):
        return False, "audit write failed — change not recorded as confirmed"
    return True, "Routing settings saved" + ("" if cfg["enabled"] else " (routing is OFF)")


def routing_rollback() -> tuple[bool, str]:
    """Emergency rollback: routing config off AND the owner switch off. Always allowed."""
    cfg = routing_load()
    cfg["enabled"] = False
    wrote = routing_write(cfg)
    try:
        switch_store().set("jev_routing", False, "owner")
    except switches.SwitchError:
        pass
    audit("routing-rollback", "all", "ok" if wrote else "config write failed")
    return wrote, "Routing is OFF everywhere" if wrote else "switch is off, but the settings file could not be updated"


def routing_report() -> dict | None:
    env = {**os.environ, "PYTHONPATH": "/opt/agentai-platform/current"}
    try:
        done = subprocess.run(["python3", "-m", "agentai_platform.routing.report_cli"], capture_output=True, text=True,
                              timeout=25, cwd="/opt/agentai-platform/current", env=env)
        return json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def routing_page(rec: dict) -> str:
    cfg = routing_load()
    store = switch_store()
    facts = live_facts()
    store.facts = lambda f=facts: f
    sw = store.describe("jev_routing")
    state = "ON (shadow: records only)" if sw["effective_on"] and cfg["enabled"] else "OFF"
    csrf = f"<input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
    r = routing_report()
    if r is None:
        stats = "<p class=muted>Statistics are not available right now.</p>"
    else:
        def v(x, suffix=""): return "—" if x is None else f"{x}{suffix}"
        rows = [("Requests seen (30 days)", v(r["total_routed"])), ("Classified by JEV", v(r["classified"])),
                ("JEV unavailable or rejected", v(r["unavailable_or_rejected"])),
                ("Would use a lightweight route", v(r["jev_selected_percent"], "%")),
                ("Would escalate to Claude", v(r["claude_escalation_percent"], "%")),
                ("Would change today's route", v(r["would_change_route_percent"], "%")),
                ("Success rate of those requests", v(r["success_percent"], "%")), ("Failed requests", v(r["failed_count"])),
                ("Average real task cost", v(r["avg_task_cost_usd"], " USD")), ("Average task time", v(r["avg_task_seconds"], " s")),
                ("Average JEV answer time", v(r["avg_classifier_latency_ms"], " ms")),
                ("Confidence spread", esc(", ".join(f"{k}: {n}" for k, n in r["confidence_distribution"].items()))),
                ("Recommended routes", esc(", ".join(f"{k}: {n}" for k, n in r["by_recommended_route"].items()) or "—")),
                ("Routing cost so far (estimate)", v(r["classifier_cost_usd_estimated"], " USD")),
                ("Estimated monthly savings", "not measured yet — needs the benchmark")]
        stats = table(["Measure", "Value"], [(esc(a), b if a in ("Confidence spread", "Recommended routes") else esc(b)) for a, b in rows], "no data")
    def chk(name, on): return f"<label class=small><input type=checkbox name={name} {'checked' if on else ''}> {name.replace('route_', '')}</label> "
    routes = "".join(chk("route_" + k, cfg["routes"].get(k, False)) for k in routing_config.ROUTES if k != "abstain")
    form = (f"<form method=post action=/routing-save>{csrf}"
            f"<p>{chk('enabled', cfg['enabled'])} <b>Routing on</b> (also needs the switch below)</p>"
            f"<p class=small>Mode: <b>shadow</b> — recommendations are recorded, nothing about how requests run changes. Canary and live routing are not built yet, so there is no rollout control to move.</p>"
            f"<p class=small>Routes JEV may recommend (only <b>claude</b> is wired end to end today; others fall back to it): {routes}</p>"
            f"<p class=small>Send straight through at confidence ≥ <input name=automatic value='{cfg['confidence']['automatic']}' size=4> "
            f"· run extra checks from <input name=review value='{cfg['confidence']['review']}' size=4> · below that, use the stronger model. "
            f"<span class=mut>(starting values, not yet calibrated)</span></p>"
            f"<p class=small>Max escalations <input name=max_escalations value='{cfg['escalation']['max_escalations']}' size=2> "
            f"· retries per step <input name=max_retries_per_step value='{cfg['escalation']['max_retries_per_step']}' size=2> "
            f"· max minutes per task <input name=max_task_duration_seconds value='{cfg['limits']['max_task_duration_seconds']}' size=5> seconds "
            f"· max spend per task $<input name=max_task_cost_usd value='{cfg['limits']['max_task_cost_usd']}' size=4></p>"
            f"<button type=submit>Save routing settings</button></form>")
    rollback = (f"<form method=post action=/routing-rollback class=inline>{csrf}<button type=submit class=danger>Emergency rollback: turn routing off everywhere</button></form>")
    return ("<h2>Smart routing (JEV)</h2>"
            f"<div class=card><b>Status: {esc(state)}</b><div class=small>Owner switch: {esc(sw['status'])}"
            + ("" if sw["effective_on"] else " — set it on the <a href=/switches>Feature switches</a> page (needs the data-terms tick and the key installed)")
            + f".</div>{form}{rollback}</div><h3>What JEV recommended (last 30 days)</h3>" + stats)


def system_page() -> str:
    """The owner's own OpenClaw runtime (gateway, proxy ledger, containers): the old overview, kept for diagnosis."""
    items = [gw_health(), gw_version(), postgres(), spend(), backups(),
             containers()]
    strip = now_running()
    ap = approvals_data()
    cards = "".join(
        f"<div class=card><h3>{esc(o['label'])}</h3>{pill(o['state'])}"
        f"<div class=small style=margin-top:.35rem>"
        f"{esc(o['detail'] if not isinstance(o['detail'], list) else chr(10).join(str(x) for x in o['detail']))}"
        f"</div><div class=ts>{esc(o['ts'])}</div></div>"
        for o in items)
    spend_card = next((o for o in items if o["label"].startswith("spend")), None)
    spend_html = ("<div class='card' style='grid-column:1/-1'><h3>Spend vs "
                  "configured caps</h3>" +
                  (spend_bars(spend_card["detail"])
                   if spend_card and spend_card["state"] != "unknown" else
                   "<p class=unknown>spend unavailable</p>") + "</div>")
    strip_html = ("<h2>Now running</h2>" + ("<div class=strip>" + "".join(
        f"<span class=chip><span class=live>●</span> {esc(x)}</span>" for x in strip)
        + "</div>" if strip else "<p class=empty>nothing running right now</p>"))
    sb = sandbox_browser_enabled()
    jev_on = jev_research_enabled()
    controls = ("<h2>Controls</h2><div class=grid>" +
                toggle_row("jev_research", "Jev research layer", jev_on, False,
                           "managed on the Feature switches page") +
                toggle_row("sandbox_browser", "Sandbox browser",
                           sb, True, "per-session browser containers for "
                           "browser-worker (pinned image)") +
                toggle_row("web_search", "Native web search", False, False,
                           "off — no supported provider credential; Brave MCP "
                           "search stays available to the researcher") +
                "</div><p><a href=/switches>All feature switches →</a></p>")
    gates = ("<h2>Fixed boundaries</h2>" +
             gate("session cancel: no owner-scoped native abort verified on "
                  "this build — use the Control UI") +
             gate("approval resolution: read-only here; resolve via "
                  "Telegram/Control UI (native policy authoritative)") +
             gate("new chat: Control UI / Telegram"))
    body = ("<h2>Health</h2><div class=grid>" + cards + "</div>" +
            spend_html + strip_html +
            f"<h2>Pending approvals</h2>" +
            (f"<div class=card><span class='pill warn'>{ap.get('count', 0)} "
             f"pending</span> <a href=/approvals>review</a></div>"
             if ap.get("count") else
             "<p class=ok>no pending approvals</p>") +
            controls + gates)
    return body


def overview_data() -> dict | None:
    """Product numbers from the app (counts, queue, spend). Cached briefly; None when the app cannot be read."""
    def load():
        rc, out = signup_admin("overview")
        if rc != 0:
            return None
        for line in reversed(out.splitlines()):
            try:
                return json.loads(line)
            except ValueError:
                continue
        return None
    value, _ = cached("overview", 12, load)
    return value


SERVICES = [("agentai-platform-app", "Customer app"), ("agentai-request-worker", "Task runner"), ("agentai-lifecycle-worker", "Assistant manager"),
            ("agentai-cell-bridge", "Assistant bridge"), ("agentai-browse", "Browser service"), ("agentai-tool-relay", "Browser tool for assistants"), ("agentai-model-proxy", "Model gateway"),
            ("agentai-billing-worker.timer", "Billing worker"), ("agentai-ops-backup.timer", "Nightly backup"), ("agentai-ops-monitor.timer", "Health monitor"),
            ("caddy", "Web front door")]


def service_states() -> dict:
    def load():
        rc, out = run(["systemctl", "is-active", *[u for u, _ in SERVICES]], timeout=10)
        lines = out.splitlines()
        return {u: (lines[i].strip() if i < len(lines) else "unknown") for i, (u, _) in enumerate(SERVICES)}
    value, _ = cached("services", 15, load)
    return value


def _json_file(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def ops_status() -> tuple[dict, dict]:
    cfg = _json_file("/etc/agentai-ops/config.json")
    backup = _json_file(cfg.get("backup_status", "/var/lib/agentai-ops/backup-status.json"))
    monitor = _json_file(cfg.get("monitor_status", "/var/lib/agentai-ops/monitor-status.json"))
    return backup, monitor


def ago(epoch) -> str:
    if not epoch:
        return "never"
    secs = max(0, int(time.time() - epoch))
    return "just now" if secs < 90 else f"{secs // 60} min ago" if secs < 5400 else f"{secs // 3600} h ago" if secs < 172800 else f"{secs // 86400} days ago"


def usd(micro) -> str:
    return f"${(micro or 0) / 1e6:,.2f}"


FRIENDLY = {"open_signups": "Open sign-ups", "customer_execution": "Assistants answer customers", "browse_tasks": "Browser tasks",
            "open_access": "Free access (no payment)", "billing_checkout": "Take payments (Stripe)", "jev_routing": "Smart routing (JEV)",
            "research_optimization": "Smarter research (JEV)", "credentialed_browsing": "Saved logins for the browser", "customer_schedules": "Scheduled tasks"}
FRIENDLY_ORDER = ["open_signups", "customer_execution", "browse_tasks", "open_access", "billing_checkout", "jev_routing"]
BACK_PATHS = ("/", "/switches")


def switch_form(rec: dict, name: str, value: str, label: str, back: str = "/", cls: str = "small") -> str:
    return (f"<form method=post action=/switch class=inline><input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
            f"<input type=hidden name=name value='{esc(name)}'><input type=hidden name=value value='{value}'><input type=hidden name=back value='{esc(back)}'>"
            f"<button type=submit class='{cls}'>{esc(label)}</button></form>")


def home_page(rec: dict) -> str:
    ov = overview_data()
    svc = service_states()
    backup, monitor = ops_status()
    facts, sw = {}, {}
    try:
        facts = live_facts()
        store = switch_store()
        store.facts = lambda f=facts: f
        sw = {d["key"]: d for d in store.all()}
    except Exception:  # noqa: BLE001
        pass
    on = lambda k: bool(sw.get(k, {}).get("recorded_on")) and sw.get(k, {}).get("status") == "on"
    cust = (ov or {}).get("customers", {})
    waiting = int(cust.get("pending", 0))
    active = int(cust.get("active", 0))
    down = [name for u, name in SERVICES if svc.get(u) not in ("active", "unknown")]
    offsite = bool(backup.get("offsite_copy"))
    mon_overall = monitor.get("overall") or monitor.get("state")

    # --- things that need you
    needs = []
    if waiting:
        needs.append(("", f"{waiting} {'person is' if waiting == 1 else 'people are'} waiting for your approval", "They confirmed their email. Nothing works for them until you decide.", "/customers", "Review"))
    if down:
        needs.append(("red", "A service is not running: " + ", ".join(down), "Customers may be affected. Check the Live page or ask your assistant to look.", "/live", "Look"))
    if backup and not offsite:
        needs.append(("", "Backups are only stored on this server", "A second, off-server copy protects you if the server is lost.", "#launch", "See checklist"))
    if ov is None:
        needs.append(("red", "The dashboard could not read customer data from the app", "The numbers below are missing. The app may be restarting.", "/live", "Look"))
    healthy = not down and ov is not None
    hero_title = ("Everything is running" if healthy and not waiting else f"{len(needs)} thing{'s' if len(needs) != 1 else ''} need{'s' if len(needs) == 1 else ''} you" if needs else "Everything is running")
    hero_class = "bad" if down or ov is None else "warn" if needs else ""
    mode = {"invite_only": "Invite-only", "open": "Free access is on", "paid_required": "Payments are required"}.get((ov or {}).get("billing_mode", ""), "")
    hero = (f"<div class=hero><div><h2><span class='statusdot {hero_class}'></span>{esc(hero_title)}</h2>"
            f"<p>{esc(mode + ' · ' if mode else '')}{esc(str((ov or {}).get('assistants', '—')))} of {esc(str((ov or {}).get('limit', '—')))} assistants in use · "
            f"{esc(str((ov or {}).get('tasks_active', 0)))} task{'s' if (ov or {}).get('tasks_active', 0) != 1 else ''} running or waiting</p></div>"
            f"<div><a class='pill ok' href=/live>Live view →</a></div></div>")
    attention = ("<div class=attention>" + "".join(
        f"<div class='todo {c}'><div class=grow><b>{esc(t)}</b><span>{esc(sub)}</span></div><a href='{href}'><button type=button class=primary>{esc(label)}</button></a></div>"
        for c, t, sub, href, label in needs) + "</div>") if needs else ""

    # --- numbers
    tasks7 = sum((ov or {}).get("tasks_7d", {}).values()) if ov else 0
    kpis = (f"<div class=kpis>"
            f"<div class=kpi><div class=label>Customers</div><div class=num>{active}<small> active</small></div><div class=note>{waiting} waiting · {cust.get('suspended', 0)} suspended</div></div>"
            f"<div class=kpi><div class=label>Tasks this week</div><div class=num>{tasks7}</div><div class=note>{(ov or {}).get('tasks_7d', {}).get('failed', 0)} failed · {(ov or {}).get('tasks_7d', {}).get('cancelled', 0)} cancelled</div></div>"
            f"<div class=kpi><div class=label>Spend (30 days)</div><div class=num>{usd((ov or {}).get('spend_d30'))}</div><div class=note>{usd((ov or {}).get('spend_today'))} today · across all customers</div></div>"
            f"<div class=kpi><div class=label>Assistants awake</div><div class=num>{(ov or {}).get('cells', {}).get('running', 0)}<small> now</small></div><div class=note>they sleep after 15 minutes idle</div></div></div>")

    # --- launch checklist
    def item(state, title, note, href=""):
        ico = {"ok": "✓", "warn": "!", "todo": "○"}[state]
        link = f"<a href='{href}'>Open →</a>" if href else ""
        return f"<div class=check><span class='ico {state}'>{ico}</span><div class=t><b>{esc(title)}</b><span>{esc(note)}</span></div>{link}</div>"
    last_ok = backup.get("last_success_epoch")
    checks = [
        item("ok" if healthy else "warn", "Server and services", "All services are running" if healthy else "Something is down: see above", "/live"),
        item("ok" if facts.get("mail_ready") else "warn", "Email sending", "Sign-up and approval emails can be sent" if facts.get("mail_ready") else "Not set up"),
        item("ok" if last_ok else "warn", "Nightly backup", f"Last complete backup {ago(last_ok)}" + ("" if offsite else " · stored on this server only")),
        item("ok" if offsite else "warn", "Off-server backup copy", "A second copy exists elsewhere" if offsite else "Not set up yet (planned: final phase item F1)"),
        item("ok" if mon_overall in ("ok", "warn") else "warn" if mon_overall else "todo", "Health monitor", f"Overall: {mon_overall or 'no report yet'} (checks every 5 minutes)"),
        item("ok" if on("open_signups") else "todo", "Sign-ups", "Open: people can create an account and wait for you" if on("open_signups") else "Closed: turn on 'Open sign-ups' when you are ready to launch", "/switches"),
        item("ok" if facts.get("stripe_test_keys_present") else "todo", "Stripe", ("Test keys installed" + (" · payments are ON" if on("billing_checkout") else " · payments are OFF (free access)")) if facts.get("stripe_test_keys_present") else "Keys not installed", "/switches"),
        item("todo", "Terms, privacy and refund pages", "Needs your text (not written yet)"),
        item("todo", "Support email address", "Needs your decision"),
    ]
    launch = f"<div class=card id=launch><h3>Launch checklist</h3><div class=checklist>{''.join(checks)}</div></div>"

    # --- features at a glance
    tiles, seen = [], set()
    for key in FRIENDLY_ORDER + [k for k in sw if k not in FRIENDLY_ORDER]:
        d = sw.get(key)
        if not d or key in seen or d.get("locked"):
            continue
        seen.add(key)
        label = FRIENDLY.get(key, d["title"])
        state_on = d["status"] == "on"
        if d["recorded_on"]:
            ctl = switch_form(rec, key, "off", "Turn off", "/", "small")
        elif d["can_turn_on"]:
            ctl = switch_form(rec, key, "on", "Turn on", "/", "small primary")
        else:
            ctl = "<a href=/switches><button type=button class=small>Set up</button></a>"
        tiles.append(f"<div class='tile {'on' if state_on else ''}'><div class=head><b>{esc(label)}</b>{pill('ok' if state_on else 'warn').replace('>ok<', '>ON<').replace('>warn<', '>OFF<')}</div>"
                     f"<p>{esc(d['plain'])}</p><div>{ctl}</div></div>")
    features = f"<h2>Features</h2><div class=tiles>{''.join(tiles)}</div><p class=small><a href=/switches>All features and what each one does →</a></p>"

    # --- customers + health
    top = ((ov or {}).get("top_spenders") or [])
    spenders = "".join(f"<div class=kv><span>{esc(t['email'])}</span><span>{usd(t['microusd'])}</span></div>" for t in top) or "<p class=empty>No usage yet.</p>"
    people = f"<div class=card><h3>Top usage (30 days)</h3>{spenders}<p class=small style='margin-top:10px'><a href=/customers>All customers →</a> · <a href=/costs>Money →</a></p></div>"
    names = {"active": ("ok", "running"), "inactive": ("bad", "stopped"), "failed": ("bad", "failed")}
    health = "".join(f"<div class=svc><i class='{names.get(svc.get(u, ''), ('warn', ''))[0] if svc.get(u) not in ('active',) else ''}'></i>{esc(name)}</div>" for u, name in SERVICES)
    return (hero + attention + kpis + f"<div class=two><div>{launch}</div><div>{people}<h2>Services</h2><div class=services>{health}</div></div></div>" + features)


APP_ENV = "/etc/agentai-platform/accounts.env"
APP_DIR = "/opt/agentai-platform/current"
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CUSTOMER_ACTIONS = ("approve", "decline", "suspend", "resume")


def signup_admin(*args: str) -> tuple[int, str]:
    """Run the host-only `signup_admin` command as the app user. Arguments are fixed words or validated ids, never shell text."""
    script = ('set -a; . "$1"; set +a; cd "$2" || exit 1; shift 2; '
              'exec runuser -u agentai-platform -m -- ./.venv/bin/python manage.py signup_admin "$@"')
    return run(["/bin/sh", "-c", script, "_", APP_ENV, APP_DIR, *args], timeout=90)


def customers_data() -> dict | None:
    rc, out = signup_admin("list")
    if rc != 0:
        return None
    for line in reversed(out.splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def customer_action(action: str, account: str) -> tuple[bool, str]:
    if action not in CUSTOMER_ACTIONS or not ACCOUNT_RE.match(account or ""):
        return False, "unknown action or customer"
    rc, out = signup_admin(action, "--account", account)
    tail = redact(out.splitlines()[-1] if out else "")[:160]
    if rc != 0:
        return False, f"{action} refused: {tail}"
    return True, {"approve": "Approved: their assistant is being created and they were emailed.",
                  "decline": "Declined.", "suspend": "Suspended: they are signed out now.", "resume": "Resumed."}[action]


def customer_limit(raw: str) -> tuple[bool, str]:
    if not raw.isdecimal() or not 1 <= int(raw) <= 200:
        return False, "the limit must be a whole number from 1 to 200"
    rc, out = signup_admin("limit", "--count", raw)
    return (rc == 0, f"Customer limit is now {int(raw)}." if rc == 0 else "could not save the limit")


def when(epoch) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M") if epoch else "—"


def customers_page(rec: dict) -> str:
    csrf = f"<input type=hidden name=csrf value='{esc(rec['csrf'])}'>"
    data = customers_data()
    if data is None:
        return gate("Could not read the customer list from the app. Nothing was changed.")
    try:
        door = switch_store().is_on("open_signups")
    except Exception:  # noqa: BLE001
        door = False

    def btn(action, account, label, cls=""):
        return (f"<form method=post action=/customer-action class=inline>{csrf}<input type=hidden name=account value='{esc(account)}'>"
                f"<input type=hidden name=action value='{action}'><button type=submit class='small {cls}'>{label}</button></form>")
    avatar = lambda email: f"<span class=avatar>{esc((email or '?')[:1])}</span>"
    waiting = [c for c in data["customers"] if c["signup"] == "pending"]
    full = data["assistants"] >= data["limit"]
    head = (f"<div class=kpis style='margin-top:6px'>"
            f"<div class=kpi><div class=label>Sign-ups</div><div class=num style='font-size:1.4rem'>{'Open' if door else 'Closed'}</div>"
            f"<div class=note><a href=/switches>{'Close them' if door else 'Open them'} on the Features page</a></div></div>"
            f"<div class=kpi><div class=label>Assistants</div><div class=num>{data['assistants']}<small> of {data['limit']}</small></div>"
            f"<div class=note>{'The limit is reached: raise it before approving more' if full else 'Room for ' + str(data['limit'] - data['assistants']) + ' more'}</div></div>"
            f"<div class=kpi><div class=label>Customer limit</div><form method=post action=/customer-limit class=inline style='display:flex;gap:8px;margin-top:8px'>{csrf}"
            f"<input name=count value='{data['limit']}' size=4 inputmode=numeric aria-label='Customer limit'><button type=submit class=small>Save</button></form>"
            f"<div class=note>How many assistants this server may carry</div></div></div>")
    if waiting:
        cards = "".join(
            f"<div class=todo><div class='grow who'>{avatar(c['email'])}<div><b>{esc(c['email'])}</b><span>Signed up {esc(when(c['created_epoch']))} UTC</span></div></div>"
            f"{btn('approve', c['account'], 'Approve', 'primary')} {btn('decline', c['account'], 'Decline', 'danger')}</div>" for c in waiting)
        wait_html = f"<h2>Waiting for your approval ({len(waiting)})</h2><div class=attention>{cards}</div>"
    else:
        wait_html = "<h2>Waiting for your approval</h2><div class=empty-card>Nobody is waiting. New sign-ups appear here after they confirm their email.</div>"
    rows = []
    for c in data["customers"]:
        if c["signup"] == "pending":
            continue
        state = {"unverified": "email not confirmed", "declined": "declined"}.get(c["signup"] or "", "")
        state = state or ("active" if c["status"] == "active" else c["status"])
        act = (btn("suspend", c["account"], "Suspend", "danger") if c["status"] == "active"
               else btn("resume", c["account"], "Resume") if c["status"] == "suspended" and c["signup"] in (None, "approved") else "")
        rows.append([avatar(c["email"]) + esc(c["email"]), f"<span class='pill {'ok' if state == 'active' else 'warn'}'>{esc(state)}</span>",
                     esc({"ready": "ready", "pending": "starting", "stopped": "asleep"}.get(c["assistant"] or "", c["assistant"] or "—")), esc(when(c["created_epoch"])), act])
    all_html = ("<h2>All customers</h2><div class=searchbar><input type=search id=filter placeholder='Search by email…' aria-label='Search customers' data-filter-table=cust></div>"
                + "<div id=cust>" + table(["Customer", "State", "Assistant", "Since (UTC)", ""], rows, "No customers yet.") + "</div>")
    return head + wait_html + all_html


def jev_research_enabled() -> bool | None:
    try:
        with open(os.path.join(JEV_DIR, "config.json")) as f:
            return bool(json.load(f).get("enabled"))
    except (OSError, ValueError):
        return None


def sandbox_browser_enabled() -> bool | None:
    rc, out = run(["docker", "exec", GATEWAY, "node", "dist/index.js", "config",
                   "get", "agents.defaults.sandbox.browser.enabled"], timeout=20)
    if rc != 0:
        return None
    v = out.strip().lower()
    return True if v == "true" else (False if v == "false" else None)


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
