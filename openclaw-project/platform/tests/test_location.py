import json
from agentai_platform.location import Locations, LocationTool, NAME
from agentai_platform.security import NotFound
from agentai_platform.tool_relay import Relay
from agentai_platform.browse.adapter import BrowserTool
from tests.test_native_run import Base, OK


class LocationChecks(Base):
    def setUp(self):
        super().setUp()
        self.sent = self.say()
        self.claim = self.queue.claim(owner='w', capacity=OK)
        self.loc = Locations(self.store, lambda: self.now)
        self.loc.start('a', self.sent['id'])
        self.id = self.loc.pending('a')['id']

    def claim_browser(self, client='tab1'):
        return self.loc.answer('a', self.id, {'action': 'claim', 'client_id': client})

    def answer(self, status='denied', **kw):
        return self.loc.answer('a', self.id, {'action': 'respond', 'client_id': 'tab1', 'status': status, **kw})

    def test_granted_is_consumed_once_without_public_coordinates(self):
        self.claim_browser()
        position = {'latitude': 37.7, 'longitude': -122.4, 'accuracy': 42}
        self.assertTrue(self.answer('granted', position=position)['accepted'])
        self.assertEqual(self.loc.take('a', self.sent['id']), {'status': 'granted', 'position': position})
        self.assertIsNone(self.rows('SELECT position_json FROM location_requests')[0][0])
        self.assertEqual(self.loc.take('a', self.sent['id'])['status'], 'unavailable')
        self.assertNotIn('37.7', str(self.rows('SELECT public_payload FROM events')))

    def test_foreign_account_unclaimed_and_duplicate_responses(self):
        self.assertIsNone(self.loc.pending('b'))
        with self.assertRaises(NotFound): self.loc.answer('b', self.id, {'action': 'claim', 'client_id': 'x'})
        with self.assertRaises(NotFound): self.loc.start('b', self.sent['id'])
        self.assertFalse(self.answer()['accepted'])
        self.assertTrue(self.claim_browser()['accepted'])
        self.assertFalse(self.claim_browser('other')['accepted'])
        self.assertTrue(self.answer()['accepted'])
        self.assertFalse(self.answer('granted', position={'latitude': 0, 'longitude': 0, 'accuracy': 1})['accepted'])
        self.loc.start('a', self.sent['id'])
        self.assertIsNone(self.loc.pending('a'))
        self.assertEqual(self.loc.take('a', self.sent['id'])['status'], 'denied')

    def test_lease_expiry_and_deadline_do_not_mean_denial(self):
        self.claim_browser()
        self.now += 16
        self.assertFalse(self.answer()['accepted'])
        self.assertTrue(self.claim_browser('other')['accepted'])
        self.now += 120
        self.assertIsNone(self.loc.pending('a'))
        self.assertEqual(self.loc.take('a', self.sent['id'])['status'], 'timeout')

    def test_cancel_and_revoked_funding_invalidate_late_coordinates(self):
        self.claim_browser()
        with self.store.connect() as con:
            con.execute('UPDATE customer_requests SET cancel_requested=1 WHERE id=?', (self.sent['id'],))
        self.assertFalse(self.answer()['accepted'])
        self.assertEqual(self.loc.take('a', self.sent['id'])['status'], 'cancelled')

    def test_nonfinite_out_of_range_boolean_and_missing_coordinates(self):
        self.claim_browser()
        for position in ({}, {'latitude': True, 'longitude': 0, 'accuracy': 1}, {'latitude': float('nan'), 'longitude': 0, 'accuracy': 1},
                         {'latitude': 91, 'longitude': 0, 'accuracy': 1}, {'latitude': 0, 'longitude': 0, 'accuracy': -1}):
            with self.subTest(position=position), self.assertRaises(ValueError): self.answer('granted', position=position)

    def test_tool_waits_and_returns_denial_or_disconnect(self):
        def respond(_):
            self.claim_browser(); self.answer()
        tool = LocationTool(self.store, clock=lambda: self.now, sleep=respond)
        result, error = tool.call('a', {}, request_id=self.sent['id'])
        self.assertFalse(error); self.assertEqual(json.loads(result)['status'], 'denied')
        self.assertTrue(tool.call('a', {})[1])

    def test_worker_waiting_and_caller_disconnect(self):
        self.assertEqual(self.driver._human_wait(self.claim), 'location_permission')
        tool = LocationTool(self.store, clock=lambda: self.now)
        self.assertEqual(json.loads(tool.call('a', {}, lambda: True, request_id=self.sent['id'])[0])['status'], 'cancelled')
        self.assertIsNone(self.driver._human_wait(self.claim))

    def test_relay_lists_tool_and_requires_origin(self):
        tool = LocationTool(self.store, clock=lambda: self.now)
        relay = Relay(BrowserTool(self.store, browse_factory=lambda a: None), location=tool, origin=lambda *a: None)
        specs = relay.handle('a', {'id': 1, 'method': 'tools/list'})['result']['tools']
        self.assertIn(NAME, [t['name'] for t in specs])
        result = relay.handle('a', {'id': 2, 'method': 'tools/call', 'params': {'name': NAME, 'arguments': {}}})
        self.assertTrue(result['result']['isError'])

    def test_housekeeping_scrubs_orphans_and_expired_positions(self):
        self.claim_browser()
        self.answer('granted', position={'latitude': 0, 'longitude': 0, 'accuracy': 10})
        self.now += 121
        self.loc.cleanup()
        self.assertIsNone(self.rows('SELECT position_json FROM location_requests')[0][0])

    def test_tool_wait_without_any_customer_page_expires(self):
        tool = LocationTool(self.store, clock=lambda: self.now, sleep=lambda _: setattr(self, 'now', self.now + 30))
        self.assertEqual(json.loads(tool.call('a', {}, request_id=self.sent['id'])[0])['status'], 'timeout')

    def test_runtime_ownership_hook_knows_the_location_tool(self):
        from agentai_platform.lifecycle.tool_origin import is_tool_name
        from agentai_platform.lifecycle.cell_config import WORKSPACE_RULES, BROWSER_TOOL_TIMEOUT_MS
        from pathlib import Path
        import agentai_platform.lifecycle.tool_origin as origin
        self.assertTrue(is_tool_name(NAME))
        self.assertIn(NAME, Path(origin.__file__).with_name('tool_origin_plugin').joinpath('index.mjs').read_text())
        self.assertIn(NAME, WORKSPACE_RULES)
        self.assertGreater(BROWSER_TOOL_TIMEOUT_MS, 120000)
