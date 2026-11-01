"""Bring your own model: a customer's own API key and endpoint for their assistant.

A customer enters an OpenAI-compatible endpoint, a model name and an API key in Settings. From then on their assistant's model calls leave through Lumina's relay
(tool_relay.py serves it at /byok/v1) instead of Lumina's model proxy: the relay finds out which assistant is calling, opens that customer's stored key and forwards
the call to their endpoint. Three rules keep this safe:

* The key never enters the assistant's sandbox. The assistant only ever holds its own Lumina credential; anything it could read, a hostile web page could trick it into
  sending away. The key is stored encrypted (AES-256-GCM, bound to the account) and is opened only inside the relay, for the length of one call.
* The endpoint must be a public HTTPS address. The relay runs inside Lumina's own network, so an endpoint pointing at a private address would turn it into a way to reach
  Lumina's internal services (the model proxy's admin API, the database, the cloud metadata address). The name must resolve ONLY to public addresses, the connection is
  made to the address that was checked (not looked up again), certificates are verified, redirects are never followed and ports below 1024 other than 443 are refused.
* Nothing about the conversation or the key is ever logged: counts and statuses only.

What is deliberately not limited: model spend and tokens (the customer pays their own provider). What stays limited, because it protects Lumina's servers and not a budget:
requests per minute, simultaneous requests, request and reply size, and connection time.
"""
from __future__ import annotations
import base64
import contextlib
import fcntl
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

log = logging.getLogger('agentai.byok')

DEFAULT_STORE = '/var/lib/agentai-platform/model-keys.json'
DEFAULT_ENGINE_FILE = '/var/lib/agentai-platform/own-model-keys.json'      # not under /etc/agentai-supervisor: that folder is root-only and the web app and tool relay run as agentai-platform
RELAY_PREFIX = '/byok/v1'
MAX_REQUEST_BYTES = 32 * 1024 * 1024        # large enough for pictures in a prompt (the same ceiling as Lumina's model proxy)
MAX_REPLY_BYTES = 64 * 1024 * 1024
CONNECT_SECONDS, READ_SECONDS = 10, 180
PROBE_CONNECT_SECONDS, PROBE_READ_SECONDS = 5, 12        # the save-time test runs inside the web app's single worker: it must be quick (a real call is allowed far longer)
RATE_PER_MINUTE, SIMULTANEOUS = 120, 6      # protect Lumina's servers from one runaway assistant; they are not spending limits
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}')
HOSTNAME = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]')
PATH = re.compile(r'(?:/[A-Za-z0-9._~-]{1,60}){0,6}')
BLOCKED_SUFFIXES = ('.local', '.localhost', '.internal', '.lan', '.home', '.corp', '.intranet', '.arpa', '.test', '.invalid', '.example', '.onion')


class ModelKeyError(ValueError):
    """Something the customer entered is not acceptable. The message is written for them."""


class RelayError(Exception):
    """A call could not be forwarded. `status` and `message` go back to the assistant in the OpenAI error shape."""

    def __init__(self, status, message, code='byok_error'):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


# --------------------------------------------------------------------------------------------------------------------- where it may point
@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    prefix: str                              # '' or '/v1' and the like

    @property
    def base_url(self):
        return f'https://{self.host}{"" if self.port == 443 else f":{self.port}"}{self.prefix}'


def parse_endpoint(raw) -> Endpoint:
    """The address as typed -> an Endpoint, or ModelKeyError. Looks only at the text; `resolve_public` checks where the name really leads."""
    if not isinstance(raw, str) or not raw.strip():
        raise ModelKeyError('Enter the address of your model endpoint, for example https://api.openai.com/v1')
    text = raw.strip()
    if len(text) > 300 or any(ord(c) < 33 or ord(c) > 126 for c in text):
        raise ModelKeyError('That address has characters an address cannot have.')
    m = re.fullmatch(r'(?i)(https?)://([^/?#@:]+)(?::(\d{1,5}))?([^?#]*)', text)
    if not m:
        raise ModelKeyError('Enter a full address starting with https://, with no username, query or #fragment.')
    scheme, host, port, path = m.group(1).lower(), m.group(2).lower().rstrip('.'), m.group(3), m.group(4)
    if scheme != 'https':
        raise ModelKeyError('The address must start with https://. Plain http is not allowed because your key would travel unprotected.')
    if not HOSTNAME.fullmatch(host) or host.endswith(BLOCKED_SUFFIXES) or host in ('localhost',):
        raise ModelKeyError('Use the public hostname of your endpoint (for example api.example.com), not an IP address or an internal name.')
    port = int(port) if port else 443
    if port != 443 and not 1024 <= port <= 65535:
        raise ModelKeyError('The port must be 443 or between 1024 and 65535.')
    path = path.rstrip('/')
    if '..' in path.split('/') or not PATH.fullmatch(path):
        raise ModelKeyError('The path after the hostname can only use letters, digits and . _ ~ - (for example /v1).')
    return Endpoint(host, port, path)


