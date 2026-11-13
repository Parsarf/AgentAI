"""The side panel in the customer's own Chrome: a mini chat and the run's activity, beside the tab the assistant is working in.

No cookie and no device token: the panel's whole credential is a short-lived ticket (agentai_platform/panel/ticket.py) that the request worker hands to the connected
extension while a run of this conversation goes on. Every request here re-checks, not just the ticket's lifetime: the origin is one of our extensions, the person and conversation
are still the customer's own, and for anything that writes (and for the status) the very computer the ticket names is connected right now with "use my own browser" on.
Sending a message goes through the same ChatService.send as the web chat (budget, steering, limits and denial categories included), labelled as coming from the panel.
Everything returned is plain fields; the extension shows them as text.

The extension also stands on its own: `session` trades the extension's paired-device token for a ticket on a NEW conversation (every time the panel is opened is a fresh session),
wakes the customer's cell, and `send` then starts a task (it steers one only when a run is already going). The device token is checked by the browse service, which alone holds it."""
import json
import re
from functools import wraps
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.budget import BudgetDenied
from agentai_platform.chat import denial_category
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.panel import ticket as panel_ticket
from agentai_platform.security import Principal, NotFound
from .chat import prewarm, service
from . import wiring
from .services import Limited, rate

REQUEST_ID = re.compile(r'^[a-f0-9]{32}$')
KEY = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
MAX_BODY = 80_000      # a message (16,000) plus the page text (20,000), the selection (4,000) and the tab list that may come with it
EVENT_FIELDS = ('summary', 'category', 'status', 'tool')


def _fail(error, status):
    return JsonResponse({'error': error}, status=status)


def _cors(response, origin):
    response['Access-Control-Allow-Origin'] = origin
    response['Vary'] = 'Origin'
    response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
    response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response['Access-Control-Max-Age'] = '600'
    return response


def _computer_ok(claims):
    """The one computer the ticket names is connected right now and the customer has "use my own browser" on. -> True / False; CapabilityUnavailable when the service is away."""
    state = wiring.browse_rpc(claims['account'])('device_list')
    return bool(state.get('allowed') and state.get('use') and any(d.get('device_id') == claims['device'] and d.get('connected') for d in state.get('devices') or []))


def panel_endpoint(methods, *, writes=False, status=False):
    """Origin, ticket, ownership and rate checks in one place. The view receives (request, claims, principal). `writes`/`status` also require the computer to be connected."""
    def decorate(fn):
        @csrf_exempt
        @wraps(fn)
        def view(request):
            if not wiring.panel_secret():
                return _fail('unavailable', 404)                                    # no key or no extension origin configured: the feature is off
            origin = request.headers.get('Origin', '')
            if origin not in settings.PANEL_ORIGINS:
                return _fail('origin_not_allowed', 403)
            if request.method == 'OPTIONS':
                response = JsonResponse({}, status=204)
                return _cors(response, origin)
            if request.method not in methods:
                return _cors(_fail('method_not_allowed', 405), origin)
            try:
                rate('panel.ip', request.client_ip, 600, 60)                       # a flood of forged tickets from one address
                header = request.headers.get('Authorization', '')
                claims = panel_ticket.verify(wiring.panel_secret(), header[6:] if header.startswith('Panel ') else '')
                principal = Principal(claims['account'], claims['actor'], 'customer')
                rate('panel.write' if writes else 'panel.read', claims['account'], 30 if writes else 240, 60)
                service().conversation(principal, claims['conversation'])           # still this person's own conversation, member still active
                if writes or status:
                    if not _computer_ok(claims):
                        return _cors(_fail('browser_off', 409), origin)
                response = fn(request, claims, principal)
            except panel_ticket.TicketError:
                response = _fail('ticket', 401)
            except NotFound:
                response = _fail('unavailable', 404)
            except Limited:
                response = JsonResponse({'error': 'rate_limited'}, status=429, headers={'Retry-After': '60'})
            except CapabilityUnavailable:
                response = _fail('unavailable_now', 503)
            return _cors(response, origin)
        return view
    return decorate


TARGETS = ('new_tab', 'this_tab', 'tab')
MODES = ('auto', 'browse', 'text')
GRANT = re.compile(r'^[a-z0-9]{1,24}$')
TAB_TEXT, TABS_TEXT_TOTAL = 6000, 24000       # the text of one extra tab, and of all the tabs together (the page the customer is on has its own, larger limit)


def _text(value, limit):
    return value[:limit] if isinstance(value, str) and '\x00' not in value else None


