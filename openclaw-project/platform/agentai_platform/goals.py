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

from .lifecycle.types import Conflict
from .security import NotFound, Principal

CONTINUE_TEXT = 'Continue pursuing the current goal.'


class GoalChain:
    def __init__(self, service, *, clock=time.time, limit=20):
        self.service, self.clock, self.limit = service, clock, limit

    def pending(self):
        """Finished turns that asked for another and have none yet."""
        with self.service.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT account_id,id,actor_id,conversation_id FROM customer_requests r
                WHERE continue_goal=1 AND state='completed' AND conversation_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM customer_requests c WHERE c.account_id=r.account_id AND c.continues=r.id) ORDER BY sequence LIMIT 20""").fetchall()]

    def tick(self):
        admitted = 0
        for row in self.pending():
            principal = Principal(row['account_id'], row['actor_id'], 'customer')
            try:
                result = self.service._spawn(principal, row['conversation_id'], message=CONTINUE_TEXT, key='goal-next-' + row['id'], intent='goal_continue',
                                             context={'goal': True}, shown='Continuing towards your goal.', provenance='system', goal_mode=True, continues=row['id'])
                admitted += 1 if result.get('execution_enabled') else 0
            except (Conflict, NotFound, PermissionError, Exception) as error:
                self._stop(principal, row, error)
        return admitted

    def _stop(self, principal, row, error):
        """The next turn could not be admitted (allowance, membership, queue). The goal is paused natively and the finished turn says so; the customer can resume."""
        category = str(error)[:80] or type(error).__name__
        self.service._pause_goal(principal, row['conversation_id'], 'Paused: the next turn could not be admitted (' + category + ').')
        with self.service.coordinator.transaction() as con:
            con.execute("UPDATE customer_requests SET continue_goal=0,outcome='partial',outcome_note=? WHERE account_id=? AND id=?",
                        ('The goal is paused: the next turn could not be started (' + category + '). Resume it when you are ready.', principal.account_id, row['id']))
