"""The rules several features share, each with one implementation: rollout files, the public-address rule, request states and the live-run rule.

Each of these used to be written out separately per feature, and the copies had drifted. These tests pin the shared rule AND that every feature's own
helper still gives the answer it gave before (same files, same keys, same formats on the server).
"""
import tempfile
import unittest
from pathlib import Path

from agentai_platform import longterm_memory as ltm, model_keys as mk, netsafe, request_states as rs, rollout, ssrf
from agentai_platform.mcp_connections import network as mcp_net, switch as mcp_switch
from tests.test_native_run import Base, OK


class RolloutFiles(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()); self.path = self.dir / 'feature.json'

    def test_who_a_config_opens_a_feature_to(self):
        self.assertTrue(rollout.allows({'k': True}, 'k', 'a'))
        self.assertTrue(rollout.allows({'k': ['a', 'b']}, 'k', 'a'))
        for config in ({}, None, [], 'x', {'k': False}, {'k': 'yes'}, {'k': 1}, {'k': []}, {'k': ['b']}, {'k': {'a': True}}, {'other': True}):
            self.assertFalse(rollout.allows(config, 'k', 'a'), config)
        self.assertFalse(rollout.allows({'k': [None]}, 'k', None))                 # a list never opens the feature to "no account"
        self.assertTrue(rollout.allows({'k': True}, 'k', None))                    # ... but "everyone" is everyone

    def test_reading_never_raises_and_refuses_odd_files(self):
        self.assertEqual(rollout.read(str(self.path)), {})                         # no file
        for text in ('', 'not json', '[]', '"x"', '7'):
            self.path.write_text(text); self.assertEqual(rollout.read(str(self.path)), {}, text)
        self.path.write_text('{"k": true}'); self.assertEqual(rollout.read(str(self.path)), {'k': True})
        link = self.dir / 'link.json'; link.symlink_to(self.path)
        self.assertEqual(rollout.read(str(link)), {})                              # a symlink is not the owner's file
        self.assertEqual(rollout.read(str(link), follow_symlinks=True), {'k': True})
        self.path.write_text('{"k": true, "pad": "' + 'x' * rollout.MAX_BYTES + '"}'); self.assertEqual(rollout.read(str(self.path)), {})
        self.assertEqual(rollout.read(str(self.dir)), {})                          # a directory
        self.assertFalse(rollout.enabled('', 'k', 'a')); self.assertFalse(rollout.enabled(None, 'k', 'a'))

    def test_each_feature_keeps_its_own_key_and_answer(self):
        self.path.write_text('{"own_model_keys": ["a"], "mcp_connections": ["b"], "long_term_memory": true}')
        config = mk.read_engine(str(self.path))
        self.assertTrue(mk.enabled_for(config, 'a')); self.assertFalse(mk.enabled_for(config, 'b'))
        self.assertTrue(mcp_switch.enabled(str(self.path), 'b')); self.assertFalse(mcp_switch.enabled(str(self.path), 'a'))
        self.assertTrue(ltm.enabled(str(self.path), 'a')); self.assertTrue(ltm.enabled(str(self.path), 'zzz'))
        self.assertEqual(mcp_switch.read(str(self.path)), config); self.assertEqual(ltm.read_switch(str(self.path)), config)

    def test_the_own_model_file_is_still_read_through_a_symlink(self):
        self.path.write_text('{"own_model_keys": true}'); link = self.dir / 'link.json'; link.symlink_to(self.path)
        self.assertTrue(mk.enabled_for(mk.read_engine(str(link)), 'a'))            # kept as it was: this file predates the symlink rule
        self.assertFalse(mcp_switch.enabled(str(link), 'a')); self.assertFalse(ltm.enabled(str(link), 'a'))
        self.assertEqual(mk.read_engine(str(self.dir / 'missing.json')), {})


class PublicAddressRule(unittest.TestCase):
    PUBLIC = ('8.8.8.8', '93.184.216.34', '2606:2800:220:1:248:1893:25c8:1946', '::ffff:8.8.8.8')
    NOT_PUBLIC = ('127.0.0.1', '10.0.0.1', '172.16.0.9', '192.168.1.1', '169.254.169.254', '100.64.0.1', '100.100.100.200', '0.0.0.0', '198.18.0.1', '192.0.2.1', '240.0.0.1',
                  '224.0.0.1', '::1', '::', 'fe80::1', 'fd00::1', 'ff02::1', '2001:db8::1', '::ffff:10.0.0.1', '::ffff:127.0.0.1',
                  '64:ff9b::a00:1', '64:ff9b::808:808', '64:ff9b:1::1', '2002:7f00:1::1', '2002:0808:0808::1', '2001:0:4136:e378:8000:63bf:3fff:fdd2',
                  '', 'example.com', 'not an address', None, 7)

    def test_the_rule(self):
        for ip in self.PUBLIC:
            self.assertTrue(netsafe.is_public_address(ip), ip)
        for ip in self.NOT_PUBLIC:
            self.assertFalse(netsafe.is_public_address(ip), ip)

    def test_every_outbound_feature_uses_that_rule(self):
        """Own-model endpoints used to accept NAT64 addresses (an internal IPv4 host in a global-looking IPv6 address) that remote MCP refused."""
        for ip in self.PUBLIC + self.NOT_PUBLIC:
            expected = netsafe.is_public_address(ip)
            self.assertEqual(mk.is_public(ip), expected, ip)
            self.assertEqual(mcp_net.public_address(ip), expected, ip)
            self.assertEqual(ssrf._public(ip), expected, ip)

    def test_a_translated_address_is_refused_at_each_door(self):
        nat64 = lambda host, port=443, type=0: [(2, 1, 6, '', ('64:ff9b::a00:1', port))]
        with self.assertRaises(mk.ModelKeyError):
            mk.resolve_public(mk.parse_endpoint('https://models.example.org/v1'), nat64)
        with self.assertRaises(ssrf.Blocked):
            ssrf.check_url('https://site.example.org/', ['site.example.org'], resolver=lambda host: ['64:ff9b::a00:1'])

    def test_names_as_typed(self):
        self.assertTrue(netsafe.HOSTNAME.fullmatch('api.example.com')); self.assertFalse(netsafe.HOSTNAME.fullmatch('10.0.0.1')); self.assertFalse(netsafe.HOSTNAME.fullmatch('localhost'))
        self.assertTrue('db.internal'.endswith(netsafe.BLOCKED_SUFFIXES))
        self.assertIs(mk.HOSTNAME, netsafe.HOSTNAME); self.assertIs(mk.BLOCKED_SUFFIXES, netsafe.BLOCKED_SUFFIXES)


