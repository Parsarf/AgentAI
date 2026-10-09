"""Connector settings: list, link (fail-closed until configured), disconnect, drafts.

Provider client registrations and a secret-custody backend do not exist yet, so
link and callback answer 503 and nothing is created. Disconnect and listing work
today so a connection can always be revoked. Tokens never appear in responses.
"""
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from agentai_platform.connectors import ConnectorService, ConnectorError, ConnectorNotConfigured
from agentai_platform.security import Principal, NotFound
from .lifecycle import AccountStore
from .services import Denied, rate
from .views import endpoint, customer


def service():
    return ConnectorService(AccountStore(connection.settings_dict['NAME']))


def _principal(request):
    return Principal(request.account_id, str(request.user.pk), 'customer')


@endpoint(['GET'])
def connections(request, page=False):
    denied = customer(request)
    if denied:
        return denied
    try:
        items = service().overview(_principal(request))
    except NotFound:
        raise Denied()
    if page:
        return render(request, 'accounts/connections.html', {'items': items, 'nav': True,
                      'nav_here': 'connections', 'email': request.user.email})
    return JsonResponse({'connections': items, 'provider_writes_enabled': False})


@endpoint(['POST'], ['service', 'resource'])
def link(request):
    denied = customer(request)
    if denied:
        return denied
    rate('connector.link', request.account_id, 10, 900)
    try:
        service().begin_link(_principal(request), request.input.get('service', ''),
                             'https://getlumina.pro/account/connections/callback',
                             [request.input['resource']] if request.input.get('resource') else [])
    except ConnectorNotConfigured:
        return JsonResponse({'error': 'connector_not_configured'}, status=503)
    except ConnectorError:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    except NotFound:
        raise Denied()
    return JsonResponse({'error': 'connector_not_configured'}, status=503)


@endpoint(['GET'])
def callback(request):
    denied = customer(request)
    if denied:
        return denied
    # No provider exchange adapter is installed: refuse without consuming link state.
    return JsonResponse({'error': 'connector_not_configured'}, status=503)


@endpoint(['POST'], ['connection_id'])
def disconnect(request):
    denied = customer(request)
    if denied:
        return denied
    try:
        cancelled = service().disconnect(_principal(request), request.input.get('connection_id', ''))
    except NotFound:
        raise Denied()
    except ValueError:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    request.form_redirect = '/account/connections/'
    return JsonResponse({'disconnected': True, 'operations_cancelled': cancelled})


@endpoint(['GET'])
def drafts(request):
    denied = customer(request)
    if denied:
        return denied
    try:
        return JsonResponse({'drafts': service().drafts(_principal(request)), 'sent': False})
    except NotFound:
        raise Denied()
