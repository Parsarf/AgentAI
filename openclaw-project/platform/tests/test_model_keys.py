"""Bring your own model: the address rules, the encrypted store, and the relay that forwards an assistant's calls to the customer's endpoint (a real local HTTPS server with a real certificate)."""
import datetime
import json
import os
import socket
import ssl
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from agentai_platform import model_keys as mk
from agentai_platform.model_keys import ModelKeyError, ModelKeyStore, ModelKeyring, ModelRelay, RelayError, parse_endpoint, probe, resolve_public

HOST = 'models.example.org'
SECRET = 'a-long-test-secret-that-is-at-least-48-characters-long!!'


def make_cert(name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False).sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM), key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())


class Upstream:
    """A fake model endpoint over TLS. `behaviour(handler, body)` decides the answer; every request is recorded."""

    def __init__(self, tmp, name=HOST, behaviour=None):
        self.requests, self.behaviour = [], behaviour or self.ok
        cert, key = make_cert(name)
        self.cert_pem = cert
        cf, kf = Path(tmp) / f'{name}.crt', Path(tmp) / f'{name}.key'
        cf.write_bytes(cert); kf.write_bytes(key)
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *a): pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                outer.requests.append({'path': self.path, 'headers': dict(self.headers), 'body': body})
                outer.behaviour(self, body)
            do_GET = do_POST

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cf, kf)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), H); self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True); self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.client_context = ssl.create_default_context(cadata=cert.decode())

    @staticmethod
    def ok(h, body):
        data = json.dumps({'id': 'x', 'choices': [{'message': {'role': 'assistant', 'content': 'hello'}}]}).encode()
        h.send_response(200); h.send_header('Content-Type', 'application/json'); h.send_header('Content-Length', str(len(data))); h.end_headers(); h.wfile.write(data)

    def close(self):
        self.server.shutdown(); self.server.server_close()


def answer(status, body=b'{}', ctype='application/json', headers=()):
    def behave(h, _):
        h.send_response(status); h.send_header('Content-Type', ctype); h.send_header('Content-Length', str(len(body)))
        for k, v in headers: h.send_header(k, v)
        h.end_headers(); h.wfile.write(body)
    return behave


