#!/usr/bin/env python3
"""Activate the customer Telegram ingress (Hermes) on the production VPS.

Reads the bot token from the private local .env (OPENCLAW_TELEGRAM_BOT_TOKEN;
optional OPENCLAW_TELEGRAM_BOT_USERNAME, otherwise fetched via getMe).
Generates the webhook secret server-side, writes the three AGENTAI_TELEGRAM_*
settings into /etc/agentai-platform/accounts.env idempotently, restarts the
app unit, registers the webhook against getlumina.pro and verifies. Secrets
are never printed or logged.
"""
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values

repo = Path(__file__).resolve().parents[2]
env_file = repo / "openclaw-project/.env"
if stat.S_IMODE(env_file.stat().st_mode) & 0o077:
    raise SystemExit("openclaw-project/.env must be private (mode 0600)")
values = dotenv_values(env_file)
pfx = "OPENCLAW_NEW_SSH_" if os.environ.get("OPENCLAW_SERVER", "new") == "new" else "OPENCLAW_SSH_"
ssh_user = values.get(pfx + "USER", "")
if not ssh_user or not values.get(pfx + "PASSWORD"):
    raise SystemExit("Set OPENCLAW_SSH_USER and OPENCLAW_SSH_PASSWORD in openclaw-project/.env")
token = values.get("OPENCLAW_TELEGRAM_BOT_TOKEN", "")
if not token or any(c.isspace() for c in token):
    raise SystemExit("Set OPENCLAW_TELEGRAM_BOT_TOKEN in openclaw-project/.env (from BotFather, no spaces)")
explicit_username = values.get("OPENCLAW_TELEGRAM_BOT_USERNAME", "").lstrip("@")
target = ssh_user + "@" + (values.get(pfx + "HOST") or "69.48.206.62")

remote_script = """
set -e
TOKEN=%(token)s
set -a; . /etc/agentai-platform/accounts.env; set +a
USERNAME=$(python3 - <<'PY'
import json, urllib.request
token = %(token)r
req = urllib.request.Request('https://api.telegram.org/bot' + token + '/getMe')
with urllib.request.urlopen(req, timeout=10) as r:
    payload = json.load(r)
if payload.get('ok') is not True:
    raise SystemExit('getMe rejected the token')
print(payload['result']['username'])
PY
)
SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
# Idempotent: replace any previous Telegram lines, then append fresh ones.
sed -i '/^AGENTAI_TELEGRAM_BOT_TOKEN=/d; /^AGENTAI_TELEGRAM_WEBHOOK_SECRET=/d; /^AGENTAI_TELEGRAM_BOT_USERNAME=/d' /etc/agentai-platform/accounts.env
printf 'AGENTAI_TELEGRAM_BOT_TOKEN=%s\\nAGENTAI_TELEGRAM_WEBHOOK_SECRET=%s\\nAGENTAI_TELEGRAM_BOT_USERNAME=%s\\n' "$TOKEN" "$SECRET" "$USERNAME" >> /etc/agentai-platform/accounts.env
chmod 600 /etc/agentai-platform/accounts.env
systemctl restart agentai-platform-app
sleep 2
systemctl is-active agentai-platform-app
RESP=$(python3 - <<'PY'
import json, urllib.request
token = %(token)r
secret = open('/etc/agentai-platform/accounts.env').read()
import re
secret = re.search(r'AGENTAI_TELEGRAM_WEBHOOK_SECRET=(.+)', secret).group(1).strip()
data = json.dumps({'url': 'https://getlumina.pro/v1/telegram/webhook',
                   'secret_token': secret, 'allowed_updates': ['message']}).encode()
req = urllib.request.Request('https://api.telegram.org/bot' + token + '/setWebhook',
                             data=data, headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=10) as r:
    payload = json.load(r)
print(json.dumps({'ok': payload.get('ok'), 'pending_update_count': payload.get('result', {}).get('pending_update_count')}))
PY
)
echo "setWebhook: $RESP"
curl -s -H "X-Forwarded-Proto: https" http://127.0.0.1:18800/readyz
echo
echo "ACTIVATED for bot: @$USERNAME"
"""

with tempfile.TemporaryDirectory(prefix="openclaw-tg-") as directory:
    askpass = Path(directory) / "askpass"
    askpass.write_text(
        "#!" + sys.executable + "\n"
        "from dotenv import dotenv_values\n"
        "print(dotenv_values(" + repr(str(env_file)) + ")[" + repr(pfx + "PASSWORD") + "])\n"
    )
    askpass.chmod(0o700)
    env = os.environ.copy()
    env.update(SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE="force", DISPLAY="openclaw:0")
    quoted = "'" + token.replace("'", "'\\''") + "'"
    script = remote_script.replace("%(token)s", quoted).replace("%(token)r", repr(token))
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15",
         "-o", "NumberOfPasswordPrompts=1", "-o", "PreferredAuthentications=password",
         "-o", "PubkeyAuthentication=no", "-T", target, "--", "bash -s"],
        input=script, env=env, text=True,
    )
    raise SystemExit(result.returncode)
