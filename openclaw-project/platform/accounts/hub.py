"""The mail and calendar dashboard (roadmap #D2 to #D4): one inbox and one calendar across every account a person connected. Read-only in this phase.

    GET  /v1/hub                          accounts (state, capabilities, freshness), settings, unread counts, calendars
    POST /v1/hub/refresh                  {"connection_id"?}  make the sync of all accounts, or one, due now
    GET  /v1/hub/pulse                    a mark that changes when anything changed: an open page asks every few seconds and reloads only then
    POST /v1/hub/settings                 {"timezone"?, "allow_images_from"?, "block_images_from"?}
    POST /v1/hub/link                     {"provider"}  begin signing in to a mail and calendar provider; answers with the address to send the customer to
    POST /v1/hub/ask                      {"conversation_id","message","key","looking_at"?}  a message to the assistant from the dashboard, with what is open (ids only)
    GET  /v1/hub/link/callback            where the provider sends the browser back (no session arrives with it): hands the values to the Inbox page in the address fragment
    POST /v1/hub/link/finish              {"state","code"}  the signed-in page finishes the sign-in; the new account then has nothing chosen yet
    GET  /v1/hub/mail/threads             ?label=inbox&accounts=a,b&provider_label=&unread=1&starred=1&attachments=1&person=&after=&before=&q=&cursor=&limit=
    GET  /v1/hub/mail/labels              the providers' own labels or folders, per account
    GET  /v1/hub/mail/thread              ?connection=&id=&images=1     opens the last message (its body is fetched now if it was not yet)
    GET  /v1/hub/mail/message             ?connection=&id=&images=1     opens one message
    GET  /v1/hub/mail/search-older        ?connection=&q=&continuation= mail older than the synced window, searched live; says when the result is partial
    POST /v1/hub/calendars                {"connection_id","calendar_id","selected"?,"colour"?}   the customer's own choices for one calendar
    GET  /v1/hub/events                   ?start=<epoch>&end=<epoch>&accounts=&cancelled=1
    GET  /v1/hub/event                    ?connection=&calendar=&id=
    GET  /v1/hub/events/search            ?q=&accounts=

Ids of threads, messages, calendars and events are the providers' own and can hold any character, so they travel as query values, never in a path.
Nothing here changes anything at a provider. Every answer is scoped to the signed-in person's account; an id of another account's is "not found".
"""
from django.conf import settings as django_settings
from django.http import HttpResponseRedirect, JsonResponse

from agentai_platform.hub import COLOURS, LIST_LABELS
from . import wiring
from .access import guarded
from .services import audit, rate
from .views import customer, endpoint


def _off():
    return JsonResponse({'error': 'feature_off'}, status=503)


def _enter(request, key=None, limit=600):
    """-> (principal, None) or (None, the response to give)."""
    denied = customer(request)
    if denied:
        return None, denied
    if not wiring.hub_on(request.account_id):
        return None, _off()
    if key:
        rate(key, request.account_id, limit, 600)
    return wiring.principal(request), None


def _run(fn):
    def body():
        try:
            return JsonResponse(fn())
        except ValueError:
            return JsonResponse({'error': 'invalid_request'}, status=400)
    return guarded(body)


def _flag(request, name):
    value = request.GET.get(name)
    return None if value in (None, '') else value in ('1', 'true', 'yes')


def _number(request, name):
    value = request.GET.get(name)
    if value in (None, ''):
        return None
    if not value.lstrip('-').isdigit() or len(value) > 12:
        raise ValueError('invalid number')
    return int(value)


def _accounts(request):
    value = request.GET.get('accounts')
    return None if value in (None, '') else [part for part in value.split(',') if part][:50]


@endpoint(['GET'])
def overview(request):
    principal, stop = _enter(request)
    if stop:
        return stop

    def run():
        hub = wiring.hub_service()
        return {'accounts': hub.accounts(principal), 'providers': [{'provider': name, 'label': p['label']} for name, p in wiring.sign_in_providers().items()], 'settings': hub.settings(principal), 'counts': hub.counts(principal), 'calendars': hub.calendars(principal),
                'labels': list(LIST_LABELS), 'colours': list(COLOURS),
                'read_only': not (wiring.switch_on('mail_calendar_writes') and wiring.hub_on(principal.account_id))}      # Phase 6: changes are possible only with the owner's writes switch
    return _run(run)


def _redirect_address():
    return django_settings.PUBLIC_ORIGIN + '/v1/hub/link/callback'


