#!/usr/bin/env python3
"""Open the private Control UI using .env SSH credentials; never print its token."""
import os
import json
import re
import subprocess
import stat
import sys
import tempfile
import webbrowser
from urllib.parse import urlsplit
from pathlib import Path

from dotenv import dotenv_values

repo = Path(__file__).resolve().parents[2]
env_file = repo / "agent/.env"
if stat.S_IMODE(env_file.stat().st_mode) & 0o077:
    raise SystemExit("agent/.env must be private (mode 0600)")
values = dotenv_values(env_file)
user = values.get("OPENCLAW_SSH_USER", "")
if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
    raise SystemExit("Set a valid OPENCLAW_SSH_USER in agent/.env")
if not values.get("OPENCLAW_SSH_PASSWORD"):
    raise SystemExit("Set OPENCLAW_SSH_PASSWORD in agent/.env")
target = user + "@69.48.206.62"

with tempfile.TemporaryDirectory(prefix="openclaw-ui-") as directory:
    askpass = Path(directory) / "askpass"
    askpass.write_text(
        "#!" + sys.executable + "\n"
        "from dotenv import dotenv_values\n"
        "print(dotenv_values(" + repr(str(repo / "agent/.env")) + ")[\"OPENCLAW_SSH_PASSWORD\"])\n"
    )
    askpass.chmod(0o700)
    env = os.environ.copy()
    env.update(SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE="force", DISPLAY="openclaw:0")
    ssh = ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
           "-o", "NumberOfPasswordPrompts=1", "-o", "PreferredAuthentications=password",
           "-o", "PubkeyAuthentication=no"]
    # A private control socket distinguishes our tunnel from another local service.
    control = repo / "openclaw-project/tmp/control-ui-ssh.sock"
    control.parent.mkdir(mode=0o700, exist_ok=True)
    check = subprocess.run(["ssh", "-S", str(control), "-O", "check", target],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check.returncode:
        tunnel = subprocess.run(
            ssh + ["-f", "-N", "-M", "-S", str(control), "-o", "ExitOnForwardFailure=yes",
                   "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
                   "-L", "127.0.0.1:18789:127.0.0.1:18789", target],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=20,
        )
        if tunnel.returncode:
            raise SystemExit("Could not create the private tunnel; check SSH access and local port 18789")
    result = subprocess.run(
        ssh + ["-T", target, "docker exec openclaw-production-openclaw-gateway-1 node dist/index.js dashboard --json"],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, timeout=30,
    )
    if result.returncode:
        raise SystemExit("Could not retrieve the private dashboard link; output withheld")
    try:
        handoff = json.loads(result.stdout[result.stdout.index("{"):])
        browser_url = handoff["browserUrl"]
        parsed = urlsplit(browser_url)
    except (ValueError, KeyError, TypeError):
        raise SystemExit("Native dashboard command returned no browser handoff; output withheld")
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.port != 18789 or not parsed.fragment:
        raise SystemExit("Native dashboard command returned an unexpected handoff; output withheld")
    # Native single-use bootstrap goes directly to the browser; no shared token.
    if not webbrowser.open(browser_url):
        raise SystemExit("Browser launch failed; rerun the helper after choosing a default browser")
    print("Opened the Control UI at http://127.0.0.1:18789 through the private SSH tunnel.")
    print("Use the native pairing confirmation in the browser to sign in this Mac.")
