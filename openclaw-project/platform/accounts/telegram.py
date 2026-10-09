"""Telegram linking API and the shared webhook ingress.

Link routes require a signed-in customer; the webhook authenticates the
provider secret and never trusts usernames, claimed ids or forwarded text.
Everything fails closed while the bot is unconfigured.
"""
import hmac
import json
import secrets
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from agentai_platform.request_queue import RequestQueue
from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatService
from agentai_platform.security import Principal, NotFound
from agentai_platform.telegram import TelegramService, TelegramBotApi
from .lifecycle import AccountStore
from .services import Denied, rate
from .views import endpoint, customer


def _store():
    return AccountStore(connection.settings_dict['NAME'])


def service():
    store = _store()
    return TelegramService(store, chat=ChatService(store, queue=RequestQueue(store),
                                                   ledger=BudgetLedger(store)),
                           transport=TelegramBotApi(settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_ENABLED else None,
                           bot_username=settings.TELEGRAM_BOT_USERNAME)


def _principal(request):
    return Principal(request.account_id, str(request.user.pk), 'customer')


@endpoint(['POST'])
def link(request):
    denied = customer(request)
    if denied:
        return denied
    if not settings.TELEGRAM_ENABLED:
        if request.content_type == 'application/x-www-form-urlencoded':
            return render(request, 'accounts/telegram_link.html', {'enabled': False})
        return JsonResponse({'error': 'telegram_not_enabled'}, status=503)
    rate('telegram.link', request.account_id, 5, 900)
    try:
        result = service().create_code(_principal(request))
    except NotFound:
        raise Denied()
    if request.content_type == 'application/x-www-form-urlencoded':
        # The bearer code renders once on this page; it never enters a URL or log.
        return render(request, 'accounts/telegram_link.html',
                      {'enabled': True, 'link': result['link'], 'expires_in': result['expires_in']})
    return JsonResponse({'link': result['link'], 'expires_in': result['expires_in']}, status=201)


@endpoint(['POST'], ['chat_id'])
def unlink(request):
    denied = customer(request)
    if denied:
        return denied
    try:
        service().unlink(_principal(request), request.input.get('chat_id') or None)
    except NotFound:
        raise Denied()
    request.form_redirect = '/account/'
    return JsonResponse({'unlinked': True}, status=200)


@endpoint(['GET'])
def bindings(request):
    denied = customer(request)
    if denied:
        return denied
    try:
        return JsonResponse({'bindings': service().bindings(_principal(request))})
    except NotFound:
        raise Denied()


def _secret_ok(request):
    if not settings.TELEGRAM_ENABLED:
        return False
    provided = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    return hmac.compare_digest(provided, settings.TELEGRAM_WEBHOOK_SECRET)


@csrf_exempt
def webhook(request):
    """Provider ingress: no customer cookie, exempt from CSRF because the
    secret header authenticates Telegram. Secret check, dedup, 200-fast."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    if not _secret_ok(request):
        print(json.dumps({'event': 'telegram_webhook', 'category': 'secret_invalid'}), flush=True)
        return JsonResponse({'error': 'unavailable'}, status=403)
    try:
        update = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': True})
    outcome = 'ignored'
    try:
        outcome = service().handle_update(update)
    except ValueError:
        outcome = 'ignored'
    print(json.dumps({'event': 'telegram_webhook', 'category': outcome}), flush=True)
    return JsonResponse({'ok': True})


def overview_context(request):
    """Context block for the account overview page."""
    if not settings.TELEGRAM_ENABLED:
        return {'telegram_enabled': False, 'telegram_bindings': []}
    try:
        bound = service().bindings(_principal(request))
    except Exception:
        bound = []
    return {'telegram_enabled': True, 'telegram_bindings': bound}
