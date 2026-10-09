import json
from pathlib import Path
import tempfile
import unittest
from agentai_platform.budget import BudgetLedger
from agentai_platform.optimization import (OptimizationGate, OptimizationDenied, cost_microusd, upper_bound_microusd,
                                           PRICE_VERSION, MODEL)
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import Principal
from agentai_platform.store import Store

PIN = json.loads((Path(__file__).resolve().parents[2] / 'plans/product/phase-12-typesafe-pin.json').read_text())


class OptimizationChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite3'); self.store.initialize()
        self.now = 2000000000
        self.switches = {'browser': True, 'research': True}
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10 ** 9, clock=lambda: self.now)
        self.gate = OptimizationGate(self.store, self.ledger, kill_switches=lambda: self.switches, clock=lambda: self.now)
        self.a = Principal('a', 'actor-a', 'customer'); self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for x in 'ab':
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (x, 'actor-' + x))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (x, 'd-' + x))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (x, 'p-' + x, 'P'))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)',
                            (x, 'p-' + x, 'c-' + x, 'd-' + x))
                limits = {'period_start_epoch': self.now - 100000, 'period_microusd': 10 ** 6, 'daily_microusd': 10 ** 6,
                          'task_microusd': 10 ** 5, 'max_queued_tasks': 3}
                con.execute("INSERT INTO entitlements VALUES (?,?,'t','trial',?,datetime(?,'unixepoch'))",
                            (x, 'e-' + x, json.dumps(limits), self.now + 10 ** 6))
        self.ledger.admit(self.a, task='t1', project='p-a', conversation='c-a', key='t1', amount_microusd=5000,
                          upper_bound_verified=True)
        self.ledger.admit(self.b, task='t1', project='p-b', conversation='c-b', key='t1', amount_microusd=5000,
                          upper_bound_verified=True)

    def open_all(self, account='a', track='browser'):
        self.gate.record_activation(account, track, enabled=True, data_handling=True, transport_review=True, account_ref='ts-acct')

    def test_pin_matches_code_constants(self):
        self.assertEqual((PIN['model'], PIN['price_version']), (MODEL, PRICE_VERSION))
        self.assertEqual(PIN['input_microusd_per_1000_tokens'], 42)
        self.assertEqual(cost_microusd(1_000_000), 42000)       # $0.042 per Mtok
        self.assertEqual(cost_microusd(1), 1)                    # rounds up, never down
        self.assertEqual(upper_bound_microusd('x' * 10 ** 6), cost_microusd(64000))

    def test_every_layer_must_be_open(self):
        req = '{"state":"x"}'
        with self.assertRaises(OptimizationDenied) as r:
            self.gate.reserve_call(self.a, 't1', 'browser', 'c1', req)
        self.assertEqual(r.exception.reason, 'account_not_enabled')
        self.gate.record_activation('a', 'browser', enabled=True)
        for kwargs, reason in (({}, 'data_handling_not_approved'),
                               ({'data_handling': True}, 'transport_not_reviewed'),
                               ({'data_handling': True, 'transport_review': True}, 'no_typesafe_account')):
            self.gate.record_activation('a', 'browser', enabled=True, **kwargs)
            with self.assertRaises(OptimizationDenied) as r:
                self.gate.reserve_call(self.a, 't1', 'browser', 'c1', req)
            self.assertEqual(r.exception.reason, reason)
        self.open_all()
        self.assertGreater(self.gate.reserve_call(self.a, 't1', 'browser', 'c1', req), 0)
        self.switches['browser'] = False
        with self.assertRaises(OptimizationDenied) as r:
            self.gate.reserve_call(self.a, 't1', 'browser', 'c2', req)
        self.assertEqual(r.exception.reason, 'server_disabled')
        self.switches['browser'] = True
        self.gate.kill_switches = lambda: (_ for _ in ()).throw(OSError('config unreadable'))
        with self.assertRaises(OptimizationDenied) as r:
            self.gate.reserve_call(self.a, 't1', 'browser', 'c3', req)
        self.assertEqual(r.exception.reason, 'kill_switch_unreadable')

    def test_other_tracks_and_accounts_are_independent(self):
        self.open_all('a', 'browser')
        with self.assertRaises(OptimizationDenied):
            self.gate.reserve_call(self.a, 't1', 'research', 'c1', '{}')
        with self.assertRaises(OptimizationDenied):
            self.gate.reserve_call(self.b, 't1', 'browser', 'c1', '{}')
        with self.assertRaises(OptimizationDenied):
            self.gate.reserve_call(self.a, 't1', 'nonsense', 'c1', '{}')

    def test_reserve_record_and_billing_through_phase5(self):
        self.open_all()
        bound = self.gate.reserve_call(self.a, 't1', 'browser', 'c1', 'x' * 4000)
        self.assertEqual(self.gate.reserve_call(self.a, 't1', 'browser', 'c1', 'x' * 4000), bound)   # idempotent
        self.assertEqual(self.gate.unreconciled('a', 't1'), 1)
        self.assertEqual(self.gate.record_call('a', 't1', 'c1', 1500), cost_microusd(1500))
        self.assertEqual(self.gate.unreconciled('a', 't1'), 0)
        with self.store.connect() as con:
            row = con.execute("SELECT provider,amount_microusd,price_version FROM provider_receipts").fetchone()
        self.assertEqual(tuple(row), ('typesafe', cost_microusd(1500), PRICE_VERSION))
        with self.assertRaises(Conflict):
            self.gate.record_call('a', 't1', 'c1', 1500)

    def test_task_budget_is_enforced_including_open_holds(self):
        self.open_all()
        big = 'x' * 64000                      # bound = 2688 microusd
        self.gate.reserve_call(self.a, 't1', 'browser', 'c1', big)
        with self.assertRaises(OptimizationDenied) as r:   # 2688*2 > 5000
            self.gate.reserve_call(self.a, 't1', 'browser', 'c2', big)
        self.assertEqual(r.exception.reason, 'task_budget_exhausted')
        self.gate.release_unsent('a', 'c1')
        self.gate.reserve_call(self.a, 't1', 'browser', 'c2', big)

    def test_uncertain_call_keeps_hold_until_reconciled_and_blocks_settlement(self):
        self.open_all()
        self.gate.reserve_call(self.a, 't1', 'browser', 'c1', 'x' * 64000)
        self.gate.mark_uncertain('a', 'c1')
        self.assertEqual(self.gate.unreconciled('a', 't1'), 1)
        with self.assertRaises(OptimizationDenied):                # hold still counts against the task
            self.gate.reserve_call(self.a, 't1', 'browser', 'c2', 'x' * 64000)
        self.assertEqual(self.gate.record_call('a', 't1', 'c1', 900), cost_microusd(900))   # reconcile from provider usage
        self.assertEqual(self.gate.unreconciled('a', 't1'), 0)
        with self.assertRaises(Conflict):
            self.gate.mark_uncertain('a', 'c1')

    def test_receipt_appears_in_customer_usage_not_other_accounts(self):
        self.open_all()
        self.gate.reserve_call(self.a, 't1', 'browser', 'c1', '{}')
        self.gate.record_call('a', 't1', 'c1', 100)
        self.assertEqual(self.ledger.summary(self.a)['reported_microusd'], cost_microusd(100))
        self.assertEqual(self.ledger.summary(self.b)['reported_microusd'], 0)


if __name__ == '__main__':
    unittest.main()
