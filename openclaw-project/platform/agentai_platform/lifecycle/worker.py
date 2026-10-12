"""Lifecycle worker: drains queued operations to the host supervisor and sleeps idle cells.

One tick: reconcile uncertain operations (receipt-based only), run pending
operations oldest first through `Coordinator.run` (claim -> supervisor -> receipt),
then enqueue a drain for a cell that has been idle past the sleep threshold with no
running, queued or approval-waiting work. Capacity is recomputed from live host
numbers before every dispatch; a supervisor busy answer is a normal wait, not a
failure. It never clears an uncertain hold, never retries an unknown effect and
never touches the owner workload.
"""
import time

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.security import NotFound

from .coordinator import Coordinator
from .sleep import CellFacts, IDLE_AFTER_SECONDS, can_sleep
from .supervisor import OutcomeUncertain, SupervisorBusy
from .types import Conflict


class LifecycleWorker:
    def __init__(self, store, driver, capacity, *, coordinator=None, clock=time.time,
                 owner='lifecycle-worker', idle_after=IDLE_AFTER_SECONDS, batch=10):
        self.store, self.driver, self.capacity = store, driver, capacity
        self.coordinator = coordinator or Coordinator(store, clock=clock)
        self.clock, self.owner, self.idle_after, self.batch = clock, owner, idle_after, batch

    def _rows(self, state):
        with self.store.connect() as con:
            return [(r['account_id'], r['id']) for r in con.execute(
                'SELECT account_id,id FROM operations WHERE state=? ORDER BY created_at,id LIMIT ?',
                (state, self.batch)).fetchall()]

    def facts(self):
        """Per-account facts for running cells, read from the app database only."""
        out = []
        with self.store.connect() as con:
            for cell in con.execute("SELECT c.account_id,d.generation FROM lifecycle_cells c JOIN deployments d "
                                    "ON d.account_id=c.account_id AND d.id=c.deployment_id "
                                    "WHERE c.observed_state='running'").fetchall():
                a = cell['account_id']
                count = lambda state: con.execute('SELECT count(*) FROM tasks WHERE account_id=? AND state=?', (a, state)).fetchone()[0]
                last = con.execute("""SELECT max(epoch) FROM (
                    SELECT strftime('%s',max(created_at)) AS epoch FROM tasks WHERE account_id=?
                    UNION ALL SELECT strftime('%s',max(created_at)) FROM events WHERE account_id=?
                    UNION ALL SELECT strftime('%s',max(created_at)) FROM operations WHERE account_id=?)""", (a, a, a)).fetchone()[0]
                busy_op = con.execute("SELECT 1 FROM operations WHERE account_id=? AND state IN ('pending','running','uncertain')", (a,)).fetchone()
                out.append((CellFacts(a, 'running', float(last or 0), count('running'), count('queued'),
                                      count('waiting_for_approval') + count('paused'), bool(busy_op)), cell['generation']))
        return out

    def tick(self):
        report = {'reconciled': 0, 'ran': 0, 'waiting': 0, 'denied': 0, 'uncertain': 0, 'drained': 0}
        for account, operation in self._rows('uncertain'):
            try:
                if self.coordinator.reconcile(self.driver, account, operation):
                    report['reconciled'] += 1
            except (Conflict, NotFound, CapabilityUnavailable, OutcomeUncertain):
                pass  # holds stay in place; operator reconciliation is required
        for account, operation in self._rows('pending'):
            try:
                if self.coordinator.run(self.driver, account, operation, capacity=self.capacity(), owner=self.owner):
                    report['ran'] += 1
                else:
                    report['waiting'] += 1
            except SupervisorBusy:
                report['waiting'] += 1
            except (CapabilityUnavailable, Conflict, NotFound):
                report['denied'] += 1
            except Exception:
                report['uncertain'] += 1
        now = self.clock()
        for facts, generation in self.facts():
            if can_sleep(facts, now, idle_after=self.idle_after):
                try:
                    self.coordinator.request_system(facts.account_id, key=f'idle-{generation}-{int(facts.last_activity_epoch)}',
                                                    generation=generation)
                    report['drained'] += 1
                except (Conflict, NotFound):
                    pass
        return report
