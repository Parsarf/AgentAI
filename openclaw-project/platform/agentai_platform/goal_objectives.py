"""A "keep working until complete" goal as a durable objective (roadmap #6, #7).

The runtime owns the goal and each turn is an ordinary admitted request (goals.py). What was missing is a record of the whole job that survives anything: this module keeps
one objective (durable.py) per chain of turns, with

* a checkpoint for every finished turn (what it was, how it ended), written once however often it is looked at;
* a budget the customer can see and change: how many turns and how much wall-clock time the job may take. Spending is bounded by the limits they set in Settings
  (spend_limits.py), not here. A budget that is reached pauses the job with a plain reason; it never fails it;
* a resume policy, theirs to choose: `ask` (the default: an interrupted or failed turn waits for them) or `auto` (Lumina resumes it, a bounded number of times).

Nothing here executes anything. The chain is driven from the database between turns, so a worker or cell restart loses nothing: the turn that was running is recovered by
the queue like any request, and its ending is recorded here when it ends. Stop pauses (the customer can resume); clearing the goal cancels, and cancel is sticky.
"""
from __future__ import annotations
import time

from .durable import MAX_CHECKPOINTS, ObjectiveService
from .lifecycle.coordinator import Coordinator
from .lifecycle.types import Conflict
from .security import NotFound, Principal

DEFAULT_TURNS = 20                # turns of one job before the customer is asked whether to go on (they can raise it per job)
MAX_AUTO_RESUMES = 3              # how many times `auto` resumes one job after interrupted turns before it waits for the customer after all
RECENT_SECONDS = 14 * 86400       # finished turns older than this are history and are not turned into objectives after the fact
OPEN_STATES = ('active', 'paused', 'needs_reconciliation')


