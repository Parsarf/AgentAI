"""Settings → Memory: what Lumina remembers about the signed-in customer over time, with delete. Scoped to the signed-in account.

Builds the one `LongTermMemory` used by both this page and the tool relay (accounts/management/commands/tool_relay.py). Everything fails closed: if the owner's switch is off, or the
server address or the bank secret is missing or unreadable, the feature is simply unavailable (no error, no partial state). See agentai_platform/longterm_memory.py."""
import os
import stat
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import JsonResponse

from agentai_platform import longterm_memory as ltm
from agentai_platform.security import NotFound
from .lifecycle import AccountStore
from .services import audit, rate
from .views import customer, endpoint


def read_secret_file(path, minimum=0):
    """A private regular file (not a symlink, not group/world readable), stripped. None if it is not usable."""
    try:
        p = Path(path)
        if not path or p.is_symlink() or not p.is_file() or p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            return None
        value = p.read_text().strip()
        return value if len(value) >= minimum else None
    except OSError:
        return None


def build(store=None):
    """The memory service, or None when it is not fully configured. Never raises."""
    try:
        secret = read_secret_file(settings.HINDSIGHT_BANK_SECRET_FILE, 16)
        if not secret or not settings.HINDSIGHT_URL:
            return None
        key = read_secret_file(settings.HINDSIGHT_KEY_FILE) if settings.HINDSIGHT_KEY_FILE else ''
        if key is None:
            return None
        client = ltm.HindsightClient(settings.HINDSIGHT_URL, key)
        return ltm.LongTermMemory(store or AccountStore(connection.settings_dict['NAME']), client, secret.encode(),
                                  enabled=lambda account: ltm.enabled(settings.LTM_SWITCH_FILE, account))
    except (ValueError, OSError):
        return None


def available(account_id):
    return ltm.enabled(settings.LTM_SWITCH_FILE, account_id) and build() is not None


@endpoint(['GET'])
def state(request):
    denied = customer(request)
    if denied:
        return denied
    memory = build() if ltm.enabled(settings.LTM_SWITCH_FILE, request.account_id) else None
    if memory is None:
        return JsonResponse({'available': False, 'memories': []})
    return JsonResponse({'available': True, 'memories': [{'id': e['id'], 'kind': e['kind'], 'content': e['content'], 'created': e['created']} for e in memory.entries(request.account_id)]})


@endpoint(['POST'], [])
def forget(request, entry_id):
    denied = customer(request)
    if denied:
        return denied
    rate('memory.forget', request.account_id, 60, 600)
    memory = build()
    if memory is None:
        return JsonResponse({'error': 'not_available'}, status=409)       # off: entries are kept untouched and can be deleted once it is back
    try:
        memory.forget(request.account_id, entry_id)
        pending = False
    except NotFound:
        return JsonResponse({'error': 'not_found'}, status=404)
    except ltm.MemoryError_:
        pending = True                                                    # already hidden and blanked here; the index removal is retried by the sweep
    audit(request.user.pk, request.account_id, 'memory', 'memory.forget', 'completed', request.request_id)
    return JsonResponse({'ok': True, 'pending': pending})


@endpoint(['POST'], [])
def forget_all(request):
    denied = customer(request)
    if denied:
        return denied
    rate('memory.forget_all', request.account_id, 6, 600)
    memory = build()
    if memory is None:
        return JsonResponse({'error': 'not_available'}, status=409)
    try:
        memory.forget_all(request.account_id)
        pending = False
    except ltm.MemoryError_:
        pending = True
    audit(request.user.pk, request.account_id, 'memory', 'memory.forget_all', 'completed', request.request_id)
    return JsonResponse({'ok': True, 'pending': pending})
