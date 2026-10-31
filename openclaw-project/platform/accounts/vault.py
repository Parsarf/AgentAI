"""Saved logins and cards: add (after the notice is accepted), list (no secrets), delete. Scoped to the signed-in account.

Nothing here ever returns a secret. A saved item is opened only inside an approved fill for a running task (see browse.py)."""
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from agentai_platform import safety as sf, vault
from .lifecycle import AccountStore
from .services import rate
from .views import endpoint, customer


def keyring():
    try:
        return vault.Keyring.from_file(getattr(settings, 'VAULT_KEY_FILE', ''))
    except vault.VaultOff:
        return None


def _store():
    return AccountStore(connection.settings_dict['NAME'])


@endpoint(['GET'])
def items(request):
    denied = customer(request)
    if denied:
        return denied
    with _store().connect() as con:
        listed = vault.list_items(con, request.account_id)
    return JsonResponse({'enabled': keyring() is not None, 'notice_version': vault.DISCLAIMER_VERSION, 'items': listed})


@endpoint(['POST'], ['kind', 'secret', 'site', 'accepted'], structured=True)
def add(request):
    """Keep one login or card. `accepted` is the customer's tick on the notice, sent with every save; without it nothing is stored."""
    denied = customer(request)
    if denied:
        return denied
    rate('vault.add', request.account_id, 20, 600)
    ring = keyring()
    if ring is None:
        return JsonResponse({'error': 'not_set_up'}, status=409)
    data = request.input
    with _store().connect() as con:
        notice = sf.is_on(con, request.account_id, 'vault_notice')       # the account's `vault_notice` switch: off = a save no longer needs the tick (a card security code is never stored either way)
    if (notice and data.get('accepted') is not True) or data.get('kind') not in vault.KINDS or not isinstance(data.get('secret'), dict) or not isinstance(data.get('site', ''), str):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    try:
        with _store().transaction() as con:
            item = vault.add(con, ring, request.account_id, data['kind'], data['secret'], site=data.get('site', ''), accepted=True)
    except vault.VaultError as exc:
        return JsonResponse({'error': 'invalid_request', 'message': str(exc)}, status=400)       # messages are ours and never include what was typed
    return JsonResponse({'item': item})


@endpoint(['POST'], [])
def remove(request, item_id):
    denied = customer(request)
    if denied:
        return denied
    rate('vault.remove', request.account_id, 60, 600)
    with _store().transaction() as con:
        vault.delete(con, request.account_id, item_id)
    return JsonResponse({'ok': True})
