"""The `local` engine: a browse job whose hands are the customer's own Chrome, through their paired extension."""
import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from agentai_platform.browse import service as svc
from agentai_platform.browse.device_transport import DeviceTransport
from agentai_platform.browse.devices import DeviceHub
from agentai_platform.browse.service_main import local_enabled, pick_engine
from tests.test_browse_service import FakeTransport, PAGES, RID, ScriptedService, Steps, wait

JPEG = b'\xff\xd8\xff\xe0' + b'jpeg' * 20


class FakeExtension:
    """Stands in for the extension: takes each command as the gateway would send it and answers as executor.js does (pictures come back as base64 `data`)."""
    def __init__(self, tmp, die_after=None):
        self.page = FakeTransport(tmp); self.link, self.log, self.die_after = None, [], die_after

    def send_text(self, text):
        m = json.loads(text); self.log.append(m)
        if self.die_after is not None and len(self.log) > self.die_after:
            threading.Thread(target=lambda: self.link.close('chrome closed'), daemon=True).start(); return
        if m['cmd'] == 'close':
            return
        self.page.send(m); reply = self.page.replies.pop()
        if m['cmd'] in ('screenshot', 'view'):
            reply.pop('file', None); reply['data'] = base64.b64encode(JPEG).decode()
        self.link.push(reply)

    def close(self, code=1000, reason=''):
        pass


class PickEngineChecks(unittest.TestCase):
    def test_local_needs_the_customers_switch_and_a_connected_extension_and_nothing_else(self):
        cfg = {'native': ['b'], 'default': 'runner'}                              # no list: the engine is for everyone
        self.assertEqual(pick_engine(cfg, 'a', True, True), 'local')
        self.assertEqual(pick_engine(cfg, 'a', True, False), 'runner')            # connected, but the customer has not switched it on
        self.assertEqual(pick_engine(cfg, 'a', False, True), 'runner')            # switched on, but the extension is off: the hosted browser
        self.assertEqual(pick_engine(cfg, 'a', True), 'runner')                   # the switch defaults to off
        self.assertEqual(pick_engine({'native': ['a']}, 'a', True, True), 'local')              # the customer's own computer wins while it is on
        self.assertEqual(pick_engine({'native': ['a']}, 'a', False, True), 'native')
        self.assertEqual(pick_engine({}, 'a', True, True), 'local')

    def test_one_line_in_the_engine_file_switches_it_off_for_everyone(self):
        self.assertEqual(pick_engine({'local': False}, 'a', True, True), 'runner')
        self.assertEqual(pick_engine({'local': False, 'native': ['a']}, 'a', True, True), 'native')
        self.assertFalse(local_enabled({'local': False}, 'a'))
        for config in ({}, {'local': True}, {'local': None}, None, [], 'x'): self.assertTrue(local_enabled(config, 'a'), config)

    def test_a_list_opens_it_to_those_accounts_only_which_is_how_it_is_tried_out_first(self):
        cfg = {'local': ['a']}
        self.assertTrue(local_enabled(cfg, 'a')); self.assertFalse(local_enabled(cfg, 'b')); self.assertFalse(local_enabled(cfg))
        self.assertEqual(pick_engine(cfg, 'a', True, True), 'local')
        self.assertEqual(pick_engine(cfg, 'b', True, True), 'runner')              # b switched it on and has an extension connected, but is not on the list
        self.assertEqual(pick_engine(cfg, 'a', False, True), 'runner'); self.assertEqual(pick_engine(cfg, 'a', True, False), 'runner')
        self.assertFalse(local_enabled({'local': []}, 'a'))                       # an empty list is nobody

    def test_the_older_engine_rules_are_unchanged(self):
        self.assertEqual(pick_engine({'native': ['a']}, 'a', False), 'native'); self.assertEqual(pick_engine({'native': ['a']}, 'z', False), 'runner')
        self.assertEqual(pick_engine({'default': 'native'}, 'z', False), 'native'); self.assertEqual(pick_engine({}, 'z', True), 'runner')
        for junk in (None, [], 'native', 3): self.assertEqual(pick_engine(junk, 'a', True, True), 'runner', junk)               # not a config at all: the hosted browser
        self.assertEqual(pick_engine({'native': 'a'}, 'a', False, False), 'runner')                                              # a malformed native entry lists nobody


class LocalEngineChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.hub, self.memory_checks, self.spawned = DeviceHub(), [], []

    def connect(self, **kw):
        self.ext = FakeExtension(self.tmp.name, **kw); self.link = self.hub.attach('acct', 'd1', self.ext); self.ext.link = self.link

    def service(self, script, *, engine='local', local=True, **kw):
        def local_spawn(account, job_id, out_dir):
            self.spawned.append((account, job_id))
            link = self.hub.link(account)
            if link is None: raise svc.BrowseError('your browser is not connected')
            return DeviceTransport(link, out_dir)
        return ScriptedService(spawn=lambda *a: self.fail('the host stage was used'), local_spawn=local_spawn if local else None, engine_for=lambda account: engine,
                               llm_for=Steps(script), root=self.tmp.name, jev_mode='off', takeover_seconds=5, free_memory=lambda: self.memory_checks.append(1) or 10 ** 9, **kw)

    def test_a_whole_job_runs_in_the_customers_chrome_and_ends_where_the_host_stage_would(self):
        self.connect(); s = self.service(['{"action":"click","ref":2}', '{"action":"click","ref":1}'])
        s.start('acct', RID, 'buy a paddle at https://shop.example/')
        p = wait(s, ('handoff',))
        self.assertEqual(s.jobs[RID].engine, 'local'); self.assertEqual(self.spawned, [('acct', RID)])
        self.assertEqual(p['pending_action']['label'], 'Checkout'); self.assertTrue(p['takeover'])
        self.assertEqual(self.memory_checks, [], 'the host\'s memory is not the question for a job that runs on the customer\'s computer')
        cmds = [m['cmd'] for m in self.ext.log]
        self.assertEqual(cmds[0], 'open'); self.assertEqual(cmds.count('act'), 1)
        shots = [e['file'] for e in p['events'] if e['kind'] == 'screenshot']
        self.assertTrue(shots and s.shot('acct', RID, shots[0]).startswith(b'\xff\xd8'))
        self.assertTrue(self.link.alive, 'the extension stays connected for the next task')

    def test_the_extension_is_told_to_close_its_tabs_when_the_job_is_over(self):
        self.connect(); s = self.service(['{"action":"click","ref":2}', '{"action":"click","ref":1}'])
        s.start('acct', RID, 'buy a paddle at https://shop.example/'); wait(s, ('handoff',)); s.cancel('acct', RID)
        end = time.time() + 8
        while time.time() < end and not any(m['cmd'] == 'close' for m in self.ext.log): time.sleep(0.02)
        self.assertEqual([m['cmd'] for m in self.ext.log].count('close'), 1)

    def test_no_connected_browser_is_a_plain_error_for_the_customer(self):
        s = self.service(['{"action":"stop"}'])
        s.start('acct', RID, 'buy a paddle at https://shop.example/')
        p = wait(s, svc.FINAL)
        self.assertEqual(p['state'], 'error'); self.assertIn('not connected', p['reason'])

    def test_a_computer_that_disconnects_mid_task_ends_the_task_instead_of_hanging(self):
        self.connect(die_after=3); s = self.service(['{"action":"click","ref":2}', '{"action":"click","ref":1}'])
        s.start('acct', RID, 'buy a paddle at https://shop.example/')
        p = wait(s, svc.FINAL, timeout=15)
        self.assertEqual(p['state'], 'error')

    def test_an_engine_without_its_spawn_falls_back_to_the_host_stage(self):
        s = ScriptedService(spawn=lambda job_id, out_dir: FakeTransport(out_dir), engine_for=lambda a: 'local', llm_for=Steps(['{"action":"click","ref":2}', '{"action":"click","ref":1}']),
                            root=self.tmp.name, jev_mode='off', takeover_seconds=5)
        s.start('acct', RID, 'buy a paddle at https://shop.example/'); wait(s, ('handoff',))
        self.assertEqual(s.jobs[RID].engine, 'runner')

    def test_two_jobs_of_one_account_take_turns_on_its_one_browser(self):
        self.connect(); s = self.service(['{"action":"click","ref":2}', '{"action":"click","ref":1}'] * 2)
        other = 'b' * 32
        s.start('acct', RID, 'buy a paddle at https://shop.example/'); s.start('acct', other, 'buy a paddle at https://shop.example/')
        self.assertIs(s._slot_for(s.jobs[RID]), s._slot_for(s.jobs[other])); self.assertIsNot(s._slot_for(s.jobs[RID]), s._slot)
        wait(s, ('handoff',), rid=RID); self.assertEqual(s.poll('acct', other, 0)['state'], 'queued')


if __name__ == '__main__':
    unittest.main()
