"""Per-account rollout files: the owner's "who gets this feature" lists (stdlib only).

One small JSON file per feature, read on every check so a change takes effect at once, without a restart:

    {"<key>": true}                        every account
    {"<key>": ["<account id>", ...]}       only those accounts
    anything else, no line, no file        nobody

A feature is off until the owner turns it on. Nothing here can raise: an unreadable, oversized, symlinked or malformed file means "nobody".

This module is the one implementation. Each feature keeps its own file, key and public helper (so paths and formats on the server do not change):

    own model keys      model_keys.enabled_for / read_engine        key `own_model_keys`
    remote MCP          mcp_connections.switch.enabled              key `mcp_connections`
    long-term memory    longterm_memory.enabled                     key `long_term_memory`

To add a rollout-gated feature: pick a key, add a `*_FILE` setting, and call `enabled(path, key, account)` (see accounts/wiring.py for where the app does this).

Not the same thing as the two other switch systems, on purpose:
  switches.py   the owner's global feature switches, with preconditions ("facts"), written by the ops dashboard
  safety.py     per-account protections that are ON unless overridden, with expiry, stored in the database
"""
import json
from pathlib import Path

MAX_BYTES = 65536


def read(path, *, max_bytes=MAX_BYTES, follow_symlinks=False) -> dict:
    """The file as a dict, or {} for anything unusable. A symlink is refused unless the caller opts in (the own-model file predates that rule)."""
    try:
        p = Path(path)
        if not follow_symlinks and (p.is_symlink() or not p.is_file() or p.stat().st_size > max_bytes):
            return {}
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def allows(config, key, account) -> bool:
    """Does `config` open feature `key` to `account`? True only for a literal `true` or a list that names the account."""
    value = config.get(key) if isinstance(config, dict) else None
    if value is True:
        return True
    return isinstance(value, list) and isinstance(account, str) and account in value


def enabled(path, key, account, *, max_bytes=MAX_BYTES) -> bool:
    return bool(path) and allows(read(path, max_bytes=max_bytes), key, account)
