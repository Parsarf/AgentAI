import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.browse import service as svc
from agentai_platform.browse.client import BrowseRpc

RID = 'a' * 32
PAGES = {'start': {'url': 'https://shop.example/', 'snap': '[1] <input type=text> "Search paddles"\n[2] <a> "Add to cart"', 'text': 'Paddle shop', 'go': {2: 'cart'}},
         'cart': {'url': 'https://shop.example/cart', 'snap': '[1] <a> "Checkout"\n[2] <a> "Keep shopping"', 'text': 'Your cart', 'go': {1: 'pay'}},
         'pay': {'url': 'https://shop.example/checkout', 'snap': '[1] <input type=text> "Card number"', 'text': 'Pay'}}


class FakeTransport:
    """Speaks the runner's JSON-lines protocol over scripted pages."""
    def __init__(self, out_dir, pages=PAGES, hang=False):
        self.pages, self.at, self.out, self.n, self.replies, self.closed, self.log, self.hang = pages, 'start', Path(out_dir), 0, [], False, [], hang
    def send(self, obj):
        self.log.append(obj)
        if obj['cmd'] == 'close':
            self.closed = True; return
        r = {'id': obj['id'], 'ok': True}
        p = self.pages[self.at]
        if obj['cmd'] == 'open': r.update(url=p['url'], title='T')
        elif obj['cmd'] == 'snapshot': r.update(url=p['url'], title='T', snapshot=p['snap'], text=p.get('text', ''))
        elif obj['cmd'] == 'act':
            nxt = p.get('go', {}).get(obj.get('ref')); self.at = nxt or self.at; r.update(url=self.pages[self.at]['url'])
        elif obj['cmd'] == 'screenshot':
            self.n += 1; name = f'shot-{self.n:03d}.jpg'; (self.out / name).write_bytes(b'\xff\xd8jpeg'); r['file'] = name
        elif obj['cmd'] == 'xy':
            r['url'] = p['url']
        self.replies.append(r)
    def recv(self, timeout):
        if self.hang: raise TimeoutError('runner did not answer in time')
        return self.replies.pop(0)
    def close(self): self.closed = True


def llm_for(script):
    steps = list(script)
    def make(account):
        def llm(tier, system, user):
            if 'ONLY one https://' in system: return {'text': 'https://shop.example/', 'cost_microusd': 1000}
            return {'text': steps.pop(0), 'cost_microusd': 3000}
        return llm
    return make


