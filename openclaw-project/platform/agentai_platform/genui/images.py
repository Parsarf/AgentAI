"""Pictures for comparison cards.

For each option on a comparison card the server finds a picture, checks it, keeps it, and puts only its id on the card. The person's browser then loads the
picture from our own origin (`/v1/media/<id>`), so it never contacts a store, an ad network or any other third-party site.

Where a picture comes from, in order:
  1. the option's own `link`: the page is fetched and its preview picture is read (`og:image`, the product's JSON-LD image, `twitter:image`);
  2. optionally Brave Image Search for the option's name, when a key file is configured (AGENTAI_BRAVE_IMAGE_KEY_FILE).
Everything is best effort: an option with no usable picture simply keeps no picture, and a card never waits more than a few seconds for them.

Nothing here trusts what it fetches. Addresses must be public (no private, loopback, link-local or cloud-metadata ranges), every redirect is re-checked,
the connection is pinned to the address that was checked, sizes and time are capped, and a file is accepted only if its own bytes say it is a still JPEG, PNG
or WebP of a sensible size (no SVG, no GIF, nothing animated). The server does no resizing: it has no image library, so a file is kept as it is or not at all.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import re
import socket
import time
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

from agentai_platform.lifecycle.coordinator import Coordinator

log = logging.getLogger('agentai.card_images')

USER_AGENT = 'Mozilla/5.0 (compatible; LuminaCardImages/1.0)'
MAX_PAGE_BYTES, MAX_IMAGE_BYTES = 300_000, 700_000
MIN_SIDE, MAX_SIDE, MAX_RATIO = 150, 6000, 3.5
REQUEST_TIMEOUT, TOTAL_BUDGET, MAX_REDIRECTS, MAX_CANDIDATES = 4.0, 7.0, 4, 3
ALLOWED_PORTS = (None, 80, 443)
IMAGE_TYPES = ('image/jpeg', 'image/png', 'image/webp')
GENERIC = re.compile(r'(logo|favicon|sprite|placeholder|default[-_]?image|no[-_]?image|blank\.|pixel\.|spacer)', re.I)
STOP_WORDS = frozenset('the and for with from new pro set kit pack of in on by'.split())


class FetchError(Exception):
    """Something about this fetch is not acceptable. The reason is for the log; the card just goes without that picture."""


# ---------------------------------------------------------------- reaching a public address, and only that
def resolve_public(host: str, port: int, resolver=socket.getaddrinfo) -> str:
    """The one address to connect to. Every address the name resolves to must be public, or the whole name is refused."""
    if not host or len(host) > 253:
        raise FetchError('bad host')
    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchError(f'could not resolve {host}') from exc
    found = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split('%')[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise FetchError('address is not public')
        found.append(str(ip))
    if not found:
        raise FetchError('no address')
    return next((a for a in found if ':' not in a), found[0])       # IPv4 first: this server has no working IPv6, and a connection to an IPv6 address just hangs until it times out


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes
    truncated: bool = False


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):                                   # the checked address, but the certificate is verified for the real name
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def http_get(url: str, ip: str, *, max_bytes: int, timeout: float, headers: dict, deadline: float) -> Response:
    parts = urlsplit(url)
    secure = parts.scheme == 'https'
    port = parts.port or (443 if secure else 80)
    conn = (_PinnedHTTPS if secure else _PinnedHTTP)(parts.hostname, port, ip, timeout)
    try:
        conn.request('GET', (parts.path or '/') + (('?' + parts.query) if parts.query else ''), headers={'Host': parts.netloc, **headers})
        resp = conn.getresponse()
        got = {k.lower(): v for k, v in resp.getheaders()}
        if resp.status != 200:
            return Response(resp.status, got, b'')
        chunks, size = [], 0
        while size <= max_bytes:
            if time.monotonic() > deadline:
                raise FetchError('too slow')
            chunk = resp.read(min(16384, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        body = b''.join(chunks)
        return Response(200, got, body[:max_bytes], truncated=len(body) > max_bytes)
    except (OSError, http.client.HTTPException) as exc:
        raise FetchError(f'{type(exc).__name__} while fetching') from exc
    finally:
        conn.close()


class SafeFetcher:
    """GET a public http(s) URL, following a few redirects, re-checking every hop. `resolver` and `transport` are seams for tests."""

    def __init__(self, resolver=socket.getaddrinfo, transport=http_get):
        self.resolver, self.transport = resolver, transport

    def get(self, url: str, *, accept: str, max_bytes: int, deadline: float):
        """-> (final_url, content_type, body, truncated)"""
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None or parts.password is not None:
                raise FetchError('not a plain http(s) address')
            try:
                port = parts.port
            except ValueError as exc:
                raise FetchError('bad port') from exc
            if port not in ALLOWED_PORTS:
                raise FetchError('port not allowed')
            ip = resolve_public(parts.hostname, port or (443 if parts.scheme == 'https' else 80), self.resolver)
            left = deadline - time.monotonic()
            if left <= 0:
                raise FetchError('out of time')
            resp = self.transport(url, ip, max_bytes=max_bytes, timeout=min(REQUEST_TIMEOUT, left), deadline=deadline,
                                  headers={'User-Agent': USER_AGENT, 'Accept': accept, 'Accept-Encoding': 'identity'})
            if resp.status in (301, 302, 303, 307, 308) and resp.headers.get('location'):
                url = urljoin(url, resp.headers['location'])
                continue
            if resp.status != 200:
                raise FetchError(f'status {resp.status}')
            return url, resp.headers.get('content-type', '').split(';')[0].strip().lower(), resp.body, resp.truncated
        raise FetchError('too many redirects')


# ---------------------------------------------------------------- is this really a picture we want?
def image_info(data: bytes):
    """-> (mime, width, height) read from the file's own header, or None. Still JPEG, PNG and WebP only: an animated file is None."""
    if data[:3] == b'\xff\xd8\xff':
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                i += 2 if marker != 0xFF else 1
                continue
            length = int.from_bytes(data[i + 2:i + 4], 'big')
            if marker in range(0xC0, 0xD0) and marker not in (0xC4, 0xC8, 0xCC):
                return 'image/jpeg', int.from_bytes(data[i + 7:i + 9], 'big'), int.from_bytes(data[i + 5:i + 7], 'big')
            i += 2 + length
        return None
    if data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR':
        if b'acTL' in data[:4096]:
            return None                                   # an animated PNG
        return 'image/png', int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) > 30:
        kind = data[12:16]
        if kind == b'VP8 ' and data[23:26] == b'\x9d\x01\x2a':
            return 'image/webp', int.from_bytes(data[26:28], 'little') & 0x3FFF, int.from_bytes(data[28:30], 'little') & 0x3FFF
        if kind == b'VP8L' and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], 'little')
            return 'image/webp', (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b'VP8X':
            if data[20] & 0x02:
                return None                               # an animated WebP
            return 'image/webp', int.from_bytes(data[24:27], 'little') + 1, int.from_bytes(data[27:30], 'little') + 1
    return None


def usable(info) -> bool:
    """A real picture of something: not an icon or a tracking pixel, not absurdly large, not a thin banner."""
    if not info:
        return False
    _, w, h = info
    return min(w, h) >= MIN_SIDE and max(w, h) <= MAX_SIDE and max(w, h) / min(w, h) <= MAX_RATIO


# ---------------------------------------------------------------- finding the picture on a product page
class _Head(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.links, self.ld, self._in_ld, self._buf = [], [], [], False, []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or '') for k, v in attrs}
        if tag == 'meta':
            key, content = (a.get('property') or a.get('name') or '').lower(), a.get('content', '').strip()
            if key and content:
                self.meta.append((key, content))
        elif tag == 'link' and 'image_src' in a.get('rel', '').lower() and a.get('href'):
            self.links.append(a['href'].strip())
        elif tag == 'script' and a.get('type', '').lower() == 'application/ld+json':
            self._in_ld, self._buf = True, []

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self._in_ld:
            self.ld.append(''.join(self._buf))
            self._in_ld = False


