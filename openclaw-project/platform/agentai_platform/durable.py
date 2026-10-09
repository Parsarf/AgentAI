"""Durable objectives, checkpoints and sticky cancellation (Phase 10, NATIVE-05).

Contract (deliberately narrower than autonomy): an objective persists its
goal reference, mapped state and ordered checkpoints, but **a restart never
resumes work by itself**; resuming is an explicit customer/operator call.
``resume_mode`` is constrained to ``explicit`` in the schema, so autonomous
post-restart execution cannot be recorded as implemented (launch gap, see
phase-10.md). Resume is refused while any checkpoint effect is uncertain
until it is reconciled, and cancellation is sticky: it cancels every
registered child job/subagent/schedule and can never be undone by resume.
"""
from __future__ import annotations
import time
import uuid
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal

# Native goal states are mapped, never passed through. Anything unrecognised is
# 'needs_reconciliation' rather than guessed.
NATIVE_TO_APP = {
    'active': 'active', 'running': 'active', 'pursuing': 'active',
    'paused': 'paused', 'blocked': 'paused',
    'complete': 'completed', 'completed': 'completed', 'done': 'completed',
    'failed': 'failed', 'error': 'failed',
    'cancelled': 'cancelled', 'canceled': 'cancelled', 'cleared': 'cancelled',
}
MAX_CHECKPOINTS = 200
MAX_CHILDREN = 20


def map_native_state(native: str) -> str:
    return NATIVE_TO_APP.get(str(native).lower(), 'needs_reconciliation')


