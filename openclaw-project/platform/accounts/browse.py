"""Browser-agent endpoints: list runs, watch one (steps + screenshots), take over after a hand-off. Scoped to the signed-in account."""
import json
import time
from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.browse.client import BrowseRpc
from .lifecycle import AccountStore
from .services import Denied, rate
from .views import endpoint, customer

LIVE = ('queued', 'running', 'handoff')


def _rpc(request):
    return BrowseRpc(request.account_id, settings.BROWSE_SOCKET)


def _run(request, request_id):
    with AccountStore(connection.settings_dict['NAME']).connect() as con:
        row = con.execute('SELECT * FROM browse_runs WHERE account_id=? AND request_id=?', (request.account_id, request_id)).fetchone()
    if not row:
        raise Denied()
    return dict(row)


def _public(row):
    return {'request_id': row['request_id'], 'goal': row['goal'][:300], 'status': row['status'], 'url': row['url'], 'created_epoch': row['created_epoch']}


@endpoint(['GET'])
def runs(request):
    denied = customer(request)
    if denied:
        return denied
    with AccountStore(connection.settings_dict['NAME']).connect() as con:
        rows = con.execute('SELECT * FROM browse_runs WHERE account_id=? ORDER BY created_epoch DESC LIMIT 30', (request.account_id,)).fetchall()
    return JsonResponse({'runs': [_public(dict(r)) for r in rows]})


@endpoint(['GET'])
def run(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    row = _run(request, request_id)
    since = int(request.GET.get('since', '0')) if request.GET.get('since', '0').isdecimal() else 0
    live, events, takeover = None, None, False
    if row['status'] in LIVE:
        try:
            live = _rpc(request)('poll', request_id=request_id, since=since)          # the service is authoritative while a job is alive
            events, takeover = live['events'], bool(live.get('takeover'))
            row = {**row, 'status': live['state'], 'url': live.get('url') or row['url'], 'answer': live.get('answer') or row['answer'], 'reason': live.get('reason') or row['reason']}
        except CapabilityUnavailable:
            live = None
    if events is None:
        with AccountStore(connection.settings_dict['NAME']).connect() as con:
            events = [{'n': r['n'], 'kind': r['kind'], **json.loads(r['data_json'])} for r in con.execute(
                'SELECT n,kind,data_json FROM browse_steps WHERE account_id=? AND request_id=? AND n>? ORDER BY n LIMIT 200', (request.account_id, request_id, since)).fetchall()]
    pending = json.loads(row['pending_json']) if row.get('pending_json') else None
    return JsonResponse({**_public(row), 'answer': row['answer'], 'reason': row['reason'], 'takeover': takeover, 'pending_action': pending, 'events': events})


@endpoint(['GET'])
def shot(request, request_id, name):
    denied = customer(request)
    if denied:
        return denied
    _run(request, request_id)
    try:
        data = _rpc(request).shot(request_id, name)
    except CapabilityUnavailable:
        raise Denied()
    response = HttpResponse(data, content_type='image/jpeg')
    response['Cache-Control'] = 'private, max-age=300'
    return response


@endpoint(['POST'], ['action', 'x', 'y', 'text'], structured=True)
def control(request, request_id):
    """Takeover: one user action (click at x,y / type / key / scroll). The service only accepts it after the agent handed over."""
    denied = customer(request)
    if denied:
        return denied
    rate('browse.control', request.account_id, 240, 60)
    _run(request, request_id)
    data = request.input
    action, x, y, text = data.get('action'), data.get('x'), data.get('y'), data.get('text')
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if action not in ('click', 'type', 'key', 'scroll') or (action == 'click' and not (num(x) and num(y) and 0 <= x <= 1280 and 0 <= y <= 800)) \
            or (action in ('type', 'key', 'scroll') and not isinstance(text, str)) or (isinstance(text, str) and len(text) > 500):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    try:
        out = _rpc(request)('control', request_id=request_id, action=action, x=x, y=y, text=text)
    except CapabilityUnavailable:
        return JsonResponse({'error': 'not_available'}, status=409)
    return JsonResponse({'ok': bool(out.get('ok')), 'error': out.get('error')}, status=200 if out.get('ok') else 409)


@endpoint(['POST'], [])
def release(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    _run(request, request_id)
    try:
        _rpc(request)('release', request_id=request_id)
    except CapabilityUnavailable:
        pass
    return JsonResponse({'ok': True})
