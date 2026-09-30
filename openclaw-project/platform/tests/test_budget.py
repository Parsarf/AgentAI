import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from agentai_platform.budget import BudgetLedger,BudgetDenied
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import Principal,NotFound
from agentai_platform.store import Store

class BudgetChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state'/'db.sqlite3');self.store.initialize()
        self.now=2000000000
        self.ledger=BudgetLedger(self.store,service_limit_microusd=1000,clock=lambda:self.now)
        self.a=Principal('a','actor-a','customer');self.b=Principal('b','actor-b','customer')
        with self.store.connect() as con:
            for a in ['a','b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')",(a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')",(a,'actor-'+a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')",(a,'d-'+a))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)',(a,'p-'+a,'Project '+a))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)',(a,'p-'+a,'c-'+a,'d-'+a))
                limits={'period_start_epoch':self.now-100000,'period_microusd':100,'daily_microusd':100,'task_microusd':100,'max_queued_tasks':3}
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))",(a,'e-'+a,json.dumps(limits),self.now+1000000))
    def admit(self,task='t1',principal=None,amount=60,**kw):
        actor=principal or self.a
        return self.ledger.admit(actor,task=task,project='p-'+actor.account_id,conversation='c-'+actor.account_id,
                                 key=task,amount_microusd=amount,upper_bound_verified=True,**kw)
    def receipt(self,request='r1',amount=20,task='t1',account='a',**kw):
        return self.ledger.receipt(account=account,task=task,provider='test-route',request=request,
            amount_microusd=amount,observed_epoch=self.now,price_version='test-price-v1',payload_hash='a'*64,**kw)
    def settle(self,task='t1',account='a'):
        return self.ledger.settle(account=account,task=task,effects_quiesced=True,all_routes_reconciled=True)
    def test_atomic_task_and_reservation_idempotency(self):
        first=self.admit();self.assertEqual(first,self.admit())
        with self.assertRaises(Conflict):self.admit(amount=61)
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT count(*) FROM usage_entries').fetchone()[0],1)
    def test_racing_final_allowance_admissions(self):
        barrier=threading.Barrier(2);outcomes=[];errors=[]
        def attempt(t):
            try:barrier.wait();self.admit(t);outcomes.append('admitted')
            except BudgetDenied:outcomes.append('denied')
            except Exception as exc:errors.append(exc)
        threads=[threading.Thread(target=attempt,args=(t,)) for t in ['t1','t2']]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertFalse(errors);self.assertCountEqual(outcomes,['admitted','denied'])
    def test_reported_usage_consumes_hold_without_double_counting(self):
        self.admit();self.receipt()
        s=self.ledger.summary(self.a);self.assertEqual((s['reported_microusd'],s['held_microusd'],s['period_remaining_microusd']),(20,40,40))
        self.admit('t2',amount=40)
        with self.assertRaises(BudgetDenied):self.admit('t3',amount=1)
    def test_uncertain_effects_keep_allowance_reserved(self):
        self.admit();self.receipt()
        self.assertFalse(self.ledger.settle(account='a',task='t1',effects_quiesced=True))
        self.assertEqual(self.ledger.summary(self.a)['held_microusd'],40)
        self.assertTrue(self.ledger.summary(self.a)['usage_pending'])
        self.settle();self.assertEqual(self.ledger.summary(self.a)['held_microusd'],0)
        self.assertFalse(self.settle())
    def test_duplicate_changed_foreign_and_late_receipts(self):
        self.admit();self.assertTrue(self.receipt());self.assertFalse(self.receipt())
        with self.assertRaises(Conflict):self.receipt(amount=21)
        with self.assertRaises(NotFound):self.receipt(account='b')
        self.settle();self.receipt('r-late',amount=5)
        self.assertTrue(self.ledger.summary(self.a)['usage_pending'])
        self.settle()
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT sum(amount_microusd) FROM usage_entries WHERE kind='released'").fetchone()[0],35)
        self.assertEqual(self.ledger.summary(self.a)['reported_microusd'],25)
    def test_service_overrun_accounted_and_blocks_new_work(self):
        self.admit();self.receipt(amount=120);self.settle()
        self.assertEqual(self.ledger.summary(self.a)['period_remaining_microusd'],0)
        with self.assertRaises(BudgetDenied):self.admit('t2',amount=1)
        self.ledger.service_limit=120
        with self.assertRaises(BudgetDenied):self.admit('t-b',self.b,amount=1)
    def test_cross_account_conversation_and_revocation(self):
        with self.assertRaises(NotFound):self.ledger.admit(self.a,task='x',project='p-b',conversation='c-b',key='x',amount_microusd=1,upper_bound_verified=True)
        with self.store.connect() as con:con.execute("UPDATE memberships SET status='revoked' WHERE account_id='a'")
        with self.assertRaises(NotFound):self.admit()
    def test_unknown_price_currency_and_service_limit_no_task(self):
        with self.assertRaises(BudgetDenied):self.ledger.admit(self.a,task='x',project='p-a',conversation='c-a',key='x',amount_microusd=1)
        with self.assertRaises(ValueError):self.admit(currency='EUR')
        self.ledger.service_limit=None
        with self.assertRaises(BudgetDenied):self.admit()
        with self.store.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM tasks').fetchone()[0],0)
    def test_period_daily_expiry_and_queue_ceiling(self):
        with self.store.connect() as con:
            limits={'period_start_epoch':self.now-100000,'period_microusd':100,'daily_microusd':30,'task_microusd':20,'max_queued_tasks':3}
            con.execute('UPDATE entitlements SET limits_json=? WHERE account_id=?',(json.dumps(limits),'a'))
        self.admit(amount=20)
        with self.assertRaises(BudgetDenied):self.admit('t2',amount=11)
        self.admit('t2',amount=5);self.admit('t3',amount=5)
        with self.assertRaises(BudgetDenied):self.admit('t4',amount=1)
        self.now+=1000001
        with self.assertRaises(BudgetDenied):self.admit('t5',amount=1)
        self.assertEqual(self.ledger.summary(self.a)['period_remaining_microusd'],0)
        self.assertFalse(self.ledger.summary(self.a)['admission_eligible'])
    def test_immutable_receipts_and_audit_atomicity(self):
        self.admit();self.receipt()
        with self.store.connect() as con:
            with self.assertRaises(sqlite3.IntegrityError):con.execute('DELETE FROM provider_receipts')
        with self.store.connect() as con:con.execute("CREATE TRIGGER reject_budget_audit BEFORE INSERT ON audit_events WHEN NEW.action='lifecycle.budget_admit' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.admit('t2',amount=1)
        with self.store.connect() as con:self.assertFalse(con.execute("SELECT 1 FROM tasks WHERE id='t2'").fetchone())

if __name__=='__main__':unittest.main()
