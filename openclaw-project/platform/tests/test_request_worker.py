import json
from pathlib import Path
import tempfile
import unittest
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.budget import BudgetLedger
from agentai_platform.capacity import CapacityResult
from agentai_platform.chat import ChatDriver, ChatService, FixedRoute, synthetic_gateway_factory
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.request_queue import RequestQueue
from agentai_platform.request_worker import RequestWorker
from agentai_platform.security import Principal
from agentai_platform.store import Store

OK = CapacityResult(1, 1, 1, 1, 1, ())
LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000000, 'daily_microusd': 100000000,
          'task_microusd': 5000000, 'max_queued_tasks': 3}


class RequestWorkerChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize(); self.now = 2000000000
        self.queue = RequestQueue(self.store, clock=lambda: self.now, require_cell=True)
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10**9, clock=lambda: self.now)
        self.chat = ChatService(self.store, queue=self.queue, ledger=self.ledger, pricer=FixedRoute(1000000), clock=lambda: self.now, execution=True)
        self.a = Principal('a', 'actor-a', 'customer')
        with self.store.connect() as con:
            con.execute("INSERT INTO accounts(id,status) VALUES ('a','active')")
            con.execute("INSERT INTO memberships VALUES ('a','actor-a','customer','active')")
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('a','d-a',1,'ready')")
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p-a','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p-a','c-a','d-a')")
            con.execute("INSERT INTO entitlements VALUES ('a','e-a','test-v1','trial',?,datetime(?,'unixepoch'))", (json.dumps(LIMITS), self.now + 10**6))
        self.gateway = SyntheticGateway()
        beats = self.beats = []
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway),
                            clock=lambda: self.now, heartbeat=lambda claim: (beats.append(1), self.queue.heartbeat(claim))[1])
        self.worker = RequestWorker(self.queue, driver, lambda: OK, clock=lambda: self.now)

    def hold_cell(self, state='active'):
        with self.store.connect() as con:
            con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation) "
                        "VALUES ('a','op1','d-a','start','completed','k','h',1)")
            con.execute("INSERT INTO lifecycle_slot VALUES (1,'a','d-a','op1',?)", (state,))

    def test_request_waits_without_a_running_cell_then_runs_and_keeps_the_cell_up(self):
        self.chat.send(self.a, conversation_id='c-a', message='hi', key='k1')
        self.assertEqual(self.worker.tick(), {'ran': 0})                       # cell stopped: nothing is claimed
        self.hold_cell()
        report = self.worker.tick()
        self.assertEqual(report, {'ran': 1, 'finished': True})
        self.assertTrue(self.beats)                                            # lease kept alive while polling
        page = self.chat.messages(self.a, 'c-a')
        self.assertEqual([m['provenance'] for m in page['messages']], ['customer', 'agent'])
        self.assertTrue(page['execution_enabled'])
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT account_id FROM lifecycle_slot').fetchone()[0], 'a')   # cell stays up for idle sleep
            self.assertIsNone(con.execute('SELECT 1 FROM request_slot').fetchone())
        self.assertEqual(self.worker.tick(), {'ran': 0})

    def test_failed_execution_leaves_the_request_uncertain_and_blocks_new_claims(self):
        self.chat.send(self.a, conversation_id='c-a', message='hi', key='k1'); self.hold_cell()
        self.gateway.fail_after_ack = True
        with self.assertRaises(RuntimeError): self.worker.tick()
        state = self.worker._uncertain_claim()
        self.assertIsNotNone(state)
        self.gateway.fail_after_ack = False
        self.assertEqual(self.worker.tick(), {'reconciled': True})              # recovered from the cell transcript
        self.assertIsNone(self.worker._uncertain_claim())


if __name__ == '__main__':
    unittest.main()


class RecoveryChecks(RequestWorkerChecks):
    def test_request_that_never_reached_a_session_fails_cleanly_and_frees_the_slot(self):
        self.chat.send(self.a, conversation_id='c-a', message='hi', key='k1'); self.hold_cell()
        claim = self.queue.claim(owner='w', capacity=OK)
        self.queue.uncertain(claim)                                     # e.g. the worker crashed before any send
        self.assertEqual(self.worker.tick(), {'reconciled': True})
        self.assertEqual(self.chat.task(self.a, claim.request_id)['state'], 'failed')
        self.assertEqual(self.rows("SELECT amount_microusd FROM provider_receipts"), [])        # nothing was spent
        self.assertEqual(self.rows("SELECT state FROM task_reservations")[0][0], 'settled')

    def test_unreachable_runtime_is_abandoned_after_the_grace_period_with_the_reserved_charge(self):
        class Down(SyntheticGateway):
            def history(self, session, cursor): raise CapabilityUnavailable('down')
        self.chat.send(self.a, conversation_id='c-a', message='hi', key='k1'); self.hold_cell()
        good = self.worker
        self.gateway.fail_after_ack = True
        with self.assertRaises(RuntimeError): good.tick()
        down = Down(); down.sessions = self.gateway.sessions
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(down), clock=lambda: self.now)
        worker = RequestWorker(self.queue, driver, lambda: OK, clock=lambda: self.now, abandon_after=600)
        self.assertEqual(worker.tick()['reconciled'], False)
        self.now += 601
        self.assertEqual(worker.tick(), {'reconciled': True, 'abandoned': True})
        self.assertEqual([tuple(r) for r in self.rows("SELECT amount_microusd,price_version FROM provider_receipts")], [(1000000, 'reservation-upper-bound-v1')])

    def rows(self, sql):
        with self.store.connect() as con:
            return con.execute(sql).fetchall()


class RecoveredUsageChecks(RequestWorkerChecks):
    def test_recovered_request_reconciles_exact_spend_from_the_stored_baseline(self):
        class Metered(SyntheticGateway):
            spend = [1000, 1700, 1700, 1700, 1700]
            def usage_snapshot(self): return self.spend.pop(0) if len(self.spend) > 1 else self.spend[0]
        gateway = Metered(fail_after_ack=True)
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(gateway), clock=lambda: self.now)
        worker = RequestWorker(self.queue, driver, lambda: OK, clock=lambda: self.now)
        self.chat.send(self.a, conversation_id='c-a', message='hi', key='k1')
        with self.store.connect() as con:
            con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation) VALUES ('a','op1','d-a','start','completed','k','h',1)")
            con.execute("INSERT INTO lifecycle_slot VALUES (1,'a','d-a','op1','active')")
        with self.assertRaises(RuntimeError): worker.tick()
        gateway.fail_after_ack = False
        self.assertEqual(worker.tick(), {'reconciled': True})
        with self.store.connect() as con:
            self.assertEqual([tuple(r) for r in con.execute('SELECT amount_microusd,price_version FROM provider_receipts')], [(700, 'litellm-reported-v1')])
