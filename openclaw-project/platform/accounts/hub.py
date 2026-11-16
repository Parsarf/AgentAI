"""The mail and calendar dashboard (roadmap #D2 to #D4): one inbox and one calendar across every account a person connected. Read-only in this phase.

    GET  /v1/hub                          accounts (state, capabilities, freshness), settings, unread counts, calendars
    POST /v1/hub/refresh                  {"connection_id"?}  make the sync of all accounts, or one, due now
    POST /v1/hub/settings                 {"timezone"?, "allow_images_from"?, "block_images_from"?}
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
from django.http import JsonResponse

from agentai_platform.hub import COLOURS, LIST_LABELS
from . import wiring
from .access import guarded
from .services import rate
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
        return {'accounts': hub.accounts(principal), 'settings': hub.settings(principal), 'counts': hub.counts(principal), 'calendars': hub.calendars(principal),
                'labels': list(LIST_LABELS), 'colours': list(COLOURS), 'read_only': True}
    return _run(run)


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
