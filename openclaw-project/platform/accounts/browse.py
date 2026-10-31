"""Browser-agent endpoints: list runs, watch one (steps + screenshots), take over after a hand-off. Scoped to the signed-in account."""
import json
import time
from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.browse.client import BrowseRpc
from agentai_platform.browse import sessions as browse_sessions
from agentai_platform import saved, vault
from agentai_platform.live import ticket as live_ticket
from .lifecycle import AccountStore
from .services import Denied, rate
from .views import endpoint, customer
from .vault import keyring

LIVE = ('queued', 'running', 'handoff', 'paused', 'asking')


def _rpc(request):
    return BrowseRpc(request.account_id, settings.BROWSE_SOCKET)


def _run(request, request_id):
    with AccountStore(connection.settings_dict['NAME']).connect() as con:
        row = con.execute('SELECT * FROM browse_runs WHERE account_id=? AND request_id=?', (request.account_id, request_id)).fetchone()
    if not row:
        raise Denied()
    return dict(row)


def _job(request, request_id):
    """(the id the browse service knows the newest session by, how many steps of this request came before it). One session: (request id, 0), as it always was."""
    with AccountStore(connection.settings_dict['NAME']).connect() as con:
        return browse_sessions.latest(con, request.account_id, request_id)


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
    job, base = _job(request, request_id)                 # a later session is a job of its own; its step numbers continue the request's (base = steps before it)
    live, events, takeover, question = None, None, False, None
    if row['status'] in LIVE:
        try:
            live = _rpc(request)('poll', request_id=job, since=max(0, since - base))          # the service is authoritative while a job is alive
            events, takeover, question = [{**e, 'n': e['n'] + base} for e in live['events']], bool(live.get('takeover')), live.get('question')
            row = {**row, 'status': live['state'], 'url': live.get('url') or row['url'], 'answer': live.get('answer') or row['answer'], 'reason': live.get('reason') or row['reason']}
        except CapabilityUnavailable:
            live = None
    if events is None:
        with AccountStore(connection.settings_dict['NAME']).connect() as con:
            events = [{'n': r['n'], 'kind': r['kind'], **json.loads(r['data_json'])} for r in con.execute(
                'SELECT n,kind,data_json FROM browse_steps WHERE account_id=? AND request_id=? AND n>? ORDER BY n LIMIT 200', (request.account_id, request_id, since)).fetchall()]
    pending = json.loads(row['pending_json']) if row.get('pending_json') else None
    return JsonResponse({**_public(row), 'answer': row['answer'], 'reason': row['reason'], 'takeover': takeover, 'pending_action': pending, 'question': question, 'events': events})


@endpoint(['GET'])
def shot(request, request_id, name):
    denied = customer(request)
    if denied:
        return denied
    _run(request, request_id)
    try:
        data = _rpc(request).shot(_job(request, request_id)[0], name)
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
    if action not in ('click', 'type', 'key', 'scroll', 'goto', 'back', 'forward', 'reload') or (action == 'click' and not (num(x) and num(y) and 0 <= x <= 1280 and 0 <= y <= 800)) \
            or (action in ('type', 'key', 'scroll', 'goto') and not isinstance(text, str)) or (isinstance(text, str) and len(text) > (2048 if action == 'goto' else 500)):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    try:
        out = _rpc(request)('control', request_id=_job(request, request_id)[0], action=action, x=x, y=y, text=text)
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
        _rpc(request)('release', request_id=_job(request, request_id)[0])
    except CapabilityUnavailable:
        pass
    return JsonResponse({'ok': True})


def _live_secret():
    path = getattr(settings, 'LIVE_SECRET_FILE', '')
    try:
        return open(path, 'rb').read().strip() if path else b''
    except OSError:
        return b''


@endpoint(['POST'], [])
def pause(request, request_id):
    """Hop in: the agent finishes its current step, then waits while you drive. The status turns 'paused' once it has stopped."""
    denied = customer(request)
    if denied:
        return denied
    rate('browse.control', request.account_id, 240, 60)
    _run(request, request_id)
    try:
        out = _rpc(request)('pause', request_id=_job(request, request_id)[0])
    except CapabilityUnavailable:
        return JsonResponse({'error': 'not_available'}, status=409)
    return JsonResponse({'ok': True, 'state': out.get('state')})


@endpoint(['POST'], [])
def resume(request, request_id):
    """Hand the browser back to Lumina; it carries on from wherever you left the page."""
    denied = customer(request)
    if denied:
        return denied
    rate('browse.control', request.account_id, 240, 60)
    _run(request, request_id)
    try:
        _rpc(request)('resume', request_id=_job(request, request_id)[0])
    except CapabilityUnavailable:
        return JsonResponse({'error': 'not_available'}, status=409)
    return JsonResponse({'ok': True})