def _ld_product_images(blobs):
    out = []

    def images(node):
        value = node.get('image')
        for v in value if isinstance(value, list) else [value]:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and isinstance(v.get('url'), str):
                out.append(v['url'])

    def visit(node, depth=0):
        if depth > 4:
            return
        if isinstance(node, list):
            for n in node:
                visit(n, depth + 1)
        elif isinstance(node, dict):
            kinds = node.get('@type')
            if 'Product' in (kinds if isinstance(kinds, list) else [kinds]):
                images(node)
            if '@graph' in node:
                visit(node['@graph'], depth + 1)
    for blob in blobs:
        try:
            visit(json.loads(blob))
        except ValueError:
            continue
    return out


def candidate_images(html: str, base_url: str) -> list[str]:
    """Picture addresses a page offers, best first: its Open Graph picture, the product's own structured-data picture, then the Twitter card picture."""
    head = _Head()
    try:
        head.feed(html)
    except Exception:                                       # a page the parser cannot read gives no picture
        return []
    meta = dict(reversed(head.meta))
    ordered = [meta.get('og:image:secure_url'), meta.get('og:image'), *_ld_product_images(head.ld), meta.get('twitter:image'), meta.get('twitter:image:src'), *head.links]
    out = []
    for raw in ordered:
        if not raw:
            continue
        url = urljoin(base_url, raw)
        path = urlsplit(url).path.lower()
        if urlsplit(url).scheme in ('http', 'https') and not path.endswith(('.svg', '.gif', '.ico')) and not GENERIC.search(path) and url not in out:
            out.append(url)
    return out[:MAX_CANDIDATES]


