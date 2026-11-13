"""Billing routes: page/JSON overview, hosted checkout and portal (owner switch), signed webhook ingress.

Access is never granted here: the success redirect only returns the customer to this page, and
the webhook worker applies verified provider state. The webhook route has no cookie and is exempt
from CSRF because the signature over the raw body authenticates Stripe.
"""
import json
from datetime import datetime, timezone
from django.db import DatabaseError
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from agentai_platform.billing import (BillingNotConfigured, BillingConflict, BillingError,
                                      PayloadTooLarge, SignatureInvalid, ProviderUnavailable, ProviderRejected, MAX_BODY)
from agentai_platform.budget import BudgetDenied
from agentai_platform.security import NotFound
from . import wiring
from .services import Denied, rate, Limited
from .views import endpoint, customer


def switch_on():
    return wiring.switch_on('billing_checkout')


def open_access_on():
    return wiring.switch_on('open_access')


access_mode = wiring.access_mode          # invite_only | open | paid_required
webhook_secrets = wiring.billing_webhook_secrets


def service():
    return wiring.billing_service()


_principal = wiring.principal


def _usage(principal):
    try:
        return wiring.ledger().summary(principal)
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
    view = service().overview(principal, usage=_usage(principal), mode=access_mode())
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


@endpoint(['POST'], form='json')
def checkout(request):
    return _hosted(request, lambda svc, principal: svc.start_checkout(principal))


@endpoint(['POST'], form='json')
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
