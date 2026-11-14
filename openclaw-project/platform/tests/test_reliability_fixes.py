"""One test per reliability fix of 14 November 2026: each one failed before its fix (see RELEASE_NOTES.md)."""
import tempfile
import unittest

from agentai_platform import request_states
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.browse import devices as dv
from agentai_platform.browse import loop as browse_loop
from agentai_platform.browse.adapter import BrowserTool
from agentai_platform.browse.device_transport import DeviceTransport
from agentai_platform.browse.session import Session
from agentai_platform.lifecycle.supervisor import SupervisorBusy
from agentai_platform.lifecycle.worker import LifecycleWorker
from tests import test_lifecycle
from tests.test_lifecycle import CAPACITY
from tests.test_native_run import OK, Base


class QueueAndDriver(Base):
    def test_a_message_sent_while_the_first_is_still_starting_does_not_replace_it(self):
        session, _, _ = self.gateway.open_session('x', 'earlier')
        with self.store.connect() as con:
            con.execute("UPDATE conversations SET native_session_ref=? WHERE account_id='a' AND id='c-a'", (session,))
        first = self.say('book a table for four on Friday', key='k1')
        claim = self.queue.claim(owner='w', capacity=OK)
        second = self.say('and make it a window seat', key='k2')
        self.assertNotIn('steered', second)                               # it waits its turn as a task of its own
        self.assertNotEqual(second['id'], first['id'])
        self.driver.execute(claim)
        self.assertTrue(any('book a table' in r['message'] for r in self.gateway.runs.values()))

    def test_a_message_sent_while_parked_does_not_make_the_worker_churn(self):
        sent = self.say(key='k1')
        self.gateway.polls = 10 ** 6
        self.browse_state(sent['id'], 'paused')
        self.assertEqual(self.worker.tick(), {'ran': 1, 'parked': 'browser_takeover'})
        self.assertTrue(self.say('use the blue one', key='k2').get('steered'))
        self.assertEqual([self.worker.tick() for _ in range(3)], [{'ran': 0}] * 3)          # still parked, and the worker goes on to claim other work
        self.assertEqual(self.request(sent['id'])['fence'], 1)
        self.assertEqual([tuple(r) for r in self.rows('SELECT kind,state FROM chat_deliveries ORDER BY attempt')], [('turn', 'acknowledged'), ('steer', 'completed')])

    def test_a_request_parked_past_the_limit_is_closed_not_parked_again(self):
        sent = self.say(key='k1')
        self.gateway.polls = 10 ** 6
        self.browse_state(sent['id'], 'asking')
        self.assertEqual(self.worker.tick(), {'ran': 1, 'parked': 'browser_question'})
        self.now += self.driver.park_limit + 1
        self.assertEqual(self.worker.tick(), {'ran': 1, 'finished': True})
        row = self.request(sent['id'])
        self.assertEqual((row['state'], row['outcome']), ('completed', 'partial'))
        self.assertTrue([c for c in self.gateway.calls if c[0] == 'abort'])

    def test_a_close_the_queue_missed_is_recorded_on_the_next_tick(self):
        reads = []
        self.gateway.usage_snapshot = lambda: (reads.append(1), 1000 if len(reads) == 1 else 2500)[1]
        sent = self.say(key='k1')
        claim = self.queue.claim(owner='request-worker', capacity=OK, lease_seconds=120)
        receipt = self.driver.execute(claim)
        self.now += 61
        self.assertFalse(self.queue.finish(claim, receipt))                # the lease ran out during the close
        self.assertEqual(self.worker.tick(), {'reconciled': True})
        self.assertEqual(self.request(sent['id'])['state'], 'completed')
        self.assertFalse(self.rows('SELECT 1 FROM request_slot'))
        self.assertEqual(len(self.rows('SELECT 1 FROM provider_receipts')), 1)

    def test_a_request_that_waited_long_is_not_abandoned_on_its_first_failed_reconnect(self):
        sent = self.say(key='k1')
        self.now += 1900
        self.gateway.polls = 10 ** 6
        claim = self.queue.claim(owner='request-worker', capacity=OK, lease_seconds=120)
        self.driver._begin(claim, self.gateway, self.driver._admit(claim))
        self.driver._deliver(claim, self.gateway, self.driver._session(claim), self.driver._deliveries(claim)[0])
        self.queue.uncertain(claim)
        self.gateway.protocol_version = 0
        self.assertEqual(self.worker.tick(), {'reconciled': False, 'blocked': 'uncertain request awaiting reconciliation'})
        self.assertEqual(self.rows('SELECT 1 FROM provider_receipts'), [])

    def test_the_plan_repair_turn_is_a_live_run(self):
        seen = []

        def on_wait(run):
            with self.store.connect() as con:
                seen.append(bool(request_states.live_runs(con, 'a')))
        self.gateway.on_wait = on_wait
        self.gateway.script = lambda text, run, gw: {'text': 'this is not a plan'}
        sent = self.say('plan my week', key='k1', mode='plan')
        self.worker.tick()
        self.assertEqual(len(self.rows('SELECT 1 FROM chat_deliveries')), 2)
        self.assertTrue(all(seen))                                         # the model relay and the tools serve the repair turn too
        self.assertEqual(self.request(sent['id'])['closing'], 1)           # and the gate is shut again at the end

    def test_a_cell_that_is_not_ready_at_claim_makes_the_request_wait(self):
        sent = self.say(key='k1')
        self.gateway.protocol_version = 0
        self.assertEqual(self.worker.tick(), {'ran': 0, 'deferred': True})
        self.assertEqual(self.request(sent['id'])['state'], 'waiting')
        self.gateway.protocol_version = 4
        self.assertEqual(self.worker.tick(), {'ran': 1, 'finished': True})
        self.assertEqual(self.request(sent['id'])['state'], 'completed')

    def test_a_cell_that_never_becomes_ready_still_ends_the_request(self):
        sent = self.say(key='k1')
        self.gateway.protocol_version = 0
        self.now += self.driver.park_limit + 1
        with self.assertRaises(CapabilityUnavailable):
            self.worker.tick()
        self.worker.tick()
        self.assertEqual(self.request(sent['id'])['state'], 'failed')

    def test_a_stopped_browser_job_keeps_the_cost_it_had(self):
        sent = self.say(key='k1')
        claim = self.queue.claim(owner='w', capacity=OK)
        self.driver._begin(claim, self.gateway, self.driver._admit(claim))
        polls = []

        def rpc(op, **kw):
            if op == 'poll':
                polls.append(1)
                return {'state': 'running', 'reason': '', 'answer': None, 'url': 'https://example.com/', 'pending_action': None, 'cost_microusd': 5000, 'events': [], 'jev': {}}
            return {'ok': True}
        tool = BrowserTool(self.store, browse_factory=lambda account: rpc, sleep=lambda s: None, clock=lambda: self.now)
        tool.call('a', {'task': 'find the cheapest racket', 'site': 'example.com'}, lambda: len(polls) >= 2, request_id=sent['id'])
        self.assertEqual(tuple(self.rows('SELECT estimated_cost_microusd,status FROM browse_runs')[0]), (5000, 'cancelled'))

    def test_a_released_browser_job_is_recorded_as_over(self):
        sent = self.say(key='k1')
        self.browse_state(sent['id'], 'running')
        state = {'released': False}

        def rpc(op, **kw):
            if op == 'agent_release':
                state['released'] = True
                return {'ok': True, 'released': True}
            if op == 'poll':
                return {'state': 'cancelled', 'reason': 'the assistant went on without this page', 'answer': None, 'url': 'https://example.com/', 'pending_action': None, 'cost_microusd': 700, 'events': [], 'jev': {}}
            return {'ok': True}
        self.make_worker(browse_factory=lambda account: rpc)
        self.worker.tick()
        self.assertTrue(state['released'])
        self.assertEqual(self.rows('SELECT status FROM browse_runs')[0][0], 'cancelled')


