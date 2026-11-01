"""Official MCP SDK adapter. Sessions are scoped to one operation and always closed.

The small OAuth subclass makes the SDK's browser rendezvous durable across web
requests; discovery, registration, issuer binding, exchange and refresh stay in
the SDK. The exact SDK version and this override are covered by fixture tests.
"""
from __future__ import annotations
import asyncio
import logging
import secrets
import time
from urllib.parse import urlencode, urlsplit
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.utils import validate_authorization_response_iss
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken, OAuthMetadata, ProtectedResourceMetadata
from mcp.client.auth.oauth2 import PKCEParameters
from .network import ConnectionError, endpoint_url, http_client

# SDK errors can contain provider response bodies. Only our fixed-vocabulary errors may escape.
logging.getLogger('mcp').setLevel(logging.CRITICAL + 1)
logging.getLogger('httpx2').setLevel(logging.CRITICAL + 1)
logging.getLogger('httpcore2').setLevel(logging.CRITICAL + 1)
MAX_TOOLS, MAX_PAGES = 100, 8


class AuthorizationPending(Exception):
    def __init__(self, url):
        self.url = url
        super().__init__('OAuth authorization required')


class Storage:
    def __init__(self, data):
        self.data = data

    async def get_tokens(self):
        value = self.data.get('tokens')
        return OAuthToken.model_validate(value) if value else None

    async def set_tokens(self, tokens):
        old_refresh = (self.data.get('tokens') or {}).get('refresh_token')
        value = tokens.model_dump(mode='json')
        if not value.get('refresh_token') and old_refresh:
            value['refresh_token'] = old_refresh
        self.data['tokens'] = value
        self.data['expires_at'] = time.time() + tokens.expires_in if tokens.expires_in is not None else None

    async def get_client_info(self):
        value = self.data.get('client')
        return OAuthClientInformationFull.model_validate(value) if value else None

    async def set_client_info(self, info):
        self.data['client'] = info.model_dump(mode='json')


class BrowserOAuth(OAuthClientProvider):
    def __init__(self, url, callback_url, storage, resume=None, metadata_url=None, authorization_validator=None):
        self.authorization_validator = authorization_validator
        self.saved, self.resume = storage, resume
        metadata = OAuthClientMetadata(client_name='Lumina', redirect_uris=[callback_url],
                                       grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
                                       token_endpoint_auth_method=(storage.data.get('client') or {}).get('token_endpoint_auth_method', 'none'))
        super().__init__(url, metadata, storage, client_metadata_url=metadata_url)
        for field, model in [('oauth_metadata', OAuthMetadata), ('protected_resource_metadata', ProtectedResourceMetadata)]:
            if storage.data.get(field):
                setattr(self.context, field, model.model_validate(storage.data[field]))
        self.context.auth_server_url = storage.data.get('auth_server_url')

    async def _initialize(self):
        await super()._initialize()
        self.context.token_expiry_time = self.saved.data.get('expires_at')

    async def _perform_authorization_code_grant(self):
        ctx = self.context
        if not ctx.oauth_metadata or not ctx.client_info:
            raise ConnectionError('oauth_setup_required', 'This server requires a registered OAuth client. Ask the Lumina operator to configure it.')
        if self.resume:
            pending = self.saved.data.get('pending') or {}
            if (not secrets.compare_digest(pending.get('state', ''), self.resume.get('state', ''))
                    or pending.get('issuer') != str(ctx.oauth_metadata.issuer) or pending.get('expires', 0) < time.time()):
                raise ConnectionError('oauth_state_invalid', 'Authorization expired or does not match this sign-in. Reconnect to try again.')
            validate_authorization_response_iss(self.resume.get('iss'), ctx.oauth_metadata)
            return self.resume['code'], pending['verifier']
        pkce = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)
        authorize = endpoint_url(str(ctx.oauth_metadata.authorization_endpoint))
        # The browser navigation is checked too; it does not inherit HTTP credentials.
        from ..model_keys import Endpoint, resolve_public
        from .network import public_address
        p = urlsplit(authorize)
        if self.authorization_validator is not None:
            await self.authorization_validator(authorize)
        else:
            await asyncio.to_thread(resolve_public, Endpoint(p.hostname, p.port or 443, ''), public=public_address)
        self.saved.data['pending'] = {'state': state, 'verifier': pkce.code_verifier, 'expires': int(time.time()) + 600,
                                      'issuer': str(ctx.oauth_metadata.issuer)}
        self.snapshot()
        params = {'response_type': 'code', 'client_id': ctx.client_info.client_id, 'redirect_uri': str(ctx.client_metadata.redirect_uris[0]),
                  'state': state, 'code_challenge': pkce.code_challenge, 'code_challenge_method': 'S256'}
        if ctx.should_include_resource_param(ctx.protocol_version):
            params['resource'] = ctx.get_resource_url()
        if ctx.client_metadata.scope:
            params['scope'] = ctx.client_metadata.scope
        raise AuthorizationPending(authorize + '?' + urlencode(params))

    def snapshot(self):
        for field in ('oauth_metadata', 'protected_resource_metadata'):
            value = getattr(self.context, field)
            if value:
                self.saved.data[field] = value.model_dump(mode='json')
        self.saved.data['auth_server_url'] = self.context.auth_server_url


