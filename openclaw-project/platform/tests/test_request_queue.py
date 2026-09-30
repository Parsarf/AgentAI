from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from agentai_platform.request_queue import RequestQueue,RequestReceipt,DisabledRequestDriver
from agentai_platform.store import Store
from agentai_platform.security import Principal,NotFound
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.capacity import CapacityResult
from agentai_platform.adapters import CapabilityUnavailable
CAPACITY=CapacityResult(1,1,1,1,1,())
class SerialQueueChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state'/'db.sqlite3');self.store.initialize()
        self.now=2000000000;self.q=RequestQueue(self.store,clock=lambda:self.now)
        self.a=Principal('a','actor-a','customer');self.b=Principal('b','actor-b','customer')
        with self.store.connect() as c:
            for a in ['a','b']:
                c.execute("INSERT INTO accounts(id,status) VALUES (?,'active')",(a,))
                c.execute("INSERT INTO memberships VALUES (?,?,'customer','active')",(a,'actor-'+a))
                c.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)',(a,'p-'+a,'P'))
    def submit(self,a=None,key='r1',message='private request'):return self.q.submit(a or self.a,message=message,key=key)
    def claim(self,owner='worker'):return self.q.claim(owner=owner,capacity=CAPACITY)
    def receipt(self,claim,**kw):return RequestReceipt(claim.account_id,claim.request_id,claim.fence,'completed','Public final result',True,**kw)
    def test_fifo_serial_handoff_and_restart(self):
        a=self.submit();b=self.submit(self.b);claim=self.claim();self.assertEqual(claim.request_id,a['id'])
        self.assertIsNone(self.claim('second'));self.q.heartbeat(claim)
        restarted=RequestQueue(self.store,clock=lambda:self.now)
        self.assertIsNone(restarted.claim(owner='new',capacity=CAPACITY))
        self.q.finish(claim,self.receipt(claim));self.assertEqual(self.claim().request_id,b['id'])
    def test_racing_workers_cannot_claim_two(self):
        self.submit();self.submit(self.b);barrier=threading.Barrier(2);results=[];errors=[]
        def worker(name):
            try:barrier.wait();results.append(self.claim(name))
            except Exception as e:errors.append(e)
        threads=[threading.Thread(target=worker,args=(x,)) for x in ['one','two']]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertFalse(errors);self.assertEqual(sum(x is not None for x in results),1)
    def test_scoped_get_cancel_and_idempotency(self):
        a=self.submit();self.assertEqual(self.submit(),a)
        with self.assertRaises(Conflict):self.submit(message='changed')
        with self.assertRaises(NotFound):self.q.get(self.b,a['id'])
        with self.assertRaises(NotFound):self.q.cancel(self.b,a['id'])
        self.assertEqual(self.q.cancel(self.a,a['id'])['state'],'cancelled');self.assertIsNone(self.claim())
    def test_running_cancel_does_not_release_slot(self):
        a=self.submit();self.submit(self.b);claim=self.claim()
        self.assertEqual(self.q.cancel(self.a,a['id'])['state'],'starting')
        self.assertTrue(self.q.heartbeat(claim));self.assertIsNone(self.claim())
        self.q.finish(claim,replace(self.receipt(claim),state='cancelled'));self.assertEqual(self.claim().account_id,'b')
    def test_expired_uncertain_no_blind_retry(self):
        self.submit();self.submit(self.b);claim=self.claim();self.now+=61
        self.assertIsNone(self.claim());self.assertEqual(self.q.get(self.a,claim.request_id)['state'],'uncertain')
        self.assertFalse(self.q.finish(claim,self.receipt(claim)))
        class ReadReceipt:
            def reconcile(s,c):return self.receipt(c)
        self.assertTrue(self.q.reconcile(ReadReceipt(),claim));self.assertEqual(self.claim().account_id,'b')
    def test_forged_receipt_undrained_runtime_and_late_completion_denied(self):
        self.submit();claim=self.claim();receipt=self.receipt(claim)
        for bad in [replace(receipt,account_id='b'),replace(receipt,quiesced=False)]:
            with self.assertRaises(Conflict):self.q.finish(claim,bad)
        self.q.finish(claim,receipt)
        with self.assertRaises(Conflict):self.q.finish(claim,receipt)
    def test_revoked_author_skipped(self):
        self.submit();self.submit(self.b)
        with self.store.connect() as c:c.execute("UPDATE memberships SET status='revoked' WHERE account_id='a'")
        self.assertEqual(self.claim().account_id,'b')
    def test_queue_limit_disabled_driver_unknown_capacity(self):
        for i in range(3):self.submit(key='r'+str(i))
        with self.assertRaises(Conflict):self.submit(key='r4')
        with self.assertRaises(CapabilityUnavailable):self.q.run_once(DisabledRequestDriver(),owner='worker',capacity=CAPACITY)
        self.assertIsNone(self.q.claim(owner='worker',capacity=replace(CAPACITY,admitted_slots=0)))
        self.assertEqual(len(self.q.get(self.a)),3)
