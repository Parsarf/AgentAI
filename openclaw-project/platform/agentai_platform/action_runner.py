"""What moves the action pipeline between requests (roadmap #26, #83, #29): one pass, run by the request worker beside plans and goals.

It executes approved changes (each at most once), reads back the ones whose outcome is unknown, advances workflows, ends waits that ran out (nothing is done by default)
and, when a person has answered, RESUMES the work that was waiting: a new turn in the same chat that tells the assistant what was decided and what happened.

It never decides anything. A change runs only because its exact payload was approved (actions.py); a workflow only because all its steps were (workflows.py).
"""
from __future__ import annotations
import json
import time

from .handoff import Handoffs, in_place
from .in_place import FINAL, outcome_of
from .request_worker import where
from .security import Principal
from .workflows import WorkflowService

GIVE_UP_RESUMING = 3600            # seconds after an answer during which the resume turn is tried; after that the outcome stays on the action for the customer to read


class ActionRunner:
    def __init__(self, store, actions, workflows: WorkflowService, *, chat=None, clock=time.time):
        self.store, self.actions, self.workflows, self.chat, self.clock = store, actions, workflows, chat, clock
        self.handoffs = Handoffs(store, clock=clock)

    def tick(self) -> int:
        """-> how many things moved (an executed change, an advanced workflow, a resumed chat)."""
        moved = 0
        self.actions.recover_stale()
        for account, action in self.actions.due('uncertain'):
            moved += 1 if self.actions.reconcile(account, action) in ('done', 'failed') else 0
        for account, action in self.actions.due('approved'):
            moved += 1 if self.actions.execute(account, action) in ('done', 'failed', 'expired') else 0
        for account, workflow in self.workflows.due():
            moved += 1 if self.workflows.advance(account, workflow) not in ('running', 'approved') else 0
        for expired in self.handoffs.expire_due():          # a wait that ran out: what waited on it ends, and nothing is done
            if expired['action_id']:
                self.actions.expire(expired['account_id'], expired['action_id'])
            if expired['workflow_id']:
                self.workflows.expire(expired['account_id'], expired['workflow_id'])
        moved += self._resume()
        return moved

    # -- resuming the chat that was waiting -------------------------------------------------------------------------------------------------------
    def _outcome(self, con, handoff):
        """-> (text for the assistant, line shown in the chat), or None while the thing it waited for is still being carried out (in_place.outcome_of: one wording for both
        ways the work hears it)."""
        return outcome_of(con, handoff, self.workflows.report_words)

    def _resume(self) -> int:
        resumed = 0
        for handoff in self.handoffs.to_resume():
            if in_place(handoff, int(self.clock())):
                continue                                   # a call is still waiting for this in the run that asked: it takes the outcome itself (in_place.hold_approval)
            with self.store.connect() as con:
                outcome = self._outcome(con, handoff)
            if outcome is None:
                continue
            if self.chat is None or not handoff['conversation_id']:
                self.handoffs.resumed(handoff['account_id'], handoff['id'], '')
                continue
            text, shown = outcome
            try:
                result = self.chat._spawn(Principal(handoff['account_id'], handoff['actor_id'], 'customer'), handoff['conversation_id'], message=text[:8000],
                                          key='handoff-' + handoff['id'], intent='chat', context={'handoff': handoff['id'], **({'follows': handoff['request_id']} if handoff['request_id'] else {})}, shown=shown[:300], provenance='system')
                self.handoffs.resumed(handoff['account_id'], handoff['id'], result.get('id', ''))
                resumed += 1
            except Exception as error:
                # The chat could not take a turn now (archived, the queue is full, the allowance): tried again for a while, then left. The outcome is on the action either way.
                if self.clock() - (handoff['answered_epoch'] or 0) > GIVE_UP_RESUMING:
                    self.handoffs.resumed(handoff['account_id'], handoff['id'], '')
                self.last_error = where(error)
        return resumed