class CardFill(unittest.TestCase):
    def test_an_expiry_field_named_credit_card_expiration_gets_the_date(self):
        typed = []

        class S:
            def act(self, action, ref, value, label, **kw):
                typed.append((label, value)); return {'ok': True}
        snap = {'snapshot': '[1] <input type=text> "Credit card number"\n[2] <input type=text> "Credit card expiration date"\n[3] <input type=text> "Name on card"'}
        self.assertTrue(browse_loop.BrowseRunner(S(), None)._fill_card({'number': '4111111111111111', 'exp_month': 4, 'exp_year': 2029, 'name': 'A Person'}, snap, []))
        self.assertEqual(typed, [('Credit card number', '4111111111111111'), ('Credit card expiration date', '04/29'), ('Name on card', 'A Person')])


class Wake(test_lifecycle.LifecycleChecks):
    def test_an_operation_turned_away_three_times_fails_and_the_next_wake_goes_through(self):
        self.request('create')
        with self.store.connect() as con:
            op = con.execute('SELECT id FROM operations').fetchone()[0]
        self.engine.run(self.driver, 'a', op, capacity=CAPACITY)
        with self.store.connect() as con:
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) SELECT 'a','p','c',id FROM deployments WHERE account_id='a'")
            con.execute("INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch) VALUES ('a','r1','customer-a','p','c','k','h','hi','waiting',?)", (self.now,))

        class Busy:
            def check(self, kind): pass
            def execute(self, claim): raise SupervisorBusy('host headroom exhausted')
            def reconcile(self, claim): return None
        worker = LifecycleWorker(self.store, Busy(), lambda: CAPACITY, coordinator=self.engine, clock=lambda: self.now, wake=True)
        for _ in range(5):
            worker.tick()
        worker.driver = self.driver
        for _ in range(3):
            worker.tick()
        with self.store.connect() as con:
            ops = [tuple(r) for r in con.execute("SELECT o.state,d.attempts FROM operations o JOIN lifecycle_details d ON d.operation_id=o.id WHERE o.kind='start' ORDER BY o.created_at,o.rowid")]
        self.assertEqual(ops, [('failed', 3), ('completed', 1)])


class LateReply(unittest.TestCase):
    def test_a_late_reply_from_an_earlier_task_is_not_taken_for_this_tasks_answer(self):
        class Conn:
            def __init__(self): self.sent = []
            def send_text(self, text): self.sent.append(text)
            def close(self, *a): pass
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        link = dv.DeviceHub().attach('acct', 'd1', Conn())
        first = DeviceTransport(link, tmp.name)
        second = DeviceTransport(link, tmp.name)                          # the next task on the same link
        s = Session(second)
        link.push({'id': first._offset + 1, 'ok': True, 'url': 'https://old.example/'})       # the earlier task's command answers late, with the same command number
        link.push({'id': second._offset + 1, 'ok': True, 'url': 'https://new.example/'})
        self.assertEqual(s.open('https://new.example/')['url'], 'https://new.example/')


if __name__ == '__main__':
    unittest.main()
