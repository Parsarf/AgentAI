#!/usr/bin/env python3
"""OpenClaw private ops dashboard (Phase 8 build).

Owner-only, read-first, loopback-only HTTP service. Python 3.12 stdlib only.
Every native operation is a fixed argv list — no client-supplied command,
path escape, or RPC name is ever executed. Mutating controls are feature-
gated OFF pending Phase 10 targeted proof and render as disabled.
Access model: SSH tunnel to 127.0.0.1:18795 + app password (possession +
knowledge). Not for exposure beyond loopback without TLS.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http import cookies as http_cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "/opt/openclaw-production"
DIR = os.path.join(BASE, "dashboard")
AUDIT_DIR = os.path.join(DIR, "audit")
AUDIT = os.path.join(AUDIT_DIR, "audit.jsonl")
OWNER_SECRET = os.path.join(DIR, "owner-secret")
SESSION_SECRET = os.path.join(DIR, "session-secret")
GATEWAY = "openclaw-production-openclaw-gateway-1"
POSTGRES = "openclaw-production-postgres-1"
PORT = 18795
BIND = "127.0.0.1"
SESSION_TTL = 12 * 3600
DOWNLOAD_TTL = 300
MAX_FILE_BYTES = 2_000_000
WORK_ROOT = "/home/node/.openclaw/work"
CAPS = {"daily_usd": 2.0, "monthly_usd": 25.0}  # owner-configured targets

FEATURE_GATES = {
    "new_chat": "awaiting Phase 10 targeted proof",
    "session_reset": "awaiting Phase 10 targeted proof",
    "approval_resolve": "native policy stays authoritative; owner resolves via Telegram/Control UI",
    "connector_toggle": "owner uses bin/connect-tool (command-owner separation)",
    "file_upload": "requires enforced permissions, size/type limits, malware scan — unavailable",
    "provisioning": "no additional audience authorized by owner",
}

_cache: dict[str, tuple[float, object]] = {}
_login_fails: dict[str, list[float]] = {}

SPEND_SQL = (
    "SELECT 'today', COALESCE(SUM(spend),0) FROM \"LiteLLM_SpendLogs\" "
    "WHERE \"startTime\" >= date_trunc('day', now() at time zone 'utc') "
    "UNION ALL SELECT '30d', COALESCE(SUM(spend),0) FROM \"LiteLLM_SpendLogs\" "
    "WHERE \"startTime\" >= now() - interval '30 days'"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def run(argv: list[str], timeout: int = 20) -> tuple[int, str]:
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
    except Exception as e:  # noqa: BLE001 — boundary must never crash the page
        return 125, f"error: {type(e).__name__}"


def cached(key: str, ttl: int, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], hit[0]
    value = fn()
    _cache[key] = (now, value)
    return value, now


def _secret_path_refresh() -> bytes:
    """Read session secret; (re)generate if absent. Regeneration = global
    revocation of all cookies (documented as the kill switch)."""
    try:
        with open(SESSION_SECRET, "rb") as f:
            return f.read().strip()
    except FileNotFoundError:
        raw = secrets.token_hex(32).encode()
        fd = os.open(SESSION_SECRET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        return raw


def check_password(supplied: str) -> bool:
    try:
        with open(OWNER_SECRET, "rb") as f:
            want = f.read().strip()
    except OSError:
        return False
    return hmac.compare_digest(want, supplied.encode())


def _sign(payload: str) -> str:
    return hmac.new(_secret_path_refresh(), payload.encode(), hashlib.sha256).hexdigest()


def audit(action: str, target: str, result: str) -> bool:
    rec = {"ts": now_iso(), "actor": "owner", "role": "owner",
           "action": action, "target": target, "result": result}
    try:
        with open(AUDIT, "a") as f:
            f.write(json.dumps(rec) + "\n")
        return True
    except OSError:
        return False


def audit_tail(n: int = 20) -> list[str]:
    try:
        with open(AUDIT, "r") as f:
            return f.readlines()[-n:]
    except OSError:
        return []


# ---------- fixed native data operations ----------

def obs(label: str, state: str, detail: str) -> dict:
    return {"label": label, "state": state, "detail": detail, "ts": now_iso()}


def gw_health() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:18789/healthz", timeout=5) as r:
            ok = r.status == 200
        return obs("gateway /healthz", "ok" if ok else "down",
                   f"HTTP {r.status}")
    except Exception as e:  # noqa: BLE001
        return obs("gateway /healthz", "down", f"unavailable: {type(e).__name__}")


def gw_version() -> dict:
    rc, out = run(["docker", "exec", GATEWAY, "node", "dist/index.js", "--version"])
    return obs("gateway release", "ok" if rc == 0 else "unknown",
               out.splitlines()[0][:120] if out else f"rc={rc}")


def containers() -> dict:
    rc, out = run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"])
    if rc != 0:
        return obs("containers", "unknown", f"rc={rc}")
    rows = [line.split("|", 1) for line in out.splitlines() if "|" in line]
    return obs(f"containers ({len(rows)})", "ok", rows)


def postgres() -> dict:
    rc, out = run(["docker", "exec", POSTGRES, "pg_isready", "-U", "litellm",
                   "-d", "litellm"])
    return obs("postgres", "ok" if rc == 0 else "down", out.splitlines()[0][:120])


def spend() -> dict:
    def q():
        return run(["docker", "exec", POSTGRES, "psql", "-U", "litellm",
                    "-d", "litellm", "-t", "-A", "-c", SPEND_SQL])
    (rc, out), ts = cached("spend", 60, q)
    vals = {}
    for line in (out or "").splitlines():
        if "|" in line:
            k, v = line.split("|", 1)
            try:
                vals[k] = float(v)
            except ValueError:
                pass
    if rc != 0 or "today" not in vals:
        return obs("litellm spend", "unknown", f"query rc={rc}")
    d, m = vals.get("today", 0.0), vals.get("30d", 0.0)
    detail = (f"today ${d:.4f} / ${CAPS['daily_usd']:.2f} — "
              f"30d ${m:.2f} / ${CAPS['monthly_usd']:.2f} (configured targets)")
    state = "ok"
    if d >= CAPS["daily_usd"] or m >= CAPS["monthly_usd"]:
        state = "warn"
    return obs("litellm spend (proxy ledger)", state, detail)


def backups() -> dict:
    ops_dir = os.path.join(BASE, "backups", "ops")
    try:
        newest = max((os.path.join(ops_dir, f) for f in os.listdir(ops_dir)
                      if f.startswith("oc-ops-")), key=os.path.getmtime)
        age_h = int((time.time() - os.path.getmtime(newest)) / 3600)
        state = "ok" if age_h <= 24 else "stale"
        return obs("operator backup", state,
                   f"{os.path.basename(newest)} age={age_h}h (RPO target 24h)")
    except (OSError, ValueError):
        return obs("operator backup", "unknown", "no ops archive found")


def approvals_pending() -> dict:
    def q():
        return run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                    "approvals", "pending", "--json"], timeout=30)
    (rc, out), _ = cached("approvals", 15, q)
    if rc != 0:
        return {"state": "unknown", "text": f"approvals pending rc={rc}"}
    try:
        data = json.loads(out)
        if isinstance(data, list):
            items = data
        else:
            items = (data.get("requests") or data.get("items")
                     or data.get("pending") or [])
        return {"state": "ok", "count": len(items), "items": items}
    except json.JSONDecodeError:
        return {"state": "ok", "text": out[:1500]}


def sessions() -> dict:
    def q():
        return run(["docker", "exec", GATEWAY, "node", "dist/index.js",
                    "sessions", "list", "--json"], timeout=30)
    (rc, out), _ = cached("sessions", 30, q)
    if rc != 0:
        return {"state": "unknown", "rows": []}
    try:
        data = json.loads(out)
        items = data.get("sessions") or data.get("list") or []
        rows = []
        for s in items:
            key = str(s.get("key", "?"))[:80]
            agent = key.split(":")[1] if key.count(":") >= 1 else "?"
            rows.append((key, agent, str(s.get("updatedAtMs", ""))[:13]))
        return {"state": "ok", "rows": rows}
    except json.JSONDecodeError:
        return {"state": "unknown", "rows": []}


def connectors() -> dict:
    def q():
        return run(["python3", os.path.join(BASE, "integrations",
                                            "manage-connectors.py"), "list"],
                   timeout=30)
    (rc, out), _ = cached("connectors", 60, q)
    state = "ok" if rc == 0 else "unknown"
    return {"state": state, "text": (out or f"rc={rc}")[:2000]}


def safe_rel(p: str) -> str | None:
    if p == "":
        return ""  # the allowlisted root itself
    if not p or p.startswith("/"):
        return None
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or ".." in parts:
        return None
    if any(x.startswith(".") for x in parts):
        return None
    if any(not re.fullmatch(r"[A-Za-z0-9_\- ]{1,80}", x) for x in parts):
        return None
    return "/".join(parts)


def list_files(rel: str) -> dict:
    r = safe_rel(rel)
    if r is None:
        return {"state": "denied", "entries": [], "path": rel}
    target = f"{WORK_ROOT}/{r}"
    rc, out = run(["docker", "exec", GATEWAY, "find", target, "-maxdepth", "1",
                   "-printf", "%y|%s|%TY-%Tm-%Td %TH:%TM|%p\n"])
    entries = []
    if rc == 0:
        for line in out.splitlines():
            bits = line.split("|", 3)
            if len(bits) == 4:
                kind, size, mtime, full = bits
                name = full.rsplit("/", 1)[-1]
                if name.startswith("."):
                    continue
                sub = f"{r}/{name}" if r else name
                entries.append({"kind": kind, "size": size, "mtime": mtime,
                                "name": name, "rel": sub, "dir": kind == "d",
                                "link": kind == "l"})
        entries.sort(key=lambda e: (not e["dir"], e["name"]))
        return {"state": "ok", "entries": entries, "path": r}
    return {"state": "unknown", "entries": [], "path": r}


def read_file(rel: str) -> tuple[str | None, str]:
    r = safe_rel(rel)
    if r is None:
        return None, "path rejected"
    path = f"{WORK_ROOT}/{r}"
    rc, _ = run(["docker", "exec", GATEWAY, "test", "-L", path])
    if rc == 0:
        return None, "symlinks are not downloadable"
    rc, out = run(["docker", "exec", GATEWAY, "stat", "-c", "%s", path])
    if rc != 0:
        return None, "stat failed"
    try:
        if int(out) > MAX_FILE_BYTES:
            return None, "file exceeds 2 MB cap"
    except ValueError:
        return None, "bad stat"
    rc, content = run(["docker", "exec", GATEWAY, "cat", path])
    if rc != 0:
        return None, "read failed"
    return content, ""


# ---------- html ----------

def esc(v) -> str:
    return html.escape(str(v), quote=True)


CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,sans-serif;background:#101418;color:#e6e6e6}
header{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;padding:.7rem 1rem;background:#171c22;border-bottom:1px solid #2a323c}
h1{font-size:1.05rem;margin:0 auto 0 0}
nav a{color:#7ab7ff;margin-right:.8rem;text-decoration:none}
nav a:focus,button:focus,input:focus{outline:2px solid #7ab7ff}
main{padding:1rem;max-width:1100px;margin:0 auto}
table{border-collapse:collapse;width:100%;margin:.5rem 0}
th,td{border:1px solid #2a323c;padding:.35rem .55rem;text-align:left;overflow-wrap:anywhere}
th{background:#171c22}
.ok{color:#5fd068}.warn{color:#ffc857}.down,.error{color:#ff6b6b}
.unknown,.stale,.denied{color:#b9a44c}
.muted{color:#9aa7b3}
.gate{border:1px dashed #b9a44c;padding:.5rem .7rem;margin:.6rem 0;border-radius:6px}
form.inline{display:inline}
button,input[type=password]{font:inherit;padding:.35rem .7rem;border-radius:6px;border:1px solid #2a323c;background:#1d242c;color:#e6e6e6}
button{cursor:pointer}
.login{max-width:22rem;margin:18vh auto;text-align:center}
dl{display:grid;grid-template-columns:max-content 1fr;gap:.25rem .9rem}
@media(max-width:640px){dl{grid-template-columns:1fr}table{font-size:.85rem}}
"""


