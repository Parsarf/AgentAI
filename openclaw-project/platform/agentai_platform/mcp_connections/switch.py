"""The owner's switch for remote MCP connections. OFF until it is turned on, on purpose.

`/var/lib/agentai-platform/mcp-connections.json` (not under /etc/agentai-supervisor: the web app and the tool relay run as `agentai-platform` and cannot read that folder):

    {"mcp_connections": true}                      every account
    {"mcp_connections": ["<account id>", ...]}     only those accounts
    anything else, no line, no file, an unreadable file   nobody

It is read on every request, so turning it off takes effect at once: the Integrations section disappears, the account routes answer "unavailable", and the assistant's remote tools are
withdrawn. Connections and approvals already stored are left alone (nothing is deleted by switching off). The file format and its reader are shared: see rollout.py.
"""
from .. import rollout

DEFAULT_FILE = '/var/lib/agentai-platform/mcp-connections.json'
MAX_BYTES = rollout.MAX_BYTES
KEY = 'mcp_connections'


def read(path):
    return rollout.read(path, max_bytes=MAX_BYTES)


def enabled_for(config, account):
    return rollout.allows(config, KEY, account)


def enabled(path, account):
    return rollout.enabled(path, KEY, account, max_bytes=MAX_BYTES)