@endpoint(['POST'], ['provider', 'connection', 'add'], structured=True)
def link(request):
    """Begin signing in. Nothing is connected by this: the customer is sent to the provider, which shows what is asked for (reading only) and sends them back.
    With `connection` and `add` (names of the provider's grants, roadmap Phase 6) it asks for more on an account already connected: finishing changes that connection in place."""
    principal, stop = _enter(request, 'hub.link', 20)
    if stop:
        return stop
    provider = wiring.sign_in_providers().get(request.input.get('provider') if isinstance(request.input.get('provider'), str) else '')
    if provider is None:
        return JsonResponse({'error': 'connector_not_configured'}, status=503)
    upgrade, add = request.input.get('connection'), request.input.get('add') or []
    if (upgrade is None) != (not add) or (upgrade is not None and not isinstance(upgrade, str)) or not isinstance(add, list) or len(add) > 5 \
            or any(not isinstance(a, str) or a not in provider['grants'] for a in add):
        return JsonResponse({'error': 'invalid_request'}, status=400)

    def run():
        started = wiring.connector_service().start_link(principal, request.input['provider'], _redirect_address(), upgrade=upgrade)
        return {'authorize_url': provider['address'](_redirect_address(), started['state'], started['challenge'], hint=started.get('identity'), add=tuple(add)),
                'expires_in': started['expires_in']}
    return _run(run)


@endpoint(['GET'])
def link_callback(request):
    """Where the provider sends the customer's browser back. This request arrives FROM ANOTHER SITE, so the browser does not send Lumina's session cookie with it (the cookie
    is SameSite=Strict, on purpose): there is nobody signed in here, and nothing can be finished here. It only hands the two values on to the Inbox page, in the part of the
    address a browser never sends to a server or writes to a log (the fragment). The page then finishes the sign-in itself, from inside Lumina, with the session and a
    CSRF token (`link_finish`). Nothing from the provider is shown; a value of the wrong shape is dropped."""
    from urllib.parse import quote
    state, code = request.GET.get('state', ''), request.GET.get('code', '')
    if request.GET.get('error') == 'access_denied':
        return HttpResponseRedirect('/app/inbox?connect=declined')
    if not state or not code or len(state) > 200 or len(code) > 2000:
        return HttpResponseRedirect('/app/inbox?connect=failed')
    return HttpResponseRedirect('/app/inbox#link-state=' + quote(state, safe='') + '&link-code=' + quote(code, safe=''))


@endpoint(['POST'], ['state', 'code'], structured=True)
def link_finish(request):
    """Finish a sign-in: the signed-in person's own page hands over what the provider sent back. The state is single use and bound to this person; a refused or replayed
    one connects nothing. -> the new connection's id (it has no grants yet: the page asks what may be read)."""
    principal, stop = _enter(request, 'hub.link', 20)
    if stop:
        return stop
    from agentai_platform.connectors import ConnectorError
    from agentai_platform.permissions import NotPermitted
    state, code = request.input.get('state'), request.input.get('code')
    if not isinstance(state, str) or not isinstance(code, str) or not state or not code or len(state) > 200 or len(code) > 2000:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    connectors = wiring.connector_service()
    provider = wiring.sign_in_providers().get(connectors.link_service(principal, state) or '')
    if provider is None:
        return JsonResponse({'error': 'link_failed'}, status=409)
    from agentai_platform.connectors import WrongAccount
    try:
        connection = connectors.finish_link(principal, state, code, _redirect_address(), provider['exchange'], needs_any=provider['needs_any'])
    except WrongAccount:
        return JsonResponse({'error': 'different_account'}, status=409)          # adding permissions: the customer signed in as another account; nothing changed
    except (ConnectorError, NotPermitted):
        return JsonResponse({'error': 'link_failed'}, status=409)
    audit(request.user.pk, request.account_id, connection, 'hub.link', 'completed', request.request_id)
    return JsonResponse({'connection_id': connection}, status=201)


