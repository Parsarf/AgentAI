"""The mail and calendar dashboard (roadmap #D2 to #D4): one inbox and one calendar across every account a person connected. Read-only in this phase.

    GET  /v1/hub                          accounts (state, capabilities, freshness), settings, unread counts, calendars
    POST /v1/hub/refresh                  {"connection_id"?}  make the sync of all accounts, or one, due now
    GET  /v1/hub/pulse                    a mark that changes when anything changed: an open page asks every few seconds and reloads only then
    POST /v1/hub/settings                 {"timezone"?, "allow_images_from"?, "block_images_from"?}
    POST /v1/hub/link                     {"provider","kind"?,"connection"?,"add"?}  begin signing in to a mail and calendar provider (`kind`: which of its sign-ins, where it
                                          has several); with `connection`, for that account: connect it again, or add permissions to it. Answers with the address to go to
    POST /v1/hub/ask                      {"conversation_id","message","key","looking_at"?}  a message to the assistant from the dashboard, with what is open (ids only)
    GET  /v1/hub/link/callback            where the provider sends the browser back (no session arrives with it): hands the values to the Inbox page in the address fragment
    POST /v1/hub/link/finish              {"state","code"}  the signed-in page finishes the sign-in; the new account then has nothing chosen yet. A sign-in that connects
                                          nothing answers 409 with `reason` (connectors.LINK_REASONS) and, when the provider gave one, its own `reference` number
    GET  /v1/hub/mail/threads             ?label=inbox&accounts=a,b&provider_label=&unread=1&starred=1&attachments=1&person=&after=&before=&q=&cursor=&limit=
    GET  /v1/hub/mail/labels              the providers' own labels or folders, per account
    GET  /v1/hub/mail/thread              ?connection=&id=&images=1     opens the last message (its body is fetched now if it was not yet)
    GET  /v1/hub/mail/message             ?connection=&id=&images=1     opens one message
    GET  /v1/hub/mail/frame               ?connection=&id=&images=1     the page a message is shown in (HTML with its own content policy; framed only by Lumina)
    GET  /v1/hub/mail/file                ?connection=&message=&attachment=&inline=1   one attachment: a download, or a picture to show (never kept by Lumina)
    GET  /v1/hub/mail/people              ?q=                            people the customer's own mail is with, for suggestions while a recipient is typed
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
from agentai_platform.security import NotFound
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
        return {'accounts': hub.accounts(principal), 'providers': [{'provider': name, 'label': p['label'], 'kinds': list(p.get('kinds') or ())} for name, p in wiring.sign_in_providers().items()], 'settings': hub.settings(principal), 'counts': hub.counts(principal), 'calendars': hub.calendars(principal),
                'labels': list(LIST_LABELS), 'colours': list(COLOURS),
                'read_only': not (wiring.switch_on('mail_calendar_writes') and wiring.hub_on(principal.account_id)),
                'feeds': _feeds_on()}      # Phase 6: changes are possible only with the owner's writes switch
    return _run(run)


LINK_CODE_MAX = 3600           # an authorization code: Google's are about 70 characters, Microsoft's for work accounts well over 1,000


def _redirect_address():
    return django_settings.PUBLIC_ORIGIN + '/v1/hub/link/callback'


@endpoint(['POST'], ['provider', 'connection', 'add', 'kind'], structured=True)
def link(request):
    """Begin signing in. Nothing is connected by this: the customer is sent to the provider, which shows what is asked for (reading only) and sends them back.
    `kind` picks which of the provider's sign-ins to use, where it has several (a personal or a work account). With `connection` the sign-in is for an account already
    connected, and finishing changes that connection in place: `add` (names of the provider's grants, roadmap Phase 6) asks for more on it; without `add` it connects it
    again (its access ended), asking for what it held."""
    principal, stop = _enter(request, 'hub.link', 20)
    if stop:
        return stop
    provider = wiring.sign_in_providers().get(request.input.get('provider') if isinstance(request.input.get('provider'), str) else '')
    if provider is None:
        return JsonResponse({'error': 'connector_not_configured'}, status=503)
    upgrade, add, kind = request.input.get('connection'), request.input.get('add') or [], request.input.get('kind')
    if (add and upgrade is None) or (upgrade is not None and not isinstance(upgrade, str)) or not isinstance(add, list) or len(add) > 5 \
            or any(not isinstance(a, str) or a not in provider['grants'] for a in add) or (kind is not None and kind not in {k['id'] for k in provider['kinds']}):
        return JsonResponse({'error': 'invalid_request'}, status=400)

    def run():
        connectors = wiring.connector_service()
        started = connectors.start_link(principal, request.input['provider'], _redirect_address(), upgrade=upgrade)
        asked = set(add)
        if upgrade is not None:                      # what the connection holds is asked for again, so connecting again (or adding one permission) never takes another away
            held = set(connectors.granted_scopes(principal, upgrade))
            asked |= {name for name, scope in provider['grant_scopes'].items() if scope in held}
        return {'authorize_url': provider['address'](_redirect_address(), started['state'], started['challenge'], hint=started.get('identity'),
                                                     add=tuple(g for g in provider['grants'] if g in asked), kind=None if upgrade is not None else kind),
                'expires_in': started['expires_in']}
    return _run(run)


# What a provider says in the address when it sends the customer back without a code, as the reasons the page has sentences for. Only the code is read; the provider's
# text is never shown or kept.
CALLBACK_REASONS = {'access_denied': 'declined', 'consent_required': 'admin_consent', 'interaction_required': 'interrupted', 'login_required': 'interrupted',
                    'temporarily_unavailable': 'provider_unreachable', 'server_error': 'provider_unreachable', 'invalid_client': 'provider_setup',
                    'unauthorized_client': 'provider_setup', 'invalid_request': 'provider_setup', 'invalid_scope': 'provider_setup', 'unsupported_response_type': 'provider_setup'}


def _note(event, request, **fields):
    """One line for the log about a sign-in that connected nothing: the reason and the provider's own number for it. No address, no code, no token, no provider text."""
    import json
    print(json.dumps({'event': event, 'request_id': str(getattr(request, 'request_id', '')), **{k: v for k, v in fields.items() if v}}), flush=True)


@endpoint(['GET'])
def link_callback(request):
    """Where the provider sends the customer's browser back. This request arrives FROM ANOTHER SITE, so the browser does not send Lumina's session cookie with it (the cookie
    is SameSite=Strict, on purpose): there is nobody signed in here, and nothing can be finished here. It only hands the two values on to the Inbox page, in the part of the
    address a browser never sends to a server or writes to a log (the fragment). The page then finishes the sign-in itself, from inside Lumina, with the session and a
    CSRF token (`link_finish`). Nothing from the provider is shown; a value of the wrong shape is dropped. A refusal comes back as one of the page's own reasons."""
    import re
    from urllib.parse import quote
    state, code, error = request.GET.get('state', ''), request.GET.get('code', ''), request.GET.get('error', '')
    if error:
        described = request.GET.get('error_description', '')
        admin = error in ('consent_required', 'admin_consent_required') or any(n in described for n in ('AADSTS65001', 'AADSTS65004', 'AADSTS90094', 'AADSTS90093'))
        reason = 'admin_consent' if admin and error != 'access_denied' or any(n in described for n in ('AADSTS90094', 'AADSTS90093')) else CALLBACK_REASONS.get(error, 'failed')
        found = re.search(r'AADSTS\d{4,8}', described)
        _note('hub_link_refused', request, reason=reason, error=error[:40] if re.fullmatch(r'[a-z_]{1,40}', error) else 'other', reference=found.group(0) if found else '')
        return HttpResponseRedirect('/app/inbox?connect=' + reason + ('&ref=' + found.group(0) if found else ''))
    if not state or not code or len(state) > 200 or len(code) > LINK_CODE_MAX:
        _note('hub_link_refused', request, reason='failed', error='shape')
        return HttpResponseRedirect('/app/inbox?connect=failed')
    return HttpResponseRedirect('/app/inbox#link-state=' + quote(state, safe='') + '&link-code=' + quote(code, safe=''))


def _feeds_on():
    from agentai_platform.ics_feed import feeds_on
    return feeds_on()


@endpoint(['POST'], ['address', 'name'], structured=True)
def feed_add(request):
    """Add a calendar feed by its address (#D9): read only, shown on the Calendar with no controls. The address is read once to check it is a calendar, then kept like a
    password (it can carry a secret): it is never shown again in full. -> the new connection's id; its first read starts at once."""
    principal, stop = _enter(request, 'hub.link', 20)
    if stop:
        return stop
    if not _feeds_on():
        return _off()
    from agentai_platform.ics_feed import FeedError
    from agentai_platform.connector_kit import ProviderError
    from agentai_platform.permissions import NotPermitted
    given = request.input
    try:
        connection = wiring.connector_service().add_feed(principal, given.get('address') or '', given.get('name') or '')
    except FeedError as reason:
        return JsonResponse({'error': 'not_a_feed', 'detail': str(reason)[:300]}, status=409)
    except ProviderError:
        return JsonResponse({'error': 'not_a_feed', 'detail': 'That address could not be read right now. Check it, or try again later.'}, status=409)
    except NotPermitted:
        return JsonResponse({'error': 'not_permitted'}, status=403)
    sync = wiring.hub_services()[2]
    try:
        sync.ensure(principal.account_id, connection)
        sync.request(principal.account_id, connection)
    except Exception:
        pass                                                                # the sync service sets it up on its next pass anyway
    audit(request.user.pk, request.account_id, connection, 'hub.feed.add', 'completed', request.request_id)
    return JsonResponse({'connection_id': connection}, status=201)


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
    if not isinstance(state, str) or not isinstance(code, str) or not state or not code or len(state) > 200 or len(code) > LINK_CODE_MAX:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    from agentai_platform.connectors import LinkFailed
    connectors = wiring.connector_service()
    name = connectors.link_service(principal, state) or ''
    provider = wiring.sign_in_providers().get(name)
    if provider is None:                                                             # no open sign-in with this state for this person: used already, or it took too long
        _note('hub_link_failed', request, reason='expired')
        return JsonResponse({'error': 'link_failed', 'reason': 'expired'}, status=409)
    try:
        connection = connectors.finish_link(principal, state, code, _redirect_address(), provider['exchange'], needs_any=provider['needs_any'])
    except LinkFailed as failure:                                                    # nothing was connected, and nothing changed on an account that was being added to
        _note('hub_link_failed', request, provider=name, reason=failure.reason, reference=failure.reference)
        return JsonResponse({'error': 'different_account' if failure.reason == 'different_account' else 'link_failed', 'reason': failure.reason,
                             **({'reference': failure.reference} if failure.reference else {})}, status=409)
    except NotPermitted:
        _note('hub_link_failed', request, provider=name, reason='not_allowed')
        return JsonResponse({'error': 'link_failed', 'reason': 'not_allowed'}, status=409)
    except ConnectorError:
        _note('hub_link_failed', request, provider=name, reason='failed')
        return JsonResponse({'error': 'link_failed', 'reason': 'failed'}, status=409)
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


@endpoint(['POST'], ['timezone', 'allow_images_from', 'block_images_from', 'mail'], structured=True)
def settings(request):
    principal, stop = _enter(request, 'hub.settings', 120)
    if stop:
        return stop
    given = request.input

    def run():
        hub = wiring.hub_service()
        if isinstance(given.get('mail'), dict):
            hub.set_mail_settings(principal, given['mail'])          # Undo send's wait, marking read on open, the customer's own sending limits
        return {'settings': hub.set_settings(principal, **({'timezone': given['timezone']} if 'timezone' in given else {}),
                                             allow_images_from=given.get('allow_images_from'), block_images_from=given.get('block_images_from'))}
    return _run(run)


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
def people(request):
    """Suggestions while a recipient is typed: people the customer's own mail is with."""
    principal, stop = _enter(request, 'hub.read', 3000)
    if stop:
        return stop
    return _run(lambda: {'people': wiring.hub_service().people(principal, request.GET.get('q', ''))})


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
def mail_frame(request):
    """The page a message is shown in, for the frame the Inbox puts it in. It is an HTML page with ITS OWN content policy as a header (nothing runs, nothing is posted,
    remote pictures only when asked for): a page the app writes into a frame itself inherits the app's policy, which allows neither the message's styles nor its
    pictures. It can be framed only by Lumina itself; opened on its own it is the same inert page."""
    from django.http import HttpResponse
    from agentai_platform import hub_html
    principal, stop = _enter(request, 'hub.open', 2400)
    if stop:
        return stop
    q = request.GET

    def body():
        found = wiring.hub_service().frame(principal, q.get('connection', ''), q.get('id', ''), images=bool(_flag(request, 'images')))
        response = HttpResponse(found['document'], content_type='text/html; charset=utf-8')
        response['Content-Security-Policy'] = hub_html.frame_policy(found['images'])
        response['Referrer-Policy'] = 'no-referrer'
        response['Cache-Control'] = 'private, no-store'
        response.frame_same_origin = True                                         # accounts/middleware.py: this one page may be framed by Lumina's own pages
        return response
    return guarded(body)


@endpoint(['GET'])
def mail_file(request):
    """One attachment of a message, read from the provider now and handed to the browser: as a download, or (`inline=1`, pictures only) to be shown, which is how a
    picture carried inside a message reaches its frame and how the Inbox previews a picture. Never kept by Lumina. It is always served as inert: no script in it can
    run from Lumina's address."""
    from urllib.parse import quote
    from django.http import HttpResponse
    principal, stop = _enter(request, 'hub.file', 600)
    if stop:
        return stop
    q = request.GET

    def body():
        found = wiring.hub_service().attachment(principal, q.get('connection', ''), q.get('message', ''), q.get('attachment', ''))
        shown = bool(_flag(request, 'inline')) and found['picture']
        response = HttpResponse(found['data'], content_type=found['type'] if shown else 'application/octet-stream')
        name = ''.join(ch for ch in str(found['name']) if ch >= ' ' and ch not in '"\\/')[:200] or 'attachment'
        plain = name.encode('ascii', 'ignore').decode() or 'attachment'
        response['Content-Disposition'] = f"{'inline' if shown else 'attachment'}; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"
        response['Content-Security-Policy'] = "default-src 'none'; sandbox"
        response['Cache-Control'] = 'private, max-age=300' if shown else 'private, no-store'
        return response
    return guarded(body)


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


# -- managing mail from the dashboard (roadmap Phase 6, #66, #67, #D6) ----------------------------------------------------------------------------------------------
@endpoint(['POST'], ['draft'], structured=True)
def mail_send(request):
    """The customer pressed Send on a draft: their press is the approval. It waits out "Undo send" (their setting, 10 seconds by default; POST /v1/hub/actions/<id>/stop
    stops it in that time), then is sent once. What they should know first (people never written to, a large audience, people outside their organization) was shown in
    the editor and is in the change's preview."""
    principal, stop = _enter(request, 'hub.write', 60)
    if stop:
        return stop
    draft = request.input.get('draft')
    if not isinstance(draft, str) or not draft:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    hub = wiring.hub_service()
    try:
        connection, payload = hub.send_payload(principal, draft)
    except NotFound:
        return JsonResponse({'error': 'not_found'}, status=404)
    except ValueError as reason:                                               # over a sending limit: said in a sentence, nothing sent
        return JsonResponse({'error': 'limit', 'detail': str(reason)[:300]}, status=409)
    stop = _writes(request, principal, connection)
    if stop:
        return stop

    def run():
        _, _, actions, _ = wiring.action_services()
        wait = int(hub.settings(principal)['mail']['undo_send_seconds'])
        action = actions.direct(principal, connection, 'mail.send', payload, screen='inbox', delay_seconds=wait)
        hub.mark_sending(principal, draft, action['id'])
        return {'action': action, 'undo_send_seconds': wait}
    return _run(run)


@endpoint(['GET'])
def mail_check(request):
    """Before Send (#66): what the customer should know about this draft's people, for the editor to show. Nothing is sent."""
    principal, stop = _enter(request, 'hub.read', 600)
    if stop:
        return stop
    try:
        return JsonResponse({'notes': wiring.hub_service().send_payload(principal, request.GET.get('draft', ''))[1].get('notes', [])})
    except NotFound:
        return JsonResponse({'error': 'not_found'}, status=404)
    except ValueError as reason:
        return JsonResponse({'notes': [], 'limit': str(reason)[:300]})


@endpoint(['POST'], ['connection', 'threads', 'op', 'label'], structured=True)
def mail_organize(request):
    """The customer archived, starred, labelled, marked or binned conversations themselves: their press is the approval, sent at once, with Undo (the state of each
    conversation before was recorded). Only conversations of their copy (what they let Lumina read) can be touched."""
    principal, stop = _enter(request, 'hub.write', 240)
    if stop:
        return stop
    given = request.input
    stop = _writes(request, principal, given.get('connection'))
    if stop:
        return stop
    if not isinstance(given.get('threads'), list) or not isinstance(given.get('op'), str):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    hub = wiring.hub_service()

    def run():
        kind, payload = hub.organize_payload(principal, given['connection'], given['threads'], given['op'], label=given.get('label'))
        _, _, actions, _ = wiring.action_services()
        action = actions.direct(principal, given['connection'], kind, payload, screen='inbox')
        try:
            hub.refresh(principal, given['connection'])                        # the copy catches up with the change at once
        except Exception:
            pass
        return {'action': action}
    return _run(run)


SCOPES = ('this', 'following', 'all')
CHANGE_FIELDS = ('title', 'start', 'end', 'timezone', 'all_day', 'attendees', 'place', 'description')


def _scoped(given):
    """(calendar, event, series, scope) from a request about an event; series and scope are for an occurrence of a repeating event, where the scope is always chosen
    by the customer (#62: never guessed). -> the tuple, or the error response."""
    if not all(isinstance(given.get(k), str) and given[k] for k in ('calendar', 'event')):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    series, scope = given.get('series'), given.get('scope')
    if series is not None and (not isinstance(series, str) or not series):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    if series and scope not in SCOPES:
        return JsonResponse({'error': 'scope_required'}, status=400)
    if scope is not None and (not series or scope not in SCOPES):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return given['calendar'], given['event'], series, scope


@endpoint(['POST'], ['connection', 'calendar', 'event', 'series', 'scope', 'title', 'start', 'end', 'timezone', 'all_day', 'attendees', 'place', 'description', 'notify'],
          structured=True)
def event_change(request):
    """The customer changes an event themselves (the inspector, or a drag on the grid): their press is the approval. Who is told is said on the screen before it is sent.
    An occurrence of a repeating event names its series and the scope the customer chose: this one, this and later ones, or all of them."""
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    given = request.input
    stop = _writes(request, principal, given.get('connection'))
    if stop:
        return stop
    found = _scoped(given)
    if isinstance(found, JsonResponse):
        return found
    calendar, event, series, scope = found
    fields = {k: given[k] for k in CHANGE_FIELDS if k in given and given[k] is not None}
    if 'start' in fields and not fields.get('all_day'):
        fields['timezone'] = given.get('timezone') or _zone(principal)[0]
    notify = bool(given.get('notify', True))
    if scope == 'following':
        kind, payload = 'event.update_rest', {'event': f'{calendar}|{event}', 'series': f'{calendar}|{series}', **fields, 'notify': notify}
    elif scope == 'all':
        kind, payload = 'event.update', {'event': f'{calendar}|{series}', **fields, 'notify': notify}
        if 'start' in fields:
            payload['occurrence'] = f'{calendar}|{event}'      # the times given are this occurrence's: the whole series moves by the same amount
    else:
        kind, payload = 'event.update', {'event': f'{calendar}|{event}', **fields, 'notify': notify}
    _, _, actions, _ = wiring.action_services()
    return _run(lambda: {'action': actions.direct(principal, given['connection'], kind, payload, screen='calendar')})


@endpoint(['POST'], ['connection', 'calendar', 'event', 'series', 'scope', 'notify'], structured=True)
def event_cancel(request):
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    given = request.input
    stop = _writes(request, principal, given.get('connection'))
    if stop:
        return stop
    found = _scoped(given)
    if isinstance(found, JsonResponse):
        return found
    calendar, event, series, scope = found
    notify = bool(given.get('notify', True))
    if scope == 'this':
        kind, payload = 'event.cancel_one', {'event': f'{calendar}|{event}', 'notify': notify}
    elif scope == 'following':
        kind, payload = 'event.end_series', {'event': f'{calendar}|{event}', 'series': f'{calendar}|{series}', 'notify': notify}
    elif scope == 'all':
        kind, payload = 'event.delete', {'event': f'{calendar}|{series}', 'notify': notify}
    else:
        kind, payload = 'event.delete', {'event': f'{calendar}|{event}', 'notify': notify}
    _, _, actions, _ = wiring.action_services()
    return _run(lambda: {'action': actions.direct(principal, given['connection'], kind, payload, screen='calendar')})


@endpoint(['POST'], ['connection', 'calendar', 'event', 'series', 'scope', 'response', 'note', 'notify'], structured=True)
def event_respond(request):
    """The customer answers an invitation themselves (Going, Maybe, Not going): their press is the approval. The organizer is told unless notify is false."""
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    given = request.input
    stop = _writes(request, principal, given.get('connection'))
    if stop:
        return stop
    if not isinstance(given.get('response'), str):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    found = _scoped(given)
    if isinstance(found, JsonResponse):
        return found
    calendar, event, series, scope = found
    if scope == 'following':
        return JsonResponse({'error': 'invalid_request'}, status=400)           # an answer is for one occurrence or the whole series
    payload = {'event': f"{calendar}|{series if scope == 'all' else event}", 'response': given['response'], 'notify': bool(given.get('notify', True))}
    if isinstance(given.get('note'), str) and given['note'].strip():
        payload['note'] = given['note'].strip()
    _, _, actions, _ = wiring.action_services()
    return _run(lambda: {'action': actions.direct(principal, given['connection'], 'event.respond', payload, screen='calendar')})


@endpoint(['POST'], ['screen'], structured=True)
def action_undo(request, action_id):
    """The customer pressed Undo on a change in the Inbox or the Calendar: its inverse, approved by that press."""
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    screen = request.input.get('screen') or 'calendar'
    _, _, actions, _ = wiring.action_services()

    def run():
        action = actions.undo_direct(principal, action_id, screen=screen)
        try:
            wiring.hub_service().refresh(principal)                            # the copy catches up with what was put back at once, as it does with the change itself
        except Exception:
            pass
        return {'action': action}
    return _run(run)


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


@endpoint(['GET'])
def proposals(request):
    """Meeting times the assistant found (#65), for the Calendar to draw as suggestions in a range of days (start and end, epoch seconds)."""
    principal, stop = _enter(request, 'hub.read', 600)
    if stop:
        return stop
    start, end = _number(request, 'start'), _number(request, 'end')
    if not start or not end or end <= start or end - start > 62 * 86400:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return _run(lambda: {'proposals': wiring.hub_service().proposals(principal, start, end)})


@endpoint(['POST'], ['state'], structured=True)
def proposal_close(request, proposal_id):
    """The customer picked one of the times (and created the event), or dismissed the suggestion: it is no longer drawn, and a wait for an answer ends."""
    principal, stop = _enter(request, 'hub.write', 120)
    if stop:
        return stop
    state = request.input.get('state')
    if state not in ('picked', 'dismissed'):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return _run(lambda: {'proposal': wiring.hub_service().close_proposal(principal, proposal_id, state)})


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
