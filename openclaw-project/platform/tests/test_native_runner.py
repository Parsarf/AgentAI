"""The native hands without a browser: how they behave when the bridge or the browser misbehaves, and how the transport and the Live view's frame loop are driven.
(The real browser is exercised by tests/e2e/test_native_browser.py.)"""
import base64
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.browse.native_runner import BRIDGE_ERROR, NativeRunner, NativeTransport, private_ip, url_allowed
from agentai_platform.browse.session import Session


class FakeBridge:
    """Answers browser.request like a cell would for a tiny page; `fail` makes a call raise or refuse."""
    def __init__(self):
        self.calls, self.url, self.fail, self.live_on, self.frames = [], 'https://shop.example/', None, [], 0

    def __call__(self, method, params):
        self.calls.append((method, params))
        if self.fail == 'down':
            raise CapabilityUnavailable('cell bridge unavailable')
        if self.fail == 'refuse':
            return {BRIDGE_ERROR: 'UNAVAILABLE'}
        if method == 'browser.live':
            self.live_on.append(params['on']); return {'on': params['on']}
        if method == 'browser.frame':
            self.frames += 1
            return {'on': True, 'seq': self.frames, 'data_b64': base64.b64encode(b'\xff\xd8\xff frame %d' % self.frames).decode()}
        if method == 'browser.shot':
            return {'data_b64': base64.b64encode(b'\xff\xd8\xff picture').decode()}
        path, body = params['path'], params.get('body') or {}
        if path == '/tabs':
            return {'tabs': [{'targetId': 'T1', 'type': 'page'}]}
        if path == '/navigate':
            self.url = body['url']
        if path == '/act' and body.get('script') == 'viewport':
            return {'result': {'w': 1280, 'h': 800, 'url': self.url, 'title': 'Shop', 'ready': 'complete'}}
        if path == '/act' and body.get('script') == 'describe':
            return {'result': {'elements': [{'ref': 1, 'tag': 'a', 'type': '', 'label': 'Home'}], 'title': 'Shop', 'url': self.url, 'text': 'hi', 'scroll': 0, 'height': 800, 'window': 800}}
        if path == '/act' and body.get('script') == 'fingerprint':
            return {'result': 'fp'}
        return {'ok': True}


