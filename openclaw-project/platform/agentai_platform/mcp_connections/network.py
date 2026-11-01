"""The only network path for remote MCP, including every SDK OAuth fetch.

HTTPX keeps the original hostname for TLS SNI/certificate verification; the
network backend connects only to an IP from the checked DNS answer. No proxies,
redirects, compression, Unix sockets, or production private-address exception.
"""
from __future__ import annotations
import asyncio
import ipaddress
from urllib.parse import urlsplit
import httpx2
from httpcore2._backends.anyio import AnyIOBackend
from ..model_keys import Endpoint, HOSTNAME, BLOCKED_SUFFIXES, is_public, resolve_public, ModelKeyError

MAX_RESPONSE = 2 * 1024 * 1024


class ConnectionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def endpoint_url(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 1000 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
        raise ConnectionError('invalid_url', 'Enter a public HTTPS server URL without spaces.')
    try:
        p = urlsplit(raw)
        host = p.hostname or ''
        if (p.scheme != 'https' or p.username is not None or p.password is not None or p.fragment or p.query
                or not HOSTNAME.fullmatch(host) or host.endswith(BLOCKED_SUFFIXES)
                or '\\' in raw or '%' in p.netloc or any(x in ('.', '..') for x in p.path.split('/'))
                or (p.port not in (None, 443) and not 1024 <= p.port <= 65535)):
            raise ValueError()
        return p.geturl()
    except ValueError:
        raise ConnectionError('invalid_url', 'Use a public HTTPS hostname, with no credentials, query, or fragment.') from None


def origin(url):
    p = urlsplit(url)
    return p.scheme, p.hostname, p.port or 443


def public_address(value):
    if not is_public(value):
        return False
    ip = ipaddress.ip_address(value)
    if ip.version == 6 and (ip.sixtofour or ip.teredo or ip in ipaddress.ip_network('64:ff9b::/96') or ip in ipaddress.ip_network('64:ff9b:1::/48')):
        return False
    return True


class PublicBackend(AnyIOBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            ips = await asyncio.to_thread(resolve_public, Endpoint(host, port, ''), public=public_address)
        except ModelKeyError:
            raise ConnectionError('invalid_url', 'The server resolves to an internal address or an unavailable hostname. Only public HTTPS endpoints are allowed.') from None
        # A literal IP is passed down, so there is no second hostname lookup.
        return await super().connect_tcp(ips[0], port, timeout=timeout, socket_options=socket_options)

    async def connect_unix_socket(self, *args, **kwargs):
        raise ConnectionError('invalid_url', 'Only public HTTPS connections are supported.')


class BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise ConnectionError('response_too_large', 'The server response exceeded Lumina’s size limit.')
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class PublicTransport(httpx2.AsyncBaseTransport):
    def __init__(self, resource_url):
        self.resource_origin = origin(resource_url)
        self.oauth_issuer = lambda: None
        self.inner = httpx2.AsyncHTTPTransport(trust_env=False, retries=0, limits=httpx2.Limits(max_connections=4, max_keepalive_connections=0))
        # Pinned httpx2/httpcore2 versions; their public transport has no backend argument.
        self.inner._pool._network_backend = PublicBackend()

    async def handle_async_request(self, request):
        # OAuth authorization URLs may carry queries, but never send those to the network here.
        url = str(request.url)
        p = urlsplit(url)
        endpoint_url(p._replace(query='').geturl())
        if request.headers.get('authorization', '').lower().startswith('bearer ') and origin(url) != self.resource_origin:
            raise ConnectionError('credential_destination', 'Refused to send the connection token to another service.')
        body = await request.aread()
        if (request.headers.get('authorization', '').lower().startswith('basic ') or b'grant_type=' in body or b'client_secret=' in body):
            issuer = self.oauth_issuer()
            if not issuer or origin(url) != origin(issuer):
                raise ConnectionError('credential_destination', 'Refused OAuth credentials for an unrelated authorization server.')
        request.headers['Accept-Encoding'] = 'identity'
        response = await self.inner.handle_async_request(request)
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise ConnectionError('redirect_refused', 'The endpoint redirects. Enter its final HTTPS URL instead.')
        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
            await response.aclose()
            raise ConnectionError('unsupported_response', 'Compressed MCP responses are not supported.')
        response.stream = BoundedStream(response.stream)
        return response

    async def aclose(self):
        await self.inner.aclose()


def http_client(resource_url):
    return httpx2.AsyncClient(transport=PublicTransport(resource_url), trust_env=False, follow_redirects=False,
                             timeout=httpx2.Timeout(20, connect=5, pool=3))