class GoalObjectives:
    def __init__(self, store, *, clock=time.time, default_turns=DEFAULT_TURNS):
        self.store, self.clock, self.default_turns = store, clock, default_turns
        self.objectives = ObjectiveService(store, clock=clock)
        self.coordinator = Coordinator(store, clock=clock)

    # -- finding the objective of a turn ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _root(con, account, request_id):
        """The first turn of the chain this request belongs to (follows `continues` back; bounded)."""
        current = request_id
        for _ in range(600):
            row = con.execute('SELECT continues FROM customer_requests WHERE account_id=? AND id=?', (account, current)).fetchone()
            if not row or not row['continues']:
                return current
            current = row['continues']
        return current

    def for_request(self, principal: Principal, request: dict) -> str | None:
        """The objective this goal turn belongs to, created on first sight. A resume turn joins the conversation's newest open objective instead of starting a new one."""
        account = principal.account_id
        with self.store.connect() as con:
            root = self._root(con, account, request['id'])
            found = con.execute('SELECT id FROM objectives WHERE account_id=? AND task_id=?', (account, root)).fetchone()
            if found:
                return found['id']
            first = con.execute('SELECT intent,project_id,conversation_id FROM customer_requests WHERE account_id=? AND id=?', (account, root)).fetchone()
            if not first:
                return None
            if first['intent'] == 'goal_resume':
                joined = con.execute(f"""SELECT id FROM objectives WHERE account_id=? AND conversation_id=? AND cancelled=0 AND app_state IN ({','.join('?' * len(OPEN_STATES))})
                    ORDER BY created_epoch DESC,id DESC LIMIT 1""", (account, first['conversation_id'], *OPEN_STATES)).fetchone()
                if joined:
                    return joined['id']
                # A job cancelled WHILE this resume turn was waiting or running still owns it: the turn must not become a new job that carries on (cancel is sticky).
                stopped = con.execute('''SELECT o.id FROM objectives o JOIN customer_requests r ON r.account_id=o.account_id AND r.id=?
                    WHERE o.account_id=? AND o.conversation_id=? AND o.cancelled=1 AND o.updated_epoch>=r.created_epoch ORDER BY o.updated_epoch DESC,o.id DESC LIMIT 1''',
                                      (root, account, first['conversation_id'])).fetchone()
                if stopped:
                    return stopped['id']
        objective = self.objectives.create(principal, first['project_id'], task_id=root)
        with self.coordinator.transaction() as con:
            con.execute('UPDATE objectives SET conversation_id=? WHERE account_id=? AND id=?', (first['conversation_id'], account, objective))
        return objective

    # -- recording what happened ----------------------------------------------------------------------------------------------------------------
    def unrecorded(self):
        """Finished goal turns that have no checkpoint yet (recent ones only)."""
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT r.account_id,r.id,r.actor_id,r.conversation_id,r.state,r.outcome,r.outcome_note,r.continue_goal,r.intent,r.created_epoch
                FROM customer_requests r WHERE r.goal_mode=1 AND r.state IN ('completed','failed','cancelled') AND r.conversation_id IS NOT NULL AND r.created_epoch>=?
                AND NOT EXISTS (SELECT 1 FROM objective_checkpoints k WHERE k.account_id=r.account_id AND k.receipt_id=r.id)
                AND NOT (r.continue_goal=1 AND EXISTS (SELECT 1 FROM customer_requests c WHERE c.account_id=r.account_id AND c.continues=r.id))
                ORDER BY r.sequence DESC LIMIT 50""", (int(self.clock()) - RECENT_SECONDS,)).fetchall()][::-1]
        # The NEWEST fifty, oldest of them first: a turn that can never get a checkpoint (its job was cancelled, or it was continued before checkpoints existed) must not
        # stand in front of the turns that can. A turn that asked for another and already has it is recorded when it is continued (may_continue), never here.

    def record(self, request: dict) -> str | None:
        """One checkpoint for a finished turn, and the objective's state after it. Safe to repeat. -> objective id."""
        principal = Principal(request['account_id'], request['actor_id'], 'customer')
        try:
            objective = self.for_request(principal, request)
            if objective is None:
                return None
            outcome = request['outcome'] or request['state']
            with self.store.connect() as con:
                turn = con.execute('SELECT count(*) FROM objective_checkpoints WHERE account_id=? AND objective_id=?', (principal.account_id, objective)).fetchone()[0] + 1
            self.objectives.checkpoint(principal, objective, f'Turn {turn}: {outcome}'[:200], receipt_id=request['id'], effect_state='confirmed')
            if request['continue_goal']:
                state, reason = 'active', None
            elif request['state'] == 'completed' and outcome == 'completed':
                state, reason = 'completed', None
            elif request['state'] == 'cancelled':
                state, reason = 'paused', 'Stopped by you.'
            elif request['state'] == 'failed':
                state, reason = 'paused', 'The last turn was interrupted or failed.'
            else:
                state, reason = 'paused', (request['outcome_note'] or 'The last turn did not finish everything.')[:300]
            with self.coordinator.transaction() as con:
                con.execute("UPDATE objectives SET app_state=?,pause_reason=?,updated_epoch=? WHERE account_id=? AND id=? AND cancelled=0 AND app_state<>'needs_reconciliation'",
                            (state, reason, int(self.clock()), principal.account_id, objective))
            return objective
        except (Conflict, NotFound):
            return None                      # a cancelled objective takes no more checkpoints; a revoked customer's chain simply ends

    # -- the budget -------------------------------------------------------------------------------------------------------------------------------
    def view(self, con, account, objective_id) -> dict | None:
        row = con.execute('SELECT * FROM objectives WHERE account_id=? AND id=?', (account, objective_id)).fetchone()
        if not row:
            return None
        steps = [dict(r) for r in con.execute('SELECT sequence,step,receipt_id,created_epoch FROM objective_checkpoints WHERE account_id=? AND objective_id=? ORDER BY sequence',
                                              (account, objective_id))]
        max_turns = row['max_turns'] or self.default_turns
        elapsed = int(self.clock()) - row['created_epoch']
        over = None
        if len(steps) >= max_turns:
            over = f'This job reached its limit of {max_turns} turns.'
        elif row['max_seconds'] and elapsed >= row['max_seconds']:
            over = 'This job reached its time limit.'
        return {'id': row['id'], 'conversation_id': row['conversation_id'], 'state': row['app_state'], 'cancelled': bool(row['cancelled']), 'pause_reason': row['pause_reason'],
                'resume_policy': row['resume_policy'], 'turns': len(steps), 'max_turns': max_turns, 'elapsed_seconds': elapsed, 'max_seconds': row['max_seconds'],
                'over_budget': over, 'auto_resumes': row['auto_resumes'], 'checkpoints': steps, 'created_epoch': row['created_epoch'], 'updated_epoch': row['updated_epoch']}

    def may_continue(self, request: dict):
        """Before the next turn of a chain is admitted. -> (True, None), or (False, the plain reason it pauses here)."""
        # Cancel is sticky, and it is looked at FIRST: a cancelled job takes no checkpoint, so asking `record` alone could not tell "cancelled" from "no record kept".
        try:
            known = self.for_request(Principal(request['account_id'], request['actor_id'], 'customer'), request)
        except (Conflict, NotFound):
            known = None
        if known is not None:
            with self.store.connect() as con:
                before = self.view(con, request['account_id'], known)
            if before is not None and before['cancelled']:
                return False, 'This job was cancelled.'
            if before is not None and before['turns'] >= MAX_CHECKPOINTS:
                return False, f'This job reached the most turns one job can have ({MAX_CHECKPOINTS}).'
        objective = self.record(request)
        if objective is None:
            return True, None                # no objective could be kept (very old chain, revoked customer): the chain's own rules still apply
        with self.store.connect() as con:
            view = self.view(con, request['account_id'], objective)
        if view is None or view['cancelled']:
            return False, 'This job was cancelled.'
        if view['over_budget']:
            with self.coordinator.transaction() as con:
                con.execute("UPDATE objectives SET app_state='paused',pause_reason=?,updated_epoch=? WHERE account_id=? AND id=? AND cancelled=0",
                            (view['over_budget'] + ' Raise the limit or resume to carry on.', int(self.clock()), request['account_id'], objective))
            return False, view['over_budget'] + ' Resume it to carry on, or raise the limit first.'
        return True, None

    def started(self, request: dict, next_request_id: str):
        """The next turn was admitted: it is a child of the objective, so cancelling the job reaches it."""
        principal = Principal(request['account_id'], request['actor_id'], 'customer')
        try:
            objective = self.for_request(principal, request)
            if objective:
                self.objectives.register_child(principal, objective, next_request_id, 'job')
        except (Conflict, NotFound):
            pass

    # -- the customer's controls ----------------------------------------------------------------------------------------------------------------
    def listing(self, principal: Principal, *, limit=20):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            ids = [r['id'] for r in con.execute('SELECT id FROM objectives WHERE account_id=? AND conversation_id IS NOT NULL ORDER BY updated_epoch DESC,id DESC LIMIT ?',
                                                (principal.account_id, max(1, min(int(limit), 50))))]
            return [self.view(con, principal.account_id, i) for i in ids]

    def get(self, principal: Principal, objective_id: str):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            view = self.view(con, principal.account_id, objective_id)
        if view is None:
            raise NotFound('unavailable')
        return view

    def configure(self, principal: Principal, objective_id: str, *, resume_policy=None, max_turns=None, max_seconds=None):
        """The customer changes how a job behaves. A raised limit lets a paused job be resumed; it never resumes it by itself."""
        if resume_policy not in (None, 'ask', 'auto'):
            raise ValueError('invalid resume policy')
        if max_turns is not None and (type(max_turns) is not int or not 1 <= max_turns <= 500):
            raise ValueError('invalid turn limit')
        if max_seconds is not None and (type(max_seconds) is not int or not 60 <= max_seconds <= 2592000):
            raise ValueError('invalid time limit')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT cancelled FROM objectives WHERE account_id=? AND id=?', (principal.account_id, objective_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            if row['cancelled']:
                raise Conflict('this job was cancelled')
            for column, value in (('resume_policy', resume_policy), ('max_turns', max_turns), ('max_seconds', max_seconds)):
                if value is not None:
                    con.execute(f'UPDATE objectives SET {column}=?,updated_epoch=? WHERE account_id=? AND id=?', (value, int(self.clock()), principal.account_id, objective_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, objective_id, 'objective.configure', 'completed')
        return self.get(principal, objective_id)

    def cancel(self, principal: Principal, objective_id: str):
        """Sticky: the job never continues or resumes again. -> the request ids of turns that must be stopped (the caller stops them): the turns registered with the job AND every
        goal turn of its chat that is waiting or running now. The second part is what reaches a resume turn (never registered) and the turns of a job past the child limit."""
        children = self.objectives.cancel(principal, objective_id)
        with self.store.connect() as con:
            row = con.execute('SELECT conversation_id FROM objectives WHERE account_id=? AND id=?', (principal.account_id, objective_id)).fetchone()
            live = [r['id'] for r in con.execute("""SELECT id FROM customer_requests WHERE account_id=? AND conversation_id=? AND goal_mode=1
                AND state IN ('waiting','starting','running','uncertain') ORDER BY sequence""", (principal.account_id, row['conversation_id']))] if row and row['conversation_id'] else []
        return children + [r for r in live if r not in children]

    def due_auto_resumes(self):
        """Jobs whose customer chose `auto`, paused by an interrupted or failed turn, with resumes left and nothing of theirs running or waiting."""
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT o.account_id,o.id,o.conversation_id,o.auto_resumes,
                    (SELECT r.actor_id FROM customer_requests r WHERE r.account_id=o.account_id AND r.id=o.task_id) AS actor_id
                FROM objectives o WHERE o.resume_policy='auto' AND o.cancelled=0 AND o.app_state='paused' AND o.pause_reason='The last turn was interrupted or failed.'
                AND o.auto_resumes<? AND o.conversation_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM customer_requests q WHERE q.account_id=o.account_id AND q.conversation_id=o.conversation_id
                                AND q.state IN ('waiting','starting','running','uncertain')) LIMIT 10""", (MAX_AUTO_RESUMES,)).fetchall()]

    def note_auto_resume(self, account, objective_id):
        with self.coordinator.transaction() as con:
            con.execute("UPDATE objectives SET auto_resumes=auto_resumes+1,app_state='active',pause_reason=NULL,updated_epoch=? WHERE account_id=? AND id=?",
                        (int(self.clock()), account, objective_id))