def is_public(ip) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def resolve_public(endpoint: Endpoint, resolver=socket.getaddrinfo, public=is_public) -> list[str]:
    """Where the name leads, and only if EVERY address it leads to is public. One private answer among several public ones is refused too: the connection could land on it."""
    try:
        found = resolver(endpoint.host, endpoint.port, type=socket.SOCK_STREAM)
    except OSError:
        raise ModelKeyError("Lumina could not find that hostname. Check the spelling, and that it's reachable from the internet.") from None
    ips = []
    for info in found:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise ModelKeyError("Lumina could not find that hostname. Check the spelling, and that it's reachable from the internet.")
    if not all(public(ip) for ip in ips):
        raise ModelKeyError('That hostname leads to a private or internal address. Lumina can only reach endpoints that are public on the internet.')
    return ips


def clean_model(raw) -> str:
    if not isinstance(raw, str) or not MODEL.fullmatch(raw.strip()):
        raise ModelKeyError('Enter the model name exactly as your provider writes it (letters, digits and . _ : / - only).')
    return raw.strip()


def clean_key(raw) -> str:
    if not isinstance(raw, str) or not 8 <= len(raw.strip()) <= 500 or any(ord(c) < 33 or ord(c) > 126 for c in raw.strip()):
        raise ModelKeyError('That does not look like an API key. Paste it exactly, with no spaces.')
    return raw.strip()


# --------------------------------------------------------------------------------------------------------------------- who may use it
def read_engine(path=DEFAULT_ENGINE_FILE) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enabled_for(config, account) -> bool:
    """own-model-keys.json: `"own_model_keys": true` = every account, a list = those accounts, anything else (or no line) = nobody. Off until it is turned on, on purpose:
    the privacy policy has to be published first."""
    value = config.get('own_model_keys') if isinstance(config, dict) else None
    if value is True:
        return True
    return isinstance(value, list) and account in value


# --------------------------------------------------------------------------------------------------------------------- the encrypted store
class ModelKeyring:
    """AES-256-GCM keys. `dk1` is derived from the app's own secret (so nothing new has to be provisioned on a server); a dedicated key file, when one exists, is used for new
    records and `dk1` still opens the old ones. Rotating the app secret without a key file makes stored keys unreadable: customers are asked to enter them again, nothing leaks."""

    def __init__(self, keys: dict[str, bytes], current: str):
        self.keys, self.current = keys, current

    @classmethod
    def derived(cls, secret: str, key_file=None):
        keys = {'dk1': HKDF(algorithm=hashes.SHA256(), length=32, salt=b'lumina-model-keys', info=b'dk1').derive(secret.encode())}
        current = 'dk1'
        if key_file:
            try:
                kid, _, b64 = Path(key_file).read_text().strip().partition(':')
                raw = base64.urlsafe_b64decode(b64 + '=' * (-len(b64) % 4))
                if re.fullmatch(r'[a-z0-9]{1,12}', kid) and len(raw) == 32:
                    keys[kid], current = raw, kid
            except (OSError, ValueError):
                pass
        return cls(keys, current)

    def _aead(self, kid, account):
        master = self.keys.get(kid)
        if master is None:
            raise ModelKeyError('stored key cannot be opened')
        return AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'lumina-model-key|' + account.encode()).derive(master))

    def seal(self, account, data: dict):
        nonce = secrets.token_bytes(12)
        return self.current, nonce, self._aead(self.current, account).encrypt(nonce, json.dumps(data, separators=(',', ':')).encode(), f'{account}|model_key'.encode())

    def open(self, kid, account, nonce, blob) -> dict:
        try:
            return json.loads(self._aead(kid, account).decrypt(nonce, blob, f'{account}|model_key'.encode()))
        except InvalidTag as exc:
            raise ModelKeyError('stored key cannot be opened') from exc