# ---------------------------------------------------------------- optional: Brave Image Search
@dataclass
class Candidate:
    url: str            # the thumbnail's address
    title: str
    page: str           # the page it was found on


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r'[a-z0-9]+', text.lower()) if len(w) >= 3 and w not in STOP_WORDS}


def matches(name: str, title: str) -> bool:
    """Is this result about the thing we asked for? Most of the option's significant words must appear in the result's title."""
    want = _words(name)
    return bool(want) and len(want & _words(title)) >= max(1, round(len(want) * 0.6))


def _brave_transport(url: str, headers: dict, timeout: float) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
        return response.read(500_000)


class BraveImages:
    ENDPOINT = 'https://api.search.brave.com/res/v1/images/search'

    def __init__(self, key, transport=_brave_transport):
        self.key, self.transport = key, transport            # key: a callable returning the key, read fresh so a rotated key is picked up

    def search(self, query: str, count: int = 6) -> list[Candidate]:
        key = self.key()
        if not key:
            return []
        url = self.ENDPOINT + '?' + urlencode({'q': query[:200], 'count': count, 'safesearch': 'strict'})
        try:
            data = json.loads(self.transport(url, {'X-Subscription-Token': key, 'Accept': 'application/json'}, REQUEST_TIMEOUT))
        except (OSError, ValueError) as exc:
            log.warning('brave image search failed: %s', type(exc).__name__)
            return []
        out = []
        for r in (data.get('results') or []) if isinstance(data, dict) else []:
            if not isinstance(r, dict):
                continue
            thumb = r.get('thumbnail')
            src = thumb.get('src') if isinstance(thumb, dict) else thumb if isinstance(thumb, str) else None
            if isinstance(src, str) and src.startswith('https://'):
                out.append(Candidate(src, str(r.get('title') or ''), str(r.get('url') or '')))
        return out


def key_from_file(path: str):
    def read():
        try:
            with open(path, encoding='utf-8') as handle:
                return handle.read().strip()
        except OSError:
            return ''
    return read


# ---------------------------------------------------------------- keeping pictures
class ImageStore:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    def put(self, account_id: str, body: bytes, mime: str, width: int, height: int, host: str) -> str:
        image_id = hashlib.sha256(body).hexdigest()[:32]
        with self.coordinator.transaction() as con:
            con.execute('INSERT OR IGNORE INTO card_images(account_id,id,mime,width,height,source_host,body,created_epoch) VALUES (?,?,?,?,?,?,?,?)',
                        (account_id, image_id, mime, width, height, host[:120], body, int(self.clock())))
        return image_id

    def read(self, account_id: str, image_id: str):
        with self.store.connect() as con:
            row = con.execute('SELECT mime,body,width,height FROM card_images WHERE account_id=? AND id=?', (account_id, image_id)).fetchone()
        return dict(row) if row else None