def leaf_errors(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for sub in error.exceptions for leaf in leaf_errors(sub)]
    return [error]


class RemoteClient:
    def __init__(self, *, client_factory=http_client, authorization_validator=None):
        # Tests inject a fixture-only transport. No setting, environment flag or API input can do so.
        self.client_factory = client_factory
        self.authorization_validator = authorization_validator

    async def perform(self, row, credentials, callback_url, *, tool=None, arguments=None, resume=None, metadata_url=None):
        storage = Storage(credentials)
        oauth = BrowserOAuth(row['url'], callback_url, storage, resume, metadata_url, self.authorization_validator) if row['auth_method'] == 'oauth' else None
        try:
            async with self.client_factory(row['url']) as http:
                async def prevent_action_replay(response):
                    if response.status_code not in (401, 403): return
                    import json
                    try: method = json.loads(response.request.content).get('method')
                    except (ValueError, AttributeError): return
                    if method == 'tools/call':
                        await response.aclose()
                        raise ConnectionError('call_authorization_lost', 'Authorization was lost during the call. Check the service before reconnecting or retrying.')
                    if row['auth_method'] != 'oauth':
                        await response.aclose()
                        raise ConnectionError('authentication_required', 'The server requires authorization or rejected this token. Reconnect with valid credentials.')
                # The SDK may refresh/replay an HTTP authentication challenge. Discovery
                # can do that; an action already sent must never be replayed automatically.
                http.event_hooks['response'].append(prevent_action_replay)
                if oauth:
                    http.auth = oauth
                    # Guard refresh/client secrets against malicious cross-origin token endpoints.
                    if hasattr(http._transport, 'oauth_issuer'):
                        http._transport.oauth_issuer = lambda: (storage.data.get('client') or {}).get('issuer')
                elif row['auth_method'] == 'bearer':
                    http.headers['Authorization'] = 'Bearer ' + storage.data['bearer']
                transport = streamable_http_client(row['url'], http_client=http, terminate_on_close=True, max_sse_event_size=2 * 1024 * 1024)
                async with Client(transport, read_timeout_seconds=25, cache=None, input_required_max_rounds=0) as client:
                    if oauth and not storage.data.get('tokens'):
                        raise ConnectionError('oauth_setup_required', 'The server did not complete OAuth authorization. Choose no authentication if this is an unauthenticated server.')
                    if client.server_capabilities.tools is None:
                        raise ConnectionError('no_tools', 'The server did not advertise MCP tools.')
                    found, cursor, seen = [], None, set()
                    for _ in range(MAX_PAGES):
                        page = await client.list_tools(cursor=cursor, cache_mode='bypass')
                        found.extend(t.model_dump(mode='json', by_alias=True, exclude_none=True) for t in page.tools)
                        if len(found) > MAX_TOOLS:
                            raise ConnectionError('discovery_limit', 'The server exposes more than 100 tools.')
                        cursor = page.next_cursor
                        if not cursor:
                            break
                        if cursor in seen:
                            raise ConnectionError('discovery_limit', 'The server repeated a tool-discovery cursor.')
                        seen.add(cursor)
                    else:
                        raise ConnectionError('discovery_limit', 'Tool discovery exceeded eight pages.')
                    if tool is not None:
                        schema = next((t for t in found if t['name'] == tool), None)
                        if schema is None:
                            raise ConnectionError('tool_removed', 'This tool is no longer available. Test the connection to refresh its tools.')
                        from .service import validate_arguments, schema_digest
                        if schema_digest(schema) != row.get('expected_schema'):
                            raise ConnectionError('tool_changed', 'The tool changed. Review and enable its new definition in Integrations.')
                        validate_arguments(schema['inputSchema'], arguments)
                        result = await client.call_tool(tool, arguments)
                        return {'tools': found, 'result': result.model_dump(mode='json', by_alias=True, exclude_none=True)}, storage.data
                    return {'tools': found}, storage.data
        except Exception as error:
            leaves = leaf_errors(error)
            pending = next((e for e in leaves if isinstance(e, AuthorizationPending)), None)
            if pending:
                return {'authorize_url': pending.url}, storage.data
            known = next((e for e in leaves if isinstance(e, ConnectionError)), None)
            if known:
                raise known from None
            # Exception text can include provider bodies/tokens. Never propagate or log it.
            status = next((getattr(getattr(e, 'response', None), 'status_code', None) for e in leaves if hasattr(e, 'response')), None)
            if any(type(e).__name__ == 'OAuthRegistrationError' for e in leaves):
                raise ConnectionError('oauth_setup_required', 'The server requires a registered OAuth client. Ask the Lumina operator to configure it.') from None
            code = 'authentication_required' if status in (401, 403) or any('OAuth' in type(e).__name__ or 'Auth' in type(e).__name__ for e in leaves) else 'unavailable'
            raise ConnectionError(code, 'Authorization was rejected or expired. Reconnect this server.' if code == 'authentication_required'
                                  else 'The MCP server did not complete the request. Check the service and try again.') from None
        finally:
            if oauth:
                oauth.snapshot()