@endpoint(['POST'], ['conversation_id', 'message', 'key', 'looking_at'], structured=True)
def ask(request):
    """A message to the assistant, sent from the Inbox or the Calendar. It is an ordinary message in an ordinary chat (same queue, admission and limits as Chat); what the
    customer has open goes with it as ids the server checked. The assistant reads the content itself with its mail and calendar tools."""
    principal, stop = _enter(request, 'hub.ask', 120)
    if stop:
        return stop
    from agentai_platform.budget import BudgetDenied
    from agentai_platform.chat import denial_category
    from agentai_platform.lifecycle.types import Conflict
    from .chat import service as chat_service
    given = request.input
    message, conversation, key = given.get('message'), given.get('conversation_id'), given.get('key')
    if not all(isinstance(v, str) and v for v in (message, conversation, key)) or len(message) > 16000:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    try:
        looking = wiring.hub_service().looking_at(principal, given.get('looking_at'))
        result = chat_service().send(principal, conversation_id=conversation, message=message, key=key, mode='text', ui='basic', dashboard_context=looking)
        return JsonResponse({'request': result, 'looking_at': looking}, status=202)
    except Conflict:
        return JsonResponse({'error': 'request_conflict'}, status=409)
    except BudgetDenied as error:
        return JsonResponse({'error': 'budget_denied', 'category': denial_category(error)}, status=402)
    except ValueError:
        return JsonResponse({'error': 'invalid_request'}, status=400)


@endpoint(['GET'])
def pulse(request):
    """Has anything changed? An open Inbox or Calendar asks this every few seconds and reloads only when the mark differs."""
    principal, stop = _enter(request, 'hub.pulse', 6000)
    if stop:
        return stop
    return _run(lambda: wiring.hub_service().pulse(principal))


@endpoint(['POST'], ['connection_id'], structured=True)
def refresh(request):
    principal, stop = _enter(request, 'hub.refresh', 60)
    if stop:
        return stop
    return _run(lambda: wiring.hub_service().refresh(principal, request.input.get('connection_id')))


@endpoint(['POST'], ['timezone', 'allow_images_from', 'block_images_from'], structured=True)
def settings(request):
    principal, stop = _enter(request, 'hub.settings', 120)
    if stop:
        return stop
    given = request.input
    return _run(lambda: {'settings': wiring.hub_service().set_settings(principal, **({'timezone': given['timezone']} if 'timezone' in given else {}),
                                                                      allow_images_from=given.get('allow_images_from'), block_images_from=given.get('block_images_from'))})


@endpoint(['GET'])
def threads(request):
    principal, stop = _enter(request, 'hub.read', 3000)
    if stop:
        return stop
    q = request.GET
    return _run(lambda: wiring.hub_service().threads(
        principal, connections=_accounts(request), label=q.get('label') or 'inbox', provider_label=q.get('provider_label') or None, unread=_flag(request, 'unread'),
        starred=_flag(request, 'starred'), attachments=_flag(request, 'attachments'), person=q.get('person') or None, after=_number(request, 'after'),
        before=_number(request, 'before'), query=q.get('q') or None, cursor=q.get('cursor') or None, limit=_number(request, 'limit') or 50))


@endpoint(['GET'])
def labels(request):
    principal, stop = _enter(request, 'hub.read', 3000)
    if stop:
        return stop
    return _run(lambda: {'labels': wiring.hub_service().labels(principal, _accounts(request))})


@endpoint(['GET'])
def thread(request):
    principal, stop = _enter(request, 'hub.open', 1200)
    if stop:
        return stop
    q = request.GET
    return _run(lambda: wiring.hub_service().thread(principal, q.get('connection', ''), q.get('id', ''), images=bool(_flag(request, 'images'))))


@endpoint(['GET'])
def message(request):
    principal, stop = _enter(request, 'hub.open', 1200)
    if stop:
        return stop
    q = request.GET
    return _run(lambda: wiring.hub_service().message(principal, q.get('connection', ''), q.get('id', ''), images=bool(_flag(request, 'images'))))


@endpoint(['GET'])
def search_older(request):
    principal, stop = _enter(request, 'hub.search', 120)
    if stop:
        return stop
    q = request.GET
    return _run(lambda: wiring.hub_service().search_older(principal, q.get('connection', ''), q.get('q', ''), continuation=q.get('continuation') or None))


@endpoint(['POST'], ['connection_id', 'calendar_id', 'selected', 'colour'], structured=True)
def calendars(request):
    principal, stop = _enter(request, 'hub.settings', 120)
    if stop:
        return stop
    given = request.input

    def run():
        if not isinstance(given.get('connection_id'), str) or not isinstance(given.get('calendar_id'), str) or ('selected' in given and not isinstance(given['selected'], bool)):
            raise ValueError('invalid calendar')
        return {'calendars': wiring.hub_service().set_calendar(principal, given['connection_id'], given['calendar_id'], selected=given.get('selected'), colour=given.get('colour'))}
    return _run(run)


