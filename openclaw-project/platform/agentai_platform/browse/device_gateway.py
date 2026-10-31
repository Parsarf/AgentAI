"""The door the customer's extension connects to: wss://<backend>/v1/device, on loopback behind the proxy (see deploy/caddy/Caddyfile.getlumina).

One WebSocket per extension. Its first message must arrive within HELLO_SECONDS and says who it is, one of
  {"hello":1, "token": "<device token>"}                        a paired device coming back
  {"hello":1, "pair": "<code>", "label": "Chrome (mac)"}        a new device trading a pairing code for its token
and is answered with {"welcome":1, "device_id": ...} (a new device also gets "token", once). Anything else closes the connection (4400/4401/4429).
After that the extension sends command replies ({"id":..., "ok":...}), {"event":"stopped"} and {"ping":...}; the service sends runner commands.
Origin must be the extension (chrome-extension://<id>, or exactly one of the configured origins): a web page cannot open this socket.
"""
from __future__ import annotations
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .devices import DeviceError, DeviceHub, DeviceStore
from .ws import Connection, WsClosed, accept_key, valid_key

log = logging.getLogger('agentai.browse.devices')

PATHS = ('/v1/device', '/device')
HANDSHAKE_SECONDS = 10
HELLO_SECONDS = 10
IDLE_SECONDS = 75                 # the extension pings every 20 s; silence for this long means the computer went to sleep or the link died
MAX_CONNECTIONS = 64
FAIL_LIMIT, FAIL_WINDOW = 20, 60  # failed logins across the whole gateway per minute; behind the proxy every peer looks the same, so this is global on purpose
MAX_HELLO = 4096


class DeviceGateway:
    def __init__(self, store: DeviceStore, hub: DeviceHub, *, origins=(), clock=time.time, idle=IDLE_SECONDS, hello=HELLO_SECONDS, max_connections=MAX_CONNECTIONS):
        self.store, self.hub, self.origins, self.clock, self.idle, self.hello = store, hub, tuple(origins), clock, idle, hello
        self.slots, self._fails, self._lock = threading.BoundedSemaphore(max_connections), [], threading.Lock()

    # ------------------------------------------------------------------ who may knock
    def origin_ok(self, origin) -> bool:
        if not isinstance(origin, str):
            return False
        return origin in self.origins if self.origins else origin.startswith('chrome-extension://') and '/' not in origin[len('chrome-extension://'):]

    def _failed(self):
        now = self.clock()
        with self._lock:
            self._fails = [t for t in self._fails if now - t < FAIL_WINDOW] + [now]

    def _locked_out(self) -> bool:
        now = self.clock()
        with self._lock:
            return len([t for t in self._fails if now - t < FAIL_WINDOW]) >= FAIL_LIMIT

    def _identify(self, hello):
        """-> (account, device_id, new_token_or_None) or None."""
        if isinstance(hello.get('pair'), str):
            try:
                made = self.store.redeem(hello['pair'], hello.get('label', ''))
            except DeviceError:
                return None
            return (made['account'], made['device_id'], made['token']) if made else None
        who = self.store.authenticate(hello.get('token'))
        return (who[0], who[1], None) if who else None

    # ------------------------------------------------------------------ one connection
    def serve(self, conn: Connection):
        conn.set_timeout(self.hello)
        try:
            text = conn.recv()
            if len(text) > MAX_HELLO:
                return conn.close(1009, 'hello too big')
            hello = json.loads(text)
        except (WsClosed, ValueError):
            return conn.close(4400, 'hello')
        if not isinstance(hello, dict) or hello.get('hello') != 1:
            return conn.close(4400, 'hello')
        if self._locked_out():
            return conn.close(4429, 'too many attempts')
        who = self._identify(hello)
        if who is None:
            self._failed()
            return conn.close(4401, 'unauthorized')
        account, device_id, token = who
        link = self.hub.attach(account, device_id, conn)
        log.info('device %s of an account connected%s', device_id, ' (new)' if token else '')
        try:
            conn.send_text(json.dumps({'welcome': 1, 'device_id': device_id, **({'token': token} if token else {})}))
            conn.set_timeout(self.idle)
            while True:
                try:
                    msg = json.loads(conn.recv())
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if 'event' in msg:
                    link.note_event(msg)
                elif 'ping' in msg:
                    conn.send_text('{"pong":1}')
                elif isinstance(msg.get('id'), int):
                    link.push(msg)
        except WsClosed:
            pass
        finally:
            self.hub.detach(link)
            log.info('device %s disconnected (%s)', device_id, link.stopped or link.reason)

    def sweep(self):
        """Drop live connections whose device was revoked elsewhere (the command line or another process shares the store, not the hub)."""
        for account, device_id in self.hub.connected():
            if not self.store.exists(account, device_id):
                self.hub.kick(account, device_id, 'revoked')


def sweep_forever(gateway: DeviceGateway, stop: threading.Event, every=15):
    while not stop.wait(every):
        try:
            gateway.sweep()
        except Exception:
            log.exception('device sweep failed')


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    timeout = HANDSHAKE_SECONDS

    def log_message(self, *args):
        pass

    def _refuse(self, code, text):
        self.send_response(code)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def do_GET(self):
        gateway: DeviceGateway = self.server.gateway
        h = self.headers
        if urlsplit(self.path).path not in PATHS:
            return self._refuse(404, 'not found')
        if h.get('Upgrade', '').lower() != 'websocket' or 'upgrade' not in h.get('Connection', '').lower() or h.get('Sec-WebSocket-Version') != '13' or not valid_key(h.get('Sec-WebSocket-Key')):
            return self._refuse(426, 'websocket only')
        if not gateway.origin_ok(h.get('Origin')):
            return self._refuse(403, 'origin')
        if not gateway.slots.acquire(blocking=False):
            return self._refuse(503, 'busy')
        try:
            self.send_response(101, 'Switching Protocols')
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', accept_key(h['Sec-WebSocket-Key']))
            self.end_headers()
            self.wfile.flush()
            self.close_connection = True
            gateway.serve(Connection(self.connection, self.rfile))
        finally:
            gateway.slots.release()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(gateway: DeviceGateway, host: str, port: int) -> ThreadingHTTPServer:
    server = _Server((host, port), _Handler)
    server.gateway = gateway
    return server
