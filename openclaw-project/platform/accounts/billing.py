"""Billing routes: page/JSON overview, hosted checkout and portal (owner switch), signed webhook ingress.

Access is never granted here: the success redirect only returns the customer to this page, and
the webhook worker applies verified provider state. The webhook route has no cookie and is exempt
from CSRF because the signature over the raw body authenticates Stripe.
"""
import json
from datetime import datetime, timezone
from django.conf import settings
from django.db import connection, DatabaseError
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from agentai_platform.billing import (BillingService, StripeHttp, BillingNotConfigured, BillingConflict, BillingError,
                                      PayloadTooLarge, SignatureInvalid, ProviderUnavailable, ProviderRejected, plan_from_plan_json, MAX_BODY)
from agentai_platform.budget import BudgetLedger, BudgetDenied
from agentai_platform.security import NotFound, Principal
from agentai_platform.switches import SwitchStore
from .lifecycle import AccountStore
from .services import Denied, rate, Limited
from .views import endpoint, customer


def _read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ''


def switch_on():
    return SwitchStore(settings.SWITCHES_FILE or None, facts_path=settings.SWITCH_FACTS_FILE or None).is_on('billing_checkout')


def open_access_on():
    return SwitchStore(settings.SWITCHES_FILE or None, facts_path=settings.SWITCH_FACTS_FILE or None).is_on('open_access')


def access_mode():
    """paid_required wins over open: turning payments on is what ends free access."""
    if switch_on(): return 'paid_required'
    return 'open' if open_access_on() else 'invite_only'


def webhook_secrets():
    return [line.strip() for line in _read(settings.BILLING_WEBHOOK_SECRET_FILE).splitlines() if line.strip().startswith('whsec_')] \
        if settings.BILLING_WEBHOOK_SECRET_FILE else []


def service():
    """Built per request so a rotated key or secret takes effect without a restart."""
    plans = []
    if settings.BILLING_PLAN_FILE:
        try:
            # Free access needs only the plan file; the Stripe price id matters once payments are configured.
            plans = [plan_from_plan_json(json.loads(_read(settings.BILLING_PLAN_FILE)), settings.BILLING_PRICE_ID or 'price_unconfigured')]
        except (ValueError, KeyError):
            plans = []
    api = None
    if settings.BILLING_SECRET_KEY_FILE and settings.BILLING_API_VERSION:
        api = StripeHttp(lambda: _read(settings.BILLING_SECRET_KEY_FILE), settings.BILLING_API_VERSION, allow_live=settings.BILLING_ALLOW_LIVE)
    return BillingService(AccountStore(connection.settings_dict['NAME']), api, plans, webhook_secrets=webhook_secrets(),
                          public_origin=settings.BILLING_PUBLIC_ORIGIN, allow_live=settings.BILLING_ALLOW_LIVE)


def _principal(request):
    return Principal(request.account_id, str(request.user.pk), 'customer')


def _usage(principal):
    try:
        return BudgetLedger(AccountStore(connection.settings_dict['NAME'])).summary(principal)
    except (BudgetDenied, NotFound):
        return None


def _dollars(micro):
    whole, fraction = divmod(int(micro or 0), 1_000_000)
    return f'{whole}.{f"{fraction:06d}".rstrip("0").ljust(2, "0")}'


def _when(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%B %d, %Y').replace(' 0', ' ') if epoch else ''


@endpoint(['GET'])
def billing(request, page=False):
    denied = customer(request)
    if denied:
        return denied
    principal = _principal(request)
    try:
        view = service().overview(principal, usage=_usage(principal), mode=access_mode())
    except NotFound:
        raise Denied()
    view['checkout_available'] = switch_on() and view['can_subscribe']
    view['manage_available'] = switch_on() and view['can_manage']
    view['period_end_text'] = _when(view['period_end'])
    view['grace_ends_text'] = _when(view['grace_ends'])
    for invoice in view['invoices']:
        invoice['created_text'] = _when(invoice['created'])
        invoice['paid_usd'] = _dollars(invoice['amount_paid'] * 10_000)   # cents -> micro-dollars
    if page:
        usage = view['usage'] or {}
        return render(request, 'accounts/billing.html', {'v': view, 'nav': True, 'nav_here': 'billing', 'email': request.user.email,
                      'reported_usd': _dollars(usage.get('reported_microusd')), 'held_usd': _dollars(usage.get('held_microusd')),
                      'limit_usd': _dollars(usage.get('period_limit_microusd')), 'returned': request.GET.get('checkout') == 'return',
                      'cancelled': request.GET.get('checkout') == 'cancelled'})
    return JsonResponse(view)


def _hosted(request, build):
    denied = customer(request)
    if denied:
        return denied
    if not switch_on():
        return JsonResponse({'error': 'feature_off'}, status=503)
    rate('billing.hosted', request.account_id, 10, 900)
    try:
        url = build(service(), _principal(request))['url']
    except BillingNotConfigured:
        return JsonResponse({'error': 'not_configured'}, status=503)
    except BillingConflict:
        return JsonResponse({'error': 'already_subscribed'}, status=409)
    except (ProviderUnavailable, ProviderRejected):
        return JsonResponse({'error': 'provider_unavailable'}, status=502)
    except NotFound:
        raise Denied()
    if request.content_type == 'application/x-www-form-urlencoded':
        return HttpResponseRedirect(url)   # straight to the provider's hosted page
    return JsonResponse({'url': url})


@endpoint(['POST'])
def checkout(request):
    return _hosted(request, lambda svc, principal: svc.start_checkout(principal))


@endpoint(['POST'])
def portal(request):
    return _hosted(request, lambda svc, principal: svc.portal_url(principal))


@csrf_exempt
def webhook(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > MAX_BODY:
            return JsonResponse({'error': 'too_large'}, status=413)
        rate('billing.webhook', request.META.get('REMOTE_ADDR', 'unknown'), 600, 60)
        outcome = service().ingest(request.body, request.META.get('HTTP_STRIPE_SIGNATURE', ''))
    except Limited:
        return JsonResponse({'error': 'rate_limited'}, status=429)
    except BillingNotConfigured:
        return JsonResponse({'error': 'not_configured'}, status=503)
    except PayloadTooLarge:
        return JsonResponse({'error': 'too_large'}, status=413)
    except SignatureInvalid:
        print(json.dumps({'event': 'billing_webhook', 'category': 'signature_invalid'}), flush=True)
        return JsonResponse({'error': 'invalid_signature'}, status=400)
    except BillingError:
        return JsonResponse({'error': 'invalid_event'}, status=400)
    except (DatabaseError, ValueError):
        return JsonResponse({'error': 'temporarily_unavailable'}, status=503)   # provider retries
    print(json.dumps({'event': 'billing_webhook', 'category': outcome}), flush=True)
    return JsonResponse({'ok': True, 'status': outcome})