def wait(service, state, rid=RID, account='acct', timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        p = service.poll(account, rid, 0)
        if p['state'] in state: return p
        time.sleep(0.02)
    raise AssertionError(service.poll(account, rid, 0))


class ServiceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.transports = []
    def make(self, script, **kw):
        def spawn(job_id, out_dir):
            t = FakeTransport(out_dir, **kw.pop('transport_kw', {})); self.transports.append(t); return t
        return svc.BrowseService(spawn=spawn, llm_for=llm_for(script), root=self.tmp.name, jev_mode='off', takeover_seconds=kw.get('takeover_seconds', 5))

    def test_job_runs_to_a_checkout_handoff_with_events_screenshots_and_cost(self):
        s = self.make(['{"action":"click","ref":2}', '{"action":"click","ref":1}'])
        self.assertEqual(s.start('acct', RID, 'buy a paddle at https://shop.example/')['state'], 'queued')
        self.assertEqual(s.start('acct', RID, 'buy a paddle at https://shop.example/')['ok'], True)               # idempotent: no second job
        p = wait(s, ('handoff',))
        self.assertEqual(p['pending_action']['label'], 'Checkout'); self.assertTrue(p['takeover'])
        kinds = [e['kind'] for e in p['events']]; self.assertIn('opened', kinds); self.assertIn('step', kinds); self.assertIn('screenshot', kinds)
        self.assertGreater(p['cost_microusd'], 0); self.assertLess(p['cost_microusd'], 100000)
        shots = [e['file'] for e in p['events'] if e['kind'] == 'screenshot']; self.assertTrue(s.shot('acct', RID, shots[0]).startswith(b'\xff\xd8'))
        self.assertEqual(len(self.transports), 1)
        self.assertEqual([c['cmd'] for c in self.transports[0].log].count('act'), 1)                              # only "Add to cart" was clicked
        later = s.poll('acct', RID, p['events'][-1]['n']); self.assertEqual(later['events'], [])                  # polling is incremental

    def test_isolation_between_accounts_and_hard_input_checks(self):
        s = self.make(['{"action":"click","ref":2}', '{"action":"click","ref":1}']); s.start('acct', RID, 'goal at https://shop.example/'); wait(s, ('handoff',))
        for call in (lambda: s.poll('other', RID), lambda: s.cancel('other', RID), lambda: s.shot('other', RID, 'shot-001.jpg'), lambda: s.control('other', RID, 'click', x=1, y=1),
                     lambda: s.start('other', RID, 'goal at https://shop.example/')):
            with self.assertRaises(svc.BrowseError): call()
        for bad in ('../../etc/passwd', 'shot-1.jpg', 'x.jpg', None):
            with self.assertRaises(svc.BrowseError): s.shot('acct', RID, bad)
        with self.assertRaises(svc.BrowseError): s.start('acct', 'not-hex', 'goal here')
        with self.assertRaises(svc.BrowseError): s.start('acct', 'b' * 32, 'x')

    def test_takeover_only_after_handoff_one_action_at_a_time_and_expires(self):
        s = self.make(['{"action":"click","ref":2}', '{"action":"click","ref":1}'], takeover_seconds=1); s.start('acct', RID, 'goal at https://shop.example/')
        with self.assertRaises(svc.BrowseError): s.control('acct', RID, 'click', x=5, y=5)                          # still running or not yet handed over
        wait(s, ('handoff',))
        self.assertTrue(s.control('acct', RID, 'click', x=5, y=5)['ok'])
        with self.assertRaises(svc.BrowseError): s.control('acct', RID, 'exec', x=5, y=5)
        self.assertTrue(any(c['cmd'] == 'xy' for c in self.transports[0].log))
        time.sleep(1.3)
        with self.assertRaises(svc.BrowseError): s.control('acct', RID, 'click', x=5, y=5)                          # window closed
        self.assertTrue(self.transports[0].closed)                                                                  # stage released

    def test_one_stage_at_a_time_cancel_budget_and_crash_do_not_hold_the_slot(self):
        s = self.make(['{"action":"click","ref":2}', '{"action":"click","ref":1}'] * 3, takeover_seconds=30)
        s.start('acct', RID, 'first goal https://shop.example/'); wait(s, ('handoff',))
        s.start('acct', 'b' * 32, 'second goal https://shop.example/')
        time.sleep(0.3); self.assertEqual(s.poll('acct', 'b' * 32)['state'], 'queued')                              # waits for the single stage
        s.cancel('acct', RID); wait(s, ('handoff', 'cancelled', 'done'), RID); wait(s, ('handoff',), 'b' * 32)
        # budget: a $0.002 cap refuses the first paid call
        s2 = self.make(['{"action":"click","ref":2}']); s2.start('acct', 'c' * 32, 'goal https://shop.example/', max_cost_microusd=2000)
        self.assertEqual(wait(s2, svc.FINAL, 'c' * 32)['state'], 'budget')
        # a runner that never answers ends as an error and frees the slot
        s3 = self.make([], transport_kw={'hang': True}); s3.start('acct', 'd' * 32, 'goal https://shop.example/')
        self.assertEqual(wait(s3, ('error',), 'd' * 32)['state'], 'error'); self.assertTrue(s3._slot.acquire(timeout=1)); s3._slot.release()

    def test_denied_site_is_blocked_before_any_stage_work(self):
        s = self.make([]); s.start('acct', RID, 'log in at https://www.paypal.com/ please')
        self.assertEqual(wait(s, svc.FINAL)['state'], 'blocked')

    def test_stage_command_is_fixed_and_hardened(self):
        argv = svc.stage_argv('a' * 32, '/var/lib/agentai-browse/jobs/x/out', '/opt/agentai-browse/runner', 'openclaw-sandbox-browser:phase4-2026.9.6')
        flat = ' '.join(argv)
        for needed in ('--read-only', '--cap-drop ALL', 'no-new-privileges', '--user 1000:1000', '--memory 1536m', '--pids-limit 256', '/job:ro', '--entrypoint node'):
            self.assertIn(needed, flat)
        self.assertNotIn('--privileged', flat); self.assertNotIn('docker.sock', flat); self.assertNotIn('--network host', flat)
        with self.assertRaises(ValueError): svc.stage_argv('x; rm', '/o', '/r', 'img')

    def test_socket_server_scopes_operations_to_the_peer_and_returns_screenshots(self):
        s = self.make(['{"action":"click","ref":2}', '{"action":"click","ref":1}'], takeover_seconds=20)
        path = os.path.join(self.tmp.name, 'b.sock'); server = svc.serve(s, path, allowed_uids={os.getuid()}, peer_uid=lambda sock: os.getuid())
        threading.Thread(target=server.serve_forever, daemon=True).start(); self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        rpc = BrowseRpc('acct', path)
        self.assertTrue(rpc('start', request_id=RID, goal='buy at https://shop.example/')['ok'])
        end = time.time() + 10
        while rpc('poll', request_id=RID, since=0)['state'] != 'handoff' and time.time() < end: time.sleep(0.05)
        polled = rpc('poll', request_id=RID, since=0); name = [e['file'] for e in polled['events'] if e['kind'] == 'screenshot'][0]
        self.assertTrue(rpc.shot(RID, name).startswith(b'\xff\xd8'))
        with self.assertRaises(CapabilityUnavailable): BrowseRpc('other', path)('poll', request_id=RID, since=0)
        with self.assertRaises(CapabilityUnavailable): rpc('rm_rf', request_id=RID)
        denied = svc.serve(s, os.path.join(self.tmp.name, 'c.sock'), allowed_uids={os.getuid() + 1}, peer_uid=lambda sock: os.getuid())
        threading.Thread(target=denied.serve_forever, daemon=True).start(); self.addCleanup(denied.server_close); self.addCleanup(denied.shutdown)
        with self.assertRaises(CapabilityUnavailable): BrowseRpc('acct', os.path.join(self.tmp.name, 'c.sock'))('poll', request_id=RID, since=0)


if __name__ == '__main__':
    unittest.main()


class DriverChecks(unittest.TestCase):
    """The chat driver's browse path against a fake host service."""
    def setUp(self):
        import json as _json
        from agentai_platform.budget import BudgetLedger
        from agentai_platform.capacity import CapacityResult
        from agentai_platform.chat import ChatDriver, ChatService, FixedRoute, synthetic_gateway_factory
        from agentai_platform.gateway import SyntheticGateway
        from agentai_platform.genui.runtime import GenUiRuntime
        from agentai_platform.events import EventService
        from agentai_platform.request_queue import RequestQueue
        from agentai_platform.request_worker import RequestWorker
        from agentai_platform.security import Principal
        from agentai_platform.store import Store
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.now = 2000000000
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize()
        self.queue = RequestQueue(self.store, clock=lambda: self.now, require_cell=True)
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10**9, clock=lambda: self.now)
        self.chat = ChatService(self.store, queue=self.queue, ledger=self.ledger, pricer=FixedRoute(1000000), clock=lambda: self.now, execution=True, browse=True)
        self.a = Principal('a', 'actor-a', 'customer')
        limits = {'period_start_epoch': self.now - 100000, 'period_microusd': 10**8, 'daily_microusd': 10**8, 'task_microusd': 5000000, 'max_queued_tasks': 3}
        with self.store.connect() as con:
            con.execute("INSERT INTO accounts(id,status) VALUES ('a','active')"); con.execute("INSERT INTO memberships VALUES ('a','actor-a','customer','active')")
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('a','d-a',1,'stopped')")      # the assistant's cell is NOT running
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p-a','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p-a','c-a','d-a')")
            con.execute("INSERT INTO entitlements VALUES ('a','e-a','t','trial',?,datetime(?,'unixepoch'))", (_json.dumps(limits), self.now + 10**6))
        self.calls = []
        outer = self
        class Rpc:
            script = []
            def __call__(s, op, **p):
                outer.calls.append((op, p))
                if op == 'poll': return s.script.pop(0) if len(s.script) > 1 else s.script[0]
                return {'ok': True}
        self.rpc = Rpc()
        class Gw(SyntheticGateway):
            spend = [100, 4100]
            def usage_snapshot(g): return g.spend.pop(0) if len(g.spend) > 1 else g.spend[0]
        self.gw = Gw()
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gw), clock=lambda: self.now, genui=GenUiRuntime(self.store, self.chat.blocks),
                            browse_factory=lambda account: self.rpc, events=EventService(self.store))
        self.worker = RequestWorker(self.queue, driver, lambda: CapacityResult(1, 1, 1, 1, 1, ()), clock=lambda: self.now)

    def rows(self, sql, args=()):
        with self.store.connect() as con: return [dict(r) for r in con.execute(sql, args).fetchall()]

    def test_interactive_goal_runs_in_the_browser_without_the_cell_and_hands_off_at_checkout(self):
        sent = self.chat.send(self.a, conversation_id='c-a', message='Order me a large pepperoni pizza from dominos.com', key='b1')
        self.assertEqual(sent['response_type'], 'browse')
        self.assertEqual(self.rows('SELECT intent FROM customer_requests')[0]['intent'], 'browse')
        step = {'n': 2, 'kind': 'step', 'by': 'haiku', 'action': 'click', 'label': 'Add to cart', 'result': 'ok', 'url': 'https://x/cart'}
        self.rpc.script = [{'state': 'running', 'events': [{'n': 1, 'kind': 'opened', 'url': 'https://dominos.com/', 'title': 'D'}, step], 'cost_microusd': 3000, 'url': 'https://x/cart'},
                           {'state': 'handoff', 'reason': 'reached a payment step', 'answer': None, 'url': 'https://x/checkout', 'takeover': True, 'cost_microusd': 6000,
                            'pending_action': {'label': 'Checkout'}, 'events': [{'n': 3, 'kind': 'screenshot', 'file': 'shot-001.jpg', 'by': 'lumina'}], 'jev': {'jev_asked': 2, 'jev_agree': 1}}]
        self.assertEqual(self.worker.tick(), {'ran': 1, 'finished': True})                                          # claimed although no cell slot exists
        self.assertEqual(self.calls[0][0], 'start'); self.assertEqual(self.calls[0][1]['max_cost_microusd'], 1000000)
        run = self.rows('SELECT * FROM browse_runs')[0]
        self.assertEqual((run['status'], run['jev_asked'], run['jev_agree']), ('handoff', 2, 1)); self.assertIsNotNone(run['takeover_until'])
        self.assertEqual([r['kind'] for r in self.rows('SELECT kind FROM browse_steps ORDER BY n')], ['opened', 'step', 'screenshot'])
        agent = [m['content'] for m in self.chat.messages(self.a, 'c-a')['messages'] if m['provenance'] == 'agent'][-1]
        self.assertIn('nothing was purchased', agent)
        tl = [r['public_payload'] for r in self.rows('SELECT public_payload FROM events')]; self.assertTrue(any('Add to cart' in t for t in tl))
        self.assertEqual(self.rows("SELECT state FROM customer_requests")[0]['state'], 'completed')
        self.assertEqual([tuple(r.values()) for r in self.rows('SELECT amount_microusd,price_version FROM provider_receipts')], [(4000, 'litellm-reported-v1')])   # real key spend, not the estimate
        self.assertEqual(self.gw.sent if hasattr(self.gw, 'sent') else [], [])                                       # the assistant was never messaged

    def test_failure_cancel_and_unavailable_service_settle_cleanly(self):
        self.chat.send(self.a, conversation_id='c-a', message='Book a table via opentable.com tonight', key='b2')
        self.rpc.script = [{'state': 'budget', 'reason': 'x', 'events': [], 'cost_microusd': 1000000, 'url': ''}]
        self.worker.tick()
        self.assertEqual(self.rows('SELECT state FROM customer_requests')[0]['state'], 'failed')
        self.assertIn('spending limit', [m['content'] for m in self.chat.messages(self.a, 'c-a')['messages'] if m['provenance'] == 'agent'][-1])
        self.chat.send(self.a, conversation_id='c-a', message='Order tacos from doordash.com now', key='b3')
        rid = self.rows("SELECT id FROM customer_requests WHERE state='waiting'")[0]['id']
        with self.store.connect() as con: con.execute('UPDATE customer_requests SET cancel_requested=1 WHERE id=?', (rid,))
        self.rpc.script = [{'state': 'cancelled', 'events': [], 'cost_microusd': 0, 'url': ''}]
        self.worker.tick()
        self.assertEqual(self.rows('SELECT state FROM customer_requests WHERE id=?', (rid,))[0]['state'], 'cancelled')

    def test_browse_is_off_unless_the_owner_switch_is_on_and_never_chosen_for_questions(self):
        self.chat.browse = False
        self.assertEqual(self.chat.send(self.a, conversation_id='c-a', message='Order me a pizza from dominos.com', key='b4', mode='auto')['response_type'], 'text')
        self.chat.browse = True
        self.assertEqual(self.chat.send(self.a, conversation_id='c-a', message='What is the best way to order pizza online?', key='b5')['response_type'], 'text')