def clean_context(raw):
    """What the extension saw in the browser, checked and cut down: a target, at most eight tabs (title, address, and a grant name for one the customer allowed), the text they
    selected and the text of their page. -> a clean dict, {} for nothing, or None when the shape is wrong. Sizes are capped here; the driver quotes it all as untrusted data."""
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - {'target', 'tabs', 'selection', 'page'}:
        return None
    out = {}
    if 'target' in raw:
        if raw['target'] not in TARGETS:
            return None
        out['target'] = raw['target']
    if 'tabs' in raw:
        if not isinstance(raw['tabs'], list) or len(raw['tabs']) > 8:
            return None
        tabs = []
        for tab in raw['tabs']:
            if not isinstance(tab, dict) or set(tab) - {'title', 'url', 'grant', 'text'}:
                return None
            title, url = _text(tab.get('title', ''), 200), _text(tab.get('url', ''), 2000)
            grant = tab.get('grant')
            body = _text(tab.get('text', ''), TAB_TEXT)
            if title is None or url is None or body is None or (grant is not None and not (isinstance(grant, str) and GRANT.fullmatch(grant))):
                return None
            tabs.append({'title': title, 'url': url, **({'grant': grant} if grant else {}), **({'text': body} if body.strip() else {})})
        if sum(len(t.get('text', '')) for t in tabs) > TABS_TEXT_TOTAL:
            return None
        out['tabs'] = tabs
    for key, limit in (('selection', 4000), ('page', 20000)):
        if key in raw:
            text = _text(raw[key], limit)
            if text is None:
                return None
            if text.strip():
                out[key] = text
    return out


def _cell_state(account):
    """Is this customer's assistant ready to work? 'ready' | 'waking' | 'asleep' | 'unknown'. For the panel's status line only."""
    store = wiring.store()
    with store.connect() as con:
        cell = con.execute('SELECT observed_state FROM lifecycle_cells WHERE account_id=?', (account,)).fetchone()
        starting = con.execute("SELECT 1 FROM operations WHERE account_id=? AND kind='start' AND state IN ('pending','running','uncertain')", (account,)).fetchone()
    if cell is None:
        return 'unknown'
    if cell['observed_state'] == 'running':
        return 'ready'
    return 'waking' if starting else 'asleep'


def _customer(account):
    """The person this account's computer belongs to: its active customer. A device is paired by the signed-in customer, so this is who the panel acts as."""
    store = wiring.store()
    with store.connect() as con:
        row = con.execute("""SELECT m.actor_id FROM memberships m JOIN accounts a ON a.id=m.account_id
            WHERE m.account_id=? AND m.role='customer' AND m.status='active' AND a.status='active' ORDER BY m.actor_id LIMIT 1""", (account,)).fetchone()
    return row['actor_id'] if row else None


