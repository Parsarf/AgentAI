from datetime import datetime,timezone
from pathlib import Path
import tempfile
import time
import unittest
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.capacity import CapacityResult
from agentai_platform.security import Principal,NotFound
from agentai_platform.store import Store
from agentai_platform.lifecycle.coordinator import Coordinator
from agentai_platform.lifecycle.profiles import host_capacity,GIB
from agentai_platform.lifecycle.supervisor import SupervisorBusy
from agentai_platform.lifecycle.types import Conflict,DisabledDriver
from agentai_platform.lifecycle.worker import LifecycleWorker
from tests.lifecycle_fixture import FixtureDriver

OK=CapacityResult(1,1,1,1,1,())
class WorkerChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.store=Store(self.root/'state'/'db.sqlite3');self.store.initialize();self.now=2000000000
        self.engine=Coordinator(self.store,clock=lambda:self.now);self.driver=FixtureDriver(self.root/'fx')
        with self.store.connect() as con:
            con.execute('CREATE TABLE auth_user(id INTEGER PRIMARY KEY,is_active INTEGER)')
            con.execute('CREATE TABLE accounts_identity(user_id INTEGER,role TEXT,verified INTEGER)')
            con.execute('CREATE TABLE accounts_operatorgrant(user_id INTEGER,account_id TEXT,action TEXT,expires_at TEXT)')
            con.execute("INSERT INTO auth_user VALUES (1,1)");con.execute("INSERT INTO accounts_identity VALUES (1,'operator',1)")
            for a in ['a','b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')",(a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')",(a,'customer-'+a))
                for k in ['create','start','stop','backup','restore','upgrade','delete']:
                    con.execute("INSERT INTO accounts_operatorgrant VALUES (1,?,?,datetime(?,'unixepoch'))",(a,'lifecycle_'+k,self.now+3600))
        self.capacity=lambda:OK
    def worker(self,driver=None,**kw):
        return LifecycleWorker(self.store,driver or self.driver,lambda:self.capacity(),coordinator=self.engine,clock=lambda:self.now,**kw)
    def request(self,kind,account='a',key=None):
        gen=None
        if kind!='create':
            with self.store.connect() as con: gen=con.execute('SELECT generation FROM deployments WHERE account_id=?',(account,)).fetchone()[0]
        return self.engine.request(Principal(account,'1','operator'),kind=kind,key=key or kind+account,generation=gen)
    def state(self,a='a'):
        with self.store.connect() as con: return con.execute('SELECT observed_state FROM lifecycle_cells WHERE account_id=?',(a,)).fetchone()[0]
    def op_state(self,op):
        with self.store.connect() as con: return con.execute('SELECT state FROM operations WHERE id=?',(op['id'],)).fetchone()[0]

    def test_tick_drains_pending_operations_in_order_and_is_idempotent(self):
        op=self.request('create');w=self.worker()
        self.assertEqual(w.tick()['ran'],1);self.assertEqual(self.state(),'stopped');self.assertEqual(self.op_state(op),'completed')
        self.assertEqual(w.tick()['ran'],0);self.assertEqual(self.driver.effects,1)
    def test_disabled_native_backend_runs_nothing(self):
        op=self.request('create');r=self.worker(DisabledDriver()).tick()
        self.assertEqual(r['denied'],1);self.assertEqual(self.op_state(op),'pending')
    def test_capacity_wait_keeps_the_operation_pending(self):
        op=self.request('create');self.capacity=lambda:CapacityResult(0,0,0,0,0,('memory_exhausted',))
        r=self.worker().tick();self.assertEqual(r['waiting'],1);self.assertEqual(self.op_state(op),'pending');self.assertEqual(self.driver.effects,0)
        self.capacity=lambda:OK;self.assertEqual(self.worker().tick()['ran'],1)
    def test_supervisor_busy_is_a_wait_not_a_failure(self):
        op=self.request('create')
        class Busy(FixtureDriver):
            def execute(s,claim): raise SupervisorBusy('headroom')
        busy=Busy(self.root/'busy');r=self.worker(busy).tick()
        self.assertEqual(r['waiting'],1);self.assertEqual(self.op_state(op),'pending')
    def test_unknown_effect_is_held_not_retried(self):
        op=self.request('create');self.driver.fail_after=True
        r=self.worker().tick();self.assertEqual(r['uncertain'],1);self.assertEqual(self.op_state(op),'uncertain')
        self.driver.fail_after=False;r=self.worker().tick()   # reconcile from the driver's receipt
        self.assertEqual(r['reconciled'],1);self.assertEqual(self.op_state(op),'completed')

    def start_cell(self,a='a'):
        for kind in ('create','start'):
            self.request(kind,a);self.worker(idle_after=10**12).tick()   # setup must not trigger the sleep policy
        self.assertEqual(self.state(a),'running')
    def test_idle_cell_is_drained_then_stopped(self):
        self.start_cell();w=self.worker(idle_after=900)
        r=w.tick();self.assertEqual(r['drained'],1)
        r=w.tick();self.assertEqual(r['ran'],1);self.assertEqual(self.state(),'stopped')
    def test_active_or_recent_work_prevents_sleep(self):
        self.start_cell()
        with self.store.connect() as con:
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p','p')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) SELECT 'a','p','c',deployment_id FROM lifecycle_cells WHERE account_id='a'")
            con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','p','c','t','running',1)")
        self.assertEqual(self.worker().tick()['drained'],0)
        with self.store.connect() as con: con.execute("UPDATE tasks SET state='completed'")
        self.assertEqual(self.worker(idle_after=10**12).tick()['drained'],0)   # not idle long enough
    def test_system_request_is_stop_only_and_bounded(self):
        quiet=lambda:self.worker(idle_after=10**12)
        self.request('create');quiet().tick()
        with self.assertRaises(Conflict): self.engine.request_system('a',key='k1',generation=1)   # stopped cell
        self.request('start');quiet().tick()
        with self.assertRaises(Conflict): self.engine.request_system('a',key='k2',generation=99)   # stale generation
        op=self.engine.request_system('a',key='k3',generation=1);self.assertEqual(op,self.engine.request_system('a',key='k3',generation=1))
        with self.assertRaises(Conflict): self.engine.request_system('a',key='k4',generation=1)    # unresolved op
        with self.assertRaises(NotFound): self.engine.request_system('zzz',key='k5',generation=1)
        with self.assertRaises(ValueError): self.engine.request_system('a',key='bad key!',generation=1)

