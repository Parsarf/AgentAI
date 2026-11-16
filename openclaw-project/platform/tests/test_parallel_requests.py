"""Roadmap #8: several customers work at once. A request runs when its own account has a cell up and no task running; accounts are served fairly; a full host
leaves requests waiting (never failed); a crash with several requests in flight recovers each one once."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from agentai_platform.budget import BudgetLedger
from agentai_platform.capacity import CapacityResult
from agentai_platform.chat import ChatService, FixedRoute
from agentai_platform.chat_driver import ChatDriver, synthetic_gateway_factory
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.request_queue import RequestQueue
from agentai_platform.request_worker import RequestWorker
from agentai_platform.security import Principal
from agentai_platform.store import Store

OK = CapacityResult(1, 1, 1, 1, 1, ())
FULL = CapacityResult(0, 0, 0, 0, 0, ('memory_exhausted', 'cpu_exhausted'))
STALE = CapacityResult(1, 1, 1, 1, 1, ('measurement_stale',))
LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000000, 'daily_microusd': 100000000, 'task_microusd': 5000000, 'max_queued_tasks': 3}


class Pool(unittest.TestCase):
    ACCOUNTS = ('a', 'b', 'c')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize(); self.now = 2000000000
        self.queue = RequestQueue(self.store, clock=lambda: self.now, require_cell=True)
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10**9, clock=lambda: self.now)
        self.chat = ChatService(self.store, queue=self.queue, ledger=self.ledger, pricer=FixedRoute(1000000), clock=lambda: self.now, execution=True)
        self.who = {a: Principal(a, 'actor-' + a, 'customer') for a in self.ACCOUNTS}
        with self.store.connect() as con:
            for a in self.ACCOUNTS:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'ready')", (a, 'd-' + a))
                con.execute("INSERT INTO projects(account_id,id,name) VALUES (?,?,'P')", (a, 'p-' + a))
                for n in (1, 2):
                    con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)", (a, 'p-' + a, f'c{n}-{a}', 'd-' + a))
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))", (a, 'e-' + a, json.dumps(LIMITS), self.now + 10**6))
        self.gateway = SyntheticGateway()

    def cell(self, account, state='active'):
        with self.store.connect() as con:
            con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation) VALUES (?,?,?,'start','completed','k','h',1)", (account, 'op-' + account, 'd-' + account))
            con.execute("INSERT INTO cell_slots(account_id,deployment_id,operation_id,state) VALUES (?,?,?,?)", (account, 'd-' + account, 'op-' + account, state))

    def send(self, account, key, conversation=1, message='hi'):
        return self.chat.send(self.who[account], conversation_id=f'c{conversation}-{account}', message=message, key=key)

    def claim(self, capacity=OK, **kw):
        return self.queue.claim(owner='w', capacity=capacity, **kw)

    def rows(self, sql, *args):
        with self.store.connect() as con:
            return [tuple(r) for r in con.execute(sql, args).fetchall()]

    def state_of(self, request):
        return self.rows('SELECT state FROM customer_requests WHERE id=?', request)[0][0]


class ClaimChecks(Pool):
    def test_two_accounts_hold_a_running_slot_at_the_same_time(self):
        self.cell('a'); self.cell('b')
        self.send('a', 'ka'); self.send('b', 'kb')
        first, second = self.claim(), self.claim()
        self.assertEqual({first.account_id, second.account_id}, {'a', 'b'})
        self.assertIsNone(self.claim())
        self.assertEqual(self.rows('SELECT count(*) FROM request_slots')[0][0], 2)

    def test_one_task_per_account_even_across_conversations(self):
        self.cell('a')
        self.send('a', 'k1', 1); self.send('a', 'k2', 2)
        first = self.claim()
        self.assertEqual(first.account_id, 'a')
        self.assertIsNone(self.claim())                                  # the second conversation waits for the account's running task
        self.queue.finish(first, self._receipt(first))
        self.assertEqual(self.claim().account_id, 'a')

    def test_a_request_admitted_on_another_model_route_waits_for_the_accounts_live_requests(self):
        self.cell('a')
        self.send('a', 'k1', 1)
        first = self.claim()
        with self.store.connect() as con:                                # a phase of a plan in its lane (it could run beside the first), admitted after the customer changed their model
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id,parent_id) VALUES ('a','p-a','lane-a','d-a','c1-a')")
        other = self.chat.send(self.who['a'], conversation_id='lane-a', message='phase', key='k2')
        other_id = other['request']['id'] if 'request' in other else other['id']
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET context_json=? WHERE id=?", (json.dumps({'model_selection': 'key:other'}), other_id))
        self.assertIsNone(self.claim())                                  # two routes live at once would get every model call of both refused
        self.assertEqual(self.state_of(other_id), 'waiting')
        self.queue.finish(first, self._receipt(first))
        self.assertEqual(self.claim().request_id, other_id)

    def test_requests_on_the_same_route_still_run_side_by_side(self):
        self.cell('a')
        self.send('a', 'k1', 1)
        with self.store.connect() as con:
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id,parent_id) VALUES ('a','p-a','lane-a','d-a','c1-a')")
        self.chat.send(self.who['a'], conversation_id='lane-a', message='phase', key='k2')
        self.assertEqual(sum(self.claim() is not None for _ in range(3)), 2)

    def _receipt(self, claim):
        from agentai_platform.request_queue import RequestReceipt
        with self.store.connect() as con:
            con.execute("UPDATE task_reservations SET state='settled' WHERE account_id=? AND task_id=?", (claim.account_id, claim.request_id))
        return RequestReceipt(claim.account_id, claim.request_id, claim.fence, 'completed', 'done', True)

    def test_an_account_without_a_cell_waits_and_does_not_block_the_others(self):
        self.cell('b')
        self.send('a', 'ka'); self.send('b', 'kb')                        # a was first in line, but its cell is not up
        claim = self.claim()
        self.assertEqual(claim.account_id, 'b')
        self.assertIsNone(self.claim())
        self.assertEqual(self.state_of(self.rows("SELECT id FROM customer_requests WHERE account_id='a'")[0][0]), 'waiting')

    def test_a_cell_still_starting_does_not_run_requests(self):
        self.cell('a', 'reserved')
        self.send('a', 'ka')
        self.assertIsNone(self.claim())

    def test_accounts_are_served_fairly_not_by_who_queued_most(self):
        self.cell('a'); self.cell('b')
        for n in range(3):
            self.send('a', f'ka{n}')
        self.send('b', 'kb')
        order = []
        for _ in range(4):
            claim = self.claim()
            order.append(claim.account_id)
            self.queue.finish(claim, self._receipt(claim))
            self.now += 1
        # a was queued first but b must not wait behind all of a's tasks: after one of a's, b goes next
        self.assertEqual(order[:2], ['a', 'b'])
        self.assertEqual(order[2:], ['a', 'a'])

    def test_a_full_host_does_not_stop_requests_on_cells_that_are_already_up(self):
        self.cell('a')
        self.send('a', 'ka')
        self.assertEqual(self.claim(capacity=FULL).account_id, 'a')

    def test_a_stale_measurement_still_blocks_every_claim(self):
        self.cell('a')
        self.send('a', 'ka')
        self.assertIsNone(self.claim(capacity=STALE))

    def test_accounts_the_caller_already_runs_are_skipped(self):
        self.cell('a'); self.cell('b')
        self.send('a', 'ka'); self.send('b', 'kb')
        self.assertEqual(self.claim(exclude={'a'}).account_id, 'b')

    def test_a_waiting_task_says_what_it_waits_for(self):
        self.send('a', 'k1', 1); self.send('a', 'k2', 2)
        waits = sorted(v['wait'] for v in self.queue.get(self.who['a']))
        self.assertEqual(waits, ['assistant', 'your_task'])              # the first waits for its assistant (no cell yet), the second behind the first

    def test_when_the_host_is_full_earlier_waiting_tasks_of_other_accounts_are_ahead(self):
        self.send('a', 'ka'); self.send('b', 'kb')
        self.assertEqual({v['ahead'] for v in self.queue.get(self.who['b'])}, {0})        # the host has room: b is not behind a
        with self.store.connect() as con:
            con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation) VALUES ('b','op-b','d-b','start','pending','k','h',1)")
            con.execute("INSERT INTO lifecycle_details(account_id,operation_id,target_profile,error_code,updated_at) VALUES ('b','op-b','p','capacity_wait',0)")
        view = self.queue.get(self.who['b'])[0]
        self.assertEqual((view['ahead'], view['wait']), (1, 'assistant'))                 # b's cell cannot start until room is made: a's earlier task is in front

    def test_other_accounts_running_tasks_do_not_count_as_ahead(self):
        self.cell('a'); self.cell('b')
        self.send('a', 'ka'); self.send('b', 'kb')
        self.claim()
        views = [v for v in self.queue.get(self.who['b']) + self.queue.get(self.who['a']) if v['state'] == 'waiting' or v['state'] == 'starting']
        for v in views:
            self.assertIn(v['ahead'], (None, 0))


class CrashChecks(Pool):
    def test_two_requests_in_flight_when_the_worker_dies_are_both_recovered_once(self):
        self.cell('a'); self.cell('b')
        self.send('a', 'ka'); self.send('b', 'kb')
        self.gateway.fail_after_ack = True
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda: self.now)
        worker = RequestWorker(self.queue, driver, lambda: OK, clock=lambda: self.now, max_parallel=4)
        worker.tick(); self.assertTrue(worker.wait_idle(10))
        self.assertEqual(self.rows("SELECT count(*) FROM customer_requests WHERE state='uncertain'")[0][0], 2)
        self.assertEqual(len(worker._uncertain_claims()), 2)
        self.gateway.fail_after_ack = False
        worker._errors.clear()
        for _ in range(5):
            worker.tick(); worker.wait_idle(10)
        self.assertEqual(self.rows("SELECT state FROM customer_requests ORDER BY account_id"), [('completed',), ('completed',)])
        self.assertEqual(self.rows('SELECT count(*) FROM request_slots')[0][0], 0)
        self.assertEqual(len(self.gateway.runs), 2)                       # one run each: a repeated send carries the same key, so the runtime never starts a second run


class ThreadChecks(Pool):
    def worker(self, **kw):
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda: self.now)
        return RequestWorker(self.queue, driver, lambda: OK, clock=lambda: self.now, **kw)

    def test_two_accounts_really_run_at_the_same_time(self):
        self.cell('a'); self.cell('b')
        self.send('a', 'ka'); self.send('b', 'kb')
        meeting = threading.Barrier(2, timeout=10)
        seen = set()

        def at_wait(run):
            if run['id'] in seen:
                return
            seen.add(run['id'])
            meeting.wait()              # both runs must be inside wait() together, or this raises BrokenBarrierError
        self.gateway.on_wait = at_wait
        worker = self.worker(max_parallel=4)
        report = worker.tick()
        self.assertEqual(report.get('started'), 2)
        self.assertTrue(worker.wait_idle(20))
        self.assertEqual(self.rows("SELECT state FROM customer_requests ORDER BY account_id"), [('completed',), ('completed',)])
        self.assertEqual(self.rows('SELECT count(*) FROM request_slots')[0][0], 0)
        self.assertEqual(worker._errors, [])

    def test_a_full_pool_of_threads_leaves_the_rest_waiting_not_failed(self):
        for a in self.ACCOUNTS:
            self.cell(a); self.send(a, 'k' + a)
        release = threading.Event()
        self.gateway.on_wait = lambda run: release.wait(10)
        worker = self.worker(max_parallel=2)
        self.assertEqual(worker.tick().get('started'), 2)
        self.assertEqual(worker.tick().get('started'), None)             # no thread left: the third waits
        self.assertEqual(self.rows("SELECT count(*) FROM customer_requests WHERE state='waiting'")[0][0], 1)
        release.set()
        self.assertTrue(worker.wait_idle(20))
        worker.tick(); self.assertTrue(worker.wait_idle(20))
        self.assertEqual(self.rows("SELECT count(*) FROM customer_requests WHERE state='completed'")[0][0], 3)

    def test_the_default_runs_one_request_at_a_time_in_the_calling_thread(self):
        self.cell('a'); self.cell('b')
        self.send('a', 'ka'); self.send('b', 'kb')
        worker = self.worker()
        self.assertEqual(worker.tick(), {'ran': 1, 'finished': True})
        self.assertEqual(self.rows("SELECT count(*) FROM customer_requests WHERE state='completed'")[0][0], 1)


if __name__ == '__main__':
    unittest.main()
