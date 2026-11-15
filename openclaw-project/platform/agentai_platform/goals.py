"""Keep working until complete: admission of the next turn of a session goal.

The goal is the runtime's: OpenClaw 2026.9.6 keeps one durable objective per session, shows it to the model on every turn, and lets the model mark it complete or blocked.
It does not start another turn by itself when a turn ends with the goal still active. Lumina therefore does the one thing that is not execution: it decides whether
another turn may be ADMITTED. Each turn is its own request with its own reservation, so every limit that applies to any task applies to each turn:

* the spending allowance (a refusal pauses the goal natively and says why);
* the account's membership (a revoked customer's chain ends);
* the chain length (GOAL_CHAIN_LIMIT turns, then the customer decides whether to resume);
* Stop (a stopped turn pauses the goal natively, so nothing here resumes it), the per-run time limit, and every state the runtime reports other than `active`:
  paused, blocked, budget-limited and complete goals are never continued.

Between turns the running slot is free, so other customers' work interleaves with a long goal.
"""
from __future__ import annotations
import time

from .goal_objectives import GoalObjectives
from .lifecycle.types import Conflict
from .security import NotFound, Principal

CONTINUE_TEXT = 'Continue pursuing the current goal.'


class GoalChain:
    def __init__(self, service, *, clock=time.time, limit=20):
        self.service, self.clock, self.limit = service, clock, limit
        # The whole job as a durable objective: checkpoints, a visible budget, a resume policy (goal_objectives.py). It records and decides; it never executes.
        self.objectives = GoalObjectives(service.store, clock=clock, default_turns=limit)

    def pending(self):
        """Finished turns that asked for another and have none yet."""
        with self.service.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT account_id,id,actor_id,conversation_id FROM customer_requests r
                WHERE continue_goal=1 AND state='completed' AND conversation_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM customer_requests c WHERE c.account_id=r.account_id AND c.continues=r.id) ORDER BY sequence LIMIT 20""").fetchall()]

    def tick(self):
        admitted = 0
        for finished in self.objectives.unrecorded():          # every finished goal turn gets its checkpoint, whether or not another turn follows
            if not finished['continue_goal']:
                self.objectives.record(finished)
        for row in self.pending():
            principal = Principal(row['account_id'], row['actor_id'], 'customer')
            allowed, why = self.objectives.may_continue({**row, **self._facts(row)})
            if not allowed:
                self._stop(principal, row, why, budget=True)
                continue
            try:
                result = self.service._spawn(principal, row['conversation_id'], message=CONTINUE_TEXT, key='goal-next-' + row['id'], intent='goal_continue',
                                             context={'goal': True}, shown='Continuing towards your goal.', provenance='system', goal_mode=True, continues=row['id'])
                admitted += 1 if result.get('execution_enabled') else 0
                self.objectives.started({**row, **self._facts(row)}, result['id'])
            except (Conflict, NotFound, PermissionError, Exception) as error:
                self._stop(principal, row, error)
        admitted += self._auto_resume()
        return admitted

    def _facts(self, row):
        with self.service.store.connect() as con:
            found = con.execute('SELECT state,outcome,outcome_note,continue_goal,intent,created_epoch FROM customer_requests WHERE account_id=? AND id=?',
                                (row['account_id'], row['id'])).fetchone()
        return dict(found) if found else {'state': 'completed', 'outcome': 'completed', 'outcome_note': None, 'continue_goal': 1, 'intent': 'chat', 'created_epoch': int(self.clock())}

    def _auto_resume(self):
        """Jobs whose customer chose to carry on automatically after an interrupted turn: one resume turn each, admitted like any task, a bounded number of times."""
        resumed = 0
        for job in self.objectives.due_auto_resumes():
            if not job['actor_id']:
                continue
            principal = Principal(job['account_id'], job['actor_id'], 'customer')
            try:
                self.service.goal_action(principal, job['conversation_id'], 'resume', key=f"auto-{job['id'][:16]}-{job['auto_resumes'] + 1}")
                self.objectives.note_auto_resume(job['account_id'], job['id'])
                resumed += 1
            except Exception:
                self.objectives.note_auto_resume(job['account_id'], job['id'])      # counted either way, so a job that cannot be resumed is not tried for ever
                with self.service.coordinator.transaction() as con:
                    con.execute("UPDATE objectives SET app_state='paused',pause_reason='It could not be resumed automatically. Resume it when you are ready.' WHERE account_id=? AND id=?",
                                (job['account_id'], job['id']))
        return resumed

    def _stop(self, principal, row, error, budget=False):
        """The next turn could not be admitted (allowance, membership, queue), or the job reached its own budget. The goal is paused natively and the finished turn says so;
        the customer can resume."""
        category = str(error)[:160] or type(error).__name__
        note = ('The goal is paused: ' + category) if budget else ('The goal is paused: the next turn could not be started (' + category[:80] + '). Resume it when you are ready.')
        self.service._pause_goal(principal, row['conversation_id'], 'Paused: ' + category if budget else 'Paused: the next turn could not be admitted (' + category[:80] + ').')
        with self.service.coordinator.transaction() as con:
            con.execute("UPDATE customer_requests SET continue_goal=0,outcome='partial',outcome_note=? WHERE account_id=? AND id=?", (note[:300], principal.account_id, row['id']))
