"""The Safety menu's data: every safety feature with its switch, in two scopes, and who may open it.

Who: the owner account (`SAFETY_OWNER_ACCOUNT`) and any account the owner has granted access. Anyone else (any other customer, a signed-out visitor) gets the same
404 as a route that does not exist. A granted account sees and changes only its OWN switches ("mine"); only the owner sees "all" (the default for every account) and
the list of who has access. Changing anything needs the signed-in password again, so a stolen session cannot turn protections off or hand the menu to someone else.
Every change is written to the audit log; the all-users changes and the grants have their own audit actions."""
import os
import time
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.http import JsonResponse
from agentai_platform import safety as sf
from .lifecycle import AccountStore
from .models import Identity
from .services import Denied, audit, rate
from .views import endpoint, customer

MAX_SECONDS = 7 * 24 * 3600
SCOPES = ('mine', 'all')


def _store():
    return AccountStore(connection.settings_dict['NAME'])


def _publish():
    """Write the snapshot the other processes read (agentai_platform/safety.py `export_snapshot`). True when it is written."""
    path = getattr(settings, 'SAFETY_SNAPSHOT_FILE', '')
    if not path:
        return True
    try:
        with _store().connect() as con:
            sf.export_snapshot(con, path)
        return True
    except Exception:
        return False


def _gate(request, owner_only=False):
    """-> (denied response or None, role). role is 'owner' or 'member' (granted by the owner). Everyone else is Denied, which answers 404."""
    denied = customer(request)
    if denied:
        return denied, None
    owner = getattr(settings, 'SAFETY_OWNER_ACCOUNT', '')
    if not owner:
        raise Denied()                                   # no owner configured: nobody, whatever grants exist
    if request.account_id == owner:
        return None, 'owner'
    if not owner_only:
        with _store().connect() as con:
            if sf.has_access(con, request.account_id):
                return None, 'member'
    raise Denied()


def _scope(requested, role):
    """The scope asked for, or None when it is not one. 'all' belongs to the owner alone."""
    if requested not in SCOPES:
        return None
    if requested == 'all' and role != 'owner':
        raise Denied()
    return requested


def _view(account_id, scope, role):
    with _store().connect() as con:
        features = sf.listing_all(con) if scope == 'all' else sf.listing(con, account_id)
    return {'role': role, 'scope': scope, 'scopes': list(SCOPES) if role == 'owner' else ['mine'],
            'groups': [{'key': k, 'title': t} for k, t in sf.GROUPS], 'features': features,
            'off_count': sum(1 for f in features if not f['on'])}


@endpoint(['GET'])
def state(request):
    denied, role = _gate(request)
    if denied:
        return denied
    scope = _scope(request.GET.get('scope', 'mine'), role)
    if scope is None:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    path = getattr(settings, 'SAFETY_SNAPSHOT_FILE', '')
    if role == 'owner' and path and not os.path.exists(path):
        _publish()                                         # first use, or after a restore: the other processes get what the database holds
    return JsonResponse(_view(request.account_id, scope, role))


@endpoint(['POST'], ['password', 'changes', 'minutes', 'scope'], structured=True)
def change(request):
    """`changes` is {feature_key: true|false} (true = safety on). `scope` is 'mine' (default) or 'all' (owner only). `minutes` optionally makes the "off" state expire by itself."""
    denied, role = _gate(request)
    if denied:
        return denied
    rate('safety.change', request.account_id, 60, 600)
    data = request.input
    scope = _scope(data.get('scope', 'mine'), role)
    changes, minutes = data.get('changes'), data.get('minutes')
    if scope is None or not isinstance(changes, dict) or not changes or any(k not in sf.FEATURES or not isinstance(v, bool) for k, v in changes.items()):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes * 60 <= MAX_SECONDS):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    for key, on in changes.items():                       # every change is checked before any is written
        try:
            sf.check_changeable(key, on, scope == 'all')
        except sf.Locked as locked:
            return JsonResponse({'error': 'locked', 'feature': key, 'reason': locked.reason}, status=400)
    if not isinstance(data.get('password'), str) or not request.user.check_password(data['password']):
        return JsonResponse({'error': 'password_required'}, status=403)
    expires = int(time.time()) + minutes * 60 if minutes else None
    target = sf.ALL if scope == 'all' else request.account_id
    with _store().transaction() as con:
        for key, on in changes.items():
            sf.set_feature(con, target, key, on, str(request.user.pk), expires_epoch=expires)
    # The audit row is written even if the audit_log switch is off: a record of the switch itself is the one thing that stays.
    audit(request.user.pk, request.account_id, 'safety', 'safety.change_all' if scope == 'all' else 'safety.change', 'completed', request.request_id)
    if not _publish():                                     # the change is saved, but the other processes still hold the old settings: say so, so it is tried again (switching a protection back ON must reach them)
        return JsonResponse({'error': 'temporarily_unavailable'}, status=503)
    return JsonResponse(_view(request.account_id, scope, role))


# -- who else may open the menu ----------------------------------------------------------------------------------------------------------------------
def _access_view():
    with _store().connect() as con:
        rows = sf.access_list(con)
    emails = {i.account_id: i.user.email for i in Identity.objects.filter(account_id__in=[a for a, _ in rows]).select_related('user')}
    return {'access': [{'email': emails.get(account, ''), 'granted_epoch': epoch} for account, epoch in rows]}


@endpoint(['GET'])
def access(request):
    """Owner only: the accounts that may open the menu."""
    denied, _ = _gate(request, owner_only=True)
    if denied:
        return denied
    return JsonResponse(_access_view())


@endpoint(['POST'], ['password', 'grant', 'revoke'])
def access_change(request):
    """Owner only: `grant` or `revoke` (one, by the account's email). Revoking also drops every switch that account had set for itself."""
    denied, _ = _gate(request, owner_only=True)
    if denied:
        return denied
    rate('safety.access', request.account_id, 30, 600)
    data = request.input
    action = [k for k in ('grant', 'revoke') if data.get(k)]
    if len(action) != 1:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    if not isinstance(data.get('password'), str) or not request.user.check_password(data['password']):
        return JsonResponse({'error': 'password_required'}, status=403)
    user = get_user_model().objects.filter(email__iexact=data[action[0]].strip().lower(), identity__role='customer').first()
    target = Identity.objects.filter(user=user).values_list('account_id', flat=True).first() if user else None
    if not target or target == request.account_id:
        return JsonResponse({'error': 'unknown_account'}, status=400)
    with _store().transaction() as con:
        if action[0] == 'grant':
            sf.grant_access(con, target, str(request.user.pk))
        else:
            sf.revoke_access(con, target)
    audit(request.user.pk, request.account_id, target, 'safety.access_' + action[0], 'completed', request.request_id)
    if not _publish():                                     # revoking also dropped that account's settings
        return JsonResponse({'error': 'temporarily_unavailable'}, status=503)
    return JsonResponse(_access_view())
