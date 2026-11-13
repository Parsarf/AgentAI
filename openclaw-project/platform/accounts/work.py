"""The customer's tasks as one picture (agentai_platform/work.py), and the ticket for the push gateway that streams it.

  GET  /v1/work                    every recent task, what needs the customer, and a rev that changes when anything shown changes
  GET  /v1/work/<id>?after=<seq>   one task in full; timeline rows touched since the cursor
  POST /v1/work/ticket             a short-lived ticket for the push gateway (live/push.py). No gateway on this server: 404, and the app polls the two routes above.

The two GET routes are also the fallback when the stream cannot be used: they run the same code the gateway runs, so a tab that polls and a tab that streams agree.
"""
from django.conf import settings
from django.http import JsonResponse
from agentai_platform.live import ticket as live_ticket
from agentai_platform.work import WorkReader
from . import wiring
from .services import Denied, rate
from .views import endpoint, customer


def _reader():
    return WorkReader(wiring.store())


@endpoint(['GET'])
def listing(request):
    denied = customer(request)
    if denied:
        return denied
    out = _reader().listing(wiring.principal(request))
    if request.GET.get('rev') == out['rev']:
        return JsonResponse({'rev': out['rev'], 'unchanged': True})
    return JsonResponse(out)


@endpoint(['GET'])
def detail(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    raw = request.GET.get('after', '0')
    if not raw.isdecimal() or len(raw) > 9:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    out = _reader().detail(wiring.principal(request), request_id, after=int(raw))
    if request.GET.get('rev') == out['task']['rev'] and not out['rows']:
        return JsonResponse({'rev': out['task']['rev'], 'cursor': out['cursor'], 'unchanged': True})
    return JsonResponse(out)


@endpoint(['POST'], [])
def ticket(request):
    denied = customer(request)
    if denied:
        return denied
    rate('work.ticket', request.account_id, 120, 60)
    secret = wiring.live_secret()
    if not secret or not getattr(settings, 'PUSH_PATH', ''):
        raise Denied()                                           # no push gateway on this server: the app keeps to the snapshot routes
    try:
        minted = live_ticket.mint_work(secret, request.account_id, str(request.user.pk))
    except live_ticket.TicketError:
        raise Denied()
    return JsonResponse({'ticket': minted, 'path': settings.PUSH_PATH, 'expires_in': live_ticket.WORK_TTL_SECONDS})
