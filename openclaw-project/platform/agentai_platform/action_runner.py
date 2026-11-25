"""What moves the action pipeline between requests (roadmap #26, #83, #29): one pass, run by the request worker beside plans and goals.

It executes approved changes (each at most once), reads back the ones whose outcome is unknown, advances workflows, ends waits that ran out (nothing is done by default)
and, when a person has answered, RESUMES the work that was waiting: a new turn in the same chat that tells the assistant what was decided and what happened.

It never decides anything. A change runs only because its exact payload was approved (actions.py); a workflow only because all its steps were (workflows.py).
"""
from __future__ import annotations
import json
import time

from .handoff import Handoffs
from .request_worker import where
from .security import Principal
from .workflows import WorkflowService

GIVE_UP_RESUMING = 3600            # seconds after an answer during which the resume turn is tried; after that the outcome stays on the action for the customer to read
FINAL = ('done', 'failed', 'declined', 'expired', 'undone', 'compensated')


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
        """-> (text for the assistant, line shown in the chat), or None while the thing it waited for is still being carried out."""
        answer = json.loads(handoff['answer_json'] or '{}')
        if handoff['kind'] == 'question':
            given = answer.get('answers') if isinstance(answer.get('answers'), list) else None
            if given and (len(given) > 1 or given[0].get('skipped')):
                lines = '\n'.join(f'- "{a["question"]}": ' + ('skipped (choose the obvious option yourself and say what you assumed)' if a.get('skipped') else str(a.get('answer', ''))[:2000]) for a in given)
                return ('The customer answered your questions:\n' + lines + '\nCarry on with the task from where you stopped.', 'Answered: ' + str(answer.get('answer', ''))[:200])
            return ('The customer answered your question "' + handoff['question'] + '": ' + str(answer.get('answer', ''))[:2000] + '\nCarry on with the task from where you stopped.',
                    'Answered: ' + str(answer.get('answer', ''))[:200])
        if handoff['kind'] == 'action_approval':
            row = con.execute('SELECT state,preview_json,ended_reason,verified,verify_note FROM actions WHERE account_id=? AND id=?', (handoff['account_id'], handoff['action_id'])).fetchone()
            if row is None or row['state'] not in FINAL:
                return None
            summary = json.loads(row['preview_json'])['summary']
            if row['state'] == 'done':
                checked = '' if row['verified'] is None else (' It was read back and matches what was sent.' if row['verified'] else ' WARNING: it was read back and ' + (row['verify_note'] or 'differs from what was sent') + '.')
                return (f'The customer approved the change you prepared ("{summary}") and Lumina carried it out once.{checked}\nCarry on with the task from where you stopped. Do not prepare it again.',
                        f'Approved and done: {summary}')
            if row['state'] == 'declined':
                return (f'The customer DECLINED the change you prepared ("{summary}"). Nothing was changed. Do not prepare it again; carry on without it, or ask what they would like instead.',
                        f'Declined: {summary}')
            from .actions import FAILED_WORDS
            why = FAILED_WORDS.get(row['ended_reason'] or '', 'It did not succeed and nothing was changed.')
            return (f'The change you prepared ("{summary}") was approved but could not be made. {why}\nTell the customer exactly that. Do not claim it was done.', f'Could not be done: {summary}')
        row = con.execute('SELECT state,title,report_json FROM workflows WHERE account_id=? AND id=?', (handoff['account_id'], handoff['workflow_id'])).fetchone()
        if row is None or row['state'] in ('approved', 'running', 'proposed'):
            return None
        if row['state'] == 'declined':
            return (f'The customer DECLINED the workflow you prepared ("{row["title"]}"). Nothing was changed. Do not prepare it again.', f'Declined: {row["title"]}')
        words = self.workflows.report_words(json.loads(row['report_json'] or '{}'), row['state']) if row['report_json'] else 'It ended.'
        return (f'The workflow you prepared ("{row["title"]}") was approved and run by Lumina. {words}\nTell the customer exactly what happened, including anything that could not be reversed.',
                ('Done: ' if row['state'] == 'done' else 'Stopped and reversed: ' if row['state'] == 'reversed' else 'Stopped, partly reversed: ') + row['title'])

    def _resume(self) -> int:
        resumed = 0
        for handoff in self.handoffs.to_resume():
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