@endpoint(['GET'])
def events(request):
    principal, stop = _enter(request, 'hub.read', 3000)
    if stop:
        return stop

    def run():
        start, end = _number(request, 'start'), _number(request, 'end')
        if start is None or end is None:
            raise ValueError('a range is required')
        return wiring.hub_service().events(principal, start, end, connections=_accounts(request), cancelled=bool(_flag(request, 'cancelled')))
    return _run(run)


@endpoint(['GET'])
def event(request):
    principal, stop = _enter(request, 'hub.read', 3000)
    if stop:
        return stop
    q = request.GET
    return _run(lambda: {'event': wiring.hub_service().event(principal, q.get('connection', ''), q.get('calendar', ''), q.get('id', ''))})


@endpoint(['GET'])
def search_events(request):
    principal, stop = _enter(request, 'hub.search', 600)
    if stop:
        return stop
    return _run(lambda: wiring.hub_service().search_events(principal, request.GET.get('q', ''), connections=_accounts(request)))


# ---- drafts (#57): Lumina records only; nothing is created in the mailbox ---------------------------------------------------------------------------
@endpoint(['GET', 'POST'], ['draft', 'connection_id', 'thread_id', 'to', 'cc', 'subject', 'body'], structured=True)
def drafts(request):
    principal, stop = _enter(request, 'hub.draft' if request.method == 'POST' else None, 600)
    if stop:
        return stop
    if request.method == 'GET':
        return _run(lambda: {'drafts': wiring.hub_service().drafts(principal, connections=_accounts(request), thread_id=request.GET.get('thread') or None)})
    given = request.input
    if any(given.get(k) is not None and not isinstance(given[k], str) for k in ('draft', 'connection_id', 'thread_id', 'subject', 'body')) \
            or any(given.get(k) is not None and not isinstance(given[k], list) for k in ('to', 'cc')):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return _run(lambda: {'draft': wiring.hub_service().save_draft(principal, draft_id=given.get('draft'), connection_id=given.get('connection_id'), thread_id=given.get('thread_id'),
                                                                  to=given.get('to'), cc=given.get('cc'), subject=given.get('subject'), body=given.get('body'), origin='customer')})


@endpoint(['POST'], [])
def draft_discard(request, draft_id):
    principal, stop = _enter(request, 'hub.draft', 600)
    if stop:
        return stop
    return _run(lambda: wiring.hub_service().discard_draft(principal, draft_id))


@endpoint(['GET'])
def draft_compose(request, draft_id):
    principal, stop = _enter(request, 'hub.read', 600)
    if stop:
        return stop
    return _run(lambda: wiring.hub_service().compose_link(principal, draft_id))


# ---- attachments (#55): read through the knowledge pipeline, on demand ------------------------------------------------------------------------------
@endpoint(['POST'], ['connection_id', 'message_id', 'attachment_id'], field_limits={'connection_id': 64, 'message_id': 300, 'attachment_id': 700})
def attachment(request):
    principal, stop = _enter(request, 'hub.attachment', 120)
    if stop:
        return stop
    if not wiring.knowledge_on(request.account_id):
        return JsonResponse({'error': 'feature_off', 'message': 'Reading attachments needs the document reader, which is not on.'}, status=503)
    service = wiring.knowledge_service()
    if service is None:
        return JsonResponse({'error': 'feature_off'}, status=503)
    given = request.input
    ref = f"{given.get('connection_id', '')}:{given.get('message_id', '')}:{given.get('attachment_id', '')}"

    def run():
        wiring.hub_service().message(principal, given.get('connection_id', ''), given.get('message_id', ''))      # the message must be open for its attachments to be known
        return {'source': service.add(principal, 'attachment', ref, system=True)}
    return _run(run)


# -- managing calendars from the dashboard (roadmap Phase 6, #59 to #61, #63, #D7) ------------------------------------------------------------------------------
def _writes(request, principal, connection_id):
    """The customer's own change: the writes switch must be on for this provider. -> None or the response to give."""
    service = wiring.connector_service().service_of(principal.account_id, connection_id) if isinstance(connection_id, str) else None
    if service is None:
        return JsonResponse({'error': 'unavailable'}, status=404)
    if not wiring.writes_on(principal.account_id, service):
        return _off()
    return None


def _zone(principal):
    from zoneinfo import ZoneInfo
    name = wiring.hub_service().settings(principal)['timezone'] or 'UTC'
    try:
        return name, ZoneInfo(name)
    except Exception:
        return 'UTC', ZoneInfo('UTC')