class CapacityChecks(unittest.TestCase):
    def cap(self,mem_gib,cpus=4,disk_gib=100):
        return host_capacity(now=datetime.now(timezone.utc),available=lambda:int(mem_gib*GIB),cpus=lambda:cpus,disk_free=lambda:disk_gib*GIB)
    def test_measured_host_admits_one_and_cpu_is_the_bottleneck(self):
        r=self.cap(13.2);self.assertEqual((r.memory_slots,r.cpu_slots),(4,1));self.assertEqual(r.admitted_slots,1)
    def test_exhausted_memory_admits_zero(self):
        r=self.cap(0.5);self.assertEqual(r.admitted_slots,0);self.assertIn('memory_exhausted',r.blockers)
    def test_small_cpu_or_disk_blocks(self):
        self.assertEqual(self.cap(13.2,cpus=2).admitted_slots,0)
        self.assertEqual(self.cap(13.2,disk_gib=25).admitted_slots,0)
if __name__=='__main__': unittest.main()


class BackupSchedulingChecks(unittest.TestCase):
    setUp, worker, request, state, op_state, start_cell = (WorkerChecks.setUp, WorkerChecks.worker, WorkerChecks.request, WorkerChecks.state,
                                                           WorkerChecks.op_state, WorkerChecks.start_cell)
    def quiet(self): return self.worker(idle_after=10**12)
    def test_stopped_cells_get_one_backup_request_and_running_cells_none(self):
        self.request('create'); self.quiet().tick()
        self.assertEqual(self.quiet().enqueue_due_backups(), 1)
        self.assertEqual(self.quiet().enqueue_due_backups(), 0)                               # pending request already counts
        self.quiet().tick()
        with self.store.connect() as con: self.assertEqual(con.execute("SELECT state FROM operations WHERE kind='backup'").fetchone()[0], 'completed')
        self.assertEqual(self.quiet().enqueue_due_backups(), 0)                               # fresh backup exists
        self.now += 21 * 3600; self.assertEqual(self.quiet().enqueue_due_backups(), 1)        # stale again
    def test_scheduling_is_off_unless_configured_and_running_cells_are_never_backed_up(self):
        self.request('create'); self.quiet().tick()
        self.assertEqual(self.quiet().tick()['backups_queued'], 0)                            # default: no automatic backups
        with self.store.connect() as con: self.assertEqual(con.execute("SELECT count(*) FROM operations WHERE kind='backup'").fetchone()[0], 0)
        scheduled = self.worker(idle_after=10**12, backup_max_age=20 * 3600); self.assertEqual(scheduled.tick()['backups_queued'], 1)
        scheduled.tick(); self.request('start'); self.quiet().tick()
        self.assertEqual(self.quiet().enqueue_due_backups(), 0)
        with self.assertRaises(ValueError): self.engine.request_system('a', key='k9', generation=1, kind='delete')
        with self.assertRaises(Conflict): self.engine.request_system('a', key='k8', generation=1, kind='backup')   # running: refused
