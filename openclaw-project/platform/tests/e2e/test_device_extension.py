"""The two halves together: the platform's device gateway and runner-protocol transport (Python) against the extension's real executor in a real Chrome (Node), over a real
WebSocket. Pairing, reconnecting with the token, a browse session on the mock shop, pictures as files, and revoking. Skipped when node, Chrome or Playwright is missing."""
import json
from pathlib import Path
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from agentai_platform.browse import devices as dv
from agentai_platform.browse.device_gateway import DeviceGateway, make_server
from agentai_platform.browse.device_transport import DeviceTransport
from agentai_platform.browse.session import Session

BROWSE = Path(__file__).resolve().parents[3] / 'browse'
CHROME = os.environ.get('BROWSE_CHROME') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
SIM = BROWSE / 'extension' / 'dev' / 'device-sim.mjs'
READY = shutil.which('node') and Path(CHROME).exists() and (BROWSE / 'node_modules' / 'playwright-core').exists() and SIM.exists()


class Sim:
    """The simulated extension as a child process; its events arrive as JSON lines."""
    def __init__(self, port, **auth):
        argv = ['node', str(SIM), '--url', f'ws://127.0.0.1:{port}/v1/device'] + [x for k, v in auth.items() for x in ('--' + k, v)]
        self.proc = subprocess.Popen(argv, cwd=BROWSE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, 'BROWSE_CHROME': CHROME})
        self.events = queue.Queue(); self.seen = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            try: self.events.put(json.loads(line))
            except ValueError: self.seen.append(line)

    def wait(self, key, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try: ev = self.events.get(timeout=0.2)
            except queue.Empty: continue
            if key in ev: return ev[key]
        raise AssertionError(f'no {key!r} event from the simulated extension; other output: {self.seen[-5:]}')

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(10)
            except subprocess.TimeoutExpired: self.proc.kill()
        self.proc.stdout.close()


@unittest.skipUnless(READY, 'needs node, Chrome and browse/node_modules/playwright-core')
class DeviceEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = dv.DeviceStore(Path(self.tmp.name) / 'devices.json'); self.hub = dv.DeviceHub()
        self.gateway = DeviceGateway(self.store, self.hub)
        self.server = make_server(self.gateway, '127.0.0.1', 0); self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.sims = []
        self.addCleanup(lambda: ([s.stop() for s in self.sims], self.server.shutdown(), self.server.server_close()))

    def sim(self, **auth):
        s = Sim(self.port, **auth); self.sims.append(s); return s

    def link(self, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            link = self.hub.link('acct')
            if link: return link
            time.sleep(0.05)
        raise AssertionError('the extension never connected')

    def test_pair_browse_come_back_and_revoke(self):
        sim = self.sim(pair=self.store.pair('acct')); shop = sim.wait('shop')
        welcome = sim.wait('welcome'); token = welcome['token']
        self.assertTrue(token); self.assertEqual(self.store.devices('acct')[0]['label'], 'Simulated Chrome')

        link = self.link(); out = Path(self.tmp.name) / 'job'; out.mkdir()
        t = DeviceTransport(link, out); s = Session(t)
        o = s.open(shop + '/'); self.assertTrue(o['ok'], o); self.assertEqual(o['title'], 'Paddle Shop')
        snap = s.snapshot(); self.assertTrue(snap['ok']); self.assertIn('Add to cart', snap['snapshot']); self.assertIn('IGNORE ALL RULES', snap['text'])
        ref = next(e for e in snap['elements'] if e['label'] == 'Add to cart')
        a = s.act('click', ref=ref['ref'], label=ref['label']); self.assertTrue(a['ok'], a); self.assertTrue(a['navigated']); self.assertTrue(a['url'].endswith('/cart'))
        v = s.view(); self.assertTrue(v['ok']); self.assertEqual((v['width'], v['height']), (1280, 800))
        shot = s.screenshot(); self.assertEqual(shot['file'], 'shot-001.jpg'); self.assertEqual((out / 'shot-001.jpg').read_bytes()[:3], b'\xff\xd8\xff')
        self.assertEqual(s.open('http://192.168.1.1/')['error'], 'url_blocked')                    # the extension refuses a private address even if the platform asked
        self.assertEqual(s.act('press', value='F5')['error'], 'key_not_allowed')
        s.close()
        self.assertTrue(link.alive, 'the computer stays paired and connected after the task')

        sim.proc.terminate(); sim.wait('closed')                                                   # Chrome quit; come back with the token, no code
        self.assertTrue(self._gone(), 'the platform noticed Chrome left')
        again = self.sim(token=token); again.wait('ready'); self.assertNotIn('token', again.wait('welcome'))
        self.link()
        self.store.revoke('acct', welcome['device_id']); self.gateway.sweep()
        self.assertEqual(again.wait('closed'), 4403)
        self.assertIsNone(self.hub.link('acct'))

    def _gone(self):
        end = time.time() + 10
        while time.time() < end:
            if self.hub.link('acct') is None: return True
            time.sleep(0.05)
        return False

    def test_a_wrong_token_is_turned_away(self):
        sim = self.sim(token='x' * 43); sim.wait('ready')
        self.assertEqual(sim.wait('closed'), 4401)
        self.assertIsNone(self.hub.link('acct'))


if __name__ == '__main__':
    unittest.main()
