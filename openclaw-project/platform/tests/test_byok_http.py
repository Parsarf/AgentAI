"""/byok/v1 on the tool relay, over a real socket: who may call, what is forwarded, and that the assistant's own credential never reaches the customer's endpoint."""
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agentai_platform import model_keys as mk
from agentai_platform.model_keys import ModelKeyStore, ModelKeyring, ModelRelay, parse_endpoint
from agentai_platform.tool_relay import Identity, make_handler, serve
from tests.test_model_keys import HOST, SECRET, Upstream, answer

CELL_CREDENTIAL = 'cell-credential-from-the-assistant-0001'


class StubRelay:
    def handle(self, account, message, closed=lambda: False):
        return {'jsonrpc': '2.0', 'id': message.get('id'), 'result': {}} if message.get('id') is not None else None


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = ModelKeyStore(Path(self.tmp.name) / 'k.json', ModelKeyring.derived(SECRET)); self.on = True

    def start(self, behaviour=None, byok=True):
        self.up = Upstream(self.tmp.name, behaviour=behaviour); self.addCleanup(self.up.close)
        self.store.put('acct', parse_endpoint(f'https://{HOST}:{self.up.port}/v1'), 'my-model', 'sk-customer-key-0001')
        self.model_relay = ModelRelay(self.store, lambda a: self.on, resolver=lambda h, p, type=0: [(2, 1, 6, '', ('127.0.0.1', p))], public=lambda ip: True, context=self.up.client_context)
        identity = Identity(lambda credential: 'acct' if credential == CELL_CREDENTIAL else None)
        self.server = serve(StubRelay(), identity, '127.0.0.1', 0, byok=self.model_relay if byok else None)
        threading.Thread(target=self.server.serve_forever, daemon=True).start(); self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        return self.server.server_address[1]

    def request(self, port, method, path, body=None, token=CELL_CREDENTIAL):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
        headers = {'Content-Type': 'application/json'}
        if token: headers['Authorization'] = 'Bearer ' + token
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        resp = conn.getresponse(); data = resp.read(); out = (resp.status, dict(resp.getheaders()), data); conn.close(); return out

    CHAT = {'model': 'x', 'messages': [{'role': 'user', 'content': 'hello'}]}

    def test_the_assistant_gets_the_customers_model_and_the_customers_endpoint_never_sees_the_assistants_credential(self):
        port = self.start()
        status, headers, data = self.request(port, 'POST', '/byok/v1/chat/completions', self.CHAT)
        self.assertEqual(status, 200); self.assertEqual(json.loads(data)['choices'][0]['message']['content'], 'hello'); self.assertEqual(headers['Connection'], 'close')
        sent = self.up.requests[0]; wire = json.dumps(sent['headers']) + sent['body'].decode()
        self.assertEqual(sent['headers']['Authorization'], 'Bearer sk-customer-key-0001'); self.assertNotIn(CELL_CREDENTIAL, wire)
        self.assertEqual(json.loads(sent['body'])['model'], 'my-model')

    def test_who_may_call(self):
        port = self.start()
        for token in (None, 'short', 'wrong-credential-that-is-long-enough'):
            status, _, data = self.request(port, 'POST', '/byok/v1/chat/completions', self.CHAT, token=token); self.assertEqual(status, 401, token)
            status, _, _ = self.request(port, 'GET', '/byok/v1/models', token=token); self.assertEqual(status, 401, token)
        self.assertEqual(self.up.requests, [])                                                       # nothing reached the customer's endpoint

    def test_streaming_reaches_the_assistant_and_the_connection_ends_with_it(self):
        events = b'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: [DONE]\n\n'
        port = self.start(answer(200, events, 'text/event-stream'))
        status, headers, data = self.request(port, 'POST', '/byok/v1/chat/completions', {**self.CHAT, 'stream': True})
        self.assertEqual((status, data, headers['Content-Type']), (200, events, 'text/event-stream'))

    def test_a_strange_content_type_from_the_endpoint_is_not_passed_on(self):
        port = self.start(answer(200, b'<script>alert(1)</script>', 'text/html'))
        status, headers, _ = self.request(port, 'POST', '/byok/v1/chat/completions', self.CHAT); self.assertEqual(headers['Content-Type'], 'application/json')

    def test_errors_use_the_openai_shape_and_say_what_to_do(self):
        port = self.start(); self.on = False
        status, _, data = self.request(port, 'POST', '/byok/v1/chat/completions', self.CHAT)
        body = json.loads(data); self.assertEqual((status, body['error']['code']), (403, 'not_enabled')); self.assertIn('message', body['error'])
        self.on = True; self.store.delete('acct')
        status, _, data = self.request(port, 'POST', '/byok/v1/chat/completions', self.CHAT); self.assertEqual((status, json.loads(data)['error']['code']), (404, 'no_key'))
        status, _, data = self.request(port, 'GET', '/byok/v1/models'); self.assertEqual(status, 404)

    def test_bad_sizes_and_bodies_are_refused_before_anything_is_forwarded(self):
        port = self.start()
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10); conn.request('POST', '/byok/v1/chat/completions', headers={'Authorization': 'Bearer ' + CELL_CREDENTIAL, 'Content-Length': str(mk.MAX_REQUEST_BYTES + 1)})
        self.assertEqual(conn.getresponse().status, 413); conn.close()
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10); conn.request('POST', '/byok/v1/chat/completions', headers={'Authorization': 'Bearer ' + CELL_CREDENTIAL, 'Content-Length': '0'})
        self.assertEqual(conn.getresponse().status, 413); conn.close()
        self.assertEqual(self.request(port, 'POST', '/byok/v1/chat/completions', {'no': 'messages'})[0], 400); self.assertEqual(self.up.requests, [])

    def test_the_model_list_and_the_old_routes(self):
        port = self.start()
        status, _, data = self.request(port, 'GET', '/byok/v1/models'); self.assertEqual((status, [m['id'] for m in json.loads(data)['data']]), (200, ['my-model']))
        self.assertEqual(self.request(port, 'POST', '/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})[0], 200)               # the browser tools are unaffected
        self.assertEqual(self.request(port, 'POST', '/byok/v1/embeddings', self.CHAT)[0], 404); self.assertEqual(self.request(port, 'POST', '/byok/v1/chat/completions/../x', self.CHAT)[0], 404)

    def test_without_the_feature_the_routes_do_not_exist(self):
        port = self.start(byok=False)
        self.assertEqual(self.request(port, 'POST', '/byok/v1/chat/completions', self.CHAT)[0], 404); self.assertEqual(self.request(port, 'GET', '/byok/v1/models')[0], 405)
        self.assertEqual(self.up.requests, [])

    def test_when_the_assistant_hangs_up_the_customers_connection_is_closed_and_the_slot_freed(self):
        gate = threading.Event()
        def slow(h, body):
            h.send_response(200); h.send_header('Content-Type', 'text/event-stream'); h.send_header('Connection', 'close'); h.end_headers()
            try:
                for _ in range(200):
                    h.wfile.write(b'data: {}\n\n'); h.wfile.flush(); time.sleep(0.02)
            except OSError: gate.set()
        port = self.start(slow)
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10); conn.request('POST', '/byok/v1/chat/completions', body=json.dumps({**self.CHAT, 'stream': True}), headers={'Authorization': 'Bearer ' + CELL_CREDENTIAL, 'Content-Type': 'application/json'})
        resp = conn.getresponse(); resp.read(20); resp.close(); conn.close()                         # take a little, then really hang up (the response object holds the socket)
        self.assertTrue(gate.wait(8), 'the customer endpoint was still being read after the assistant left')
        deadline = time.time() + 5
        while self.model_relay._busy.get('acct', 0) and time.time() < deadline: time.sleep(0.05)
        self.assertEqual(self.model_relay._busy.get('acct', 0), 0)


if __name__ == '__main__':
    unittest.main()