def page(title: str, body: str, session_valid: bool, csrf: str = "",
         flash: str = "") -> str:
    nav = ""
    logout = ""
    if session_valid:
        nav = (f"<nav><a href=/>Overview</a><a href=/sessions>Sessions</a>"
               f"<a href=/files>Files</a><a href=/decisions>Decisions</a>"
               f"<a href=/integrations>Integrations</a><a href=/audit>Audit</a></nav>")
        logout = (f"<form method=post action=/logout class=inline>"
                  f"<input type=hidden name=csrf value='{esc(csrf)}'>"
                  f"<button type=submit>Logout</button></form>")
    fl = f"<p class=warn>{esc(flash)}</p>" if flash else ""
    return (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} — OpenClaw ops</title>"
            f"<style>{CSS}</style></head><body>"
            f"<header><h1>OpenClaw ops</h1>{nav}{logout}</header>"
            f"<main>{fl}{body}</main></body></html>")


def obs_table(items: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{esc(o['label'])}</td><td class={esc(o['state'])}>"
        f"{esc(o['state'])}</td><td>{esc(o['detail'])}</td>"
        f"<td class=muted>{esc(o['ts'])}</td></tr>"
        for o in items)
    return (f"<table><tr><th>Check</th><th>State</th><th>Detail</th>"
            f"<th>Observed (UTC)</th></tr>{rows}</table>")