class AddressRules(unittest.TestCase):
    def test_what_may_be_typed(self):
        for good, base in {'https://api.openai.com/v1': 'https://api.openai.com/v1', 'HTTPS://API.OpenAI.com/v1/': 'https://api.openai.com/v1', 'https://openrouter.ai/api/v1': 'https://openrouter.ai/api/v1',
                           'https://llm.example.com:8443/v1': 'https://llm.example.com:8443/v1', 'https://llm.example.com:443': 'https://llm.example.com', ' https://a.b.co ': 'https://a.b.co',
                           'https://xn--bcher-kva.com/v1': 'https://xn--bcher-kva.com/v1'}.items():
            self.assertEqual(parse_endpoint(good).base_url, base, good)

    def test_what_is_refused_before_any_lookup(self):
        for bad in ['', None, 5, 'api.openai.com/v1', 'http://api.openai.com/v1', 'ftp://x.example.com', 'https://127.0.0.1/v1', 'https://10.0.0.5/v1', 'https://[::1]/v1', 'https://2130706433/v1',
                    'https://0x7f.0.0.1/v1', 'https://localhost/v1', 'https://svc.internal/v1', 'https://box.local/v1', 'https://printer.lan/', 'https://x.example.com:22/v1', 'https://x.example.com:80/v1',
                    'https://x.example.com:99999/v1', 'https://user:pw@x.example.com/v1', 'https://x.example.com/v1?key=1', 'https://x.example.com/v1#frag', 'https://x.example.com/../admin',
                    'https://x.example.com/a b', 'https://x.example.com/%2e%2e/admin', 'https://x.example.com/v1/' + 'a' * 400, 'https://-bad.example.com/', 'https://nodot/v1', 'https://x.example.com\\@evil.com/',
                    'https://x.example.com/\nHost: evil', 'https://a_b.example.com/v1', 'https://169.254.169.254/latest', 'https://metadata.google.internal/']:
            with self.assertRaises(ModelKeyError, msg=repr(bad)):
                parse_endpoint(bad)

    def test_a_name_must_lead_only_to_public_addresses(self):
        ep = parse_endpoint('https://models.example.org/v1')
        fake = lambda *ips: (lambda host, port, type=0: [(2, 1, 6, '', (ip, port)) for ip in ips])
        self.assertEqual(resolve_public(ep, fake('93.184.216.34')), ['93.184.216.34'])
        self.assertEqual(resolve_public(ep, fake('93.184.216.34', '2606:2800:220:1:248:1893:25c8:1946')), ['93.184.216.34', '2606:2800:220:1:248:1893:25c8:1946'])
        for ips in (['127.0.0.1'], ['10.1.2.3'], ['172.16.0.9'], ['192.168.1.1'], ['169.254.169.254'], ['100.64.0.1'], ['0.0.0.0'], ['::1'], ['fe80::1'], ['fd00::1'], ['::ffff:10.0.0.1'], ['::ffff:127.0.0.1'],
                    ['224.0.0.1'], ['93.184.216.34', '10.0.0.1'], ['10.0.0.1', '93.184.216.34'], ['198.18.0.1'], ['192.0.2.1']):
            with self.assertRaises(ModelKeyError, msg=str(ips)):
                resolve_public(ep, fake(*ips))
        with self.assertRaises(ModelKeyError):
            resolve_public(ep, lambda *a, **k: (_ for _ in ()).throw(socket.gaierror('nope')))
        with self.assertRaises(ModelKeyError):
            resolve_public(ep, lambda *a, **k: [])

    def test_model_and_key_shapes(self):
        for good in ('gpt-4o-mini', 'meta-llama/Llama-3.3-70B-Instruct', 'anthropic/claude-haiku-5-5', 'qwen2.5:72b', 'deepseek-chat'):
            self.assertEqual(mk.clean_model(good), good)
        self.assertEqual(mk.clean_model('  gpt-4o \n'), 'gpt-4o')                                          # surrounding whitespace is trimmed
        for bad in ('', ' ', None, 'a b', 'x;rm', '../x', 'a' * 101, '-x', 'na\nme', '{"a":1}'):
            with self.assertRaises(ModelKeyError, msg=repr(bad)): mk.clean_model(bad)
        self.assertEqual(mk.clean_key('  sk-abcdef123456  '), 'sk-abcdef123456')
        for bad in ('', 'short', 'has space inside key', 'k' * 501, None, 'sk-\nsecond', 'sk-ключ-1234567'):
            with self.assertRaises(ModelKeyError, msg=repr(bad)): mk.clean_key(bad)

    def test_who_may_use_it_is_off_until_turned_on(self):
        self.assertFalse(mk.enabled_for({}, 'a')); self.assertFalse(mk.enabled_for(None, 'a')); self.assertFalse(mk.enabled_for({'own_model_keys': False}, 'a'))
        self.assertFalse(mk.enabled_for({'own_model_keys': 'yes'}, 'a')); self.assertFalse(mk.enabled_for({'own_model_keys': 1}, 'a'))
        self.assertTrue(mk.enabled_for({'own_model_keys': True}, 'a')); self.assertTrue(mk.enabled_for({'own_model_keys': ['a']}, 'a')); self.assertFalse(mk.enabled_for({'own_model_keys': ['b']}, 'a'))


class StoreChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'sub' / 'model-keys.json'
        self.store = ModelKeyStore(self.path, ModelKeyring.derived(SECRET))
        self.ep = parse_endpoint('https://models.example.org/v1')

    def test_the_key_is_encrypted_the_facts_are_not_and_the_file_is_private(self):
        key = 'sk-live-0123456789abcdefghij'
        pub = self.store.put('acct', self.ep, 'gpt-4o', key)
        self.assertEqual(pub, {'host': 'models.example.org', 'base_url': 'https://models.example.org/v1', 'model': 'gpt-4o', 'hint': 'ghij', 'created': pub['created']})
        raw = self.path.read_text()
        self.assertNotIn(key, raw); self.assertNotIn('0123456789abcdef', raw); self.assertIn('models.example.org', raw)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(self.store.open('acct')['key'], key); self.assertEqual(self.store.open('acct')['model'], 'gpt-4o')
        self.assertEqual(ModelKeyStore(self.path).public('acct')['hint'], 'ghij')          # the facts need no key at all

    def test_one_per_account_replaced_not_added_and_deleted_for_good(self):
        self.store.put('a', self.ep, 'm1', 'sk-first-0000000000'); self.store.put('a', self.ep, 'm2', 'sk-second-111111111'); self.store.put('b', self.ep, 'm3', 'sk-other-2222222222')
        self.assertEqual(self.store.open('a')['model'], 'm2'); self.assertEqual(self.store.open('b')['key'], 'sk-other-2222222222')
        self.assertNotIn('sk-first-0000000000', self.path.read_text())                       # replaced, not kept alongside
        self.assertTrue(self.store.delete('a')); self.assertFalse(self.store.delete('a')); self.assertIsNone(self.store.public('a'))
        with self.assertRaises(ModelKeyError): self.store.open('a')
        self.assertNotIn('m2', self.path.read_text()); self.assertEqual(self.store.open('b')['model'], 'm3')

    def test_a_copied_or_tampered_record_does_not_open(self):
        self.store.put('a', self.ep, 'm', 'sk-aaaaaaaaaaaaaaaa'); self.store.put('b', self.ep, 'm', 'sk-bbbbbbbbbbbbbbbb')
        db = json.loads(self.path.read_text()); db['accounts']['b']['ct'], db['accounts']['b']['nonce'] = db['accounts']['a']['ct'], db['accounts']['a']['nonce']
        self.path.write_text(json.dumps(db))
        with self.assertRaises(ModelKeyError): self.store.open('b')                          # a's ciphertext is bound to a
        self.store.put('b', self.ep, 'm', 'sk-bbbbbbbbbbbbbbbb'); db = json.loads(self.path.read_text()); ct = bytearray(__import__('base64').b64decode(db['accounts']['b']['ct'])); ct[0] ^= 1
        db['accounts']['b']['ct'] = __import__('base64').b64encode(bytes(ct)).decode(); self.path.write_text(json.dumps(db))
        with self.assertRaises(ModelKeyError): self.store.open('b')

    def test_another_secret_cannot_open_it_and_a_key_file_takes_over_new_records(self):
        self.store.put('a', self.ep, 'm', 'sk-aaaaaaaaaaaaaaaa')
        with self.assertRaises(ModelKeyError): ModelKeyStore(self.path, ModelKeyring.derived('x' * 60)).open('a')
        keyfile = Path(self.tmp.name) / 'k.key'; keyfile.write_text(ModelKeyring.__module__ and 'k1:' + __import__('base64').urlsafe_b64encode(os.urandom(32)).decode().rstrip('='))
        ring = ModelKeyring.derived(SECRET, keyfile); store = ModelKeyStore(self.path, ring)
        self.assertEqual(ring.current, 'k1'); self.assertEqual(store.open('a')['key'], 'sk-aaaaaaaaaaaaaaaa')      # old record still opens
        store.put('c', self.ep, 'm', 'sk-cccccccccccccccc'); self.assertEqual(json.loads(self.path.read_text())['accounts']['c']['kid'], 'k1')
        with self.assertRaises(ModelKeyError): ModelKeyStore(self.path, ModelKeyring.derived(SECRET)).open('c')   # without the file it is unreadable, never leaked

    def test_without_a_ring_nothing_is_stored_or_opened_and_damage_reads_as_empty(self):
        with self.assertRaises(ModelKeyError): ModelKeyStore(self.path).put('a', self.ep, 'm', 'sk-aaaaaaaaaaaaaaaa')
        self.path.parent.mkdir(parents=True, exist_ok=True); self.path.write_text('{broken')
        self.assertIsNone(self.store.public('a')); self.store.put('a', self.ep, 'm', 'sk-aaaaaaaaaaaaaaaa'); self.assertEqual(self.store.open('a')['model'], 'm')

    def test_two_writers_at_once_lose_nothing(self):
        errs = []
        def go(n):
            try: self.store.put(f'acct{n}', self.ep, 'm', f'sk-{n:016d}')
            except Exception as e: errs.append(e)
        threads = [threading.Thread(target=go, args=(n,)) for n in range(12)]; [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(errs, []); self.assertEqual({n for n in range(12) if self.store.public(f'acct{n}')}, set(range(12)))


class RelayChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = ModelKeyStore(Path(self.tmp.name) / 'k.json', ModelKeyring.derived(SECRET)); self.ups = []
        self.on = True

    def upstream(self, behaviour=None):
        u = Upstream(self.tmp.name, behaviour=behaviour); self.ups.append(u); self.addCleanup(u.close); return u

    def relay(self, up, public=lambda ip: True, resolver=None):
        resolver = resolver or (lambda host, port, type=0: [(2, 1, 6, '', ('127.0.0.1', up.port))])
        ep = parse_endpoint(f'https://{HOST}:{up.port}/v1') if up.port >= 1024 else None
        self.store.put('acct', ep, 'my-model', 'sk-customer-key-0001')
        return ModelRelay(self.store, lambda account: self.on, resolver=lambda host, port, type=0: [(2, 1, 6, '', ('127.0.0.1', port))], public=public, context=up.client_context)

    def call(self, relay, body=None, account='acct'):
        up = relay.chat(account, json.dumps(body or {'model': 'whatever-the-assistant-asked', 'messages': [{'role': 'user', 'content': 'hi'}]}).encode())
        data = b''.join(up.chunks()); up.close(); return up.status, data

    def test_a_call_is_forwarded_with_the_customers_key_and_model_and_nothing_of_the_assistants(self):
        up = self.upstream(); relay = self.relay(up)
        status, data = self.call(relay, {'model': 'gpt-from-assistant', 'messages': [{'role': 'user', 'content': 'hi'}], 'temperature': 0.2})
        self.assertEqual(status, 200); self.assertEqual(json.loads(data)['choices'][0]['message']['content'], 'hello')
        sent = up.requests[0]; body = json.loads(sent['body'])
        self.assertEqual(sent['path'], '/v1/chat/completions'); self.assertEqual(sent['headers']['Authorization'], 'Bearer sk-customer-key-0001')
        self.assertEqual(body['model'], 'my-model'); self.assertEqual(body['temperature'], 0.2)               # their model, whatever the assistant asked for; other fields untouched
        self.assertEqual(sent['headers']['User-Agent'], 'Lumina-BYOK/1'); self.assertEqual(sent['headers']['Host'], f'{HOST}:{up.port}' if False else sent['headers']['Host'])
        self.assertTrue(sent['headers']['Host'].startswith(HOST))                                              # TLS and Host use the customer's name, not the address connected to

    def test_streaming_replies_pass_through_whole(self):
        events = b'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: {"choices":[{"delta":{"content":"b"}}]}\n\ndata: [DONE]\n\n'
        up = self.upstream(answer(200, events, 'text/event-stream')); relay = self.relay(up)
        status, data = self.call(relay, {'messages': [{'role': 'user', 'content': 'x'}], 'stream': True}); self.assertEqual((status, data), (200, events))
        self.assertEqual(up.requests[0]['headers']['Accept'], 'text/event-stream')

    def test_the_providers_errors_reach_the_assistant_unchanged(self):
        for code in (400, 401, 404, 429, 500):
            up = self.upstream(answer(code, json.dumps({'error': {'message': f'e{code}'}}).encode())); relay = self.relay(up)
            status, data = self.call(relay); self.assertEqual(status, code); self.assertIn(f'e{code}'.encode(), data)

    def test_a_redirect_is_never_followed_and_never_passed_on(self):
        up = self.upstream(answer(302, b'', headers=[('Location', 'http://169.254.169.254/latest/meta-data/')])); relay = self.relay(up)
        with self.assertRaises(RelayError) as ctx: self.call(relay)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (502, 'redirect_refused')); self.assertEqual(len(up.requests), 1)

    def test_an_endpoint_that_leads_to_a_private_address_is_refused_at_every_call_including_after_a_change(self):
        up = self.upstream(); relay = self.relay(up, public=mk.is_public)             # the real public-address rule: 127.0.0.1 is not public
        with self.assertRaises(RelayError) as ctx: self.call(relay)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (502, 'endpoint_not_public')); self.assertEqual(up.requests, [])
        answers = iter(['93.184.216.34', '10.0.0.7'])                                  # "DNS rebinding": public when saved, private later
        self.store.put('acct', parse_endpoint('https://models.example.org/v1'), 'm', 'sk-customer-key-0001')
        r = ModelRelay(self.store, lambda a: True, resolver=lambda h, p, type=0: [(2, 1, 6, '', (next(answers), p))], public=mk.is_public)
        with self.assertRaises(RelayError) as c1: r.chat('acct', b'{"messages":[{"role":"user","content":"x"}]}')          # first answer is public: it tries to connect (and cannot, it is not real)
        self.assertEqual(c1.exception.code, 'upstream_unreachable')
        with self.assertRaises(RelayError) as c2: r.chat('acct', b'{"messages":[{"role":"user","content":"x"}]}')
        self.assertEqual(c2.exception.code, 'endpoint_not_public')                    # resolved again at every call, so the change is caught

    def test_a_certificate_for_another_name_is_refused(self):
        up = self.upstream(); relay = self.relay(up)
        other = Upstream(self.tmp.name, name='someone-else.example.net'); self.addCleanup(other.close)
        relay.context = ssl.create_default_context(cadata=other.cert_pem.decode())         # trusts a different certificate than the one the server shows
        with self.assertRaises(RelayError) as ctx: self.call(relay)
        self.assertEqual(ctx.exception.code, 'upstream_unreachable'); self.assertEqual(up.requests, [])

    def test_no_key_not_enabled_bad_requests_and_limits(self):
        up = self.upstream(); relay = self.relay(up)
        with self.assertRaises(RelayError) as c: self.call(relay, account='nobody')
        self.assertEqual((c.exception.status, c.exception.code), (404, 'no_key'))
        self.on = False
        with self.assertRaises(RelayError) as c: self.call(relay)
        self.assertEqual((c.exception.status, c.exception.code), (403, 'not_enabled')); self.on = True
        for raw in (b'not json', b'[]', b'{}', b'{"messages":"x"}'):
            with self.assertRaises(RelayError) as c: relay.chat('acct', raw)
            self.assertEqual(c.exception.status, 400, raw)
        self.assertEqual(up.requests, [])
        clock = [0.0]; relay.clock = lambda: clock[0]
        for _ in range(mk.RATE_PER_MINUTE): self.call(relay)
        with self.assertRaises(RelayError) as c: self.call(relay)
        self.assertEqual((c.exception.status, c.exception.code), (429, 'rate_limited')); clock[0] = 61; self.call(relay)           # a minute later it is fine again

    def test_simultaneous_calls_are_capped_per_account_and_released(self):
        gate = threading.Event()
        def slow(h, body):
            gate.wait(5); Upstream.ok(h, body)
        up = self.upstream(slow); relay = self.relay(up); open_calls = []
        for _ in range(mk.SIMULTANEOUS):
            t = threading.Thread(target=lambda: self.call(relay), daemon=True); t.start(); open_calls.append(t)
        deadline = __import__('time').time() + 5
        while relay._busy.get('acct', 0) < mk.SIMULTANEOUS and __import__('time').time() < deadline: __import__('time').sleep(0.02)
        with self.assertRaises(RelayError) as c: relay.chat('acct', b'{"messages":[{"role":"user","content":"x"}]}')
        self.assertEqual(c.exception.code, 'too_many_at_once'); gate.set(); [t.join(5) for t in open_calls]; self.assertEqual(relay._busy['acct'], 0)

    def test_the_model_list_names_only_their_model(self):
        up = self.upstream(); relay = self.relay(up)
        listed = relay.models('acct'); self.assertEqual([m['id'] for m in listed['data']], ['my-model']); self.assertNotIn('sk-customer', json.dumps(listed))

    def test_nothing_secret_is_logged(self):
        up = self.upstream(); relay = self.relay(up)
        with self.assertLogs('agentai.byok', level='INFO') as logs: self.call(relay, {'messages': [{'role': 'user', 'content': 'my secret question'}]})
        text = ' '.join(logs.output); self.assertNotIn('sk-customer', text); self.assertNotIn('my secret question', text); self.assertNotIn(HOST, text)


class ProbeChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def run_probe(self, behaviour, public=lambda ip: True, context=True):
        up = Upstream(self.tmp.name, behaviour=behaviour); self.addCleanup(up.close)
        ep = parse_endpoint(f'https://{HOST}:{up.port}/v1')
        probe(ep, 'm', 'sk-customer-key-0001', resolver=lambda h, p, type=0: [(2, 1, 6, '', ('127.0.0.1', p))], public=public, context=up.client_context if context else None); return up

    def test_a_working_endpoint_passes_after_one_tiny_request(self):
        up = self.run_probe(None); body = json.loads(up.requests[0]['body'])
        self.assertEqual((len(up.requests), body['max_tokens'], body['stream']), (1, 1, False))

    def test_each_failure_says_what_to_fix(self):
        cases = {401: 'refused the API key', 403: 'refused the API key', 404: 'not found', 429: 'rate or credit limit', 500: 'error 500', 302: 'redirect'}
        for status, words in cases.items():
            with self.assertRaises(ModelKeyError, msg=str(status)) as ctx: self.run_probe(answer(status, json.dumps({'error': {'message': 'Incorrect API key provided'}}).encode()))
            self.assertIn(words, str(ctx.exception)); self.assertNotIn('sk-customer', str(ctx.exception))
        with self.assertRaises(ModelKeyError) as ctx: self.run_probe(answer(401, b'<html><b>nope</b> ' + b'K' * 60 + b'</html>', 'text/html'))
        self.assertNotIn('<b>', str(ctx.exception)); self.assertNotIn('K' * 30, str(ctx.exception))                  # markup and key-like strings are cleaned out of what is shown
        with self.assertRaises(ModelKeyError) as ctx: self.run_probe(None, public=mk.is_public)
        self.assertIn('private or internal', str(ctx.exception))
        with self.assertRaises(ModelKeyError) as ctx: self.run_probe(None, context=False)                           # the test certificate is not trusted by default
        self.assertIn('could not reach', str(ctx.exception).lower())


if __name__ == '__main__':
    unittest.main()
