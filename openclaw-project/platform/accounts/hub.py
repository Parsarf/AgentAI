"""The mail and calendar dashboard (roadmap #D2 to #D4): one inbox and one calendar across every account a person connected. Read-only in this phase.

    GET  /v1/hub                          accounts (state, capabilities, freshness), settings, unread counts, calendars
    POST /v1/hub/refresh                  {"connection_id"?}  make the sync of all accounts, or one, due now
    POST /v1/hub/settings                 {"timezone"?, "allow_images_from"?, "block_images_from"?}
    POST /v1/hub/link                     {"provider"}  begin signing in to a mail and calendar provider; answers with the address to send the customer to
    GET  /v1/hub/link/callback            where the provider sends the customer back; finishes the sign-in and returns them to the Inbox to choose what may be read
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
                'labels': list(LIST_LABELS), 'colours': list(COLOURS), 'read_only': True}
    return _run(run)


def _redirect_address():
    return django_settings.PUBLIC_ORIGIN + '/v1/hub/link/callback'


@endpoint(['POST'], ['provider'], structured=True)
def link(request):
    """Begin signing in. Nothing is connected by this: the customer is sent to the provider, which shows what is asked for (reading only) and sends them back."""
    principal, stop = _enter(request, 'hub.link', 20)
    if stop:
        return stop
    provider = wiring.sign_in_providers().get(request.input.get('provider') if isinstance(request.input.get('provider'), str) else '')
    if provider is None:
        return JsonResponse({'error': 'connector_not_configured'}, status=503)

    def run():
        started = wiring.connector_service().start_link(principal, request.input['provider'], _redirect_address())
        return {'authorize_url': provider['address'](_redirect_address(), started['state'], started['challenge']), 'expires_in': started['expires_in']}
    return _run(run)


@endpoint(['GET'])
def link_callback(request):
    """Where the provider sends the customer back. Whatever happened, they land on the Inbox: with the new account to choose what it may read, or with a plain note that
    it did not work. Nothing from the provider is shown, and a refused or replayed callback connects nothing."""
    principal, stop = _enter(request, 'hub.link', 20)
    if stop:
        return HttpResponseRedirect('/app/inbox?connect=failed')
    state, code = request.GET.get('state', ''), request.GET.get('code', '')
    if not state or not code or len(state) > 200 or len(code) > 2000:
        return HttpResponseRedirect('/app/inbox?connect=' + ('declined' if request.GET.get('error') == 'access_denied' else 'failed'))
    from agentai_platform.connectors import ConnectorError
    from agentai_platform.permissions import NotPermitted
    connectors = wiring.connector_service()
    provider = wiring.sign_in_providers().get(connectors.link_service(principal, state) or '')
    if provider is None:
        return HttpResponseRedirect('/app/inbox?connect=failed')
    try:
        connection = connectors.finish_link(principal, state, code, _redirect_address(), provider['exchange'], needs_any=provider['needs_any'])
    except (ConnectorError, NotPermitted):
        return HttpResponseRedirect('/app/inbox?connect=failed')
    from urllib.parse import quote
    audit(request.user.pk, request.account_id, connection, 'hub.link', 'completed', request.request_id)
    return HttpResponseRedirect('/app/inbox?connected=' + quote(connection, safe=''))


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
