"""The native hands against a real OpenClaw 2026.9.6 gateway and a real Chromium: the runner's commands answered over the real cell bridge and the real relay program, on a local test
site. Skipped when node, the pinned OpenClaw package or a Chrome/Chromium binary is not on this machine.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agentai_platform.browse.native_runner import NativeRunner, NativeTransport, url_allowed
from agentai_platform.browse.session import Session
from agentai_platform.lifecycle import cell_config
from agentai_platform.lifecycle.cell_bridge import CellBridge
from .harness import LocalRelay, free_port, openclaw_package

CHROMES = [os.environ.get('LUMINA_E2E_CHROME', ''), '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome']
CHROME = next((c for c in CHROMES if c and os.path.exists(c)), None)

PAGES = {
    '/': '''<html><head><title>Shop</title></head><body><h1>Welcome</h1>
<a href="/two">Next page</a> <a href="/popup" target="_blank">Open popup</a>
<form action="/result" method="get"><label for="q">Search</label><input id="q" name="q" type="text">
<select name="size" aria-label="Size"><option>Small</option><option>Medium</option><option>Large</option></select>
<button type="submit">Go</button></form>
<input type="password" aria-label="Password" value="hunter2"><button id="add" onclick="document.title='added'">Add to cart</button>
<div style="height:2500px">tall</div></body></html>''',
    '/shop': '<html><head><title>Shop</title></head><body><h1>Welcome to the shop</h1><a href="/two">Next page</a></body></html>',
    '/two': '<html><head><title>Two</title></head><body><h1>Second</h1><a href="/">Home</a></body></html>',
    '/popup': '<html><head><title>Popup</title></head><body><h1>Popup page</h1></body></html>',
    '/covered': '<html><head><title>Covered</title></head><body><button>Hidden under</button><div style="position:fixed;top:0;left:0;width:100%;height:100%;background:#fff;z-index:9">cookie banner</div></body></html>',
}


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/result':
            body = '<html><head><title>Result</title></head><body>You searched: ' + self.path.split('?', 1)[1].replace('<', '') + '</body></html>'
        else:
            body = PAGES.get(path)
        self.send_response(200 if body else 404)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write((body or 'nope').encode())

    def log_message(self, *args):
        pass


@unittest.skipUnless(openclaw_package() and CHROME and shutil.which('node'), 'needs node, OpenClaw 2026.9.6 and Chrome/Chromium')
class NativeHandsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='lumina-nb-'))
        (cls.root / 'state').mkdir()
        (cls.root / 'home').mkdir()
        cls.site = ThreadingHTTPServer(('127.0.0.1', 0), Site)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.site.server_port}'
        cls.port, cls.token = free_port(), 'gw-token-nb'
        config = {'gateway': {'mode': 'local', 'port': cls.port, 'bind': 'loopback', 'auth': {'mode': 'token', 'token': cls.token}},
                  'tools': {'deny': ['ask_user', 'browser']},
                  'browser': {**cell_config.NATIVE_BROWSER, 'executablePath': CHROME, 'ssrfPolicy': {'dangerouslyAllowPrivateNetwork': True}}}
        (cls.root / 'state' / 'openclaw.json').write_text(json.dumps(config))
        env = {**os.environ, 'HOME': str(cls.root / 'home'), 'OPENCLAW_STATE_DIR': str(cls.root / 'state'), 'OPENCLAW_CONFIG_PATH': str(cls.root / 'state' / 'openclaw.json')}
        cls.log = open(cls.root / 'gateway.log', 'wb')
        cls.gateway = subprocess.Popen(['node', str(openclaw_package() / 'openclaw.mjs'), 'gateway', 'run', '--port', str(cls.port), '--auth', 'token', '--token', cls.token,
                                        '--allow-unconfigured'], env=env, stdout=cls.log, stderr=subprocess.STDOUT)
        import urllib.request
        for _ in range(120):
            try:
                if urllib.request.urlopen(f'http://127.0.0.1:{cls.port}/', timeout=2).status == 200:
                    break
            except OSError:
                time.sleep(0.5)
        cls.bridge = CellBridge(lambda a: ('tnt', cls.token) if a == 'acct' else None,
                                lambda tenant, token, scopes=None: LocalRelay(cls.port, token, scopes, media_root=cls.root / 'state' / 'media' / 'browser'), lambda t: 0,
                                browser_callers={os.getuid()}, ready_timeout=60)
        cls.call = staticmethod(lambda method, params: cls.bridge.call('acct', method, params, caller=os.getuid()))

    @classmethod
    def tearDownClass(cls):
        cls.bridge.close_all()
        cls.gateway.terminate()
        try:
            cls.gateway.wait(15)
        except subprocess.TimeoutExpired:
            cls.gateway.kill()
        subprocess.run(['pkill', '-f', str(cls.root)], check=False)
        cls.site.shutdown()
        cls.log.close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix='lumina-nb-out-'))
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)
        self.r = NativeRunner(self.call, self.out, allow_loopback=True)
        self.addCleanup(self.r.close)

    def do(self, cmd, **kw):
        return self.r.handle({'id': 1, 'cmd': cmd, **kw})

    def element(self, snap, label):
        return next(e for e in snap['elements'] if e['label'] == label)

    def test_open_and_snapshot_describe_the_page_in_the_runners_format(self):
        opened = self.do('open', url=self.base + '/')
        self.assertTrue(opened['ok'], opened)
        self.assertEqual(opened['title'], 'Shop')
        snap = self.do('snapshot')
        labels = [e['label'] for e in snap['elements']]
        for wanted in ('Next page', 'Open popup', 'Search', 'Size', 'Go', 'Password', 'Add to cart'):
            self.assertIn(wanted, labels)
        self.assertIn('"Next page"', snap['snapshot'])
        self.assertEqual(self.element(snap, 'Password')['value'], '')                 # a secret field is listed, never with its value
        self.assertIn('Welcome', snap['text'])
        self.assertEqual(snap['window'], 800)
        self.assertEqual(snap['page_fp'], self.do('snapshot')['page_fp'])               # an unchanged page has an unchanged fingerprint

    def test_click_navigates_back_returns_and_a_scroll_changes_the_fingerprint(self):
        self.do('open', url=self.base + '/')
        snap = self.do('snapshot')
        link = self.element(snap, 'Next page')
        out = self.do('act', action='click', ref=link['ref'], expect={'label': 'Next page'})
        self.assertTrue(out['ok'], out)
        self.assertTrue(out['navigated'])
        self.assertTrue(out['url'].endswith('/two'))
        self.assertEqual(self.do('act', action='back')['url'], self.base + '/')
        before = self.do('snapshot')['page_fp']
        self.assertTrue(self.do('act', action='scroll', value='down')['ok'])
        self.assertNotEqual(self.do('snapshot')['page_fp'], before)

    def test_type_select_and_enter_submit_a_form(self):
        self.do('open', url=self.base + '/')
        snap = self.do('snapshot')
        self.assertTrue(self.do('act', action='type', ref=self.element(snap, 'Search')['ref'], value='red shoes', expect={'label': 'Search'})['ok'])
        self.assertTrue(self.do('act', action='select', ref=self.element(snap, 'Size')['ref'], value='large', expect={'label': 'Size'})['ok'])
        after = self.do('snapshot')
        self.assertEqual(self.element(after, 'Search')['value'], 'red shoes')
        self.assertEqual(self.element(after, 'Size')['value'], 'Large')
        self.assertEqual(self.do('act', action='select', ref=self.element(snap, 'Size')['ref'], value='Huge', expect={'label': 'Size'})['error'], 'no_option')
        self.assertTrue(self.do('act', action='press', value='Enter')['ok'])
        page = self.do('snapshot')
        self.assertIn('q=red+shoes', page['url'])
        self.assertIn('size=Large', page['url'])
        self.assertEqual(self.do('act', action='press', value='Control+C')['error'], 'key_not_allowed')

    def test_a_stale_or_covered_target_is_never_clicked(self):
        self.do('open', url=self.base + '/')
        snap = self.do('snapshot')
        add = self.element(snap, 'Add to cart')
        self.assertEqual(self.do('act', action='click', ref=add['ref'], expect={'label': 'Something else'})['error'], 'stale')
        self.assertEqual(self.do('act', action='click', ref=9999, expect={'label': 'x'})['error'], 'stale')
        self.assertEqual(self.do('snapshot')['title'], 'Shop')                           # nothing was clicked
        self.do('open', url=self.base + '/covered')
        hidden = self.element(self.do('snapshot'), 'Hidden under')
        self.assertEqual(self.do('act', action='click', ref=hidden['ref'], expect={'label': 'Hidden under'})['error'], 'covered')
        self.assertEqual(self.do('act', action='click', ref=True, expect={'label': 'x'})['error'], 'bad_action')

    def test_the_click_lands_and_the_page_reacts(self):
        self.do('open', url=self.base + '/')
        add = self.element(self.do('snapshot'), 'Add to cart')
        self.assertTrue(self.do('act', action='click', ref=add['ref'], expect={'label': 'Add to cart'})['ok'])
        self.assertEqual(self.do('snapshot')['title'], 'added')

    def test_a_link_that_opens_a_new_tab_moves_the_loop_onto_it(self):
        self.do('open', url=self.base + '/')
        link = self.element(self.do('snapshot'), 'Open popup')
        out = self.do('act', action='click', ref=link['ref'], expect={'label': 'Open popup'})
        self.assertTrue(out['ok'], out)
        self.assertTrue(out['new_tab'])
        self.assertEqual(self.do('snapshot')['title'], 'Popup')

    def test_pictures_probe_and_clicks_by_point(self):
        self.do('open', url=self.base + '/')
        snap = self.do('snapshot')
        view = self.do('view', save=True)
        self.assertTrue(view['ok'])
        import base64
        self.assertEqual(base64.b64decode(view['data'])[:3], b'\xff\xd8\xff')            # a JPEG
        self.assertTrue((self.out / view['file']).is_file())
        self.assertEqual((view['width'], view['height']), (1280, 800))
        shot = self.do('screenshot')
        self.assertTrue((self.out / shot['file']).is_file())
        box = self.ev_box('Add to cart')
        hit = self.do('probe', x=box[0], y=box[1])['hit']
        self.assertEqual((hit['tag'], hit['label'], hit['editable']), ('button', 'Add to cart', False))
        self.assertEqual(self.do('probe', x=5000, y=5)['error'], 'bad_coordinates')
        self.assertTrue(self.do('act', action='clickat', x=box[0], y=box[1])['ok'])
        self.assertEqual(self.do('snapshot')['title'], 'added')
        field = self.ev_box('Search')
        self.assertEqual(self.do('probe', x=field[0], y=field[1])['hit']['editable'], True)
        self.assertTrue(self.do('act', action='typeat', x=field[0], y=field[1], value='by point')['ok'])
        self.assertEqual(self.element(self.do('snapshot'), 'Search')['value'], 'by point')
        self.assertEqual(self.do('act', action='typeat', x=box[0], y=box[1], value='x')['error'], 'not_a_field')
        pw = self.element(snap, 'Password')
        self.assertTrue(self.do('probe', x=box[0], y=box[1])['ok'])
        self.assertEqual(self.do('act', action='clickat', x=-1, y=5)['error'], 'bad_coordinates')
        del pw

    def ev_box(self, label):
        """Centre of the labelled control in window coordinates, asked of the page itself."""
        located = self.r.ev('locate', {'ref': self.element(self.do('snapshot'), label)['ref'], 'label': label, 'action': 'click'})
        return located['x'], located['y']

    def test_the_password_field_is_named_a_secret_by_a_point_too(self):
        self.do('open', url=self.base + '/')
        box = self.ev_box('Password')
        hit = self.do('probe', x=box[0], y=box[1])['hit']
        self.assertEqual((hit['secret'], hit['label']), (True, 'Password'))

    def test_takeover_input_and_the_address_rules(self):
        self.do('open', url=self.base + '/')
        box = self.ev_box('Search')
        self.assertTrue(self.do('xy', action='click', x=box[0], y=box[1])['ok'])
        self.assertTrue(self.do('xy', action='type', text='typed by me')['ok'])
        self.assertEqual(self.element(self.do('snapshot'), 'Search')['value'], 'typed by me')
        self.assertTrue(self.do('xy', action='key', text='Backspace')['ok'])
        self.assertEqual(self.do('xy', action='key', text='F12')['error'], 'key_not_allowed')
        self.assertTrue(self.do('xy', action='scroll', text='1')['ok'])
        self.assertEqual(self.do('xy', action='goto', text='http://169.254.169.254/latest')['error'], 'url_blocked')
        self.assertEqual(self.do('xy', action='goto', text='file:///etc/passwd')['error'], 'url_blocked')
        self.assertTrue(self.do('xy', action='goto', text=self.base + '/two')['ok'])
        self.assertTrue(self.do('xy', action='back')['ok'])
        self.assertEqual(self.do('xy', action='shell', text='ls')['error'], 'bad_action')

    def test_addresses_are_judged_before_the_browser_is_asked(self):
        for bad in ('http://localhost/', 'http://127.0.0.1:3000/', 'http://10.0.0.5/', 'http://192.168.1.1/', 'http://169.254.169.254/', 'http://[::1]/', 'http://[::ffff:10.0.0.1]/',
                    'http://100.64.0.1/', 'http://printer.local/', 'http://app.internal/', 'http://user:pw@example.com/', 'ftp://example.com/', 'javascript:alert(1)', 'https://exa mple.com/', ''):
            self.assertFalse(url_allowed(bad), bad)
        self.assertTrue(url_allowed('https://example.com/a?b=1'))
        strict = NativeRunner(self.call, self.out)
        self.assertEqual(strict.handle({'id': 1, 'cmd': 'open', 'url': self.base + '/'})['error'], 'url_blocked')

    def test_the_session_and_transport_work_unchanged_and_the_live_frame_follows_the_viewer(self):
        transport = NativeTransport(self.call, self.out, runner=self.r)
        session = Session(transport)
        self.addCleanup(session.close)
        self.assertTrue(session.open(self.base + '/')['ok'])
        snap = session.snapshot()
        self.assertTrue(snap['ok'])
        self.assertTrue(session.act('click', self.element(snap, 'Add to cart')['ref'], None, 'Add to cart')['ok'])
        self.assertEqual(session.snapshot()['title'], 'added')
        (self.out / 'watching').touch()
        deadline = time.time() + 20
        while time.time() < deadline and not (self.out / 'live.jpg').exists():
            (self.out / 'watching').touch()
            time.sleep(0.3)
            session.act('scroll', None, 'down')
        self.assertTrue((self.out / 'live.jpg').exists(), 'no live frame arrived')
        self.assertEqual((self.out / 'live.jpg').read_bytes()[:3], b'\xff\xd8\xff')

    def test_a_whole_browse_job_runs_on_the_cells_browser_with_the_assistant_driving_and_leaves_nothing_running(self):
        import re
        from agentai_platform.browse import service as svc
        rid = 'c' * 32
        service = svc.BrowseService(spawn=None, native_spawn=lambda account, job, out: NativeTransport(self.call, out, runner=NativeRunner(self.call, out, sleep=lambda s: None, allow_loopback=True)),
                                    engine_for=lambda account: 'native', root=self.out, jev_mode='off', takeover_seconds=3)
        self.addCleanup(service.cancel_all)
        login = 'd' * 32
        service.start('acct', login, 'Open the account page and look at my orders', start_url=self.base + '/')           # a page with a password field: the loop's own rule hands it to the customer
        end = time.time() + 40
        while time.time() < end and service.poll('acct', login, 0)['state'] != 'handoff':
            time.sleep(0.1)
        self.assertEqual(service.poll('acct', login, 0)['state'], 'handoff'); self.assertIn('sign in', service.poll('acct', login, 0)['reason'])
        service.cancel('acct', login)
        end = time.time() + 20                                                                                              # the sign-in job releases the browser (it waits out its hand-off window)
        while time.time() < end and service.jobs[login].session is not None:
            time.sleep(0.2)
        service.start('acct', rid, 'Open the second page and tell me its heading', start_url=self.base + '/shop')

        def next_question(after):
            end = time.time() + 40
            while time.time() < end:
                polled = service.poll('acct', rid, 0)
                if polled['observation'] and polled['observation']['n'] > after:
                    return polled
                if polled['state'] in svc.FINAL:
                    raise AssertionError(polled)
                time.sleep(0.1)
            raise AssertionError(service.poll('acct', rid, 0))

        first = next_question(0)
        text = first['observation']['text']
        self.assertIn('Next page', text); self.assertIn('Welcome to the shop', text)
        ref = int(re.search(r'c(\d+): click "Next page"', text).group(1))
        service.agent_step('acct', rid, {'action': 'click', 'ref': ref})
        second = next_question(first['observation']['n'])
        self.assertIn('Second', second['observation']['text']); self.assertIn('/two', second['url'])
        service.agent_step('acct', rid, {'action': 'done', 'answer': 'The heading is Second.'})
        end = time.time() + 20
        while time.time() < end and service.poll('acct', rid, 0)['state'] not in svc.FINAL:
            time.sleep(0.1)
        final = service.poll('acct', rid, 0)
        self.assertEqual((final['state'], final['answer']), ('done', 'The heading is Second.'))
        steps = [e for e in final['events'] if e['kind'] == 'step']
        self.assertEqual([(e['by'], e['action'], e['label'], e['result']) for e in steps], [('agent', 'click', 'Next page', 'ok')])
        end = time.time() + 15
        while time.time() < end and self.call('browser.request', {'method': 'GET', 'path': '/'}).get('running'):
            time.sleep(0.2)
        self.assertFalse(self.call('browser.request', {'method': 'GET', 'path': '/'})['running'])          # the job is over: no browser is left running in the cell

    def test_closing_shuts_the_browser_down(self):
        self.do('open', url=self.base + '/')
        self.assertTrue(self.call('browser.request', {'method': 'GET', 'path': '/'})['running'])
        self.r.close()
        self.assertFalse(self.call('browser.request', {'method': 'GET', 'path': '/'})['running'])


if __name__ == '__main__':
    unittest.main()
