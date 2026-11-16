"""Cross-application workflows (roadmap #29): several changes, in one or more connected services, approved together and run in order.

A workflow is durable: its row and its steps (each one an action row: actions.py) are in the database, so a restart continues where it stopped.

Rules the runner enforces:
* ORDER. Reversible changes come before changes that cannot be undone. (Reads are not steps: the assistant reads through the connector tools first, before it proposes.) A
  proposal in another order is refused with the reason, so the assistant puts it right.
* ONE APPROVAL may cover the whole workflow, because the preview shows every step. It binds to a hash over every step's payload hash, in order. Any change to any step
  makes it void.
* FAILURE. If a step fails, the steps that already finished are walked back in reverse order, each with its registered inverse, or with its registered compensation when it
  cannot be undone. The report says exactly what was reversed and what could not be.
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid

from . import permissions
from .connector_kit import ConnectorFault, payload_hash
from .handoff import Handoffs
from .lifecycle.coordinator import Coordinator
from .lifecycle.types import Conflict
from .security import NotFound, Principal, require

MAX_STEPS = 12


class WorkflowRefused(Exception):
    """The proposed workflow breaks a rule; the text is a plain sentence the assistant and the customer can read."""


def steps_hash(hashes) -> str:
    return hashlib.sha256('\n'.join(hashes).encode()).hexdigest()


class WorkflowService:
    def __init__(self, store, actions, *, clock=time.time):
        self.store, self.actions, self.clock = store, actions, clock
        self.coordinator = Coordinator(store, clock=clock)
        self.handoffs = Handoffs(store, clock=clock)

    # -- views ---------------------------------------------------------------------------------------------------------------------------------
    def _steps(self, con, account_id, workflow_id):
        return con.execute('SELECT * FROM actions WHERE account_id=? AND workflow_id=? AND undo_of IS NULL AND compensates IS NULL ORDER BY workflow_position', (account_id, workflow_id)).fetchall()

    def public(self, con, row) -> dict:
        steps = [self.actions.public(s) for s in self._steps(con, row['account_id'], row['id'])]
        return {'id': row['id'], 'title': row['title'], 'state': row['state'], 'request_id': row['request_id'], 'steps_hash': row['steps_hash'], 'steps': steps,
                'report': json.loads(row['report_json']) if row['report_json'] else None, 'created_epoch': row['created_epoch']}

    def get(self, principal: Principal, workflow_id: str) -> dict:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT * FROM workflows WHERE account_id=? AND id=?', (principal.account_id, str(workflow_id))).fetchone()
            if not row:
                raise NotFound('unavailable')
            return self.public(con, row)

    # -- proposing -----------------------------------------------------------------------------------------------------------------------------
    def propose(self, principal: Principal, title: str, steps: list, *, request_id=None) -> dict:
        """`steps`: [{'connection_id','kind','payload'}, ...] in the order they will run. Every step is checked like a single action (role, grant, policy, shape) before
        anything is stored; if one cannot be proposed, none is."""
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            raise WorkflowRefused('A workflow needs a short title.')
        if not isinstance(steps, list) or not 2 <= len(steps) <= MAX_STEPS:
            raise WorkflowRefused(f'A workflow has between 2 and {MAX_STEPS} steps. For one change, propose it by itself.')
        reversible = []
        for n, step in enumerate(steps, 1):
            if not isinstance(step, dict) or set(step) - {'connection_id', 'kind', 'payload'} or not isinstance(step.get('connection_id'), str) or not isinstance(step.get('kind'), str):
                raise WorkflowRefused(f'Step {n} is not a change: it needs a connection, a kind and a payload.')
            declaration = self.actions.client.declaration_for(principal, step['connection_id'])
            write_kind = declaration.write_kind(step['kind'])
            if write_kind is None:
                raise WorkflowRefused(f'Step {n}: this service has no such kind of change.')
            reversible.append(bool(write_kind.undo))
        if any(not earlier and later for earlier, later in zip(reversible, reversible[1:])):
            raise WorkflowRefused('Changes that cannot be undone must come last: put every step that can be undone before them, then propose the workflow again.')
        workflow_id, made = uuid.uuid4().hex, []
        try:
            for position, step in enumerate(steps, 1):
                made.append(self.actions.propose(principal, step['connection_id'], step['kind'], step.get('payload'), request_id=request_id, workflow=(workflow_id, position)))
        except Exception:
            for action in made:                                # none of it stands
                self.actions.expire(principal.account_id, action['id'], 'workflow_stopped')
            raise
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            require(principal, 'action.propose', con=con)
            con.execute('''INSERT INTO workflows(account_id,id,request_id,actor_id,title,steps_hash,state,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?,'proposed',?,?)''',
                        (principal.account_id, workflow_id, request_id, principal.actor_id, title.strip(), steps_hash([a['payload_hash'] for a in made]), now, now))
            self.handoffs.create(con, account_id=principal.account_id, actor_id=principal.actor_id, kind='workflow_approval', request_id=request_id, workflow_id=workflow_id,
                                 question=title.strip(), evidence={'steps': len(made), 'irreversible': sum(1 for r in reversible if not r)}, resume={'workflow': workflow_id})
            return self.public(con, con.execute('SELECT * FROM workflows WHERE account_id=? AND id=?', (principal.account_id, workflow_id)).fetchone())

    # -- approving -----------------------------------------------------------------------------------------------------------------------------
    def approve(self, principal: Principal, workflow_id: str, approved_hash: str) -> dict:
        with self.coordinator.transaction() as con:
            require(principal, 'action.approve', con=con)
            row = con.execute('SELECT * FROM workflows WHERE account_id=? AND id=?', (principal.account_id, str(workflow_id))).fetchone()
            if not row:
                raise NotFound('unavailable')
            if row['state'] != 'proposed':
                raise Conflict('this workflow is not waiting for approval')
            steps = self._steps(con, principal.account_id, row['id'])
            current = steps_hash([s['payload_hash'] for s in steps])
            intact = all(payload_hash(json.loads(s['payload_json'])) == s['payload_hash'] for s in steps)
            if not isinstance(approved_hash, str) or approved_hash != row['steps_hash'] or current != row['steps_hash'] or not intact or any(s['state'] != 'proposed' for s in steps):
                raise Conflict('a step changed since this was shown: review the workflow again')       # any change to any step voids the approval
            if any(s['needs_admin'] for s in steps) and not permissions.role_allows(permissions.member_role(con, principal.account_id, principal.actor_id) or '', 'policy.change'):
                raise Conflict('your organization asks for an admin to approve a step of this workflow: ask them to approve each step')
            now = int(self.clock())
            con.execute("UPDATE workflows SET state='approved',approved_by=?,approved_epoch=?,updated_epoch=? WHERE account_id=? AND id=?", (principal.actor_id, now, now, principal.account_id, row['id']))
            self.handoffs.settle(con, principal.account_id, workflow_id=row['id'], answer={'decision': 'approved'})
            self.coordinator._audit(con, principal.account_id, principal.actor_id, row['id'], 'workflow.approve', 'completed')
            return self.public(con, con.execute('SELECT * FROM workflows WHERE account_id=? AND id=?', (principal.account_id, row['id'])).fetchone())

    def decline(self, principal: Principal, workflow_id: str) -> dict:
        with self.coordinator.transaction() as con:
            require(principal, 'action.approve', con=con)
            row = con.execute('SELECT * FROM workflows WHERE account_id=? AND id=?', (principal.account_id, str(workflow_id))).fetchone()
            if not row:
                raise NotFound('unavailable')
            if row['state'] != 'proposed':
                raise Conflict('this workflow can no longer be declined')
            now = int(self.clock())
            con.execute("UPDATE workflows SET state='declined',updated_epoch=? WHERE account_id=? AND id=?", (now, principal.account_id, row['id']))
            con.execute("UPDATE actions SET state='declined',updated_epoch=? WHERE account_id=? AND workflow_id=? AND state='proposed'", (now, principal.account_id, row['id']))
            self.handoffs.settle(con, principal.account_id, workflow_id=row['id'], answer={'decision': 'declined'})
            return self.public(con, con.execute('SELECT * FROM workflows WHERE account_id=? AND id=?', (principal.account_id, row['id'])).fetchone())

    def expire(self, account_id, workflow_id):
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            if con.execute("UPDATE workflows SET state='expired',updated_epoch=? WHERE account_id=? AND id=? AND state='proposed'", (now, account_id, workflow_id)).rowcount:
                con.execute("UPDATE actions SET state='expired',ended_reason='approval_expired',updated_epoch=? WHERE account_id=? AND workflow_id=? AND state='proposed'", (now, account_id, workflow_id))

    # -- running -------------------------------------------------------------------------------------------------------------------------------
    def due(self) -> list[tuple]:
        with self.store.connect() as con:
            return [(r[0], r[1]) for r in con.execute("SELECT account_id,id FROM workflows WHERE state IN ('approved','running') ORDER BY updated_epoch LIMIT 20")]

    def advance(self, account_id: str, workflow_id: str) -> str:
        """Move one workflow as far as it goes now. -> its state. Safe to repeat and to resume after a restart: every step is an action that runs at most once."""
        with self.coordinator.transaction() as con:
            row = con.execute('SELECT * FROM workflows WHERE account_id=? AND id=?', (account_id, workflow_id)).fetchone()
            if not row or row['state'] not in ('approved', 'running'):
                return row['state'] if row else 'missing'
            con.execute("UPDATE workflows SET state='running',updated_epoch=? WHERE account_id=? AND id=?", (int(self.clock()), account_id, workflow_id))
        while True:
            with self.store.connect() as con:
                steps = self._steps(con, account_id, workflow_id)
            pending = next((s for s in steps if s['state'] != 'done'), None)
            if pending is None:
                return self._finish(account_id, workflow_id, 'done', {'completed': len(steps), 'reversed': [], 'not_reversed': []})
            if pending['state'] == 'proposed':
                self.actions.approve_internal(account_id, pending['id'])            # covered by the workflow's own approval
                state = self.actions.execute(account_id, pending['id'])
            elif pending['state'] == 'approved':
                state = self.actions.execute(account_id, pending['id'])
            elif pending['state'] == 'uncertain':
                state = self.actions.reconcile(account_id, pending['id'])
            else:
                state = pending['state']
            if state == 'done':
                continue
            if state in ('approved', 'executing', 'uncertain'):
                return 'running'                              # waiting for the provider (busy, or an answer that never came is being read back): looked at again next pass
            return self._walk_back(account_id, workflow_id, pending)

    def _walk_back(self, account_id, workflow_id, failed) -> str:
        """A step did not succeed. Reverse what finished, last first: the inverse where there is one, else the first registered compensation. Say exactly what happened."""
        with self.store.connect() as con:
            row = con.execute('SELECT * FROM workflows WHERE account_id=? AND id=?', (account_id, workflow_id)).fetchone()
            steps = self._steps(con, account_id, workflow_id)
        principal = Principal(account_id, row['actor_id'], 'customer')
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            con.execute("UPDATE actions SET state='expired',ended_reason='workflow_stopped',updated_epoch=? WHERE account_id=? AND workflow_id=? AND state IN ('proposed','approved') AND undo_of IS NULL AND compensates IS NULL",
                        (now, account_id, workflow_id))
        reversed_, not_reversed = [], []
        for step in reversed([s for s in steps if s['state'] == 'done']):
            label = json.loads(step['preview_json'])['summary']
            how, reversal = None, None
            try:
                if step['can_undo'] and step['undo_payload_json']:
                    how, reversal = 'undone', self.actions.undo(principal, step['id'], ask=False, workflow=(workflow_id, 100 + step['workflow_position']))
                else:
                    prepared = sorted(json.loads(step['compensation_json'] or '{}'))
                    if prepared:
                        how, reversal = 'compensated', self.actions.compensate(principal, step['id'], prepared[0], ask=False, workflow=(workflow_id, 100 + step['workflow_position']))
            except (ConnectorFault, Conflict, NotFound) as error:
                not_reversed.append({'step': step['workflow_position'], 'summary': label, 'why': getattr(error, 'kind', 'refused')})
                continue
            if reversal is None:
                not_reversed.append({'step': step['workflow_position'], 'summary': label, 'why': 'cannot_be_undone'})
                continue
            self.actions.approve_internal(account_id, reversal['id'])
            state = self.actions.execute(account_id, reversal['id'])
            if state == 'uncertain':
                state = self.actions.reconcile(account_id, reversal['id'])
            if state == 'done':
                reversed_.append({'step': step['workflow_position'], 'summary': label, 'how': how})
            else:
                not_reversed.append({'step': step['workflow_position'], 'summary': label, 'why': state})
        report = {'failed_step': failed['workflow_position'], 'failed_summary': json.loads(failed['preview_json'])['summary'], 'failed_reason': failed['ended_reason'] or self._reason(account_id, failed['id']),
                  'reversed': reversed_, 'not_reversed': not_reversed}
        return self._finish(account_id, workflow_id, 'partly_reversed' if not_reversed else 'reversed', report)

    def _reason(self, account_id, action_id):
        with self.store.connect() as con:
            row = con.execute('SELECT ended_reason,state FROM actions WHERE account_id=? AND id=?', (account_id, action_id)).fetchone()
        return (row['ended_reason'] or row['state']) if row else 'failed'

    def _finish(self, account_id, workflow_id, state, report) -> str:
        with self.coordinator.transaction() as con:
            con.execute('UPDATE workflows SET state=?,report_json=?,updated_epoch=? WHERE account_id=? AND id=?', (state, json.dumps(report), int(self.clock()), account_id, workflow_id))
        return state

    @staticmethod
    def report_words(report, state) -> str:
        """The exact account of a workflow, in plain words, from its report."""
        if state == 'done':
            return f'All {report["completed"]} steps were carried out.'
        lines = [f'Step {report["failed_step"]} ("{report["failed_summary"]}") did not succeed, so the workflow stopped.']
        for r in report['reversed']:
            lines.append(f'Step {r["step"]} ("{r["summary"]}") was {"undone" if r["how"] == "undone" else "followed by its correction, because it cannot be undone"}.')
        for r in report['not_reversed']:
            lines.append(f'Step {r["step"]} ("{r["summary"]}") could NOT be reversed and is still in effect.')
        if not report['reversed'] and not report['not_reversed']:
            lines.append('No earlier step had been carried out, so nothing needed reversing.')
        return ' '.join(lines)
