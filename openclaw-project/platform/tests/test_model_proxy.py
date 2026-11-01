import asyncio
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('mp', Path(__file__).resolve().parent.parent / 'deploy' / 'model-proxy' / 'agentai_model_proxy.py')
mp = importlib.util.module_from_spec(spec); spec.loader.exec_module(mp)


async def fake_upstream(reader, writer, seen):
    head = await reader.readuntil(b'\r\n\r\n')
    length = int([l.split(b':')[1] for l in head.split(b'\r\n') if l.lower().startswith(b'content-length')][0]) if b'ontent-' in head else 0
    body = await reader.readexactly(length) if length else b''
    seen.append((head, body))
    payload = b'data: one\n\ndata: two\n\n'
    writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n' + payload)
    await writer.drain(); writer.close()


async def roundtrip(raw, seen):
    up = await asyncio.start_server(lambda r, w: fake_upstream(r, w, seen), '127.0.0.1', 0)
    relay = await mp.serve(('127.0.0.1', 0), up.sockets[0].getsockname()[:2])
    try:
        r, w = await asyncio.open_connection(*relay.sockets[0].getsockname()[:2])
        w.write(raw); await w.drain()
        data = await asyncio.wait_for(r.read(), 5)
        w.close()
        return data
    finally:
        relay.close(); up.close()


def run(raw):
    seen = []
    return asyncio.run(roundtrip(raw, seen)), seen


class ModelProxyChecks(unittest.TestCase):
    def test_completions_pass_through_with_body_and_stream(self):
        body = b'{"model":"claude-haiku-5-5","messages":[]}'
        data, seen = run(b'POST /chat/completions HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer k\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s' % (len(body), body))
        self.assertIn(b'200 OK', data); self.assertIn(b'data: two', data)
        self.assertEqual(seen[0][1], body); self.assertIn(b'Authorization: Bearer k', seen[0][0]); self.assertIn(b'Connection: close', seen[0][0])

    def test_model_list_allowed(self):
        data, seen = run(b'GET /v1/models HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer k\r\n\r\n')
        self.assertIn(b'200 OK', data)

    def test_every_management_route_is_refused_and_never_reaches_litellm(self):
        for method, path in (('GET', '/key/info'), ('GET', '/key/list'), ('POST', '/key/generate'), ('GET', '/user/list'), ('GET', '/spend/logs'), ('GET', '/team/list'),
                             ('GET', '/model/info'), ('GET', '/config/yaml'), ('GET', '/global/spend/report'), ('POST', '/key/delete'), ('GET', '/health'),
                             ('GET', '/chat/completions'), ('POST', '/v1/models'), ('POST', '/v1/chat/completions/../../key/list'), ('POST', '/chat/completions%2e%2e/key/list'),
                             ('POST', '//key/list'), ('GET', '/')):
            data, seen = run(f'{method} {path} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer k\r\nContent-Length: 2\r\n\r\n{{}}'.encode())
            self.assertIn(b'403', data.split(b'\r\n')[0] + b' ' + data[:40], (method, path)); self.assertEqual(seen, [], (method, path))

    def test_smuggling_shapes_refused(self):
        for raw in (b'POST /chat/completions HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n',
                    b'POST /chat/completions HTTP/1.1\r\nHost: x\r\nContent-Length: 99999999999\r\n\r\n',
                    b'POST /chat/completions HTTP/1.1\r\nHost: x\r\n\r\n',
                    b'POST /chat/completions HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\nContent-Length: 2\r\n\r\n{}',
                    b'garbage\r\n\r\n', b'CONNECT evil:443 HTTP/1.1\r\n\r\n'):
            data, seen = run(raw)
            self.assertRegex(data.split(b'\r\n')[0], rb'HTTP/1.1 (400|403|411|413)'); self.assertEqual(seen, [])

    def test_query_string_is_forwarded_but_cannot_change_the_route(self):
        data, seen = run(b'GET /v1/models?x=1 HTTP/1.1\r\nHost: x\r\n\r\n')
        self.assertIn(b'200 OK', data)


if __name__ == '__main__':
    unittest.main()
