"""Paired computers: pairing codes, device tokens, the live hub, and the transport that carries the runner protocol to a device."""
import base64
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest

from agentai_platform.browse import devices as dv
from agentai_platform.browse.device_transport import DeviceTransport
from agentai_platform.browse.session import RunnerError, Session

JPEG = b'\xff\xd8\xff\xe0' + b'x' * 50


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t


class FakeConn:
    def __init__(self): self.sent, self.closed = [], None
    def send_text(self, text): self.sent.append(json.loads(text))
    def close(self, code=1000, reason=''): self.closed = (code, reason)


class StoreChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock = Clock(); self.store = dv.DeviceStore(Path(self.tmp.name) / 'sub' / 'devices.json', clock=self.clock)

    def test_a_code_is_traded_once_for_a_token_and_only_the_hash_is_kept(self):
        code = self.store.pair('acct')
        self.assertEqual(len(code), dv.CODE_LENGTH); self.assertTrue(set(code) <= set(dv.ALPHABET))
        made = self.store.redeem(code.lower()[:4] + ' - ' + code[4:], 'My Mac')          # typed with a space, a dash and lower case
        self.assertEqual(made['account'], 'acct'); self.assertGreaterEqual(len(made['token']), 40)
        self.assertIsNone(self.store.redeem(code, 'again'))                                # single use
        raw = (Path(self.tmp.name) / 'sub' / 'devices.json').read_text()
        self.assertNotIn(made['token'], raw); self.assertNotIn(code, raw)
        self.assertEqual(stat.S_IMODE(os.stat(Path(self.tmp.name) / 'sub' / 'devices.json').st_mode), 0o600)
        self.assertEqual(self.store.authenticate(made['token']), ('acct', made['device_id']))
        self.assertIsNone(self.store.authenticate(made['token'] + 'x')); self.assertIsNone(self.store.authenticate('')); self.assertIsNone(self.store.authenticate(None))

    def test_a_code_expires_and_unknown_codes_fail_the_same_way(self):
        code = self.store.pair('acct')
        self.clock.t += dv.PAIR_TTL + 1
        self.assertIsNone(self.store.redeem(code)); self.assertIsNone(self.store.redeem('NOSUCHCODE')); self.assertIsNone(self.store.redeem(None))

    def test_only_a_few_codes_and_devices_per_account(self):
        codes = [self.store.pair('acct') for _ in range(dv.MAX_OPEN_CODES + 2)]
        self.assertIsNone(self.store.redeem(codes[0]))                                     # the oldest were dropped
        for _ in range(dv.MAX_DEVICES):
            self.assertTrue(self.store.redeem(self.store.pair('acct')))
        with self.assertRaises(dv.DeviceError):
            self.store.redeem(self.store.pair('acct'))
        self.assertTrue(self.store.redeem(self.store.pair('other')))                       # another account is not affected

    def test_devices_are_listed_and_revoked_per_account(self):
        a = self.store.redeem(self.store.pair('acct'), 'Mac\x00\x1b[31m' + 'x' * 100)
        listed = self.store.devices('acct'); self.assertEqual(len(listed), 1); self.assertLessEqual(len(listed[0]['label']), dv.LABEL_MAX); self.assertNotIn('\x1b', listed[0]['label'])
        self.assertNotIn('token', listed[0]); self.assertEqual(self.store.devices('other'), [])
        self.assertFalse(self.store.revoke('other', a['device_id'])); self.assertTrue(self.store.exists('acct', a['device_id']))
        self.assertTrue(self.store.revoke('acct', a['device_id']))
        self.assertIsNone(self.store.authenticate(a['token'])); self.assertFalse(self.store.exists('acct', a['device_id']))

    def test_two_stores_on_one_file_see_each_other(self):
        other = dv.DeviceStore(Path(self.tmp.name) / 'sub' / 'devices.json', clock=self.clock)       # the command line and the service are different processes
        code = other.pair('acct'); made = self.store.redeem(code)
        self.assertEqual(other.authenticate(made['token'])[0], 'acct')

    def test_concurrent_pairings_do_not_lose_updates(self):
        out = []
        def go(): out.append(self.store.pair('acct'))
        threads = [threading.Thread(target=go) for _ in range(4)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(len(set(out)), 4)
        self.assertEqual(sum(1 for c in out if self.store.redeem(c)), 4)

    def test_a_damaged_file_is_treated_as_empty_not_a_crash(self):
        p = Path(self.tmp.name) / 'sub' / 'devices.json'; self.store.pair('acct'); p.write_text('{not json')
        self.assertEqual(self.store.devices('acct'), []); self.assertTrue(self.store.pair('acct'))

    def test_the_command_line_prints_a_code(self):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dv.main(['--store', str(Path(self.tmp.name) / 'cli.json'), 'pair', '--account', 'acct'])
        code = out.getvalue().split(': ')[-1].strip()
        self.assertTrue(dv.DeviceStore(Path(self.tmp.name) / 'cli.json').redeem(code))


class PreferenceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = dv.DeviceStore(Path(self.tmp.name) / 'd.json')

    def test_the_switch_starts_off_is_per_account_and_survives_a_restart(self):
        self.assertFalse(self.store.wants_local('a'))
        self.assertTrue(self.store.set_wants_local('a', True))
        self.assertTrue(self.store.wants_local('a')); self.assertFalse(self.store.wants_local('b'))
        self.assertTrue(dv.DeviceStore(Path(self.tmp.name) / 'd.json').wants_local('a'))
        self.assertFalse(self.store.set_wants_local('a', False)); self.assertFalse(self.store.wants_local('a'))

    def test_pairing_and_the_switch_do_not_disturb_each_other(self):
        self.store.set_wants_local('a', True); made = self.store.redeem(self.store.pair('a'), 'Mac')
        self.assertTrue(self.store.wants_local('a')); self.assertEqual(self.store.authenticate(made['token'])[0], 'a')
        self.assertTrue(self.store.revoke('a', made['device_id'])); self.assertTrue(self.store.wants_local('a'))


class HubChecks(unittest.TestCase):
    def test_one_live_link_per_account_and_the_newest_wins(self):
        hub = dv.DeviceHub(); a, b = FakeConn(), FakeConn()
        first = hub.attach('acct', 'd1', a); self.assertIs(hub.link('acct'), first)
        second = hub.attach('acct', 'd2', b)
        self.assertIs(hub.link('acct'), second); self.assertFalse(first.alive); self.assertEqual(a.closed[0], 4409)
        self.assertIsNone(hub.link('nobody'))
        hub.detach(first); self.assertIs(hub.link('acct'), second)                          # a late detach of the old link does not remove the new one
        self.assertTrue(hub.kick('acct', 'd2')); self.assertEqual(b.closed[0], 4403); self.assertIsNone(hub.link('acct'))
        self.assertFalse(hub.kick('acct', 'd2'))

    def test_replies_come_back_in_order_and_a_departure_ends_the_wait(self):
        hub = dv.DeviceHub(); link = hub.attach('acct', 'd1', FakeConn())
        link.push({'id': 1}); link.push({'id': 2})
        self.assertEqual(link.recv(1)['id'], 1); self.assertEqual(link.recv(1)['id'], 2)
        with self.assertRaises(TimeoutError): link.recv(0.05)
        threading.Timer(0.05, lambda: (link.note_event({'event': 'stopped', 'reason': 'stopped_by_customer'}), hub.detach(link))).start()
        with self.assertRaises(RunnerError) as ctx: link.recv(2)
        self.assertIn('stopped_by_customer', str(ctx.exception))
        with self.assertRaises(BrokenPipeError): link.send({'cmd': 'open'})


class TransportChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.conn = FakeConn(); self.link = dv.DeviceHub().attach('acct', 'd1', self.conn); self.t = DeviceTransport(self.link, self.tmp.name)

    def answer(self, **reply):
        self.link.push({**reply})

    def test_commands_go_out_and_replies_come_back_for_a_whole_session(self):
        s = Session(self.t)
        self.answer(id=1, ok=True, url='https://x/', title='T'); self.assertTrue(s.open('https://x/')['ok'])
        self.assertEqual(self.conn.sent[0], {'id': 1, 'cmd': 'open', 'url': 'https://x/'})
        self.answer(id=2, ok=True, snapshot='[1] <a> "Go"'); self.assertTrue(s.snapshot()['ok'])
        s.close()
        self.assertEqual([m['cmd'] for m in self.conn.sent], ['open', 'snapshot', 'close'])        # told once, though Session.close and close() both ask
        self.assertTrue(self.link.alive, 'the computer stays connected for the next task')
        with self.assertRaises(BrokenPipeError): self.t.send({'id': 9, 'cmd': 'open'})

    def test_screenshots_become_files_like_the_other_engines_and_views_only_when_saved(self):
        s = Session(self.t); b64 = base64.b64encode(JPEG).decode()
        self.answer(id=1, ok=True, data=b64); shot = s.screenshot()
        self.assertEqual(shot['file'], 'shot-001.jpg'); self.assertNotIn('data', shot); self.assertEqual((Path(self.tmp.name) / 'shot-001.jpg').read_bytes(), JPEG)
        self.answer(id=2, ok=True, data=b64, width=1280, height=800); v = s.view()
        self.assertEqual(v['data'], b64); self.assertNotIn('file', v); self.assertFalse((Path(self.tmp.name) / 'shot-002.jpg').exists())
        self.answer(id=3, ok=True, data=b64, width=1280, height=800); v = s.view(save=True)
        self.assertEqual(v['file'], 'shot-002.jpg'); self.assertEqual(v['data'], b64)

    def test_something_that_is_not_a_small_jpeg_is_never_stored(self):
        s = Session(self.t)
        for bad in (base64.b64encode(b'<html>not a picture</html>').decode(), 'not base64 !!', '', None, 12, base64.b64encode(b'\xff\xd8\xff' + b'0' * 3_000_001).decode()):
            self.answer(id=s._id + 1, ok=True, data=bad); r = s.screenshot()
            self.assertEqual((r['ok'], r['error']), (False, 'bad_picture'), repr(bad)[:30])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_a_new_task_does_not_see_the_last_ones_leftovers(self):
        self.link.push({'id': 1, 'ok': True, 'url': 'stale'})
        DeviceTransport(self.link, self.tmp.name)
        with self.assertRaises(TimeoutError): self.link.recv(0.05)

    def test_a_device_that_leaves_mid_task_is_a_runner_error_not_a_hang(self):
        s = Session(self.t)
        threading.Timer(0.05, lambda: self.link.close('gone')).start()
        with self.assertRaises(RunnerError): s.snapshot()


if __name__ == '__main__':
    unittest.main()
