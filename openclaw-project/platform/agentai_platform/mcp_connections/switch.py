"""The owner's switch for remote MCP connections. OFF until it is turned on, on purpose.

`/var/lib/agentai-platform/mcp-connections.json` (not under /etc/agentai-supervisor: the web app and the tool relay run as `agentai-platform` and cannot read that folder):

    {"mcp_connections": true}                      every account
    {"mcp_connections": ["<account id>", ...]}     only those accounts
    anything else, no line, no file, an unreadable file   nobody

It is read on every request, so turning it off takes effect at once: the Integrations section disappears, the account routes answer "unavailable", and the assistant's remote tools are
withdrawn. Connections and approvals already stored are left alone (nothing is deleted by switching off). Same shape as the own-model switch (model_keys.py).
"""
import json
from pathlib import Path

DEFAULT_FILE = '/var/lib/agentai-platform/mcp-connections.json'
MAX_BYTES = 65536


def read(path):
    try:
        p = Path(path)
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_BYTES:
            return {}
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def enabled_for(config, account):
    value = config.get('mcp_connections') if isinstance(config, dict) else None
    if value is True:
        return True
    return isinstance(value, list) and isinstance(account, str) and account in value


def enabled(path, account):
    return bool(path) and enabled_for(read(path), account)
