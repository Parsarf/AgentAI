"""The WebSocket layer and the gateway the customers' extensions connect to, over real sockets (a hand-written client, like the browser's, with masked frames)."""
import base64
import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agentai_platform.browse import devices as dv
from agentai_platform.browse import ws
from agentai_platform.browse.device_gateway import DeviceGateway, FAIL_LIMIT, make_server
from agentai_platform.browse.device_transport import DeviceTransport
from agentai_platform.browse.session import RunnerError, Session

ORIGIN = 'chrome-extension://abcdefghijklmnopabcdefghijklmnop'


def mask_frame(opcode, payload, *, fin=True, masked=True, rsv=0):
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | rsv | opcode])
    mbit = 0x80 if masked else 0
    head += bytes([mbit | n]) if n < 126 else bytes([mbit | 126]) + struct.pack('>H', n) if n < 65536 else bytes([mbit | 127]) + struct.pack('>Q', n)
    if not masked:
        return head + payload
    key = os.urandom(4)
    return head + key + ws.unmask(payload, key)


class Client:
    def __init__(self, port, *, origin=ORIGIN, path='/v1/device', extra='', version='13', upgrade=True):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        req = f'GET {path} HTTP/1.1\r\nHost: x\r\n' + ('Upgrade: websocket\r\nConnection: Upgrade\r\n' if upgrade else '') + f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: {version}\r\n'
        if origin: req += f'Origin: {origin}\r\n'
        self.sock.sendall((req + extra + '\r\n').encode())
        self.buf = b''
        while b'\r\n\r\n' not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk: break
            self.buf += chunk
        head, _, self.buf = self.buf.partition(b'\r\n\r\n')
        self.status = int(head.split(b' ')[1]) if head else 0
        self.accept = next((l.split(b': ')[1].decode() for l in head.split(b'\r\n') if l.lower().startswith(b'sec-websocket-accept')), None)
        self.key = key

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk: raise EOFError
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        """-> ('text', str) | ('close', code) | ('eof', None)"""
        try:
            while True:
                b0, b1 = self._need(2); n = b1 & 0x7F; op = b0 & 0xF
                if n == 126: n = struct.unpack('>H', self._need(2))[0]
                elif n == 127: n = struct.unpack('>Q', self._need(8))[0]
                data = self._need(n)
                if op == 1: return 'text', data.decode()
                if op == 8: return 'close', struct.unpack('>H', data[:2])[0] if len(data) >= 2 else None
                if op == 0xA: return 'pong', data
        except (EOFError, ConnectionError, socket.timeout):
            return 'eof', None

    def send(self, obj, **kw):
        self.sock.sendall(mask_frame(1, (obj if isinstance(obj, str) else json.dumps(obj)).encode(), **kw))

    def raw(self, data): self.sock.sendall(data)
    def close(self): self.sock.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = dv.DeviceStore(Path(self.tmp.name) / 'd.json'); self.hub = dv.DeviceHub(); self.clients = []
        self.gateway = None

    def start(self, **kw):
        self.gateway = DeviceGateway(self.store, self.hub, **kw)
        self.server = make_server(self.gateway, '127.0.0.1', 0); self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), [c.close() for c in self.clients]))
        return self

    def client(self, **kw):
        c = Client(self.port, **kw); self.clients.append(c); return c

    def connect(self, hello):
        c = self.client(); self.assertEqual(c.status, 101); c.send(hello); return c

    def paired(self, account='acct'):
        made = self.store.redeem(self.store.pair(account), 'Test'); return made

    def wait_for(self, fn, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v: return v
            time.sleep(0.01)
        self.fail('timed out')


class WsLayerChecks(unittest.TestCase):
    """ws.Connection on a socket pair: the rules, one at a time."""
    def setUp(self):
        self.a, self.b = socket.socketpair(); self.a.settimeout(2); self.b.settimeout(2)
        self.conn = ws.Connection(self.a, self.a.makefile('rb'), max_message=1000)
        self.addCleanup(lambda: (self.a.close(), self.b.close()))

    def test_fragments_pings_and_big_messages(self):
        self.b.sendall(mask_frame(1, b'he', fin=False) + mask_frame(9, b'p') + mask_frame(0, b'llo'))
        self.assertEqual(self.conn.recv(), 'hello')
        self.assertEqual(self.b.recv(100), ws.frame(0xA, b'p'))                            # the ping was answered in between
        self.b.sendall(mask_frame(1, 'é'.encode() * 400)); self.assertEqual(self.conn.recv(), 'é' * 400)       # 16-bit length

    def test_every_rule_ends_the_connection_with_the_right_code(self):
        cases = {1002: [mask_frame(1, b'x', masked=False), mask_frame(1, b'x', rsv=0x40), mask_frame(0, b'x'), mask_frame(1, b'a', fin=False) + mask_frame(1, b'b'), mask_frame(9, b'x' * 126), mask_frame(9, b'x', fin=False)],
                 1003: [mask_frame(2, b'binary'), mask_frame(3, b'')], 1007: [mask_frame(1, b'\xff\xfe')], 1009: [mask_frame(1, b'x' * 1001), mask_frame(1, b'x' * 600, fin=False) + mask_frame(0, b'x' * 600)]}
        for code, frames in cases.items():
            for data in frames:
                a, b = socket.socketpair(); a.settimeout(2); b.settimeout(2)
                conn = ws.Connection(a, a.makefile('rb'), max_message=1000)
                b.sendall(data)
                with self.assertRaises(ws.WsClosed): conn.recv()
                self.assertEqual(struct.unpack('>H', b.recv(100)[2:4])[0], code, data[:6])
                a.close(); b.close()

    def test_a_peer_that_goes_away_or_stalls_is_a_closed_connection(self):
        self.b.close()
        with self.assertRaises(ws.WsClosed): self.conn.recv()
        a, b = socket.socketpair(); a.settimeout(0.1); conn = ws.Connection(a, a.makefile('rb'))
        with self.assertRaises(ws.WsClosed): conn.recv()
        a.close(); b.close()

    def test_the_handshake_key_matches_the_rfc_example(self):
        self.assertEqual(ws.accept_key('dGhlIHNhbXBsZSBub25jZQ=='), 's3pPLMBiTxaQ9kYGzzhZRbK+xOo=')
        self.assertTrue(ws.valid_key(base64.b64encode(b'0' * 16).decode())); self.assertFalse(ws.valid_key('short')); self.assertFalse(ws.valid_key(None))


class GatewayChecks(Base):
    def test_pairing_then_coming_back_with_the_token(self):
        self.start()
        code = self.store.pair('acct')
        c = self.connect({'hello': 1, 'pair': code, 'label': 'Chrome (mac)'})
        kind, text = c.recv(); w = json.loads(text); self.assertEqual((kind, w['welcome']), ('text', 1)); self.assertTrue(w['token'])
        self.assertEqual(c.accept, ws.accept_key(c.key))
        self.assertEqual(self.store.devices('acct')[0]['label'], 'Chrome (mac)'); self.assertIsNotNone(self.wait_for(lambda: self.hub.link('acct')))
        c.close(); self.wait_for(lambda: self.hub.link('acct') is None)
        again = self.connect({'hello': 1, 'token': w['token']}); w2 = json.loads(again.recv()[1])
        self.assertEqual(w2['device_id'], w['device_id']); self.assertNotIn('token', w2)

    def test_the_wrong_credentials_are_refused_and_repeated_failures_lock_the_door(self):
        self.start()
        made = self.paired()
        for hello in ({'hello': 1, 'token': 'x' * 43}, {'hello': 1, 'pair': 'WRONGONE'}, {'hello': 1}):
            self.assertEqual(self.connect(hello).recv(), ('close', 4401))
        self.assertEqual(self.connect({'nope': 1}).recv(), ('close', 4400)); self.assertEqual(self.connect('not json').recv(), ('close', 4400))
        for _ in range(FAIL_LIMIT): self.connect({'hello': 1, 'token': 'y' * 43}).recv()
        self.assertEqual(self.connect({'hello': 1, 'token': made['token']}).recv(), ('close', 4429))     # even the right token waits out the window

    def test_a_connection_that_says_nothing_is_dropped(self):
        self.start(hello=0.2)
        self.assertEqual(self.client().recv(), ('close', 4400))

    def test_only_the_extension_may_knock(self):
        self.start()
        self.assertEqual(self.client(origin='https://evil.example').status, 403)
        self.assertEqual(self.client(origin=None).status, 403)
        self.assertEqual(self.client(origin='chrome-extension://abc/evil').status, 403)
        self.assertEqual(self.client(path='/elsewhere').status, 404)
        self.assertEqual(self.client(upgrade=False).status, 426); self.assertEqual(self.client(version='8').status, 426)
        self.assertEqual(self.client(origin=ORIGIN).status, 101)
        self.start(origins=['chrome-extension://mine'])
        self.assertEqual(self.client(origin=ORIGIN).status, 403); self.assertEqual(self.client(origin='chrome-extension://mine').status, 101)

    def test_commands_go_down_and_replies_come_up_including_big_ones(self):
        self.start(); made = self.paired()
        c = self.connect({'hello': 1, 'token': made['token']}); c.recv()
        link = self.wait_for(lambda: self.hub.link('acct')); t = DeviceTransport(link, self.tmp.name); s = Session(t)
        def device():
            while True:
                kind, text = c.recv()
                if kind != 'text': return
                m = json.loads(text)
                if m['cmd'] == 'close': continue
                reply = {'id': m['id'], 'ok': True}
                if m['cmd'] == 'screenshot': reply['data'] = base64.b64encode(b'\xff\xd8\xff' + b'1' * 1_500_000).decode()
                if m['cmd'] == 'snapshot': reply['snapshot'] = 'é' * 70000
                c.send(reply)
        threading.Thread(target=device, daemon=True).start()
        self.assertTrue(s.open('https://x/')['ok']); self.assertEqual(len(s.snapshot()['snapshot']), 70000)
        self.assertEqual(s.screenshot()['file'], 'shot-001.jpg'); self.assertEqual(len((Path(self.tmp.name) / 'shot-001.jpg').read_bytes()), 1_500_003)
        s.close(); self.assertTrue(link.alive)

    def test_ping_and_stop_events(self):
        self.start(); made = self.paired()
        c = self.connect({'hello': 1, 'token': made['token']}); c.recv()
        c.send({'ping': 1}); self.assertEqual(json.loads(c.recv()[1]), {'pong': 1})
        link = self.wait_for(lambda: self.hub.link('acct'))
        c.send({'event': 'stopped', 'reason': 'stopped_by_customer'}); c.send('garbage'); c.send([1, 2]); c.send({'id': 'not-an-int'})
        self.wait_for(lambda: link.stopped); c.close(); self.wait_for(lambda: not link.alive)
        with self.assertRaises(RunnerError) as ctx: link.recv(1)
        self.assertIn('stopped_by_customer', str(ctx.exception))

    def test_a_second_computer_replaces_the_first(self):
        self.start(); one, two = self.paired(), self.paired()
        a = self.connect({'hello': 1, 'token': one['token']}); a.recv(); self.wait_for(lambda: self.hub.link('acct'))
        b = self.connect({'hello': 1, 'token': two['token']}); b.recv()
        self.assertEqual(a.recv(), ('close', 4409)); self.assertEqual(self.wait_for(lambda: self.hub.link('acct')).device_id, two['device_id'])

    def test_a_revoked_device_is_dropped_by_the_sweep(self):
        self.start(); made = self.paired()
        c = self.connect({'hello': 1, 'token': made['token']}); c.recv(); self.wait_for(lambda: self.hub.link('acct'))
        self.gateway.sweep(); self.assertIsNotNone(self.hub.link('acct'))
        self.store.revoke('acct', made['device_id']); self.gateway.sweep()
        self.assertEqual(c.recv(), ('close', 4403)); self.assertIsNone(self.hub.link('acct'))
        self.assertEqual(self.connect({'hello': 1, 'token': made['token']}).recv(), ('close', 4401))

    def test_a_silent_link_is_dropped_and_the_pool_is_limited(self):
        self.start(idle=0.3, max_connections=1); made = self.paired()
        c = self.connect({'hello': 1, 'token': made['token']}); c.recv()
        self.assertEqual(self.client().status, 503)
        self.wait_for(lambda: self.hub.link('acct') is None, timeout=3)
        self.assertEqual(self.client().status, 101)                                         # the slot came back


if __name__ == '__main__':
    unittest.main()
