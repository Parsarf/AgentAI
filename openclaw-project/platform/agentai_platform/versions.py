"""Which implementation served a request (stdlib only).

Every request is stamped once, when it is first handed to the runtime, with: the release commit of this code, a hash of the assistant's rules and skills, the names of the
tools Lumina offers it, the runtime's version and the model route the request was admitted under. With that, "which code, prompt and tools ran this" has an answer for any
past request, and an evaluation result can be tied to an exact release. Nothing here is a secret and nothing here is customer content.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

_cache = {}


def release() -> str:
    """The commit this code was released from (RELEASE.json beside the tree, written by the release tools), or 'unreleased' for a working copy."""
    if 'release' not in _cache:
        commit = 'unreleased'
        try:
            meta = json.loads((Path(__file__).resolve().parents[1] / 'RELEASE.json').read_text())
            if isinstance(meta.get('commit'), str) and meta['commit']:
                commit = meta['commit'][:40]
        except (OSError, ValueError, AttributeError):
            pass
        _cache['release'] = commit
    return _cache['release']


def rules() -> str:
    """A short hash of what the assistant is told: its core rules and every skill Lumina writes into its workspace."""
    if 'rules' not in _cache:
        try:
            from . import agent_rules
            parts = [agent_rules.CORE] + [f'{name}\n{body}' for name, body in sorted((k, json.dumps(v, sort_keys=True, default=str)) for k, v in agent_rules.skills().items())]
            _cache['rules'] = hashlib.sha256('\n\x00'.join(parts).encode()).hexdigest()[:16]
        except Exception:
            _cache['rules'] = 'unknown'
    return _cache['rules']


def tools() -> str:
    """A short hash of the names of the tools Lumina's own relay offers (the runtime's built-in tools are covered by its version)."""
    if 'tools' not in _cache:
        try:
            from . import tool_relay
            _cache['tools'] = hashlib.sha256('\n'.join(sorted(tool_relay.TOOLS)).encode()).hexdigest()[:16]
        except Exception:
            _cache['tools'] = 'unknown'
    return _cache['tools']


def stamp(*, runtime: str = '', model: str = '') -> dict:
    """The stamp for one request. `runtime` is the gateway's reported version; `model` is the admitted model route ('lumina-default', 'key:...' is reduced to 'own-key')."""
    route = 'own-key' if isinstance(model, str) and model.startswith('key:') else (model if isinstance(model, str) and model else 'default')
    return {'release': release(), 'rules': rules(), 'tools': tools(), 'runtime': str(runtime or 'unverified')[:64], 'model': route[:64]}