EVENT_FIELDS = ('calendar', 'title', 'start', 'end', 'all_day', 'attendees', 'place', 'description', 'notify')


@endpoint(['POST'], ['connection', 'calendar', 'title', 'start', 'end', 'timezone', 'all_day', 'attendees', 'place', 'description', 'repeat', 'notify'], structured=True)
def event_create(request):
    """The customer creates an event themselves: their press is the approval (recorded as theirs, from the Calendar). Sent at once through the action pipeline."""
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    given = request.input
    stop = _writes(request, principal, given.get('connection'))
    if stop:
        return stop
    payload = {k: given[k] for k in EVENT_FIELDS if k in given and given[k] not in (None, '', [])}
    if not payload.get('all_day'):
        payload['timezone'] = given.get('timezone') or _zone(principal)[0]
    if given.get('repeat'):
        payload['recurrence'] = [given['repeat']]
    _, _, actions, _ = wiring.action_services()
    return _run(lambda: {'action': actions.direct(principal, given['connection'], 'event.create', payload, screen='calendar')})


@endpoint(['POST'], ['connection', 'calendar', 'event', 'notify'], structured=True)
def event_cancel(request):
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    given = request.input
    stop = _writes(request, principal, given.get('connection'))
    if stop:
        return stop
    if not all(isinstance(given.get(k), str) and given[k] for k in ('calendar', 'event')):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    payload = {'event': f"{given['calendar']}|{given['event']}", 'notify': bool(given.get('notify', True))}
    _, _, actions, _ = wiring.action_services()
    return _run(lambda: {'action': actions.direct(principal, given['connection'], 'event.delete', payload, screen='calendar')})


@endpoint(['POST'], ['screen'], structured=True)
def action_undo(request, action_id):
    """The customer pressed Undo on a change in the Inbox or the Calendar: its inverse, approved by that press."""
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    screen = request.input.get('screen') or 'calendar'
    _, _, actions, _ = wiring.action_services()
    return _run(lambda: {'action': actions.undo_direct(principal, action_id, screen=screen)})


@endpoint(['POST'])
def action_stop(request, action_id):
    """Stop a change that is still waiting its few seconds ("Undo send"). Nothing reaches the provider."""
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    _, _, actions, _ = wiring.action_services()
    return _run(lambda: {'action': actions.cancel(principal, action_id)})


@endpoint(['GET'])
def free(request):
    """Free time between two days (YYYY-MM-DD, at most 62), in the customer's timezone, for the Calendar's "find a time"."""
    principal, stop = _enter(request, 'hub.read', 600)
    if stop:
        return stop
    from datetime import datetime, timedelta
    name, zone = _zone(principal)
    try:
        start = int(datetime.strptime(request.GET.get('start', ''), '%Y-%m-%d').replace(tzinfo=zone).timestamp())
        end = int((datetime.strptime(request.GET.get('end', ''), '%Y-%m-%d').replace(tzinfo=zone) + timedelta(days=1)).timestamp())
    except ValueError:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    minutes = _number(request, 'minutes') or 30

    def run():
        found = wiring.hub_service().free(principal, start, end, zone, minutes=minutes)
        return {'timezone': name, 'free': [{'start_epoch': a, 'end_epoch': b} for a, b in found['free']], 'settings': found['settings'], 'sources': found['sources']}
    return _run(run)


@endpoint(['POST'], ['start', 'end', 'repeat'], structured=True)
def conflicts(request):
    principal, stop = _enter(request, 'hub.read', 600)
    if stop:
        return stop
    given = request.input
    if not all(isinstance(given.get(k), str) for k in ('start', 'end')) or (given.get('repeat') is not None and not isinstance(given['repeat'], str)):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    name, zone = _zone(principal)
    return _run(lambda: {'timezone': name, **wiring.hub_service().conflicts(principal, given['start'], given['end'], zone, rule=given.get('repeat') or None)})


@endpoint(['GET', 'POST'], ['hours', 'notice_minutes', 'buffer_minutes', 'busy_calendars', 'tentative_busy', 'all_day_busy'], structured=True)
def availability(request):
    principal, stop = _enter(request, 'hub.settings', 120)
    if stop:
        return stop
    if request.method == 'GET':
        return _run(lambda: {'availability': wiring.hub_service().availability(principal)})
    return _run(lambda: {'availability': wiring.hub_service().set_availability(principal, request.input)})