class ModelKeyStore:
    """One entry per account in a small JSON file (0600), safe for several processes. The non-secret facts (host, model, last four characters of the key) are readable
    without any key: Lumina's supervisor uses them to set up the assistant. Only the key itself is encrypted."""

    def __init__(self, path=DEFAULT_STORE, ring: ModelKeyring | None = None, *, clock=time.time):
        self.path, self.ring, self.clock, self._lock = Path(path), ring, clock, threading.RLock()

    @contextlib.contextmanager
    def _txn(self, write=False):
        with self._lock:
            if write:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            lock = str(self.path) + '.lock'
            try:
                fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600) if write else os.open(lock, os.O_RDONLY)
            except OSError:
                fd = None                                                       # a reader with no lock file simply reads
            try:
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
                try:
                    db = json.loads(self.path.read_text())
                except (OSError, ValueError):
                    db = {}
                if not isinstance(db, dict):
                    db = {}
                db.setdefault('accounts', {})
                before = json.dumps(db, sort_keys=True)
                yield db
                if write and json.dumps(db, sort_keys=True) != before:
                    tmp = tempfile.NamedTemporaryFile('w', dir=self.path.parent, prefix='.model-keys-', delete=False)
                    try:
                        os.chmod(tmp.name, 0o600)
                        json.dump(db, tmp)
                        tmp.flush()
                        os.fsync(tmp.fileno())
                        tmp.close()
                        os.replace(tmp.name, self.path)
                    except BaseException:
                        with contextlib.suppress(OSError):
                            os.unlink(tmp.name)
                        raise
            finally:
                if fd is not None:
                    os.close(fd)

    def put(self, account: str, endpoint: Endpoint, model: str, api_key: str) -> dict:
        if self.ring is None:
            raise ModelKeyError('model keys are not set up on this server')
        kid, nonce, blob = self.ring.seal(account, {'key': api_key})
        entry = {'host': endpoint.host, 'base_url': endpoint.base_url, 'model': model, 'hint': api_key[-4:], 'kid': kid,
                 'nonce': base64.b64encode(nonce).decode(), 'ct': base64.b64encode(blob).decode(), 'created': int(self.clock())}
        with self._txn(write=True) as db:
            db['accounts'][account] = entry
        return self._public(entry)

    @staticmethod
    def _public(entry):
        return {'host': entry['host'], 'base_url': entry['base_url'], 'model': entry['model'], 'hint': entry['hint'], 'created': entry['created']}

    def public(self, account: str):
        """The non-secret facts, or None. Needs no key."""
        with self._txn() as db:
            entry = db['accounts'].get(account)
        return self._public(entry) if isinstance(entry, dict) else None

    def open(self, account: str) -> dict:
        """-> {'base_url', 'host', 'port', 'prefix', 'model', 'key'} for one call. Raises ModelKeyError when there is none or it cannot be opened."""
        if self.ring is None:
            raise ModelKeyError('model keys are not set up on this server')
        with self._txn() as db:
            entry = db['accounts'].get(account)
        if not isinstance(entry, dict):
            raise ModelKeyError('no model key')
        secret = self.ring.open(entry['kid'], account, base64.b64decode(entry['nonce']), base64.b64decode(entry['ct']))
        endpoint = parse_endpoint(entry['base_url'])
        return {'base_url': entry['base_url'], 'host': endpoint.host, 'port': endpoint.port, 'prefix': endpoint.prefix, 'model': entry['model'], 'key': secret['key']}

    def delete(self, account: str) -> bool:
        with self._txn(write=True) as db:
            return db['accounts'].pop(account, None) is not None


def public_facts(path, account):
    """For processes that only need to know whether an account has its own model and which (the supervisor): no key, no decryption."""
    return ModelKeyStore(path).public(account)


