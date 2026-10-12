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
                 owner='lifecycle-worker', idle_after=IDLE_AFTER_SECONDS, batch=10, backup_max_age=None, wake=False, handover_idle=60, observe=None):
        self.store, self.driver, self.capacity = store, driver, capacity
        self.coordinator = coordinator or Coordinator(store, clock=clock)
        self.clock, self.owner, self.idle_after, self.batch = clock, owner, idle_after, batch
        self.observe = observe   # observe(account)->True/False/None: is the cell's container really running?
        self.wake, self.handover_idle = wake, handover_idle   # wake: start cells for waiting customer requests
        self.backup_max_age = backup_max_age   # seconds; None leaves backup scheduling to the operator

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

    def enqueue_due_backups(self, max_age=20 * 3600):
        """A stopped cell with no completed backup in the last `max_age` seconds gets a backup request.

        Running cells cannot be archived consistently; the idle-sleep policy stops them, and the
        monitor flags any tenant whose newest backup is stale.
        """
        queued, now = 0, self.clock()
        with self.store.connect() as con:
            due = []
            for cell in con.execute("SELECT c.account_id,d.generation FROM lifecycle_cells c JOIN deployments d ON d.account_id=c.account_id AND d.id=c.deployment_id "
                                    "WHERE c.observed_state='stopped'").fetchall():
                if con.execute("SELECT 1 FROM operations WHERE account_id=? AND state IN ('pending','running','uncertain')", (cell['account_id'],)).fetchone():
                    continue   # something is already in flight for this account
                last = con.execute("SELECT max(d.updated_at) FROM operations o JOIN lifecycle_details d ON d.account_id=o.account_id AND d.operation_id=o.id "
                                   "WHERE o.account_id=? AND o.kind='backup' AND o.state='completed'", (cell['account_id'],)).fetchone()[0]
                if not last or now - float(last) > max_age: due.append((cell['account_id'], cell['generation']))
        for account, generation in due:
            try:
                self.coordinator.request_system(account, key=f'backup-{generation}-{int(now) // 3600}', generation=generation, kind='backup'); queued += 1
            except (Conflict, NotFound):
                pass
        return queued

    def _wake(self):
        return bool(self.wake() if callable(self.wake) else self.wake)   # callable: re-read the owner switch every tick

    def realign(self, now):
        """A cell recorded as running whose container is really gone (engine or host restart) gets a stop, so the record is true again."""
        if self.observe is None:
            return 0
        done = 0
        for facts, generation in self.facts():
            if facts.maintenance or self.observe(facts.account_id) is not False:
                continue
            try:
                self.coordinator.request_system(facts.account_id, key=f'realign-{generation}-{int(now) // 60}', generation=generation)
                done += 1
            except (Conflict, NotFound):
                pass
        return done

    def enqueue_wakes(self):
        """A stopped cell with a waiting customer request gets a system start (the request worker then claims it)."""
        queued = 0
        with self.store.connect() as con:
            due = [(r['account_id'], r['generation'], r['request_id']) for r in con.execute(
                "SELECT c.account_id,d.generation,(SELECT id FROM customer_requests q WHERE q.account_id=c.account_id AND q.state='waiting' "
                "ORDER BY q.sequence LIMIT 1) AS request_id FROM lifecycle_cells c JOIN deployments d "
                "ON d.account_id=c.account_id AND d.id=c.deployment_id WHERE c.observed_state='stopped'").fetchall() if r['request_id']]
        for account, generation, request in due:
            try:
                self.coordinator.request_system(account, key=f'wake-{generation}-{request}', generation=generation, kind='start')
                queued += 1
            except (Conflict, NotFound):
                pass
        return queued

    def waiting_accounts(self):
        with self.store.connect() as con:
            return {r[0] for r in con.execute("SELECT DISTINCT account_id FROM customer_requests WHERE state='waiting'")}

    def tick(self):
        report = {'reconciled': 0, 'ran': 0, 'waiting': 0, 'denied': 0, 'uncertain': 0, 'drained': 0, 'backups_queued': 0, 'woken': 0, 'realigned': 0}
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
        report['realigned'] = self.realign(now)
        waiting = self.waiting_accounts() if self._wake() else set()
        for facts, generation in self.facts():
            # Another account's request is waiting for the one cell slot: hand over after a short idle.
            idle = self.handover_idle if waiting - {facts.account_id} else self.idle_after
            if can_sleep(facts, now, idle_after=idle):
                try:
                    self.coordinator.request_system(facts.account_id, key=f'idle-{generation}-{int(facts.last_activity_epoch)}',
                                                    generation=generation)
                    report['drained'] += 1
                except (Conflict, NotFound):
                    pass
        if self._wake(): report['woken'] = self.enqueue_wakes()
        if self.backup_max_age: report['backups_queued'] = self.enqueue_due_backups(self.backup_max_age)
        return report