class ObjectiveService:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    def _row(self, con, principal, objective_id):
        self.store._authorize(con, principal)
        row = con.execute('SELECT * FROM objectives WHERE account_id=? AND id=?',
                          (principal.account_id, identifier(objective_id))).fetchone()
        if not row:
            raise NotFound('unavailable')
        return row

    def create(self, principal: Principal, project_id: str, *, task_id=None, native_goal_ref=None) -> str:
        identifier(project_id)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?',
                               (principal.account_id, project_id)).fetchone():
                raise NotFound('unavailable')
            now, objective_id = int(self.clock()), uuid.uuid4().hex
            con.execute('''INSERT INTO objectives(account_id,project_id,id,task_id,native_goal_ref,app_state,
                created_epoch,updated_epoch) VALUES (?,?,?,?,?,'active',?,?)''',
                        (principal.account_id, project_id, objective_id, task_id,
                         None if native_goal_ref is None else str(native_goal_ref)[:200], now, now))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, objective_id,
                                    'objective.create', 'completed')
            return objective_id

    def checkpoint(self, principal: Principal, objective_id: str, step: str, *, receipt_id=None,
                   effect_state='confirmed') -> int:
        """Append a checkpoint. Duplicate receipts are idempotent (same sequence returned)."""
        with self.coordinator.transaction() as con:
            row = self._row(con, principal, objective_id)
            if row['cancelled']:
                raise Conflict('objective cancelled')
            if receipt_id is not None:
                dup = con.execute('''SELECT sequence FROM objective_checkpoints WHERE account_id=?
                    AND objective_id=? AND receipt_id=?''', (principal.account_id, objective_id, receipt_id)).fetchone()
                if dup:
                    return dup['sequence']
            sequence = con.execute('''SELECT coalesce(max(sequence),0)+1 FROM objective_checkpoints
                WHERE account_id=? AND objective_id=?''', (principal.account_id, objective_id)).fetchone()[0]
            if sequence > MAX_CHECKPOINTS:
                raise Conflict('checkpoint limit reached')
            con.execute('INSERT INTO objective_checkpoints VALUES (?,?,?,?,?,?,?)',
                        (principal.account_id, objective_id, sequence, step, receipt_id, effect_state,
                         int(self.clock())))
            if effect_state == 'uncertain':
                con.execute("UPDATE objectives SET app_state='needs_reconciliation',updated_epoch=? "
                            "WHERE account_id=? AND id=?", (int(self.clock()), principal.account_id, objective_id))
            return sequence

    def sync_native_state(self, principal: Principal, objective_id: str, native_state: str) -> str:
        """Record the observed native state; map it. Never un-cancels, never auto-resumes."""
        with self.coordinator.transaction() as con:
            row = self._row(con, principal, objective_id)
            mapped = 'cancelled' if row['cancelled'] else map_native_state(native_state)
            if row['app_state'] == 'needs_reconciliation' and mapped in {'active', 'paused'}:
                mapped = 'needs_reconciliation'
            con.execute('UPDATE objectives SET native_state=?,app_state=?,updated_epoch=? WHERE account_id=? AND id=?',
                        (str(native_state)[:40], mapped, int(self.clock()), principal.account_id, objective_id))
            return mapped

    def register_child(self, principal: Principal, objective_id: str, child_ref: str, kind: str) -> None:
        with self.coordinator.transaction() as con:
            row = self._row(con, principal, objective_id)
            if row['cancelled']:
                raise Conflict('objective cancelled')
            if con.execute('SELECT count(*) FROM objective_children WHERE account_id=? AND objective_id=?',
                           (principal.account_id, objective_id)).fetchone()[0] >= MAX_CHILDREN:
                raise Conflict('child limit reached')
            con.execute('INSERT OR IGNORE INTO objective_children VALUES (?,?,?,?,?)',
                        (principal.account_id, objective_id, str(child_ref)[:200], kind, 'active'))

    def cancel(self, principal: Principal, objective_id: str) -> list[str]:
        """Sticky: marks cancelled and returns the active children the caller must stop."""
        with self.coordinator.transaction() as con:
            self._row(con, principal, objective_id)
            children = [r['child_ref'] for r in con.execute('''SELECT child_ref FROM objective_children
                WHERE account_id=? AND objective_id=? AND state='active' ''', (principal.account_id, objective_id))]
            con.execute("UPDATE objective_children SET state='cancelled' WHERE account_id=? AND objective_id=? "
                        "AND state='active'", (principal.account_id, objective_id))
            con.execute("UPDATE objectives SET cancelled=1,app_state='cancelled',updated_epoch=? "
                        "WHERE account_id=? AND id=?", (int(self.clock()), principal.account_id, objective_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, objective_id,
                                    'objective.cancel', 'completed')
            return children

    def reconcile(self, principal: Principal, objective_id: str, sequence: int, *, effect_happened: bool) -> None:
        """Operator/customer resolves an uncertain effect from observed state (never by resending)."""
        with self.coordinator.transaction() as con:
            self._row(con, principal, objective_id)
            cur = con.execute('''UPDATE objective_checkpoints SET effect_state='reconciled' WHERE account_id=?
                AND objective_id=? AND sequence=? AND effect_state='uncertain' ''',
                              (principal.account_id, objective_id, sequence))
            if cur.rowcount != 1:
                raise NotFound('unavailable')
            if not con.execute('''SELECT 1 FROM objective_checkpoints WHERE account_id=? AND objective_id=?
                AND effect_state='uncertain' ''', (principal.account_id, objective_id)).fetchone():
                con.execute("UPDATE objectives SET app_state='paused',updated_epoch=? WHERE account_id=? AND id=? "
                            "AND cancelled=0", (int(self.clock()), principal.account_id, objective_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, objective_id,
                                    'objective.reconcile.' + ('happened' if effect_happened else 'absent'), 'completed')

    def resume(self, principal: Principal, objective_id: str) -> dict:
        """Explicit resume: refused if cancelled, uncertain, or finished. Returns the
        next step context (completed checkpoints) for the caller to continue from."""
        with self.coordinator.transaction() as con:
            row = self._row(con, principal, objective_id)
            if row['cancelled'] or row['app_state'] in {'cancelled', 'completed', 'failed'}:
                raise Conflict('objective is not resumable')
            if row['app_state'] == 'needs_reconciliation' or con.execute('''SELECT 1 FROM objective_checkpoints
                    WHERE account_id=? AND objective_id=? AND effect_state='uncertain' ''',
                                                                       (principal.account_id, objective_id)).fetchone():
                raise Conflict('reconcile uncertain effects before resume')
            done = [dict(r) for r in con.execute('''SELECT sequence,step,receipt_id FROM objective_checkpoints
                WHERE account_id=? AND objective_id=? ORDER BY sequence''', (principal.account_id, objective_id))]
            con.execute("UPDATE objectives SET app_state='active',updated_epoch=? WHERE account_id=? AND id=?",
                        (int(self.clock()), principal.account_id, objective_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, objective_id,
                                    'objective.resume', 'completed')
            return {'objective_id': objective_id, 'completed_steps': done}

    def restart_recovery(self) -> int:
        """Host restart: every active objective becomes paused. Nothing resumes by itself."""
        with self.coordinator.transaction() as con:
            cur = con.execute("UPDATE objectives SET app_state='paused',updated_epoch=? "
                              "WHERE app_state='active' AND cancelled=0", (int(self.clock()),))
            return cur.rowcount
