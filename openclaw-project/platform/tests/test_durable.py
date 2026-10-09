from pathlib import Path
import tempfile
import unittest
from agentai_platform.durable import ObjectiveService, map_native_state
from agentai_platform.schedules import ScheduleService, ScheduleDisabled, unattended_decision
from agentai_platform.watchers import WatcherService
from agentai_platform.security import Principal, NotFound
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.store import Store


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite3'); self.store.initialize()
        self.now = 2000000000  # 2033-05-18 03:33:20 UTC
        self.clock = lambda: self.now
        self.a = Principal('a', 'actor-a', 'customer'); self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for x in 'ab':
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (x, 'actor-' + x))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (x, 'p-' + x, 'P'))


class ObjectiveChecks(Base):
    def setUp(self):
        super().setUp(); self.o = ObjectiveService(self.store, clock=self.clock)

    def test_state_mapping_unknown_needs_reconciliation(self):
        self.assertEqual(map_native_state('Pursuing'), 'active')
        self.assertEqual(map_native_state('cleared'), 'cancelled')
        self.assertEqual(map_native_state('???'), 'needs_reconciliation')

    def test_three_step_restart_ambiguous_checkpoint_and_explicit_resume(self):
        oid = self.o.create(self.a, 'p-a', native_goal_ref='goal-1')
        self.assertEqual(self.o.checkpoint(self.a, oid, 'step 1', receipt_id='r1'), 1)
        self.assertEqual(self.o.checkpoint(self.a, oid, 'step 1 again', receipt_id='r1'), 1)  # idempotent
        self.o.checkpoint(self.a, oid, 'step 2 send', receipt_id='r2', effect_state='uncertain')
        self.assertEqual(self.o.restart_recovery(), 0)  # already needs_reconciliation, not 'active'
        with self.assertRaises(Conflict):
            self.o.resume(self.a, oid)
        self.assertEqual(self.o.sync_native_state(self.a, oid, 'active'), 'needs_reconciliation')
        self.o.reconcile(self.a, oid, 2, effect_happened=True)
        ctx = self.o.resume(self.a, oid)
        self.assertEqual([s['sequence'] for s in ctx['completed_steps']], [1, 2])
        self.o.checkpoint(self.a, oid, 'step 3', receipt_id='r3')

    def test_restart_pauses_and_never_auto_resumes(self):
        oid = self.o.create(self.a, 'p-a')
        self.assertEqual(self.o.restart_recovery(), 1)
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT app_state FROM objectives').fetchone()[0], 'paused')
            with self.assertRaises(Exception):  # schema forbids recording autonomous resume
                con.execute("UPDATE objectives SET resume_mode='autonomous'")
        self.o.resume(self.a, oid)

    def test_cancellation_is_sticky_across_children_and_restart(self):
        oid = self.o.create(self.a, 'p-a')
        self.o.register_child(self.a, oid, 'job-1', 'job'); self.o.register_child(self.a, oid, 'sub-1', 'subagent')
        self.assertEqual(sorted(self.o.cancel(self.a, oid)), ['job-1', 'sub-1'])
        self.assertEqual(self.o.cancel(self.a, oid), [])
        self.o.restart_recovery()
        self.assertEqual(self.o.sync_native_state(self.a, oid, 'active'), 'cancelled')
        for call in (lambda: self.o.resume(self.a, oid), lambda: self.o.checkpoint(self.a, oid, 'x'),
                     lambda: self.o.register_child(self.a, oid, 'job-2', 'job')):
            with self.assertRaises(Conflict):
                call()

    def test_cross_tenant_denied(self):
        oid = self.o.create(self.a, 'p-a')
        for call in (lambda: self.o.resume(self.b, oid), lambda: self.o.cancel(self.b, oid),
                     lambda: self.o.checkpoint(self.b, oid, 'x'), lambda: self.o.create(self.b, 'p-a')):
            with self.assertRaises(NotFound):
                call()


class ScheduleChecks(Base):
    def setUp(self):
        super().setUp()
        self.s = ScheduleService(self.store, enforcement_proven=True, clock=self.clock)

    def admit(self, ok=True):
        self.calls = getattr(self, 'calls', 0)
        def f():
            self.calls += 1
            return ok
        return f

    def test_disabled_until_enforcement_proven(self):
        with self.assertRaises(ScheduleDisabled):
            ScheduleService(self.store, clock=self.clock).create(self.a, 'p-a', 'x', timezone='UTC', hour=1)

    def test_timezone_validation_and_local_due_time(self):
        with self.assertRaises(ValueError):
            self.s.create(self.a, 'p-a', 'bad', timezone='Mars/Base', hour=1)
        berlin = self.s.create(self.a, 'p-a', 'berlin', timezone='Europe/Berlin', hour=5)
        la = self.s.create(self.a, 'p-a', 'la', timezone='America/Los_Angeles', hour=22)
        self.assertTrue(self.s.due(self.a, berlin, admit=self.admit(), approval_state='granted')['run'])
        self.assertEqual(self.s.due(self.a, la, admit=self.admit(), approval_state='granted')['reason'], 'not_due')
        self.assertEqual(self.s.due(self.a, berlin, admit=self.admit(), approval_state='granted')['reason'],
                         'already_fired_today')

    def test_no_change_costs_nothing_and_unattended_authority(self):
        sid = self.s.create(self.a, 'p-a', 'n', timezone='UTC', hour=0)
        self.assertEqual(unattended_decision('expired'), 'deny')
        self.assertEqual(unattended_decision('unavailable'), 'deny')
        self.assertEqual(self.s.due(self.a, sid, admit=self.admit(), approval_state='expired')['reason'],
                         'unattended_authority_denied')
        self.assertEqual(self.s.due(self.a, sid, admit=self.admit(), approval_state='pending')['reason'],
                         'waiting_for_approval')
        quiet = self.s.due(self.a, sid, admit=self.admit(), approval_state='granted', changed=False)
        self.assertEqual((quiet['reason'], quiet['model_calls']), ('unchanged', 0))
        self.assertEqual(self.calls, 0)

    def test_admission_denied_does_not_consume_the_day_and_limits(self):
        sid = self.s.create(self.a, 'p-a', 'n', timezone='UTC', hour=0)
        self.assertEqual(self.s.due(self.a, sid, admit=self.admit(False), approval_state='granted')['reason'],
                         'admission_denied')
        self.assertTrue(self.s.due(self.a, sid, admit=self.admit(True), approval_state='granted')['run'])
        self.assertEqual(self.s.create(self.a, 'p-a', 'n', timezone='UTC', hour=0), sid)  # no duplicate job
        for i in range(4):
            self.s.create(self.a, 'p-a', f's{i}', timezone='UTC', hour=1)
        with self.assertRaises(Conflict):
            self.s.create(self.a, 'p-a', 'sixth', timezone='UTC', hour=1)
        with self.assertRaises(NotFound):
            self.s.due(self.b, sid, admit=self.admit(), approval_state='granted')
        with self.assertRaises(NotFound):
            self.s.create(self.b, 'p-a', 'x', timezone='UTC', hour=1)

    def test_watcher_link_must_be_same_tenant(self):
        w = WatcherService(self.store, clock=self.clock).ensure(self.b, 'p-b', 'w', {})
        with self.assertRaises(NotFound):
            self.s.create(self.a, 'p-a', 'linked', timezone='UTC', hour=1, watcher_id=w)


if __name__ == '__main__':
    unittest.main()