@dataclass
class Found:
    body: bytes
    mime: str
    width: int
    height: int
    host: str


class CardImages:
    """Adds a picture to each option of a comparison, places or products card that has one to be found."""

    def __init__(self, store, *, fetcher=None, brave=None, clock=time.time, budget=TOTAL_BUDGET, workers=3):
        self.images = ImageStore(store, clock=clock)
        self.fetcher, self.brave, self.budget, self.workers = fetcher or SafeFetcher(), brave, budget, workers

    def enrich(self, account_id: str, spec: dict) -> dict:
        """-> a copy of a validated comparison, places or products spec, with `image` on every item a picture was found for. Never raises."""
        from .data import WITH_PICTURES
        if not isinstance(spec, dict) or spec.get('type') not in WITH_PICTURES:
            return spec
        out = json.loads(json.dumps(spec))
        deadline = time.monotonic() + self.budget
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix='card-image')
        try:
            jobs = {pool.submit(self._find, item, deadline): i for i, item in enumerate(out['items'])}
            done, _late = concurrent.futures.wait(jobs, timeout=self.budget + 0.5)
            for future in done:
                try:
                    found = future.result()
                except Exception:                                # one option failing never touches the others
                    found = None
                if found is None:
                    continue
                try:
                    image_id = self.images.put(account_id, found.body, found.mime, found.width, found.height, found.host)
                except Exception:
                    log.warning('card image not stored')
                    continue
                out['items'][jobs[future]]['image'] = {'id': image_id, 'w': found.width, 'h': found.height, 'source': found.host}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)       # a slow fetch that missed the budget is abandoned, not waited for
        return out

    # -- one option -------------------------------------------------------------------------------------------
    def _find(self, item: dict, deadline: float):
        if item.get('link'):
            found = self._from_page(item['link'], deadline)
            if found:
                return found
        return self._from_search(item.get('name', ''), deadline) if self.brave else None

    def _from_page(self, link: str, deadline: float):
        try:
            final, _type, body, _truncated = self.fetcher.get(link, accept='text/html,application/xhtml+xml', max_bytes=MAX_PAGE_BYTES, deadline=deadline)
            html = body.decode('utf-8', 'replace')
        except FetchError as exc:
            log.info('product page not read: %s', exc)
            return None
        for url in candidate_images(html, final):
            found = self._image(url, urlsplit(final).hostname or '', deadline)
            if found:
                return found
        return None

    def _from_search(self, name: str, deadline: float):
        for c in self.brave.search(name):
            if not matches(name, c.title):
                continue
            found = self._image(c.url, urlsplit(c.page).hostname or 'search.brave.com', deadline)
            if found:
                return found
        return None

    def _image(self, url: str, host: str, deadline: float):
        try:
            _final, _type, body, truncated = self.fetcher.get(url, accept=', '.join(IMAGE_TYPES), max_bytes=MAX_IMAGE_BYTES, deadline=deadline)
        except FetchError as exc:
            log.info('picture not fetched: %s', exc)
            return None
        info = None if truncated else image_info(body)
        if not usable(info):
            return None
        return Found(body, info[0], info[1], info[2], host.lower()[:120])


def from_environment(store, clock=time.time, env=None):
    """Off unless AGENTAI_CARD_IMAGES=1. AGENTAI_BRAVE_IMAGE_KEY_FILE (a file holding a Brave key that may use Image Search) adds the search fallback."""
    env = os.environ if env is None else env
    if env.get('AGENTAI_CARD_IMAGES') != '1':
        return None
    key_file = env.get('AGENTAI_BRAVE_IMAGE_KEY_FILE', '')
    return CardImages(store, brave=BraveImages(key_from_file(key_file)) if key_file else None, clock=clock)
