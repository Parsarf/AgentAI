"""UI-facing contract helpers: CSRF for script clients and one bootstrap call.

A replacement front end needs exactly two things before it can draw anything: a CSRF token (no HTML scraping) and the
signed-in user's feature map. Everything else is the documented /v1 resource API (see UI_CONTRACT.md).
"""
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.middleware.csrf import get_token

from .views import endpoint, customer

API_VERSION = '2026-10-13'


@endpoint(['GET'])
def csrf(request):
    """Public. Returns a token to send as X-CSRFToken on every POST; also sets the CSRF cookie."""
    return JsonResponse({'csrf_token': get_token(request), 'api_version': API_VERSION})


def features(request):
    from .billing import access_mode
    from .chat import browse_on, execution_on
    from .connections import switch_on as connectors_on
    storage = bool(settings.STORAGE_DIR) and settings.STORAGE_READY
    return {
        'chat': True,
        'execution': execution_on(),
        'browse': browse_on(),                            # the browser agent may be chosen for interactive goals                      # false: messages are saved and wait; true: the assistant answers
        'files': storage,
        'uploads': storage and settings.UPLOADS_ENABLED,
        'telegram': bool(settings.TELEGRAM_ENABLED),
        'connectors': connectors_on(),
        'billing_mode': access_mode(),                    # invite_only | open | paid_required
        'requests': True,
        'usage': True,
    }


@endpoint(['GET'])
def app(request):
    """Signed-in bootstrap: who, what is available, where the account stands. One round trip for any shell."""
    denied = customer(request)
    if denied:
        return denied
    with connection.cursor() as c:
        c.execute('SELECT state FROM deployments WHERE account_id=%s ORDER BY generation DESC LIMIT 1', [request.account_id])
        row = c.fetchone()
    return JsonResponse({
        'api_version': API_VERSION,
        'user': {'email': request.user.email, 'role': 'customer'},
        'assistant': {'state': row[0] if row else 'not_provisioned'},
        'features': features(request),
        'limits': {'max_message_chars': 16000, 'max_projects': 10, 'max_conversations_per_project': 10},
        'links': {'classic_ui': '/account/', 'sign_out': '/auth/logout'},
    })