# --------------------------------------------------------------------------------------------------------------------- the connection
class _Pinned(http.client.HTTPSConnection):
    """HTTPS to an address that was already checked: connect to that address, but verify the certificate against (and send as SNI) the name the customer entered."""

    def __init__(self, host, ip, port, *, context, timeout, connect_seconds=CONNECT_SECONDS):
        super().__init__(host, port, context=context, timeout=timeout)
        self._ip, self._ctx, self._connect_seconds = ip, context, connect_seconds

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), timeout=self._connect_seconds)
        sock.settimeout(self.timeout)
        self.sock = self._ctx.wrap_socket(sock, server_hostname=self.host)


def default_context():
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def open_upstream(endpoint: Endpoint, ips, suffix: str, body: bytes | None, key: str, *, method='POST', accept='application/json', context=None, read_seconds=READ_SECONDS,
                  connect_seconds=CONNECT_SECONDS, max_addresses=None):
    """Send one request to the customer's endpoint. -> (connection, response). The caller reads the response and closes the connection. Redirects are never followed."""
    context = context or default_context()
    headers = {'Authorization': f'Bearer {key}', 'Accept': accept, 'User-Agent': 'Lumina-BYOK/1', 'Connection': 'close'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
        headers['Content-Length'] = str(len(body))
    last = None
    for ip in (ips if max_addresses is None else ips[:max_addresses]):
        conn = _Pinned(endpoint.host, ip, endpoint.port, context=context, timeout=read_seconds, connect_seconds=connect_seconds)
        try:
            conn.request(method, endpoint.prefix + suffix, body=body, headers=headers)
            return conn, conn.getresponse()
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last = exc
            conn.close()
    raise RelayError(502, 'Lumina could not reach your model endpoint' + (f' ({type(last).__name__})' if last else '') + '. Check that it is online and the certificate is valid.', 'upstream_unreachable')


def close_upstream(conn, resp=None):
    """Both halves: closing the connection object alone leaves the real socket open for as long as the response object lives, so an abandoned reply would keep streaming."""
    for part in (resp, conn):
        if part is not None:
            with contextlib.suppress(Exception):
                part.close()


def short_reason(raw: bytes) -> str:
    """A provider's error message, trimmed to something safe to show: text only, no markup, no long strings that could be a key."""
    try:
        data = json.loads(raw[:4000])
        message = (data.get('error') or {}).get('message') if isinstance(data.get('error'), dict) else data.get('error') or data.get('message')
    except (ValueError, AttributeError):
        message = None
    text = re.sub(r'<[^>]+>', ' ', str(message or raw[:300].decode('utf-8', 'replace')))
    text = re.sub(r'[A-Za-z0-9_-]{24,}', '[…]', re.sub(r'\s+', ' ', text)).strip()
    return text[:160]


def probe(endpoint: Endpoint, model: str, key: str, *, resolver=socket.getaddrinfo, public=is_public, context=None) -> None:
    """One tiny request, to learn whether the address, the key and the model name work before anything is stored. Raises ModelKeyError with a message for the customer."""
    ips = resolve_public(endpoint, resolver, public)
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': 'ping'}], 'max_tokens': 1, 'stream': False}).encode()
    try:
        conn, resp = open_upstream(endpoint, ips, '/chat/completions', body, key, context=context, read_seconds=PROBE_READ_SECONDS, connect_seconds=PROBE_CONNECT_SECONDS, max_addresses=2)
    except RelayError as exc:
        raise ModelKeyError(exc.message) from None
    try:
        raw = resp.read(8192)
        status = resp.status
    except (OSError, http.client.HTTPException):
        raise ModelKeyError('Your endpoint answered but the reply was cut off. Try again.') from None
    finally:
        close_upstream(conn, resp)
    if status == 200:
        return
    reason = short_reason(raw)
    if status in (401, 403):
        raise ModelKeyError('Your endpoint refused the API key' + (f': {reason}' if reason else '.'))
    if status == 404:
        raise ModelKeyError('Your endpoint answered "not found". Check the address (many need /v1 at the end) and the model name' + (f': {reason}' if reason else '.'))
    if 300 <= status < 400:
        raise ModelKeyError('Your endpoint tried to redirect to another address, which is not allowed. Enter the final address.')
    if status == 429:
        raise ModelKeyError('Your endpoint says you have hit a rate or credit limit' + (f': {reason}' if reason else '.'))
    raise ModelKeyError(f'Your endpoint answered with error {status}' + (f': {reason}' if reason else '.'))


# --------------------------------------------------------------------------------------------------------------------- the relay
class Upstream:
    def __init__(self, status, content_type, conn, resp):
        self.status, self.content_type, self._conn, self._resp, self.sent = status, content_type, conn, resp, 0

    def chunks(self, size=16384):
        try:
            while True:
                data = self._resp.read1(size) if hasattr(self._resp, 'read1') else self._resp.read(size)
                if not data:
                    return
                self.sent += len(data)
                if self.sent > MAX_REPLY_BYTES:
                    return
                yield data
        finally:
            self.close()

    def close(self):
        close_upstream(self._conn, self._resp)


class ModelRelay:
    """The logic behind /byok/v1 (the HTTP wrapper is in tool_relay.py): who the caller is has already been established."""

    def __init__(self, store: ModelKeyStore, enabled, *, resolver=socket.getaddrinfo, public=is_public, context=None, clock=time.monotonic):
        self.store, self.enabled, self.resolver, self.public, self.context, self.clock = store, enabled, resolver, public, context, clock
        self._hits, self._busy, self._guard = {}, {}, threading.Lock()

    def _admit(self, account):
        now = self.clock()
        with self._guard:
            recent = [t for t in self._hits.get(account, []) if now - t < 60]
            if len(recent) >= RATE_PER_MINUTE:
                raise RelayError(429, 'Too many requests in a minute. Slow down.', 'rate_limited')
            if self._busy.get(account, 0) >= SIMULTANEOUS:
                raise RelayError(429, 'Too many requests at once for this account.', 'too_many_at_once')
            self._hits[account] = recent + [now]
            self._busy[account] = self._busy.get(account, 0) + 1

    def _release(self, account):
        with self._guard:
            self._busy[account] = max(0, self._busy.get(account, 1) - 1)

    def _config(self, account):
        if not self.enabled(account):
            raise RelayError(403, 'Using your own model is not switched on for this account.', 'not_enabled')
        try:
            return self.store.open(account)
        except ModelKeyError:
            raise RelayError(404, 'No own model key is saved for this account, or it can no longer be opened. Enter it again in Settings.', 'no_key') from None

    def models(self, account):
        cfg = self._config(account)
        return {'object': 'list', 'data': [{'id': cfg['model'], 'object': 'model', 'owned_by': cfg['host']}]}

    def chat(self, account, raw: bytes) -> Upstream:
        """Forward one chat-completions request. The model is always the customer's chosen one, whatever the assistant asked for."""
        cfg = self._config(account)
        try:
            body = json.loads(raw)
        except ValueError:
            raise RelayError(400, 'The request was not valid JSON.', 'bad_request') from None
        if not isinstance(body, dict) or not isinstance(body.get('messages'), list):
            raise RelayError(400, 'The request had no messages.', 'bad_request')
        body['model'] = cfg['model']
        endpoint = Endpoint(cfg['host'], cfg['port'], cfg['prefix'])
        self._admit(account)
        try:
            try:
                ips = resolve_public(endpoint, self.resolver, self.public)
            except ModelKeyError as exc:
                raise RelayError(502, str(exc), 'endpoint_not_public') from None
            streaming = bool(body.get('stream'))
            conn, resp = open_upstream(endpoint, ips, '/chat/completions', json.dumps(body, separators=(',', ':')).encode(), cfg['key'],
                                       accept='text/event-stream' if streaming else 'application/json', context=self.context)
        except BaseException:
            self._release(account)
            raise
        if 300 <= resp.status < 400:
            close_upstream(conn, resp)
            self._release(account)
            raise RelayError(502, 'Your endpoint tried to redirect to another address, which is not allowed.', 'redirect_refused')
        up = Upstream(resp.status, resp.getheader('Content-Type') or 'application/json', conn, resp)
        original = up.close
        released = []

        def close():
            original()
            if not released:
                released.append(1)
                self._release(account)
        up.close = close
        log.info('byok call status=%s stream=%s', resp.status, streaming)
        return up


def error_body(message, code):
    return {'error': {'message': message, 'type': 'lumina_own_key', 'code': code}}


def fingerprint(key: str) -> str:
    """For logs and tests: something that identifies a key without revealing it."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]
