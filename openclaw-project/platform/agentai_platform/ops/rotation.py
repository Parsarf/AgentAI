"""Secret rotation helpers. Each step is ordered so there is never a moment with no working secret.

Provider key: issue new -> store durably -> revoke old (a failed revoke is recorded for retry, never lost).
Webhook secret: add the new secret next to the old (the provider signs with both during its overlap), later drop the old.
Session secret: replace in the app environment file; every signed-in session ends (documented).
"""
import json
import os
from pathlib import Path
import re
import secrets

from agentai_platform.lifecycle.secrets_custody import CustodyError


class RotationError(Exception): pass


def rotate_provider_key(provider_keys, store, tenant, account_id, *, max_budget_usd, duration_days, models, pending_path):
    old = store.provider_key(tenant)
    if old is None: raise RotationError('no key to rotate; issue one first')
    status, body = provider_keys.http('POST', '/key/generate', {'key_alias': tenant, 'max_budget': max_budget_usd, 'duration': f'{duration_days}d',
                                                               'models': models, 'metadata': {'account_id': account_id, 'tenant': tenant, 'rotated': True}})
    new = body.get('key') if isinstance(body, dict) else None
    if status != 200 or not isinstance(new, str): raise RotationError('could not issue the replacement key; the old key is unchanged')
    store.replace_provider_key(tenant, new)
    status, _ = provider_keys.http('POST', '/key/delete', {'keys': [old]})
    if status != 200:
        pending = Path(pending_path)
        try: queue = json.loads(pending.read_text())
        except (OSError, ValueError): queue = []
        queue.append(old); pending.write_text(json.dumps(queue)); os.chmod(pending, 0o600)
        return {'rotated': True, 'old_key_revoked': False}
    return {'rotated': True, 'old_key_revoked': True}


def retry_pending_revocations(provider_keys, pending_path):
    pending = Path(pending_path)
    try: queue = json.loads(pending.read_text())
    except (OSError, ValueError): return 0
    left = [k for k in queue if provider_keys.http('POST', '/key/delete', {'keys': [k]})[0] != 200]
    pending.write_text(json.dumps(left)); return len(queue) - len(left)


def add_webhook_secret(path, new_secret):
    if not re.fullmatch(r'whsec_[A-Za-z0-9]{16,}', new_secret): raise RotationError('not a webhook signing secret')
    path = Path(path); current = [l.strip() for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
    if new_secret in current: return current
    updated = (current + [new_secret])[-2:]   # at most the previous and the new one
    path.write_text('\n'.join(updated) + '\n'); os.chmod(path, 0o600)
    return updated


def drop_old_webhook_secrets(path):
    path = Path(path); lines = [l.strip() for l in path.read_text().splitlines() if l.strip()]
    if not lines: raise RotationError('no secrets to keep')
    path.write_text(lines[-1] + '\n'); os.chmod(path, 0o600)
    return 1


def rotate_session_secret(env_file, key='AGENTAI_SESSION_SECRET'):
    env = Path(env_file); lines = env.read_text().splitlines(); new = secrets.token_urlsafe(64)
    if not any(l.startswith(key + '=') for l in lines): raise RotationError(f'{key} not found')
    env.write_text('\n'.join(f'{key}={new}' if l.startswith(key + '=') else l for l in lines) + '\n')
    return {'rotated': True, 'sessions_invalidated': True, 'restart_required': 'agentai-platform-app'}
