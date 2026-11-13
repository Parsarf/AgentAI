"""Settings → Memory: what Lumina remembers about the signed-in customer over time, with delete. Scoped to the signed-in account.

Builds the one `LongTermMemory` used by both this page and the tool relay (accounts/management/commands/tool_relay.py). Everything fails closed: if the owner's switch is off, or the
server address or the bank secret is missing or unreadable, the feature is simply unavailable (no error, no partial state). See agentai_platform/longterm_memory.py."""
import os

from django.http import JsonResponse

from agentai_platform import longterm_memory as ltm
from agentai_platform.security import NotFound
from . import wiring
from .services import audit, rate
from .views import customer, endpoint


read_secret_file = wiring.read_private


def build(store=None):
    """The memory service, or None when it is not fully configured. Never raises."""
    return wiring.memory_service(store)


def available(account_id):
    return wiring.memory_on(account_id) and build() is not None


@endpoint(['GET'])
def state(request):
    denied = customer(request)
    if denied:
        return denied
    memory = build() if wiring.memory_on(request.account_id) else None
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
