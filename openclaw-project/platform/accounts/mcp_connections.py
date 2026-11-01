"""Authenticated account API; network calls and credential custody stay server-side."""
import json
import secrets
from pathlib import Path
from django.conf import settings
from django.db import connection
from django.http import JsonResponse, HttpResponseRedirect
from agentai_platform.mcp_connections.service import ConnectionService, ASANA_URL
from agentai_platform.mcp_connections.network import ConnectionError
from agentai_platform.model_keys import ModelKeyring
from agentai_platform.security import Principal, NotFound
from .lifecycle import AccountStore
from .services import rate, audit, Denied
from .views import endpoint, customer


def service(store=None):
    registrations = {}
    if settings.MCP_OAUTH_CLIENTS_FILE:
        try:
            p = Path(settings.MCP_OAUTH_CLIENTS_FILE)
            if p.is_symlink() or p.stat().st_mode & 0o077:
                raise ValueError('OAuth client registrations must be private')
            if not p.is_file() or p.stat().st_size > 65536: raise ValueError('invalid registration file')
            registrations = json.loads(p.read_text())
            if not isinstance(registrations, dict): raise ValueError('invalid registrations')
            from agentai_platform.mcp_connections.network import endpoint_url
            for url, value in registrations.items():
                endpoint_url(url)
                if not isinstance(value, dict) or not isinstance(value.get('client_id'), str) or not value['client_id'] or not isinstance(value.get('issuer'), str):
                    raise ValueError('invalid registration')
                endpoint_url(value['issuer'])
                if value.get('client_secret') is not None and not isinstance(value['client_secret'], str): raise ValueError('invalid secret')
        except (OSError, ValueError):
            raise ConnectionError('oauth_setup_required', 'OAuth registration configuration is unavailable.') from None
    if settings.ASANA_MCP_CLIENT_ID and settings.ASANA_MCP_CLIENT_SECRET:
        registrations[ASANA_URL] = {'client_id': settings.ASANA_MCP_CLIENT_ID, 'client_secret': settings.ASANA_MCP_CLIENT_SECRET,
                                    'issuer': 'https://app.asana.com', 'token_endpoint_auth_method': 'client_secret_post'}
    return ConnectionService(store or AccountStore(connection.settings_dict['NAME']),
                             ModelKeyring.derived(settings.SECRET_KEY, settings.MCP_KEY_FILE or settings.MODEL_KEY_FILE or None),
                             callback_url=settings.PUBLIC_ORIGIN + '/v1/account/mcp/callback', registrations=registrations)


def principal(request):
    return Principal(request.account_id, str(request.user.pk), 'customer')


def failure(error):
    return JsonResponse({'error': error.code, 'message': error.message}, status=422 if error.code.startswith('invalid') else 409)


@endpoint(['GET', 'POST'], ['name', 'url', 'auth_method', 'token'], field_limits={'url': 1000, 'token': 4096, 'name': 80})
def connections(request):
    denied = customer(request)
    if denied: return denied
    try:
        s, p = service(), principal(request)
        if request.method == 'POST':
            rate('mcp.create', request.account_id, 10, 600)
            cid = s.create(p, **{k: request.input.get(k, '') for k in ('name', 'url', 'auth_method', 'token')})
            audit(request.user.pk, request.account_id, cid, 'mcp.create', 'completed', request.request_id)
            # Creation is not connection success. Explicit test/auth completes discovery.
            return JsonResponse({'id': cid}, status=201)
        rate('mcp.list', request.account_id, 90, 60)
        return JsonResponse(s.listing(p))
    except ConnectionError as e: return failure(e)
    except NotFound: raise Denied()


@endpoint(['POST'], ['name', 'enabled', 'tools', 'token'], structured=True)
def change(request, connection_id, action):
    denied = customer(request)
    if denied: return denied
    rate('mcp.change', request.account_id, 30, 60)
    try:
        s, p = service(), principal(request)
        body = request.input
        if action == 'update':
            if set(body) - {'name', 'enabled', 'tools'}: raise ValueError('invalid fields')
            s.update(p, connection_id, **body)
            result = {'updated': True}
        elif action in ('test', 'reconnect'):
            rate('mcp.discover', request.account_id, 10, 60)
            if action == 'reconnect': s.reconnect(p, connection_id, body.get('token'))
            elif body: raise ValueError('invalid fields')
            browser = secrets.token_urlsafe(32)
            result = s.test(p, connection_id, session=request.session.session_key, browser=browser)
        elif action == 'disconnect':
            if body: raise ValueError('invalid fields')
            result = s.disconnect(p, connection_id)
        else: raise NotFound()
        audit(request.user.pk, request.account_id, connection_id, 'mcp.' + action, 'completed', request.request_id)
        response = JsonResponse(result)
        if result.get('authorize_url'):
            response.set_cookie('__Host-lumina_mcp_oauth', browser, max_age=600, secure=True, httponly=True, samesite='Lax', path='/')
        return response
    except ConnectionError as e: return failure(e)
    except NotFound: raise Denied()


@endpoint(['GET'])
def callback(request):
    # The ordinary session stays SameSite=Strict. A dedicated one-use Lax cookie
    # carries only a random browser binding for this top-level provider redirect.
    try:
        from django.contrib.auth.models import User
        from django.contrib.sessions.backends.db import SessionStore
        from django.utils.crypto import constant_time_compare
        s = service()
        state = request.GET.get('state', '')
        row = s.browser_callback_binding(state, request.COOKIES.get('__Host-lumina_mcp_oauth', ''))
        login = SessionStore(session_key=row['oauth_session']).load()
        user = User.objects.get(pk=row['oauth_actor'], is_active=True)
        if (str(login.get('_auth_user_id')) != str(user.pk) or not constant_time_compare(login.get('_auth_user_hash', ''), user.get_session_auth_hash())
                or login.get('epoch') != user.identity.epoch or not user.identity.verified):
            raise ConnectionError('oauth_state_invalid', 'The initiating sign-in was revoked. Sign in and reconnect.')
        p = Principal(row['account_id'], str(user.pk), 'customer')
        rate('mcp.callback', row['account_id'], 20, 600)
        if request.GET.get('error'):
            with s.coordinator.transaction() as con:
                s.store._authorize(con, p)
                con.execute('UPDATE mcp_connections SET oauth_state_hash=NULL WHERE account_id=? AND id=?', (p.account_id, row['id']))
            s._error(row, 'authentication_required')
            raise ConnectionError('authentication_required', 'Authorization was declined.')
        s.callback(p, state, request.GET.get('code', ''), row['oauth_session'], request.GET.get('iss'))
        target = '/app/integrations?mcp=connected'
    except (ConnectionError, NotFound, User.DoesNotExist):
        target = '/app/integrations?mcp=authorization_failed'
    response = HttpResponseRedirect(target)
    response.delete_cookie('__Host-lumina_mcp_oauth', path='/', samesite='Lax')
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'no-store'
    return response


@endpoint(['POST'], ['approved'], structured=True)
def approve(request, call_id):
    denied = customer(request)
    if denied: return denied
    rate('mcp.approve', request.account_id, 30, 60)
    try:
        if set(request.input) != {'approved'} or type(request.input['approved']) is not bool: raise ValueError('invalid decision')
        service().approve(principal(request), call_id, request.input['approved'])
        audit(request.user.pk, request.account_id, call_id, 'mcp.approval', 'completed', request.request_id)
        return JsonResponse({'decided': True})
    except ConnectionError as e: return failure(e)
    except NotFound: raise Denied()
