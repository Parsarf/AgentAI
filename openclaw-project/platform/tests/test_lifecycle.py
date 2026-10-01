from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.store import Store
from agentai_platform.security import Principal,NotFound
from agentai_platform.capacity import CapacityResult
from agentai_platform.lifecycle.coordinator import Coordinator
from agentai_platform.lifecycle.types import Conflict,DisabledDriver
from tests.lifecycle_fixture import FixtureDriver

CAPACITY=CapacityResult(1,1,1,1,1,())
class LifecycleChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'state'/'db.sqlite3');self.store.initialize()
        self.now=2000000000
        self.engine=Coordinator(self.store,profiles={'trial-unmeasured-v1','next-pinned-v1'},clock=lambda:self.now)
        self.driver=FixtureDriver(self.root/'fixture')
        with self.store.connect() as con:
            # Minimal authority tables for this unit boundary. HTTP tests use the real Django schema/MFA.
            con.execute('CREATE TABLE auth_user(id INTEGER PRIMARY KEY,is_active INTEGER)')
            con.execute('CREATE TABLE accounts_identity(user_id INTEGER,role TEXT,verified INTEGER)')
            con.execute('CREATE TABLE accounts_operatorgrant(user_id INTEGER,account_id TEXT,action TEXT,expires_at TEXT)')
            con.execute("INSERT INTO auth_user VALUES (1,1)")
            con.execute("INSERT INTO accounts_identity VALUES (1,'operator',1)")
            for a in ['a','b','c']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')",(a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')",(a,'customer-'+a))
                for kind in ['create','start','stop','backup','restore','upgrade','delete']:
                    con.execute("INSERT INTO accounts_operatorgrant VALUES (1,?,?,datetime(?,'unixepoch'))",(a,'lifecycle_'+kind,self.now+3600))
    def request(self,kind,account='a',key=None,**kw):
        if kind!='create':
            with self.store.connect() as con:
                kw.setdefault('generation',con.execute('SELECT generation FROM deployments WHERE account_id=?',(account,)).fetchone()[0])
        return self.engine.request(Principal(account,'1','operator'),kind=kind,key=key or kind+str(self.now),**kw)
    def execute(self,op,account='a'):
        return self.engine.run(self.driver,account,op['id'],capacity=CAPACITY)
    def create(self,a='a'):
        op=self.request('create',a);self.assertTrue(self.execute(op,a));return op
    def cell(self,a='a'):
        with self.store.connect() as con:return dict(con.execute('SELECT * FROM lifecycle_cells WHERE account_id=?',(a,)).fetchone())
    def test_fixed_account_binding_and_idempotency(self):
        op=self.request('create',key='fixed');self.assertEqual(op,self.request('create',key='fixed'))
        with self.assertRaises(Conflict): self.request('create',key='fixed',target_profile='next-pinned-v1')
        self.assertTrue(self.execute(op));self.assertFalse(self.execute(op));self.assertEqual(self.driver.effects,1)
        with self.assertRaises(NotFound):self.engine.get(Principal('b','customer-b','customer'),op['id'])
        public=self.engine.get(Principal('a','customer-a','customer'),op['id'])
        self.assertNotIn('tenant_ref',public);self.assertNotIn('lease_owner',public)
    def test_customer_cannot_queue_and_expired_grant_denied(self):
        with self.assertRaises(NotFound):self.engine.request(Principal('a','customer-a','customer'),kind='create',key='x')
        self.now+=3601
        with self.assertRaises(NotFound):self.request('create')
        with self.store.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM deployments').fetchone()[0],0)
    def test_trial_ceiling_and_unique_cells(self):
        self.create('a');self.create('b')
        self.assertNotEqual(self.cell('a')['tenant_ref'],self.cell('b')['tenant_ref'])
        with self.assertRaises(Conflict):self.request('create','c')
    def test_single_global_slot_and_stop_before_switch(self):
        self.create('a');self.create('b');a=self.request('start','a');b=self.request('start','b')
        self.assertTrue(self.execute(a,'a'));self.assertFalse(self.execute(b,'b'))
        self.assertTrue(self.execute(self.request('stop','a'),'a'));self.assertTrue(self.execute(b,'b'))
        self.assertEqual(self.cell('a')['observed_state'],'stopped');self.assertEqual(self.cell('b')['observed_state'],'running')
    def test_racing_workers_only_one_claim(self):
        self.create('a');self.create('b');ops={a:self.request('start',a)['id'] for a in ['a','b']}
        barrier=threading.Barrier(2);results=[];errors=[]
        def worker(a):
            try:
                barrier.wait();results.append(self.engine.claim(a,ops[a],owner=a,capacity=CAPACITY))
            except Exception as exc:errors.append(exc)
        threads=[threading.Thread(target=worker,args=(a,)) for a in ['a','b']]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertFalse(errors);self.assertEqual(sum(x is not None for x in results),1)
    def test_unknown_outcome_reconciles_without_repeating_effect(self):
        self.create('a');self.create('b');op=self.request('start');self.driver.fail_after=True
        with self.assertRaises(TimeoutError):self.execute(op)
        self.assertEqual(self.cell()['observed_state'],'unknown')
        self.assertFalse(self.execute(self.request('start','b'),'b'))
        with self.assertRaises(Conflict):self.engine.retry(Principal('a','1','operator'),op['id'])
        count=self.driver.effects;self.assertTrue(self.engine.reconcile(self.driver,'a',op['id']))
        self.assertEqual(self.driver.effects,count);self.assertEqual(self.cell()['observed_state'],'running')
    def test_expired_lease_cannot_dispatch_or_release_slot(self):
        self.create();op=self.request('start');claim=self.engine.claim('a',op['id'],owner='old',capacity=CAPACITY)
        self.now+=61
        self.assertIsNone(self.engine.claim('a',op['id'],owner='new',capacity=CAPACITY))
        self.assertFalse(self.engine.reconcile(self.driver,'a',op['id']))
        with self.store.connect() as con:self.assertEqual(con.execute('SELECT state FROM lifecycle_slot').fetchone()[0],'uncertain')
        receipt=self.driver.execute(claim)
        self.assertFalse(self.engine.finish(claim,receipt))
        self.assertTrue(self.engine.reconcile(self.driver,'a',op['id']))
    def test_receipt_binding_and_late_worker_fenced(self):
        op=self.request('create');claim=self.engine.claim('a',op['id'],owner='old',capacity=CAPACITY)
        receipt=self.driver.execute(claim)
        with self.assertRaises(Conflict):self.engine.finish(claim,replace(receipt,account_id='b'))
        with self.assertRaises(Conflict):self.engine.finish(claim,replace(receipt,fence=claim.fence+1))
        with self.assertRaises(Conflict):self.engine.finish(claim,replace(receipt,fence=True))
        self.assertTrue(self.engine.finish(claim,receipt))
        with self.assertRaises(Conflict):self.engine.finish(claim,receipt)
    def test_definite_failure_retry_limit_and_same_deployment(self):
        op=self.request('create');self.driver.fail_before=True
        for i in range(3):
            self.assertTrue(self.execute(op))
            if i<2:self.engine.retry(Principal('a','1','operator'),op['id'])
        with self.assertRaises(Conflict):self.engine.retry(Principal('a','1','operator'),op['id'])
        with self.store.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM deployments').fetchone()[0],1)
    def test_partial_setup_retry_success_preserves_identity(self):
        op=self.request('create');deployment=self.cell()['deployment_id'];self.driver.fail_before=True;self.execute(op)
        self.engine.retry(Principal('a','1','operator'),op['id']);self.driver.fail_before=False;self.assertTrue(self.execute(op))
        self.assertEqual(self.cell()['deployment_id'],deployment)
    def test_backup_restore_upgrade_and_delete_only_bound_account(self):
        self.create('a');self.create('b');b=self.cell('b');bfile=self.driver.root/b['tenant_ref']/'state.json';prior=bfile.read_bytes()
        with self.assertRaises(Conflict):self.request('upgrade',target_profile='next-pinned-v1')
        backup=self.request('backup');self.execute(backup)
        with self.assertRaises(NotFound):self.request('restore','b',backup_ref=backup['id'])
        restore=self.request('restore',backup_ref=backup['id']);self.execute(restore)
        self.assertEqual(self.cell()['observed_state'],'stopped')
        backup2=self.request('backup',key='second-backup');self.execute(backup2)
        upgrade=self.request('upgrade',target_profile='next-pinned-v1');self.execute(upgrade)
        with self.assertRaises(Conflict):self.request('stop',generation=1)
        self.execute(self.request('stop',target_profile='next-pinned-v1'))
        self.execute(self.request('delete',target_profile='next-pinned-v1'))
        self.assertEqual(bfile.read_bytes(),prior);self.assertEqual(self.cell('b'),b)
        # Deletion removes runtime only. Contract-governed data purge is separate.
        self.assertTrue((self.driver.root/self.cell()['tenant_ref']/'state.json').exists())
    def test_unknown_capacity_and_disabled_driver_no_dispatch(self):
        op=self.request('create')
        with self.assertRaises(CapabilityUnavailable):self.engine.run(DisabledDriver(),'a',op['id'],capacity=CAPACITY)
        self.assertFalse(self.engine.run(self.driver,'a',op['id'],capacity=replace(CAPACITY,admitted_slots=0,blockers=('memory_unknown',))))
        self.assertEqual(self.driver.effects,0)
    def test_audit_failure_rolls_back_binding(self):
        with patch.object(self.engine,'_audit',side_effect=sqlite3.OperationalError('synthetic audit failure')):
            with self.assertRaises(sqlite3.OperationalError):self.request('create')
        with self.store.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM lifecycle_cells').fetchone()[0],0)
    def test_maintenance_denied_while_task_needs_drain(self):
        self.create();self.execute(self.request('start'));op=self.request('stop')
        with self.store.connect() as con:
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p','c',?)",(self.cell()['deployment_id'],))
            con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','p','c','t','waiting_for_approval',0)")
        with self.assertRaises(Conflict):self.execute(op)
        self.assertEqual(self.cell()['observed_state'],'running')

if __name__=='__main__':unittest.main()
