"""Spending limits the customer sets for themselves: GET/POST /v1/spending-limits (Settings > Usage in the web app).

Lumina applies no spending limit of its own. An account may choose the most one task, one day and one billing period may cost; an empty field means no limit.
The amounts are dollars typed by a person ("5", "2.50"); they are stored as micro-dollars by agentai_platform/spend_limits.py, which the ledger, the run
supervisor and the browser tool read.
"""
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse

from agentai_platform import spend_limits
from . import wiring
from .services import audit
from .views import customer, endpoint

FIELDS = ('task', 'daily', 'period')


def _view(con, account_id):
    own = spend_limits.own(con, account_id)
    effective = spend_limits.get(con, account_id)
    return {'limits': {name + '_microusd': effective[name] for name in FIELDS}, 'chosen': own is not None, 'max_microusd': spend_limits.MAX_LIMIT}


def _amount(text):
    """'' -> None (no limit); '2.50' -> 2500000. Raises ValueError for anything that is not a positive dollar amount with at most two decimals."""
    text = text.strip().lstrip('$').replace(',', '')
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError('invalid amount')
    if not value.is_finite() or value <= 0 or value != value.quantize(Decimal('0.01')):
        raise ValueError('invalid amount')
    micro = int(value * 1_000_000)
    if micro > spend_limits.MAX_LIMIT:
        raise ValueError('invalid amount')
    return micro


@endpoint(['GET', 'POST'], fields=FIELDS, field_limits={name: 16 for name in FIELDS})
def limits(request):
    denied = customer(request)
    if denied:
        return denied
    store = wiring.store()
    if request.method == 'GET':
        with store.connect() as con:
            return JsonResponse(_view(con, request.account_id))
    data = request.input
    if set(data) != set(FIELDS):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    chosen = {name: _amount(data[name]) for name in FIELDS}          # ValueError -> 400 by the endpoint wrapper
    with store.transaction() as con:
        spend_limits.put(con, request.account_id, chosen)
        view = _view(con, request.account_id)
    audit(request.user.pk, request.account_id, 'spending', 'spending.limits_change', 'completed', request.request_id)
    return JsonResponse(view)
