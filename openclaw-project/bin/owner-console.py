#!/usr/bin/env python3
"""Owner console: one private launcher page with a button for every owner view.

Starts one SSH tunnel (ops dashboard 18795 and OpenClaw Control UI 18789, loopback only) using the .env SSH credentials, then
serves a small page on http://127.0.0.1:18790/ with buttons for Customers, Feature switches, Overview, Live, Costs, Audit, the
Control UI, Lumina and Stripe test mode. Nothing is exposed to the network: every port is bound to 127.0.0.1.

  python3 openclaw-project/bin/owner-console.py            start (or reuse) the tunnel and open the page
  python3 openclaw-project/bin/owner-console.py --no-browser   same, without opening a browser
  python3 openclaw-project/bin/owner-console.py --stop     close the tunnel

The dashboard password is never shown on the page. The "Copy dashboard password" button puts it on your clipboard only.
"""
import html
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONSOLE_PORT, OPS_PORT, CONTROL_PORT = 18790, 18795, 18789
OPS = f"http://127.0.0.1:{OPS_PORT}"
BUTTONS = [
    ("Customers", f"{OPS}/customers", "Approve or decline sign-ups, suspend, set the customer limit"),
    ("Feature switches", f"{OPS}/switches", "Open sign-ups, browser tasks, free access, checkout"),
    ("Overview", f"{OPS}/", "Health of the server and assistants"),
    ("Live", f"{OPS}/live", "What is running right now"),
    ("Costs", f"{OPS}/costs", "Provider spend"),
    ("Audit", f"{OPS}/audit", "Owner action log"),
    ("Routing (JEV)", f"{OPS}/routing", "Smart-routing settings and report"),
]
OUTSIDE = [
    ("Lumina app", "https://getlumina.pro/app/", "What customers see"),
    ("Stripe (test mode)", "https://dashboard.stripe.com/test/dashboard", "Payments, customers, webhooks"),
]


