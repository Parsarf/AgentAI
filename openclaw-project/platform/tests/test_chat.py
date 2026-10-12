import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from agentai_platform.budget import BudgetLedger, BudgetDenied
from agentai_platform.chat import ChatService, ChatDriver, FixedRoute, UnmeasuredRoute, synthetic_gateway_factory
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.request_queue import RequestQueue
from agentai_platform.security import Principal, NotFound
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.capacity import CapacityResult
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.store import Store

CAPACITY = CapacityResult(1, 1, 1, 1, 1, ())
LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000,
          'daily_microusd': 100000, 'task_microusd': 100000, 'max_queued_tasks': 3}


class ChatChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3');self.store.initialize()
        self.now = 2000000000
        self.gateway = SyntheticGateway()
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10000000, clock=lambda:self.now)
        self.route = FixedRoute(500)
        self.service = ChatService(self.store, queue=RequestQueue(self.store, clock=lambda:self.now),
                                   ledger=self.ledger, pricer=self.route, clock=lambda:self.now)
        self.queue = self.service.queue
        self.a = Principal('a', 'actor-a', 'customer');self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for a in ['a', 'b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (a, 'd-' + a))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (a, 'p-' + a, 'Project ' + a))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)', (a, 'p-' + a, 'c-' + a, 'd-' + a))
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))",
                            (a, 'e-' + a, json.dumps(LIMITS), self.now + 1000000))

    def send(self, principal=None, conversation=None, message='hello agent', key='k1'):
        actor = principal or self.a
        return self.service.send(actor, conversation_id=conversation or ('c-' + actor.account_id), message=message, key=key)

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return con.execute(sql, args).fetchall()

    def test_send_admits_task_and_transcript_once(self):
        result = self.send()
        self.assertEqual((result['admission'], result['execution_enabled']), ('reserved', True))
        self.assertTrue(self.rows("SELECT 1 FROM tasks WHERE account_id='a' AND id=? AND state='queued'", (result['id'],)))
        self.assertTrue(self.rows("SELECT 1 FROM task_reservations WHERE account_id='a' AND task_id=? AND state='active'", (result['id'],)))
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE request_id=? AND provenance='customer'", (result['id'],))), 1)
        again = self.send(key='k1')
        self.assertEqual(again['id'], result['id'])
        self.assertEqual(len(self.rows('SELECT 1 FROM tasks WHERE account_id="a"')), 1)
        self.assertEqual(len(self.rows('SELECT 1 FROM chat_messages')), 1)

    def test_duplicate_payload_change_and_foreign_conversation(self):
        self.send(key='k1')
        with self.assertRaises(Conflict):
            self.send(key='k1', message='changed')
        with self.assertRaises(NotFound):
            self.service.send(self.b, conversation_id='c-a', message='x', key='k9')
        with self.assertRaises(ValueError):
            self.send(key='bad key!')
        with self.assertRaises(ValueError):
            self.send(message='')

    def test_unmeasured_route_leaves_request_waiting_unfunded(self):
        self.service.pricer = UnmeasuredRoute()
        result = self.send()
        self.assertEqual((result['admission'], result['execution_enabled']), ('route_unconfigured', False))
        self.assertFalse(self.rows('SELECT 1 FROM tasks'))
        self.assertTrue(self.rows("SELECT 1 FROM customer_requests WHERE state='waiting' AND id=?", (result['id'],)))

    def test_budget_denial_cancels_request_without_residue(self):
        with self.store.connect() as con:
            limits = dict(LIMITS, period_microusd=600)
            con.execute("UPDATE entitlements SET limits_json=? WHERE account_id='a'", (json.dumps(limits),))
        self.send(key='first')
        with self.assertRaises(BudgetDenied) as caught:
            self.send(key='second')
        self.assertEqual(str(caught.exception), 'account allowance exhausted')
        self.assertEqual(self.rows("SELECT state FROM customer_requests WHERE idempotency_key='second'")[0][0], 'cancelled')

    def test_queue_ceiling_denial_cancels_request(self):
        with self.store.connect() as con:
            limits = dict(LIMITS, max_queued_tasks=1)
            con.execute("UPDATE entitlements SET limits_json=? WHERE account_id='a'", (json.dumps(limits),))
        self.send(key='first')
        with self.assertRaises(BudgetDenied):
            self.send(key='second')
        self.assertFalse(self.rows("SELECT 1 FROM customer_requests WHERE state='waiting' AND idempotency_key='second'"))

    def test_conversation_scoping_and_cap(self):
        self.service.max_conversations_per_project = 3
        first = self.service.create_conversation(self.a, 'p-a')
        second = self.service.create_conversation(self.a, 'p-a')
        self.assertNotEqual(first['id'], second['id'])
        with self.assertRaises(Conflict):
            self.service.create_conversation(self.a, 'p-a')
        with self.assertRaises(NotFound):
            self.service.create_conversation(self.a, 'p-b')
        self.assertEqual([c['id'] for c in self.service.conversations(self.a, 'p-a')], ['c-a', first['id'], second['id']])
        project = self.service.create_project(self.a, 'Second project')
        self.assertTrue(self.service.projects(self.a)[1]['id'] == project['id'] != 'p-a')
        with self.assertRaises(Conflict):
            for i in range(10):
                self.service.create_project(self.a, 'project ' + str(i))

    def test_messages_pagination_and_cross_account(self):
        result = self.send()
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        self.queue.finish(claim, ChatDriver(self.store, ledger=self.ledger,
                          gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda:self.now).execute(claim))
        page = self.service.messages(self.a, 'c-a')
        self.assertEqual([m['provenance'] for m in page['messages']], ['customer', 'agent'])
        self.assertEqual(page['messages'][0]['content'], 'hello agent')
        self.assertEqual([t['state'] for t in page['tasks']], ['completed'])
        after = page['messages'][0]['id']
        self.assertEqual([m['provenance'] for m in self.service.messages(self.a, 'c-a', after=after)['messages']], ['agent'])
        with self.assertRaises(NotFound):
            self.service.messages(self.b, 'c-a')
        with self.assertRaises(ValueError):
            self.service.messages(self.a, 'c-a', after=-1)
        with self.assertRaises(ValueError):
            self.service.messages(self.a, 'c-a', limit=101)

    def test_task_read_and_waiting_cancel(self):
        result = self.send()
        state = self.service.task(self.a, result['id'])
        self.assertEqual((state['state'], state['task_state'], state['reservation_state']), ('waiting', 'queued', 'active'))
        with self.assertRaises(NotFound):
            self.service.task(self.b, result['id'])
        self.assertEqual(self.service.cancel(self.a, result['id'])['state'], 'cancelled')
        self.assertIsNone(self.queue.claim(owner='w', capacity=CAPACITY))

    def metered_driver(self, gateway, **kw):
        return ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(gateway),
                          clock=lambda: self.now, sleep=lambda s: None, **kw)

    def test_usage_is_reconciled_from_provider_spend_delta(self):
        class Metered(SyntheticGateway):
            spend = [1000, 1000, 1700, 1700, 1700]
            def usage_snapshot(self): return self.spend.pop(0) if len(self.spend) > 1 else self.spend[0]
        self.send()
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        self.queue.finish(claim, self.metered_driver(Metered()).execute(claim))
        receipt = self.rows("SELECT amount_microusd,price_version FROM provider_receipts WHERE account_id='a'")
        self.assertEqual([tuple(r) for r in receipt], [(700, 'litellm-reported-v1')])
        self.assertEqual(self.rows("SELECT state FROM task_reservations WHERE account_id='a'")[0][0], 'settled')

    def test_unreadable_spend_charges_the_reserved_upper_bound(self):
        class Blind(SyntheticGateway):
            def usage_snapshot(self): raise RuntimeError('no spend')
        self.send()
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        self.queue.finish(claim, self.metered_driver(Blind()).execute(claim))
        self.assertEqual([tuple(r) for r in self.rows("SELECT amount_microusd,price_version FROM provider_receipts")],
                         [(500, 'reservation-upper-bound-v1')])

    def test_run_that_never_goes_idle_is_aborted_and_failed(self):
        gateway = SyntheticGateway(active_pages=10**6)
        def advance(seconds): self.now += 300
        self.send()
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(gateway),
                            clock=lambda: self.now, sleep=advance, run_timeout=900)
        receipt = driver.execute(claim)
        self.assertEqual(receipt.state, 'failed')
        self.assertTrue(gateway.abort_requests)

    def driver(self):
        return ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda:self.now)

    def test_driver_completes_serial_handoff_without_duplicate_transcript(self):
        first = self.send(key='r1');self.send(self.b, key='r2')
        self.assertTrue(self.queue.run_once(self.driver(), owner='w', capacity=CAPACITY))
        self.assertEqual(self.queue.get(self.a, first['id'])['state'], 'completed')
        self.assertIn('ack ', self.queue.get(self.a, first['id'])['result'])
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE conversation_id='c-a'")), 2)
        self.assertEqual(self.rows("SELECT state FROM task_reservations WHERE account_id='a'")[0][0], 'settled')
        self.assertEqual(self.rows("SELECT state FROM tasks WHERE account_id='a'")[0][0], 'completed')
        self.assertTrue(self.queue.run_once(self.driver(), owner='w', capacity=CAPACITY))
        self.assertEqual(self.queue.get(self.b, self.queue.get(self.b)[0]['id'])['state'], 'completed')
        self.assertIsNone(self.queue.claim(owner='w', capacity=CAPACITY))
        self.assertEqual(sum(1 for call in self.gateway.calls if call[0] == 'send'), 2)

    def test_driver_cancel_before_send_records_aborted_delivery(self):
        result = self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        # Claimed (starting): cancel records intent that the driver honours before any effect.
        self.service.cancel(self.a, result['id'])
        receipt = self.driver().execute(claim)
        self.assertEqual(receipt.state, 'cancelled')
        self.assertTrue(self.queue.finish(claim, receipt))
        self.assertEqual(self.rows('SELECT state FROM chat_deliveries')[0][0], 'aborted')
        self.assertEqual(self.rows('SELECT state FROM tasks')[0][0], 'cancelled')
        self.assertEqual(self.gateway.calls, [])

    def test_driver_cancel_during_run_aborts_scoped_run(self):
        result = self.send(key='r1')
        request_id = result['id']

        def set_cancel():
            with self.store.connect() as con:
                con.execute('UPDATE customer_requests SET cancel_requested=1 WHERE id=?', (request_id,))
        self.gateway.active_pages = 2
        self.gateway.on_history = set_cancel
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        receipt = self.driver().execute(claim)
        self.assertEqual(receipt.state, 'cancelled')
        self.assertTrue(self.queue.finish(claim, receipt))
        self.assertTrue(self.gateway.abort_requests)
        self.assertEqual(self.gateway.abort_requests[0][1], self.rows('SELECT native_run_id FROM chat_deliveries')[0][0])
        self.assertEqual(self.rows('SELECT state FROM chat_deliveries')[0][0], 'aborted')

    def test_unsupported_abort_stays_uncertain_with_intent(self):
        self.gateway.abort_supported = False
        result = self.send(key='r1')
        request_id = result['id']

        def set_cancel():
            with self.store.connect() as con:
                con.execute('UPDATE customer_requests SET cancel_requested=1 WHERE id=?', (request_id,))
        self.gateway.active_pages = 2
        self.gateway.on_history = set_cancel
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        with self.assertRaises(CapabilityUnavailable):
            self.driver().execute(claim)
        self.queue.uncertain(claim)
        self.assertEqual(self.queue.get(self.a, request_id)['state'], 'uncertain')
        self.assertEqual(self.rows('SELECT cancel_requested FROM customer_requests')[0][0], 1)
        self.assertFalse(self.gateway.abort_requests)

    def test_timeout_after_write_reconciles_without_resend(self):
        self.gateway.timeout_after_write = True
        result = self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        with self.assertRaises(TimeoutError):
            self.driver().execute(claim)
        self.queue.uncertain(claim)
        self.assertEqual(len(self.rows('SELECT 1 FROM chat_deliveries')), 1)
        self.assertEqual(self.rows('SELECT state FROM chat_deliveries')[0][0], 'uncertain')
        self.assertTrue(self.queue.reconcile(self.driver(), claim))
        self.assertEqual(self.queue.get(self.a, result['id'])['state'], 'completed')
        self.assertEqual(sum(1 for call in self.gateway.calls if call[0] == 'send'), 1)
        self.assertEqual(len(self.rows('SELECT 1 FROM chat_messages')), 1)

    def test_fail_after_ack_reconciles_terminal_history(self):
        self.gateway.fail_after_ack = True
        result = self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        with self.assertRaises(RuntimeError):
            self.driver().execute(claim)
        self.queue.uncertain(claim)
        self.assertTrue(self.queue.reconcile(self.driver(), claim))
        self.assertIn('ack ', self.queue.get(self.a, result['id'])['result'])
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE provenance='agent'")), 1)
        self.assertEqual(self.rows('SELECT state FROM chat_deliveries')[0][0], 'acknowledged')

    def test_execute_requires_admission_and_probe(self):
        self.service.pricer = UnmeasuredRoute()
        result = self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        with self.assertRaises(Conflict):
            self.driver().execute(claim)
        self.queue.uncertain(claim)
        broken = SyntheticGateway(protocol_version=99)
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(broken))
        with self.assertRaises(CapabilityUnavailable):
            driver.preflight()
        with self.assertRaises(ValueError):
            ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway)).execute(
                replace(claim, conversation_id=None))


if __name__ == '__main__':
    unittest.main()