class LiveRunRule(Base):
    """A tool acts only for a run that is in progress, not closing and not being stopped. One query says so for the browser, progress, location and model relay."""

    def setUp(self):
        super().setUp()
        self.sent = self.say()
        self.id = self.sent['id']

    def live(self, **kw):
        with self.store.connect() as con:
            return rs.live_runs(con, 'a', **kw)

    def set(self, **fields):
        with self.store.connect() as con:
            con.execute('UPDATE customer_requests SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), self.id))

    def test_a_waiting_request_is_not_a_live_run(self):
        self.assertEqual(self.request(self.id)['state'], 'waiting')
        self.assertEqual(self.live(), [])

    def test_claimed_then_closing_or_stopped(self):
        self.queue.claim(owner='w', capacity=OK)
        self.assertIn(self.request(self.id)['state'], rs.LIVE)
        self.assertEqual(self.live(), [self.id])
        self.assertEqual(self.live(funded=True, active_account=True), [self.id])
        self.assertEqual(self.live(request_id=self.id), [self.id]); self.assertEqual(self.live(request_id='other'), [])
        with self.store.connect() as con:
            self.assertTrue(rs.is_live_run(con, 'a', self.id, funded=True, active_account=True))
            self.assertFalse(rs.is_live_run(con, 'b', self.id))                  # never another account's run
            self.assertFalse(rs.run_ended(con.execute('SELECT state,closing,cancel_requested FROM customer_requests WHERE id=?', (self.id,)).fetchone()))
        self.set(closing=1); self.assertEqual(self.live(), [])
        self.set(closing=0, cancel_requested=1); self.assertEqual(self.live(), [])
        self.set(cancel_requested=0); self.assertEqual(self.live(), [self.id])
        for state in ('uncertain', 'completed', 'failed', 'cancelled', 'waiting'):
            self.set(state=state); self.assertEqual(self.live(), [], state)
        self.assertTrue(rs.run_ended(None))

    def test_funded_and_account_conditions_are_separate(self):
        self.queue.claim(owner='w', capacity=OK)
        with self.store.connect() as con:
            con.execute("UPDATE task_reservations SET state='settled' WHERE task_id=?", (self.id,))
        self.assertEqual(self.live(), [self.id]); self.assertEqual(self.live(funded=True), [])
        with self.store.connect() as con:
            con.execute("UPDATE task_reservations SET state='active' WHERE task_id=?", (self.id,))
            con.execute("UPDATE accounts SET status='suspended' WHERE id='a'")
        self.assertEqual(self.live(funded=True), [self.id]); self.assertEqual(self.live(active_account=True), [])

    def test_the_tools_agree_with_the_rule(self):
        from agentai_platform.browse.adapter import BrowserTool
        from agentai_platform.location import Locations
        from agentai_platform.task_progress import TaskProgressTool
        self.queue.claim(owner='w', capacity=OK)
        browser = BrowserTool(self.store, browse_factory=lambda account: None, enabled=lambda: True)
        locations = Locations(self.store, lambda: self.now); progress = TaskProgressTool(self.store)
        with self.store.connect() as con:
            self.assertTrue(locations.live(con, 'a', self.id))
        self.assertEqual(browser.current_request('a')['id'], self.id); self.assertFalse(browser._ended('a', self.id))
        self.assertFalse(progress.current('a')[1])                               # (text, is_error)
        self.set(cancel_requested=1)                                             # the customer pressed Stop: every tool lets go at once
        with self.store.connect() as con:
            self.assertFalse(locations.live(con, 'a', self.id))
        self.assertIsNone(browser.current_request('a')); self.assertTrue(browser._ended('a', self.id))
        self.assertTrue(progress.current('a')[1])
        self.assertIsNone(self.queue.open_for_steer(self.a, 'c-a'))


if __name__ == '__main__':
    unittest.main()
