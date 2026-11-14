"""Validate customer credentials before encryption. Never accept these through agent tools."""
import re
from .network import ConnectionError, endpoint_url

AUTH_METHODS = ('auto', 'oauth', 'bearer', 'header', 'basic', 'none')
BLOCKED_HEADERS = {'host', 'cookie', 'set-cookie', 'connection', 'content-length', 'content-type', 'accept', 'origin', 'referer', 'transfer-encoding', 'proxy-authorization', 'authorization', 'accept-encoding', 'upgrade', 'te', 'trailer', 'user-agent'}

def secret(value, label='credential', *, empty=False):
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= 4096 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ConnectionError('invalid_token', 'Enter a valid ' + label + ' without control characters.')
    return value

def credentials(method, token='', options=None):
    if method not in AUTH_METHODS:
        raise ConnectionError('invalid_authentication', 'Choose automatic, OAuth, API token, API-key header, Basic authentication or no authentication.')
    if options is None: options = {}
    if not isinstance(options, dict) or set(options) - {'header_name', 'username', 'password', 'client_id', 'client_secret', 'issuer', 'token_endpoint_auth_method'}:
        raise ConnectionError('invalid_authentication', 'Invalid authentication settings.')
    allowed = {'auto': set(), 'none': set(), 'bearer': set(), 'header': {'header_name'}, 'basic': {'username', 'password'},
               'oauth': {'client_id', 'client_secret', 'issuer', 'token_endpoint_auth_method'}}
    if set(options) - allowed[method]: raise ConnectionError('invalid_authentication', 'These credentials do not match the selected authentication method.')
    if method == 'bearer':
        value = secret(token, 'bearer token')
        if any(c.isspace() for c in value): raise ConnectionError('invalid_token', 'Enter only the token, without the Bearer prefix or spaces.')
        return {'bearer': value}
    if method == 'header':
        name = options.get('header_name', '')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name) or name.lower() in BLOCKED_HEADERS or name.lower().startswith(('proxy-', 'sec-', 'mcp-', 'x-forwarded-', 'x-agentai-')):
            raise ConnectionError('invalid_header', 'Use an API-key header such as X-API-Key. Reserved HTTP headers are not supported.')
        return {'header': {'name': name, 'value': secret(token, 'API key')}}
    if method == 'basic':
        username = secret(options.get('username'), 'username')
        if ':' in username: raise ConnectionError('invalid_authentication', 'The Basic authentication username cannot contain a colon.')
        return {'basic': {'username': username, 'password': secret(options.get('password', ''), 'password', empty=True)}}
    if method == 'oauth' and options.get('client_id'):
        issuer = endpoint_url(options.get('issuer', ''))
        auth = options.get('token_endpoint_auth_method', 'none')
        if auth not in ('none', 'client_secret_post', 'client_secret_basic'):
            raise ConnectionError('invalid_authentication', 'Unsupported OAuth client authentication method.')
        client = {'client_id': secret(options['client_id'], 'client ID'), 'issuer': issuer, 'token_endpoint_auth_method': auth}
        if auth != 'none': client['client_secret'] = secret(options.get('client_secret'), 'OAuth client secret')
        return {'client': client, 'user_client': True}
    if options or token: raise ConnectionError('invalid_authentication', 'These credentials do not match the selected authentication method.')
    return {}
