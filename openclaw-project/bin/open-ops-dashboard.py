#!/usr/bin/env python3
"""Open the private ops dashboard (Phase 8) via the .env SSH credentials.

Opens a loopback-only SSH tunnel (127.0.0.1:18795), launches the browser,
and prints the dashboard app password so the owner can sign in. The
password lives only on the VPS (owner-secret, mode 0600) and is shown in
this terminal on request — never embedded in the page or logs.
"""
import os
import re
import stat
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

from dotenv import dotenv_values

repo = Path(__file__).resolve().parents[2]
env_file = repo / "openclaw-project/.env"
if stat.S_IMODE(env_file.stat().st_mode) & 0o077:
    raise SystemExit("openclaw-project/.env must be private (mode 0600)")
values = dotenv_values(env_file)
user = values.get("OPENCLAW_SSH_USER", "")
if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
    raise SystemExit("Set a valid OPENCLAW_SSH_USER in openclaw-project/.env")
if not values.get("OPENCLAW_SSH_PASSWORD"):
    raise SystemExit("Set OPENCLAW_SSH_PASSWORD in openclaw-project/.env")
target = user + "@69.48.206.62"
LOCAL_PORT = 18795

with tempfile.TemporaryDirectory(prefix="openclaw-ops-") as directory:
    askpass = Path(directory) / "askpass"
    askpass.write_text(
        "#!" + sys.executable + "\n"
        "from dotenv import dotenv_values\n"
        "print(dotenv_values(" + repr(str(repo / "openclaw-project/.env")) + ")[\"OPENCLAW_SSH_PASSWORD\"])\n"
    )
    askpass.chmod(0o700)
    env = os.environ.copy()
    env.update(SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE="force", DISPLAY="openclaw:0")
    ssh = ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
           "-o", "NumberOfPasswordPrompts=1", "-o", "PreferredAuthentications=password",
           "-o", "PubkeyAuthentication=no"]
    control = repo / "openclaw-project/tmp/ops-dashboard-ssh.sock"
    control.parent.mkdir(mode=0o700, exist_ok=True)
    check = subprocess.run(["ssh", "-S", str(control), "-O", "check", target],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check.returncode:
        tunnel = subprocess.run(
            ssh + ["-f", "-N", "-M", "-S", str(control), "-o", "ExitOnForwardFailure=yes",
                   "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
                   "-L", f"127.0.0.1:{LOCAL_PORT}:127.0.0.1:{LOCAL_PORT}", target],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=20,
        )
        if tunnel.returncode:
            raise SystemExit(f"Could not create the tunnel; check SSH access and local port {LOCAL_PORT}")

    result = subprocess.run(
        ssh + ["-T", target, "cat /opt/openclaw-production/dashboard/owner-secret"],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, timeout=30,
    )
    if result.returncode or not result.stdout.strip():
        raise SystemExit("Could not read the dashboard password; output withheld")

if not webbrowser.open(f"http://127.0.0.1:{LOCAL_PORT}/"):
    print(f"Browser launch failed; open http://127.0.0.1:{LOCAL_PORT}/ manually.")
print("Ops dashboard open at http://127.0.0.1:18795 through the private SSH tunnel.")
print("Dashboard password (paste into the sign-in page):")
print(result.stdout.strip())
print("Close the tunnel later with:")
print(f"  ssh -S {control} -O exit {target}")