def gate_notes() -> str:
    rows = "".join(f"<div class=gate><b>{esc(k)}</b> — DISABLED: {esc(v)}</div>"
                   for k, v in FEATURE_GATES.items())
    return f"<h2>Disabled controls (truthful availability)</h2>{rows}"


# ---------- http handler ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet; never log cookies/paths with tokens
        pass

    # helpers
    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8",
              extra: list[tuple[str, str]] | None = None) -> None:
        raw = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _cookie(self, name: str) -> str | None:
        hdr = self.headers.get("Cookie", "")
        jar = http_cookies.SimpleCookie()
        try:
            jar.load(hdr)
        except http_cookies.CookieError:
            return None
        morsel = jar.get(name)
        return morsel.value if morsel else None

    def _session(self) -> tuple[bool, str]:
        raw = self._cookie("dsh")
        if not raw:
            return False, ""
        try:
            ts_s, sig = raw.split(".", 1)
            ts = int(ts_s)
        except ValueError:
            return False, ""
        if not hmac.compare_digest(_sign(f"s|{ts_s}"), sig):
            return False, ""
        if time.time() - ts > SESSION_TTL:
            return False, ""
        return True, ts_s

    def _csrf(self, ts_s: str) -> str:
        return _sign(f"csrf|{ts_s}")

    def _check_csrf(self, ts_s: str, supplied: str) -> bool:
        return bool(ts_s) and hmac.compare_digest(self._csrf(ts_s), supplied or "")

    def _form(self) -> dict[str, str]:
        length = min(int(self.headers.get("Content-Length") or 0), 8192)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def _page(self, code: int, title: str, body: str, authed: tuple[bool, str],
              flash: str = "") -> None:
        ok, ts_s = authed
        self._send(code, page(title, body, ok, self._csrf(ts_s) if ok else "", flash))

    # routes
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        authed = self._session()

        if path == "/login" or (path == "/" and not authed[0]):
            body = (f"<div class=login><h2>Owner sign-in</h2>"
                    f"<form method=post action=/login>"
                    f"<input type=password name=password placeholder='app password' "
                    f"autocomplete=current-password required> "
                    f"<button type=submit>Sign in</button></form></div>")
            self._send(200, page("sign in", body, False))
            return

        if not authed[0]:
            self._redirect("/login")
            return

        if path == "/":
            sections = [gw_health(), gw_version(), postgres(), spend(), backups(),
                        containers()]
            body = "<h2>Overview</h2>" + obs_table(sections) + gate_notes()
            self._page(200, "overview", body, authed)
            return

        if path == "/sessions":
            s = sessions()
            if s["state"] != "ok":
                body = f"<h2>Sessions</h2><p class=unknown>unavailable</p>"
                rows = ""
            else:
                rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(a)}</td>"
                               f"<td class=muted>{esc(u)}</td></tr>"
                               for k, a, u in s["rows"]) or \
                    "<tr><td colspan=3 class=muted>no sessions</td></tr>"
                body = (f"<h2>Sessions</h2>"
                        f"<table><tr><th>Session key</th><th>Agent</th>"
                        f"<th>Updated (ms epoch)</th></tr>{rows}</table>")
            body += (f"<div class=gate><b>new_chat / session_reset</b> — DISABLED: "
                     f"{esc(FEATURE_GATES['new_chat'])}</div>")
            self._page(200, "sessions", body, authed)
            return

        if path == "/files":
            rel = urllib.parse.parse_qs(parsed.query).get("dir", [""])[0]
            listing = list_files(rel)
            if listing["state"] == "denied":
                body = "<h2>Files</h2><p class=denied>path rejected</p>"
            elif listing["state"] != "ok":
                body = f"<h2>Files</h2><p class=unknown>listing unavailable</p>"
            else:
                rows = ""
                for e in listing["entries"]:
                    size = "—" if e["dir"] else f"{int(e['size'] or 0):,} B"
                    if e["dir"]:
                        name = f"<a href='/files?dir={urllib.parse.quote(e['rel'])}'>{esc(e['name'])}/</a>"
                        dl = ""
                    elif e["link"]:
                        name, dl = f"{esc(e['name'])} (symlink — download refused)", ""
                    else:
                        exp = int(time.time()) + DOWNLOAD_TTL
                        sig = _sign(f"dl|{e['rel']}|{exp}")
                        name = esc(e["name"])
                        dl = (f"<a href='/files/dl?path={urllib.parse.quote(e['rel'])}"
                              f"&exp={exp}&sig={sig}'>download</a>")
                    rows += (f"<tr><td>{name}</td><td>{size}</td>"
                             f"<td class=muted>{esc(e['mtime'])}</td><td>{dl}</td></tr>")
                body = (f"<h2>Files — allowlisted root <code>work/</code></h2>"
                        f"<table><tr><th>Name</th><th>Size</th><th>Modified (UTC)</th>"
                        f"<th></th></tr>{rows or '<tr><td colspan=4 class=muted>empty</td></tr>'}</table>"
                        f"<div class=gate><b>file_upload</b> — DISABLED: "
                        f"{esc(FEATURE_GATES['file_upload'])}</div>")
            self._page(200, "files", body, authed)
            return

        if path == "/files/dl":
            q = urllib.parse.parse_qs(parsed.query)
            rel = q.get("path", [""])[0]
            try:
                exp = int(q.get("exp", ["0"])[0])
            except ValueError:
                exp = 0
            sig = q.get("sig", [""])[0]
            ok, ts_s = authed
            if not ok:
                return self._redirect("/login")
            if exp < time.time() or not hmac.compare_digest(_sign(f"dl|{rel}|{exp}"), sig):
                return self._deny(403, "download token expired or invalid")
            content, err = read_file(rel)
            if content is None:
                return self._deny(403, err)
            if not audit("download", rel, "ok"):
                return self._deny(500, "audit write failed — download refused")
            self._send(200, content, ctype="application/octet-stream",
                       extra=[("Content-Disposition",
                               f"attachment; filename=\"{os.path.basename(rel)}\"")])
            return

        if path == "/decisions":
            d = approvals_pending()
            if d.get("state") != "ok":
                body = "<h2>Decisions (pending approvals)</h2><p class=unknown>unavailable</p>"
            elif "items" in d and not d["items"]:
                body = ("<h2>Decisions (pending approvals)</h2>"
                        "<p class=ok>no pending approvals</p>")
            else:
                text = json.dumps(d.get("items", d.get("text", "")), indent=1)[:3000]
                body = (f"<h2>Decisions (pending approvals)</h2><pre>{esc(text)}</pre>")
            body += (f"<div class=gate><b>approval_resolve</b> — DISABLED: "
                     f"{esc(FEATURE_GATES['approval_resolve'])}</div>")
            self._page(200, "decisions", body, authed)
            return

        if path == "/integrations":
            c = connectors()
            body = (f"<h2>Integrations</h2><pre>{esc(c['text'])}</pre>"
                    f"<div class=gate><b>connector_toggle</b> — DISABLED: "
                    f"{esc(FEATURE_GATES['connector_toggle'])}</div>"
                    f"<p class=muted>Account sign-in is owner-only via "
                    f"bin/connect-tool (protected flows; no credentials here).</p>")
            self._page(200, "integrations", body, authed)
            return

        if path == "/audit":
            tail = audit_tail()
            rows = "".join(f"<tr><td>{esc(l.strip())}</td></tr>" for l in tail) or \
                "<tr><td class=muted>no audit records yet</td></tr>"
            body = (f"<h2>Application audit (append-only JSONL)</h2>"
                    f"<table>{rows}</table>"
                    f"<p class=muted>Retention: on host; host administrator can "
                    f"edit — stated, not hidden. Edits/deletes through app roles "
                    f"are impossible (no such route).</p>")
            self._page(200, "audit", body, authed)
            return

        self._deny(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path == "/login":
            form = self._form()
            ip = self.client_address[0]
            now = time.time()
            fails = [t for t in _login_fails.get(ip, []) if now - t < 3600]
            if len(fails) >= 5:
                return self._deny(429, "too many failed attempts; wait an hour")
            if not check_password(form.get("password", "")):
                _login_fails.setdefault(ip, []).append(now)
                audit("login", ip, "failed")
                return self._deny(403, "wrong password")
            _login_fails[ip] = []
            ts_s = str(int(time.time()))
            cookie = (f"dsh={ts_s}.{_sign('s|' + ts_s)}; HttpOnly; SameSite=Strict; "
                      f"Max-Age={SESSION_TTL}; Path=/")
            if not audit("login", ip, "ok"):
                return self._deny(500, "audit write failed — login refused")
            self._redirect("/", cookie=cookie)
            return

        ok, ts_s = self._session()
        form = self._form()
        if not ok or not self._check_csrf(ts_s, form.get("csrf", "")):
            return self._deny(403, "bad session or csrf")
        if path == "/logout":
            audit("logout", self.client_address[0], "ok")
            self._redirect("/", cookie="dsh=; HttpOnly; Max-Age=0; Path=/")
            return
        if path == "/revoke-all":
            try:
                os.remove(SESSION_SECRET)
            except FileNotFoundError:
                pass
            _secret_path_refresh()
            ok = audit("revoke-all-sessions", "all", "ok")
            if not ok:
                return self._deny(500, "audit write failed — action refused")
            self._redirect("/login", cookie="dsh=; HttpOnly; Max-Age=0; Path=/")
            return
        self._deny(404, "not found")

    def _redirect(self, loc: str, cookie: str | None = None) -> None:
        extra = [("Location", loc)]
        if cookie:
            extra.append(("Set-Cookie", cookie))
        self.send_response(303)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _deny(self, code: int, msg: str) -> None:
        body = (f"<div class=login><p class=error>{esc(msg)}</p>"
                f"<p><a href=/>back</a></p></div>")
        self._send(code, page("denied", body, self._session()[0]))


def main() -> None:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    os.chmod(DIR, 0o700)
    _secret_path_refresh()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    server.daemon_threads = True
    print(f"dashboard listening on {BIND}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