@csrf_exempt
def session(request):
    """Start a panel session from the extension's own sign-in (its device token): a NEW conversation (or, with `conversation`, a fresh ticket for one made earlier), the assistant
    woken up, and the ticket the other panel calls use. Same gate as every panel call: the feature is on, the origin is one of our extensions, and the computer is connected."""
    if not wiring.panel_secret():
        return _fail('unavailable', 404)
    origin = request.headers.get('Origin', '')
    if origin not in settings.PANEL_ORIGINS:
        return _fail('origin_not_allowed', 403)
    if request.method == 'OPTIONS':
        return _cors(JsonResponse({}, status=204), origin)
    if request.method != 'POST':
        return _cors(_fail('method_not_allowed', 405), origin)
    try:
        rate('panel.ip', request.client_ip, 600, 60)
        data = _body(request)
        header = request.headers.get('Authorization', '')
        token = header[7:] if header.startswith('Device ') else ''
        if data is None or set(data) - {'conversation'} or not token:
            return _cors(_fail('invalid_request', 400), origin)
        conversation = data.get('conversation')
        if conversation is not None and not (isinstance(conversation, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', conversation)):
            return _cors(_fail('invalid_request', 400), origin)
        who = wiring.browse_rpc('')('device_auth', token=token)
        if not who.get('ok'):
            return _cors(_fail('device', 401), origin)
        account, device = who['account'], who['device_id']
        if not who.get('allowed'):
            return _cors(_fail('unavailable', 404), origin)
        if not who.get('connected'):
            return _cors(_fail('browser_off', 409), origin)
        rate('panel.session', account, 40, 600)
        actor = _customer(account)
        if not actor:
            return _cors(_fail('unavailable', 404), origin)
        principal = Principal(account, actor, 'customer')
        s = service()
        if conversation is None:
            projects = s.projects(principal)
            if not projects:
                return _cors(_fail('unavailable', 404), origin)
            created = s.create_conversation(principal, projects[0]['id'])
            conversation = created['id']
            try:
                s.rename_conversation(principal, conversation, 'Browser extension')
            except Exception:
                pass                                                                # the title is a courtesy
        else:
            s.conversation(principal, conversation)                                  # theirs and still there, or NotFound
        if not who.get('use'):
            wiring.browse_rpc(account)('device_use', on=True)        # using the extension is the customer saying "use my own browser"
        prewarm(account)                                                             # the assistant starts waking now, not when the first message is sent
        ticket = panel_ticket.mint(wiring.panel_secret(), account, actor, conversation, device)
        response = JsonResponse({'ticket': ticket, 'conversation': conversation, 'expires_in': panel_ticket.TTL_SECONDS, 'cell': _cell_state(account)})
    except Limited:
        response = JsonResponse({'error': 'rate_limited'}, status=429, headers={'Retry-After': '60'})
    except NotFound:
        response = _fail('unavailable', 404)
    except Conflict:
        response = _fail('request_conflict', 409)
    except panel_ticket.TicketError:
        response = _fail('unavailable', 404)
    except CapabilityUnavailable:
        response = _fail('unavailable_now', 503)
    return _cors(response, origin)


def _message(row):
    return {'id': row['id'], 'role': row['provenance'], 'text': row['content'], 'surface': row['surface'], 'at': row['created_at']}


@panel_endpoint(['GET'], status=True)
def state(request, claims, principal):
    view = service().panel_view(principal, claims['conversation'])
    latest = view['request']
    request_view = {'id': latest['id'], 'state': latest['state'], 'paused': bool(latest['paused']), 'outcome': latest['outcome']} if latest else None
    if request_view:
        # The same status every Lumina screen shows (agentai_platform/work.py): the side panel words nothing itself. Older panels ignore these fields.
        try:
            from agentai_platform.work import WorkReader
            shown = WorkReader(wiring.store()).detail(principal, latest['id'], after=10 ** 9)['task']
            request_view.update(phase=shown['phase'], label=shown['label'], tone=shown['tone'], note=shown['note'][:300], attention=shown['attention'])
        except Exception:
            pass
    return JsonResponse({'messages': [_message(r) for r in view['messages']], 'live': view['live'], 'cell': _cell_state(claims['account']), 'request': request_view})


@panel_endpoint(['GET'])
def history(request, claims, principal):
    """The customer's recent chats, so a past session can be reopened in the panel (the panel then asks `session` for a ticket on it). Titles and times only: no message text."""
    s = service()
    projects = s.projects(principal)
    if not projects:
        return JsonResponse({'conversations': []})
    rows = s.conversations(principal, projects[0]['id'], limit=15)
    return JsonResponse({'conversations': [{'id': r['id'], 'title': str(r.get('title') or 'New chat')[:90], 'at': r.get('last_activity') or r.get('created_at'), 'current': r['id'] == claims['conversation']} for r in rows]})


@panel_endpoint(['GET'])
def events(request, claims, principal):
    rid, raw_after, raw_limit = request.GET.get('request', ''), request.GET.get('after', '0'), request.GET.get('limit', '100')
    if not REQUEST_ID.fullmatch(rid) or not raw_after.isdecimal() or not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= 100:
        return _fail('invalid_request', 400)
    if service().task(principal, rid).get('conversation_id') != claims['conversation']:
        raise NotFound('unavailable')                                              # only this conversation's runs
    out = wiring.event_service().events(principal, rid, after=int(raw_after), limit=int(raw_limit))
    rows = [{'sequence': e['sequence'], 'kind': e['kind'], 'payload': {k: str(e['payload'][k])[:300] for k in EVENT_FIELDS if isinstance(e['payload'].get(k), (str, int))}} for e in out['events']]
    return JsonResponse({'task_state': out['task_state'], 'events': rows})


def _body(request):
    if request.content_type != 'application/json' or len(request.body) > MAX_BODY:
        return None
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@panel_endpoint(['POST'], writes=True)
def send(request, claims, principal):
    data = _body(request)
    if data is None or set(data) - {'message', 'key', 'mode', 'context'} or not isinstance(data.get('message'), str) or len(data['message']) > 16_000 or not isinstance(data.get('key'), str) or not KEY.fullmatch(data['key']):
        return _fail('invalid_request', 400)
    mode = data.get('mode', 'auto')
    context = clean_context(data.get('context'))
    if mode not in MODES or context is None:
        return _fail('invalid_request', 400)
    s = service()
    live = s.panel_view(principal, claims['conversation'], limit=1)['live']
    try:
        # A run going on takes the message as a steer (the same ChatService.send decides); otherwise this starts a task, and the assistant is woken if it is asleep.
        result = s.send(principal, conversation_id=claims['conversation'], message=data['message'], key=data['key'], mode=mode, surface='panel',
                        panel_context=None if live else (context or None))
    except Conflict:
        return _fail('request_conflict', 409)
    except BudgetDenied as error:
        return JsonResponse({'error': 'budget_denied', 'category': denial_category(error)}, status=402)
    except ValueError:
        return _fail('invalid_request', 400)
    prewarm(claims['account'])
    return JsonResponse({'ok': True, 'request': result.get('id') or result.get('request_id'), 'started': not live}, status=202)


@panel_endpoint(['POST'], writes=True)
def stop(request, claims, principal):
    s = service()
    live = s.panel_view(principal, claims['conversation'], limit=1)['live_request_id']
    if not live:
        return _fail('no_active_run', 409)
    try:
        s.cancel(principal, live)
    except Conflict:
        return _fail('request_conflict', 409)
    return JsonResponse({'ok': True}, status=202)
