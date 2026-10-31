"""Pair the customer's own Chrome: ask for a pairing code, list the computers, revoke one. Scoped to the signed-in account.

The extension trades the code for its own long token over its own connection (agentai_platform/browse/device_gateway.py); no token ever passes through here."""
import re
from django.conf import settings
from django.http import JsonResponse
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.browse.client import BrowseRpc
from .services import Denied, audit, rate
from .views import endpoint, customer

DEVICE_ID = re.compile(r'^[a-f0-9]{16}$')


def _rpc(request):
    return BrowseRpc(request.account_id, settings.BROWSE_SOCKET)


@endpoint(['GET'])
def listing(request):
    denied = customer(request)
    if denied:
        return denied
    try:
        out = _rpc(request)('device_list')
    except CapabilityUnavailable:
        return JsonResponse({'available': False, 'use': False, 'connected': False, 'devices': []})
    return JsonResponse({'available': bool(out.get('allowed')), 'use': bool(out.get('use')), 'connected': bool(out.get('connected')), 'devices': out.get('devices') or []})


@endpoint(['POST'], ['on'], structured=True)
def use(request):
    """The switch at the top of every chat: run my browser tasks in my own Chrome (while its extension is on and connected). A plain true/false; nothing else is accepted."""
    denied = customer(request)
    if denied:
        return denied
    rate('devices.use', request.account_id, 60, 600)
    on = request.input.get('on')
    if not isinstance(on, bool):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    try:
        out = _rpc(request)('device_use', on=on)
    except CapabilityUnavailable:
        return JsonResponse({'error': 'unavailable_now'}, status=503)
    if not out.get('allowed'):
        return JsonResponse({'error': 'not_available'}, status=409)
    audit(request.user.pk, request.account_id, 'devices', 'devices.use.' + ('on' if on else 'off'), 'completed', request.request_id)
    return JsonResponse({'use': bool(out.get('use'))})


@endpoint(['POST'], [])
def pair(request):
    denied = customer(request)
    if denied:
        return denied
    rate('devices.pair', request.account_id, 10, 600)
    try:
        out = _rpc(request)('device_pair')
    except CapabilityUnavailable:
        return JsonResponse({'error': 'unavailable_now'}, status=503)
    if not out.get('allowed'):
        return JsonResponse({'error': 'not_available'}, status=409)
    audit(request.user.pk, request.account_id, 'devices', 'devices.pair', 'completed', request.request_id)
    code = out['code']
    return JsonResponse({'code': code, 'display': code[:4] + '-' + code[4:], 'expires_in': out['expires_in']})


@endpoint(['POST'], [])
def revoke(request, device_id):
    denied = customer(request)
    if denied:
        return denied
    rate('devices.revoke', request.account_id, 30, 600)
    if not DEVICE_ID.fullmatch(device_id):
        raise Denied()
    try:
        out = _rpc(request)('device_revoke', device_id=device_id)
    except CapabilityUnavailable:
        return JsonResponse({'error': 'unavailable_now'}, status=503)
    if not out.get('ok'):
        raise Denied()
    audit(request.user.pk, request.account_id, device_id, 'devices.revoke', 'completed', request.request_id)
    return JsonResponse({'ok': True})
