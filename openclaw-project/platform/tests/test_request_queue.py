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
    def test_queue_position_counts_the_running_task_and_earlier_waiting_tasks_of_any_account(self):
        a1 = self.submit(key='a1'); b1 = self.submit(self.b, key='b1'); a2 = self.submit(key='a2')
        ahead = lambda who, r: self.q.get(who, r['id'])['ahead']
        self.assertEqual([ahead(self.a, a1), ahead(self.b, b1), ahead(self.a, a2)], [0, 1, 2])
        claim = self.claim()                                                      # a1 now holds the slot
        self.assertEqual([ahead(self.a, a1), ahead(self.b, b1), ahead(self.a, a2)], [None, 1, 2])
        self.assertEqual([r['ahead'] for r in self.q.get(self.a)], [2, None])       # the list carries it too (newest first)
        self.q.finish(claim, self.receipt(claim)); self.assertEqual([ahead(self.b, b1), ahead(self.a, a2)], [0, 1])
        self.assertNotIn('account_id', self.q.get(self.b, b1['id']))                 # only a number crosses accounts

    def test_a_paused_task_keeps_its_place_but_is_never_claimed_and_does_not_count_as_ahead(self):
        a1 = self.submit(key='a1'); b1 = self.submit(self.b, key='b1'); a2 = self.submit(key='a2')
        held = self.q.pause(self.a, a1['id'])
        self.assertEqual((held['state'], held['paused'], held['ahead']), ('waiting', True, None))
        self.assertEqual(self.q.pause(self.a, a1['id'])['paused'], True)              # pressing it twice changes nothing
        self.assertEqual(self.q.get(self.b, b1['id'])['ahead'], 0); self.assertEqual(self.q.get(self.a, a2['id'])['ahead'], 1)
        claim = self.claim(); self.assertEqual(claim.request_id, b1['id'])             # the paused task was skipped
        self.q.finish(claim, self.receipt(claim)); self.assertEqual(self.claim().request_id, a2['id'])
        resumed = self.q.resume(self.a, a1['id']); self.assertEqual((resumed['paused'], resumed['state']), (False, 'waiting'))
        self.assertEqual(self.q.resume(self.a, a1['id'])['paused'], False)
        with self.assertRaises(Conflict): self.q.pause(self.a, a2['id'])              # it has started: no safe place to stop it
        with self.assertRaises(NotFound): self.q.pause(self.b, a1['id'])
        with self.assertRaises(NotFound): self.q.resume(self.b, a1['id'])

    def test_paused_tasks_still_count_toward_the_queue_limit_and_can_be_cancelled(self):
        ids = [self.submit(key=f'k{i}')['id'] for i in range(3)]
        for i in ids: self.q.pause(self.a, i)
        with self.assertRaises(Conflict): self.submit(key='k9')                         # holding work is not a way around the limit of 3
        self.assertEqual(self.q.cancel(self.a, ids[0])['state'], 'cancelled'); self.assertIsNone(self.claim())

    def test_a_paused_task_survives_a_restart(self):
        a1 = self.submit(); self.q.pause(self.a, a1['id'])
        again = RequestQueue(self.store, clock=lambda: self.now)
        self.assertEqual(again.get(self.a, a1['id'])['paused'], True); self.assertIsNone(again.claim(owner='w', capacity=CAPACITY))

    def test_only_a_failed_or_cancelled_task_can_be_retried_and_attempts_are_counted(self):
        a1 = self.submit(); self.assertRaises(Conflict, self.q.retry_source, self.a, a1['id'])           # still waiting
        self.q.cancel(self.a, a1['id'])
        with self.store.connect() as c: c.execute("UPDATE customer_requests SET conversation_id='c1',intent='plan',context_json='{\"mode\":\"text\"}' WHERE id=?", (a1['id'],))
        src = self.q.retry_source(self.a, a1['id'])
        self.assertEqual((src['message'], src['conversation_id'], src['intent'], src['context'], src['attempts'], src['latest']), ('private request', 'c1', 'plan', {'mode': 'text'}, 0, None))
        with self.assertRaises(NotFound): self.q.retry_source(self.b, a1['id'])
        with self.store.connect() as c: c.execute("UPDATE customer_requests SET conversation_id=NULL WHERE id=?", (a1['id'],))
        with self.assertRaises(Conflict): self.q.retry_source(self.a, a1['id'])                          # nowhere to retry it
        with self.store.connect() as c:
            c.execute("UPDATE customer_requests SET conversation_id='c1',state='completed' WHERE id=?", (a1['id'],))
        with self.assertRaises(Conflict): self.q.retry_source(self.a, a1['id'])                          # nothing to retry

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