class RunnerChecks(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.TemporaryDirectory(); self.addCleanup(self.out.cleanup)
        self.bridge = FakeBridge()
        self.r = NativeRunner(self.bridge, self.out.name, sleep=lambda s: None)

    def test_a_bridge_that_is_down_or_refuses_is_a_failed_command_never_a_crash(self):
        for mode in ('down', 'refuse'):
            self.bridge.fail = mode
            out = self.r.handle({'id': 1, 'cmd': 'open', 'url': 'https://shop.example/'})
            self.assertEqual(out['ok'], False, mode); self.assertIn(out['error'], ('action_failed', 'navigation_failed'))
            self.assertEqual(self.r.handle({'id': 2, 'cmd': 'snapshot'})['ok'], False)
        self.bridge.fail = None
        self.r.started = False
        self.assertTrue(self.r.handle({'id': 3, 'cmd': 'open', 'url': 'https://shop.example/'})['ok'])             # it recovers when the bridge does

    def test_a_failed_command_leaves_the_browsers_error_code_in_the_trace(self):
        class Rows:
            def __init__(s): s.rows = []
            def emit(s, kind, **fields): s.rows.append((kind, fields))
        rows = Rows()
        self.bridge.fail = 'refuse'
        session = Session(NativeTransport(self.bridge, self.out.name, runner=self.r), rows); self.addCleanup(session.t.close)
        self.assertFalse(session.open('https://shop.example/')['ok'])
        failed = [f for k, f in rows.rows if k == 'runner' and f.get('ok') is False]
        self.assertEqual((failed[0]['error'], failed[0]['detail']), ('action_failed', 'UNAVAILABLE'))

    def test_unknown_commands_and_bad_addresses_never_reach_the_browser(self):
        self.assertEqual(self.r.handle({'id': 1, 'cmd': 'eval'})['error'], 'unknown_command')
        before = len(self.bridge.calls)
        for url in ('http://10.0.0.1/', 'file:///etc/passwd', 'javascript:1', 'http://localhost/', None, 5):
            self.assertEqual(self.r.handle({'id': 1, 'cmd': 'open', 'url': url})['error'], 'url_blocked', str(url))
        self.assertEqual([c for c in self.bridge.calls[before:] if c[1].get('path') == '/navigate'], [])

    def test_open_navigates_and_reports_the_page(self):
        out = self.r.handle({'id': 1, 'cmd': 'open', 'url': 'https://shop.example/a'})
        self.assertEqual((out['ok'], out['url'], out['title']), (True, 'https://shop.example/a', 'Shop'))
        snap = self.r.handle({'id': 2, 'cmd': 'snapshot'})
        self.assertEqual((snap['snapshot'], snap['page_fp'], snap['window']), ('[1] <a> "Home"', hashlib_sha1('fp'), 800))

    def test_close_stops_the_stream_and_the_browser_even_when_the_bridge_is_gone(self):
        self.r.handle({'id': 1, 'cmd': 'open', 'url': 'https://shop.example/'})
        self.bridge.fail = 'down'
        self.assertEqual(self.r.handle({'id': 2, 'cmd': 'close'}), {'ok': True})
        self.bridge.fail = None
        self.r.handle({'id': 3, 'cmd': 'close'})
        self.assertTrue(any(c[0] == 'browser.live' and c[1] == {'on': False} for c in self.bridge.calls))
        self.assertTrue(any(c[1].get('path') == '/stop' for c in self.bridge.calls))

    def test_address_rules(self):
        for ip in ('10.1.2.3', '127.0.0.1', '169.254.169.254', '192.168.0.1', '172.16.5.5', '100.64.0.9', '0.0.0.0', '::1', 'fd00::1', 'fe80::1', '::ffff:10.0.0.1'):
            self.assertTrue(private_ip(ip), ip)
        for ip in ('8.8.8.8', '1.1.1.1', 'example.com', '2606:4700::1111'):
            self.assertFalse(private_ip(ip), ip)
        self.assertTrue(url_allowed('http://localhost:3000/', allow_loopback=True)); self.assertFalse(url_allowed('http://localhost:3000/'))
        self.assertFalse(url_allowed('https://example.com:99999/')); self.assertFalse(url_allowed('https://user:pw@example.com/')); self.assertFalse(url_allowed('x' * 3000))


def hashlib_sha1(text):
    import hashlib
    return hashlib.sha1(text.encode()).hexdigest()[:12]


class TransportChecks(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.TemporaryDirectory(); self.addCleanup(self.out.cleanup)
        self.bridge = FakeBridge()

    def transport(self, **kw):
        t = NativeTransport(self.bridge, self.out.name, runner=NativeRunner(self.bridge, self.out.name, sleep=lambda s: None))
        self.addCleanup(t.close)
        return t

    def test_the_session_speaks_to_it_exactly_as_it_does_to_the_runner(self):
        session = Session(self.transport())
        self.assertTrue(session.open('https://shop.example/')['ok'])
        self.assertEqual(session.snapshot()['snapshot'], '[1] <a> "Home"')
        view = session.view(save=True)
        self.assertTrue(view['ok'] and view['file'] and (Path(self.out.name) / view['file']).is_file())
        self.assertTrue(session.screenshot()['ok'])

    def test_a_command_that_outlasts_its_deadline_times_out_like_a_runner_that_stopped_answering(self):
        release = threading.Event()
        class Slow(NativeRunner):
            def handle(s, msg): release.wait(5); return {'ok': True}
        t = NativeTransport(self.bridge, self.out.name, runner=Slow(self.bridge, self.out.name)); self.addCleanup(release.set); self.addCleanup(t.close)
        t.send({'id': 1, 'cmd': 'snapshot'})
        with self.assertRaises(TimeoutError): t.recv(0.2)

    def test_a_crashing_command_still_answers(self):
        class Crashing(NativeRunner):
            def handle(s, msg): raise RuntimeError('boom')
        t = NativeTransport(self.bridge, self.out.name, runner=Crashing(self.bridge, self.out.name)); self.addCleanup(t.close)
        t.send({'id': 7, 'cmd': 'snapshot'})
        self.assertEqual(t.recv(2), {'ok': False, 'error': 'action_failed', 'id': 7})

    def test_after_close_nothing_more_is_accepted_and_the_browser_is_shut_down(self):
        t = self.transport()
        t.close()
        with self.assertRaises(BrokenPipeError): t.send({'id': 1, 'cmd': 'snapshot'})
        end = time.time() + 3
        while time.time() < end and not any(c[1].get('path') == '/stop' for c in self.bridge.calls): time.sleep(0.02)
        self.assertTrue(any(c[1].get('path') == '/stop' for c in self.bridge.calls))

    def test_frames_flow_only_while_someone_watches(self):
        t = self.transport()
        time.sleep(0.6)
        self.assertEqual(self.bridge.frames, 0); self.assertFalse((Path(self.out.name) / 'live.jpg').exists())          # nobody watching: no stream, no cost
        end = time.time() + 5
        while time.time() < end and not (Path(self.out.name) / 'live.jpg').exists():
            (Path(self.out.name) / 'watching').touch(); time.sleep(0.1)
        self.assertEqual((Path(self.out.name) / 'live.jpg').read_bytes()[:3], b'\xff\xd8\xff')
        self.assertIn(True, self.bridge.live_on)
        end = time.time() + 12                                                                                              # the viewer leaves: the stream is switched off
        while time.time() < end and False not in self.bridge.live_on: time.sleep(0.2)
        self.assertIn(False, self.bridge.live_on)


if __name__ == '__main__':
    unittest.main()