def load_env():
    repo = Path(__file__).resolve().parents[2]
    env_file = repo / "openclaw-project/.env"
    if stat.S_IMODE(env_file.stat().st_mode) & 0o077:
        raise SystemExit("openclaw-project/.env must be private (mode 0600)")
    from dotenv import dotenv_values
    values = dotenv_values(env_file)
    pfx = "OPENCLAW_NEW_SSH_" if os.environ.get("OPENCLAW_SERVER", "new") == "new" else "OPENCLAW_SSH_"
    user = values.get(pfx + "USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user) or not values.get(pfx + "PASSWORD"):
        raise SystemExit("Set the SSH user and password in openclaw-project/.env")
    return repo, env_file, pfx, user + "@" + (values.get(pfx + "HOST") or "69.48.206.62")


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def render(token, status):
    def card(label, href, note, external=False):
        return (f"<a class=card href='{html.escape(href, quote=True)}' target=_blank rel=noopener><b>{html.escape(label)}</b>"
                f"<span>{html.escape(note)}</span></a>")
    dot = lambda ok: "<i class=ok></i>" if ok else "<i class=bad></i>"
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Owner console</title><style>
body{{margin:0;background:#0b0c10;color:#e9e9ee;font:15px/1.5 system-ui,sans-serif;padding:32px;max-width:900px;margin:auto}}
h1{{font-size:22px;margin:0 0 4px}} p.s{{color:#9a9aa6;margin:0 0 22px}} h2{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#9a9aa6;margin:26px 0 10px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}}
.card{{display:grid;gap:4px;padding:16px;border:1px solid #2a2b36;border-radius:14px;background:#14151c;color:inherit;text-decoration:none}}
.card:hover{{border-color:#6865ff;background:#191a24}} .card span{{color:#9a9aa6;font-size:13px}}
button{{font:inherit;padding:10px 14px;border-radius:10px;border:1px solid #2a2b36;background:#14151c;color:inherit;cursor:pointer}} button:hover{{border-color:#6865ff}}
i{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}} .ok{{background:#3ddc97}} .bad{{background:#ef6060}}
.row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}} small{{color:#9a9aa6}}
</style></head><body>
<h1>Owner console</h1><p class=s>{dot(status['ops'])}Dashboard tunnel &nbsp; {dot(status['control'])}Control UI tunnel &nbsp; {dot(status['site'])}getlumina.pro</p>
<h2>Lumina owner dashboard</h2><div class=grid>{''.join(card(*b) for b in BUTTONS)}</div>
<h2>Other views</h2><div class=grid>{''.join(card(*b) for b in OUTSIDE)}
<a class=card href='/control?t={token}' target=_blank><b>OpenClaw Control UI</b><span>Your own agent runtime</span></a></div>
<h2>Sign-in help</h2><div class=row><form method=post action='/copy-password'><input type=hidden name=t value='{token}'><button>Copy dashboard password</button></form>
<small>It goes to your clipboard only and is never shown here. Paste it on the dashboard sign-in page.</small></div>
</body></html>"""


class Console:
    def __init__(self, repo, env_file, pfx, target):
        self.repo, self.env_file, self.pfx, self.target = repo, env_file, pfx, target
        self.control = repo / "openclaw-project/tmp/owner-console-ssh.sock"
        self.token = secrets.token_urlsafe(16)

    def ssh_env(self, directory):
        askpass = Path(directory) / "askpass"
        askpass.write_text("#!" + sys.executable + "\nfrom dotenv import dotenv_values\n"
                           f"print(dotenv_values({str(self.env_file)!r})[{self.pfx + 'PASSWORD'!r}])\n")
        askpass.chmod(0o700)
        env = os.environ.copy()
        env.update(SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE="force", DISPLAY="openclaw:0")
        return env

    SSH = ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10", "-o", "NumberOfPasswordPrompts=1",
           "-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"]

    def tunnel_up(self):
        return subprocess.run(["ssh", "-S", str(self.control), "-O", "check", self.target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

    def start_tunnel(self):
        if self.tunnel_up():
            return
        self.control.parent.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="owner-console-") as d:
            out = subprocess.run(self.SSH + ["-f", "-N", "-M", "-S", str(self.control), "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
                                             "-o", "ServerAliveCountMax=3",
                                             "-L", f"127.0.0.1:{OPS_PORT}:127.0.0.1:{OPS_PORT}", "-L", f"127.0.0.1:{CONTROL_PORT}:127.0.0.1:{CONTROL_PORT}", self.target],
                                 env=self.ssh_env(d), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=25)
        if out.returncode:
            raise SystemExit(f"Could not create the tunnel (is another one using ports {OPS_PORT}/{CONTROL_PORT}?): {out.stderr.strip()[:200]}")

    def stop(self):
        subprocess.run(["ssh", "-S", str(self.control), "-O", "exit", self.target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def copy_password(self):
        with tempfile.TemporaryDirectory(prefix="owner-console-") as d:
            r = subprocess.run(self.SSH + ["-T", self.target, "cat /opt/openclaw-production/dashboard/owner-secret"], env=self.ssh_env(d),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        secret = r.stdout.strip()
        if r.returncode or not secret:
            return False
        clip = "pbcopy" if sys.platform == "darwin" else "xclip"
        subprocess.run([clip] if clip == "pbcopy" else [clip, "-selection", "clipboard"], input=secret, text=True, timeout=5)
        return True

    def control_ui(self):
        subprocess.Popen([sys.executable, str(Path(__file__).with_name("open-control-ui.py"))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def status(self):
        return {"ops": port_open(OPS_PORT), "control": port_open(CONTROL_PORT), "site": port_open_remote("getlumina.pro")}


def port_open_remote(host):
    try:
        with socket.create_connection((host, 443), timeout=1.5):
            return True
    except OSError:
        return False


def handler_for(console):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            raw = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(raw)

        def _local(self):
            return self.headers.get("Host", "") in (f"127.0.0.1:{CONSOLE_PORT}", f"localhost:{CONSOLE_PORT}")

        def do_GET(self):
            if not self._local():
                return self._send(403, "forbidden")
            if self.path == "/" or self.path.startswith("/?"):
                return self._send(200, render(console.token, console.status()))
            if self.path.startswith("/control") and f"t={console.token}" in self.path:
                console.control_ui()
                return self._send(200, "<p>Opening the Control UI… you can close this tab.</p>")
            self._send(404, "not found")

        def do_POST(self):
            if not self._local() or self.path != "/copy-password":
                return self._send(403, "forbidden")
            body = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 512)).decode()
            if f"t={console.token}" not in body:
                return self._send(403, "forbidden")
            ok = console.copy_password()
            self._send(200, "<p>" + ("Password copied to your clipboard. Paste it on the dashboard sign-in page." if ok else "Could not read the password.") + "</p><p><a href='/'>Back</a></p>")
    return Handler


def main(argv):
    repo, env_file, pfx, target = load_env()
    console = Console(repo, env_file, pfx, target)
    if "--stop" in argv:
        console.stop()
        print("Tunnel closed.")
        return
    console.start_tunnel()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", CONSOLE_PORT), handler_for(console))
    except OSError:
        print(f"The console is already running: open http://127.0.0.1:{CONSOLE_PORT}/")
        if "--no-browser" not in argv:
            webbrowser.open(f"http://127.0.0.1:{CONSOLE_PORT}/")
        return
    url = f"http://127.0.0.1:{CONSOLE_PORT}/"
    print(f"Owner console: {url}  (Ctrl+C to stop; the tunnel stays open, close it with --stop)")
    if "--no-browser" not in argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
