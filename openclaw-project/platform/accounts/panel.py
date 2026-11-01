"""The side panel in the customer's own Chrome: a mini chat and the run's activity, beside the tab the assistant is working in.

No cookie and no device token: the panel's whole credential is a short-lived ticket (agentai_platform/panel/ticket.py) that the request worker hands to the connected
extension while a run of this conversation goes on. Every request here re-checks, not just the ticket's lifetime: the origin is one of our extensions, the person and conversation
are still the customer's own, and for anything that writes (and for the status) the very computer the ticket names is connected right now with "use my own browser" on.
Sending a message goes through the same ChatService.send as the web chat (budget, steering, limits and denial categories included), labelled as coming from the panel.
Everything returned is plain fields; the extension shows them as text."""
import json
import re
from functools import wraps
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.browse.client import BrowseRpc
from agentai_platform.budget import BudgetDenied
from agentai_platform.chat import denial_category
from agentai_platform.events import EventService
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.panel import ticket as panel_ticket
from agentai_platform.panel.offer import read_secret
from agentai_platform.security import Principal, NotFound
from .chat import service
from .lifecycle import AccountStore
from .services import Limited, rate

REQUEST_ID = re.compile(r'^[a-f0-9]{32}$')
KEY = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
MAX_BODY = 20_000
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
    state = BrowseRpc(claims['account'], settings.BROWSE_SOCKET)('device_list')
    return bool(state.get('allowed') and state.get('use') and any(d.get('device_id') == claims['device'] and d.get('connected') for d in state.get('devices') or []))


def panel_endpoint(methods, *, writes=False, status=False):
    """Origin, ticket, ownership and rate checks in one place. The view receives (request, claims, principal). `writes`/`status` also require the computer to be connected."""
    def decorate(fn):
        @csrf_exempt
        @wraps(fn)
        def view(request):
            if not settings.PANEL_ORIGINS or not read_secret(settings.PANEL_SECRET_FILE):
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
                claims = panel_ticket.verify(read_secret(settings.PANEL_SECRET_FILE), header[6:] if header.startswith('Panel ') else '')
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


def _message(row):
    return {'id': row['id'], 'role': row['provenance'], 'text': row['content'], 'surface': row['surface'], 'at': row['created_at']}


@panel_endpoint(['GET'], status=True)
def state(request, claims, principal):
    view = service().panel_view(principal, claims['conversation'])
    latest = view['request']
    return JsonResponse({'messages': [_message(r) for r in view['messages']], 'live': view['live'],
                         'request': {'id': latest['id'], 'state': latest['state'], 'paused': bool(latest['paused']), 'outcome': latest['outcome']} if latest else None})


@panel_endpoint(['GET'])
def events(request, claims, principal):
    rid, raw_after, raw_limit = request.GET.get('request', ''), request.GET.get('after', '0'), request.GET.get('limit', '100')
    if not REQUEST_ID.fullmatch(rid) or not raw_after.isdecimal() or not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= 100:
        return _fail('invalid_request', 400)
    if service().task(principal, rid).get('conversation_id') != claims['conversation']:
        raise NotFound('unavailable')                                              # only this conversation's runs
    out = EventService(AccountStore(connection.settings_dict['NAME'])).events(principal, rid, after=int(raw_after), limit=int(raw_limit))
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
    if data is None or set(data) - {'message', 'key'} or not isinstance(data.get('message'), str) or not isinstance(data.get('key'), str) or not KEY.fullmatch(data['key']):
        return _fail('invalid_request', 400)
    s = service()
    if not s.panel_view(principal, claims['conversation'], limit=1)['live']:
        return _fail('no_active_run', 409)                                         # the panel steers a running task; it does not start new ones
    try:
        result = s.send(principal, conversation_id=claims['conversation'], message=data['message'], key=data['key'], mode='auto', surface='panel')
    except Conflict:
        return _fail('request_conflict', 409)
    except BudgetDenied as error:
        return JsonResponse({'error': 'budget_denied', 'category': denial_category(error)}, status=402)
    except ValueError:
        return _fail('invalid_request', 400)
    return JsonResponse({'ok': True, 'request': result.get('id') or result.get('request_id')}, status=202)


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
