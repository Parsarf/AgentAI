import json, os, socket, tempfile, threading, unittest
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.bridge_client import BridgeRpc
from agentai_platform.gateway import NativeGateway
from agentai_platform.lifecycle.cell_bridge import BridgeError, CellBridge, serve


class FakeRelay:
    def __init__(self, tenant, token):
        self.tenant, self.token, self.sent, self.closed = tenant, token, [], False
        self.out = [{'ready': True, 'protocol': 4, 'server': {'version': '2026.9.6'},
                     'methods': ['chat.send', 'chat.history', 'chat.abort', 'sessions.create']}]
    def write(self, obj): self.sent.append(obj)
    def read(self, timeout):
        if self.out: return self.out.pop(0)
        last = self.sent[-1]
        m = last['method']
        payload = {'sessions.create': {'key': 'agent:main:dashboard:abc'},
                   'chat.send': {'runId': 'r1', 'status': 'started'},
                   'chat.abort': {'ok': True, 'aborted': True},
                   'chat.history': {'messages': [{'role': 'user', 'content': 'hi', '__openclaw': {'id': 'u1', 'seq': 1}},
                                                 {'role': 'assistant', 'content': [{'type': 'text', 'text': 'pong'}], '__openclaw': {'id': 'a1', 'seq': 2}}],
                                    'sessionInfo': {'hasActiveRun': False}}}[m]
        return {'id': last['id'], 'ok': True, 'payload': payload}
    def alive(self): return not self.closed
    def close(self): self.closed = True


def bridge(relays):
    def spawn(tenant, token):
        r = FakeRelay(tenant, token); relays.append(r); return r
    return CellBridge(lambda a: ('aa-' + 'a' * 32, 'tok') if a == 'acct' else None, spawn, lambda t: 12345)


class BridgeTests(unittest.TestCase):
    def test_validation_refuses_unknown_and_malformed(self):
        b = bridge([])
        for method, params in [('exec', {}), ('chat.send', {'sessionKey': 'agent:main:x', 'message': '', 'idempotencyKey': 'k'}),
                               ('chat.send', {'sessionKey': 'evil', 'message': 'm', 'idempotencyKey': 'k'}),
                               ('chat.history', {'sessionKey': 'agent:other:x'}), ('sessions.create', {'label': 'a b'})]:
            with self.assertRaises(BridgeError): b.call('acct', method, params)
        with self.assertRaises(BridgeError): b.call('nobody', 'hello', {})

    def test_full_flow_through_native_gateway(self):
        relays = []; b = bridge(relays)
        gw = NativeGateway(lambda m, p: b.call('acct', m, p))
        self.assertTrue(gw.capabilities().send)
        key, _, _ = gw.open_session('op1', 'chat-1')
        self.assertEqual(key, 'agent:main:dashboard:abc')
        self.assertEqual(gw.send(key, 'op1', 'hi')['run_id'], 'r1')
        page = gw.history(key, None)
        self.assertEqual([m['content'] for m in page['messages']], ['pong']); self.assertFalse(page['active_run'])
        gw.abort(key, 'r1')
        self.assertEqual(len(relays), 1)                       # one relay reused across calls
        self.assertEqual(relays[0].sent[0]['params']['agentId'], 'main')
        self.assertEqual(b.call('acct', 'usage.snapshot', {}), {'spend_microusd': 12345})

    def test_idle_sweep_and_dead_relay_respawn(self):
        relays = []; t = [0]
        b = bridge(relays); b.clock = lambda: t[0]; b.idle_seconds = 10
        b.call('acct', 'hello', {}); t[0] = 11; b.sweep()
        self.assertTrue(relays[0].closed)
        b.call('acct', 'hello', {}); self.assertEqual(len(relays), 2)

    def test_socket_roundtrip_and_peer_check(self):
        b = bridge([]); d = tempfile.mkdtemp(); path = os.path.join(d, 's')
        server = serve(b, path, allowed_uids={os.getuid()}, peer_uid=lambda sock: os.getuid())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            rpc = BridgeRpc('acct', path)
            self.assertEqual(rpc('hello', {})['protocol'], 4)
            with self.assertRaises(CapabilityUnavailable): BridgeRpc('acct', path)('exec', {})
        finally:
            server.shutdown(); server.server_close()
        with self.assertRaises(CapabilityUnavailable): BridgeRpc('acct', path)('hello', {})


if __name__ == '__main__':
    unittest.main()
