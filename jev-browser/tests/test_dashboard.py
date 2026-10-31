"""The dashboard end to end: a real (headless) Chrome on the tiny local shop, a stand-in for JEV, and the dashboard's own web interface."""
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from jevbrowse.browser import find_chrome
from jevbrowse.dashboard import App, serve
from tests.test_loop import Shop, fake_jev


def with_log(jev, log):
    jev.log = log
    return jev


@unittest.skipUnless(find_chrome(), 'needs Chrome and Node')
class Dashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shop = ThreadingHTTPServer(('127.0.0.1', 0), Shop)
        threading.Thread(target=cls.shop.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.shop.server_address[1]}'
        cls.tmp = tempfile.mkdtemp()
        cls.script = lambda state, q: {'operation': 'click', 'at': 'Place order'}
        cls.app = App(Path(cls.tmp), jev_factory=lambda log: with_log(fake_jev(lambda s, q: cls.script(s, q)), log))
        cls.server = serve(cls.app, 0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.shop.shutdown(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, path, body=None, headers=None):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=None if body is None else json.dumps(body).encode(), method='GET' if body is None else 'POST',
                                     headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def start(self, goal='add boxer briefs size M', path='/product', **extra):
        status, body = self.call('/api/run', {'goal': goal, 'url': self.base + path, 'visible': False, **extra})
        self.assertEqual(status, 200, body)
        return json.loads(body)['id']

    def wait(self, rid, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            s = json.loads(self.call(f'/api/run/{rid}?since=0')[1])
            if not s['active']:
                return s
            time.sleep(0.2)
        self.fail('the run did not finish')

    def test_a_run_shows_every_step_with_pictures_and_lands_in_earlier_runs(self):
        type(self).script = staticmethod(lambda state, q: {'operation': 'click', 'at': 'Place order'})
        rid = self.start()
        s = self.wait(rid)
        self.assertEqual(s['status'], 'sensitive'); self.assertIn('Place order', s['detail'])
        kinds = [r['kind'] for r in s['rows']]
        for kind in ('run_start', 'browser_start', 'page', 'jev_call', 'jev_answer', 'decision', 'safety_stop', 'end'):
            self.assertIn(kind, kinds)
        page = next(r for r in s['rows'] if r['kind'] == 'page')
        self.assertTrue(page['shot'])
        status, body = self.call(f'/api/shot/{rid}/{page["shot"]}')
        self.assertEqual((status, body[:2]), (200, b'\xff\xd8'))                                  # a real JPEG of the page JEV was shown
        past = json.loads(self.call('/api/status')[1])['past']
        self.assertTrue(any(p['id'] == rid and p['status'] == 'sensitive' and 'boxer briefs' in p['goal'] for p in past))
        later = json.loads(self.call(f'/api/run/{rid}?since={len(s["rows"]) - 1}')[1])
        self.assertEqual(len(later['rows']), 1)                                                    # only what is new since the last poll

    def test_stop_ends_a_run_that_would_go_on(self):
        type(self).script = staticmethod(lambda state, q: {'operation': 'scroll_down'})
        rid = self.start(steps=60)
        time.sleep(1.5)
        self.assertEqual(self.call(f'/api/run/{rid}/stop', {})[0], 200)
        s = self.wait(rid)
        self.assertEqual(s['status'], 'stopped')

    def test_only_one_run_at_a_time(self):
        type(self).script = staticmethod(lambda state, q: {'operation': 'scroll_down'})
        rid = self.start(steps=60)
        status, body = self.call('/api/run', {'goal': 'another one', 'url': self.base + '/', 'visible': False})
        self.assertEqual(status, 409)
        self.call(f'/api/run/{rid}/stop', {}); self.wait(rid)

    def test_bad_input_and_foreign_hosts_are_refused(self):
        self.assertEqual(self.call('/api/status', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.call('/api/run', {'goal': 'x'})[0], 400)
        self.assertEqual(self.call('/api/run', {'goal': 'order underwear'})[0], 400)               # no site named and no start page
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/run', data=b'goal=hello', method='POST', headers={'Content-Type': 'text/plain'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 415)                                                   # a form on another website cannot start a run
        self.assertEqual(self.call('/api/shot/20260101-000000/../../x.jpg')[0], 404)
        self.assertEqual(self.call('/')[0], 200)


if __name__ == '__main__':
    unittest.main()