@endpoint(['POST'], [])
def live(request, request_id):
    """A short-lived, view-only ticket for the frame gateway (a separate process, so watching never queues behind the site)."""
    denied = customer(request)
    if denied:
        return denied
    rate('browse.live', request.account_id, 60, 60)
    row = _run(request, request_id)
    secret = _live_secret()
    if not secret:
        raise Denied()                                           # live view is not set up on this server: the page falls back to snapshots
    if row['status'] not in LIVE:
        return JsonResponse({'error': 'not_available'}, status=409)
    base = getattr(settings, 'LIVE_PATH', '/v1/live').rstrip('/')
    job = _job(request, request_id)[0]                   # the frame gateway serves the run folder of the job, which for a later session is not the request id
    try:
        minted = live_ticket.mint(secret, request.account_id, job)
    except live_ticket.TicketError:
        raise Denied()
    return JsonResponse({'ticket': minted, 'path': f'{base}/{job}/frame', 'expires_in': live_ticket.TTL_SECONDS})


@endpoint(['POST'], ['question_id', 'option', 'resume', 'remember', 'fields', 'remember_fields'], structured=True)
def answer(request, request_id):
    """The customer's reply to a question the browser stopped to ask: one of the offered options, or Continue after choosing on the page themselves.
    `remember` saves the choice for next time; it is the customer's own tick, never a default."""
    denied = customer(request)
    if denied:
        return denied
    rate('browse.answer', request.account_id, 60, 60)
    _run(request, request_id)
    data = request.input
    qid, option, fields, keep = data.get('question_id'), data.get('option'), data.get('fields'), data.get('remember_fields', [])
    chosen_ways = (option is not None) + bool(data.get('resume')) + (fields is not None)           # exactly one way of answering
    if not isinstance(qid, str) or not 0 < len(qid) <= 40 or not (option is None or (isinstance(option, str) and len(option) <= 8)) \
            or not isinstance(data.get('resume', False), bool) or not isinstance(data.get('remember', False), bool) or chosen_ways != 1 \
            or not (fields is None or (isinstance(fields, dict) and 0 < len(fields) <= 12 and all(isinstance(k, str) and len(k) <= 8 and isinstance(v, str) and len(v) <= 200 for k, v in fields.items()))) \
            or not (isinstance(keep, list) and len(keep) <= 12 and all(isinstance(k, str) and len(k) <= 8 for k in keep)):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    secret = None
    try:
        if option is not None:
            asked = (_rpc(request)('poll', request_id=_job(request, request_id)[0], since=1 << 30).get('question') or {})
            chosen = next((o for o in asked.get('options', []) if o.get('id') == option), None) if asked.get('id') == qid else None
            if chosen and chosen.get('item'):             # the customer said yes to using a saved login or card: open it now, for this one fill
                ring = keyring()
                if ring is None:
                    return JsonResponse({'error': 'not_available'}, status=409)
                try:
                    with AccountStore(connection.settings_dict['NAME']).transaction() as con:
                        _kind, secret = vault.open_item(con, ring, request.account_id, chosen['item'])
                except vault.VaultError:
                    return JsonResponse({'error': 'not_available'}, status=409)
        out = _rpc(request)('answer', request_id=_job(request, request_id)[0], question_id=qid, option=option, resume=bool(data.get('resume')), **({'secret': secret} if secret else {}), **({'fields': fields} if fields is not None else {}))
    except CapabilityUnavailable:
        return JsonResponse({'error': 'not_available'}, status=409)
    finally:
        secret = None
    remembered = None
    if data.get('remember') and out.get('field') and out.get('label'):
        try:
            with AccountStore(connection.settings_dict['NAME']).transaction() as con:
                remembered = saved.remember(con, request.account_id, out['field'], out['label'])
        except ValueError:
            remembered = None
    kept = []
    if fields is not None and keep:                      # the customer ticked "save" on these details: remembered in plain words under the field's own name, deletable in Settings
        keys = out.get('keys') or {}
        for fid in keep:
            if fid in fields and keys.get(fid):
                try:
                    with AccountStore(connection.settings_dict['NAME']).transaction() as con:
                        kept.append(saved.remember(con, request.account_id, keys[fid], fields[fid]))
                except ValueError:
                    pass
    return JsonResponse({'ok': True, 'remembered': remembered, 'saved_fields': kept})


@endpoint(['GET'])
def saved_list(request):
    denied = customer(request)
    if denied:
        return denied
    with AccountStore(connection.settings_dict['NAME']).connect() as con:
        return JsonResponse({'saved': [{'field': k, 'value': v} for k, v in saved.choices(con, request.account_id).items()]})


@endpoint(['POST'], [])
def saved_forget(request, field):
    denied = customer(request)
    if denied:
        return denied
    rate('browse.saved', request.account_id, 60, 60)
    with AccountStore(connection.settings_dict['NAME']).transaction() as con:
        saved.forget(con, request.account_id, field)
    return JsonResponse({'ok': True})
