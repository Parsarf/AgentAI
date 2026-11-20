"""Handing work to a person and taking it back (roadmap #83): the general form of "the task is waiting for you".

Any piece of work can stop with a reason, a question, the evidence, the options and where it will resume. Two shapes, one rule for how long each may wait:

* a RUN that waits inside a tool call (the browser asking, the customer driving the browser, a location permission) is parked by the request queue, as before: it gives up
  its running slot and keeps its cell. These waits are short.
* work that waits for a decision that may take days (approving a change in a connected service, answering a question) is a HANDOFF row. The turn that asked ends normally,
  so nothing is held: no running slot and no cell. When the person answers, the work resumes from what the row recorded, as a new turn in the same chat.

How long each kind waits is one table (`WAITS`), which the customer can see. When a wait ends without an answer nothing is done by default: the action expires and the work
stays paused until the customer picks it up again.
"""
from __future__ import annotations
import json
import time
import uuid

from .lifecycle.coordinator import Coordinator
from .lifecycle.types import Conflict
from .security import NotFound, Principal, require

# Seconds each kind of wait may last. The first three hold a cell and a live run, so they are short; the others hold nothing.
WAITS = {
    'browser_question': 1800, 'browser_takeover': 1800, 'location_permission': 1800,
    'action_approval': 3 * 86400, 'workflow_approval': 3 * 86400, 'question': 86400,
}
WAIT_WORDS = {
    'browser_question': 'A question from the browser', 'browser_takeover': 'You driving the browser', 'location_permission': 'Sharing your location',
    'action_approval': 'Approving a change in a connected service', 'workflow_approval': 'Approving several changes together', 'question': 'A question from your assistant',
}
KINDS = ('action_approval', 'workflow_approval', 'question')


def wait_seconds(kind, default=1800) -> int:
    return WAITS.get(kind, default)


def waits_public() -> list[dict]:
    """What the customer is shown: each kind of wait and how long it lasts before it ends by itself."""
    return [{'kind': kind, 'label': WAIT_WORDS[kind], 'seconds': seconds} for kind, seconds in WAITS.items()]


class Handoffs:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    def create(self, con, *, account_id, actor_id, kind, request_id=None, conversation_id=None, action_id=None, workflow_id=None, question='', options=(), evidence=None, resume=None,
               seconds=None) -> str:
        """Inside the caller's transaction. -> the handoff id."""
        if kind not in KINDS:
            raise ValueError('unknown handoff kind')
        if conversation_id is None and request_id is not None:
            row = con.execute('SELECT conversation_id FROM customer_requests WHERE account_id=? AND id=?', (account_id, request_id)).fetchone()
            conversation_id = row[0] if row else None
        now, handoff = int(self.clock()), uuid.uuid4().hex
        con.execute('''INSERT INTO handoffs(account_id,id,request_id,conversation_id,actor_id,kind,action_id,workflow_id,question,options_json,evidence_json,resume_json,state,created_epoch,expires_epoch)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'waiting',?,?)''',
                    (account_id, handoff, request_id, conversation_id, actor_id, kind, action_id, workflow_id, str(question)[:1000], json.dumps(list(options)[:8]),
                     json.dumps(evidence or {}), json.dumps(resume or {}), now, now + (min(int(seconds), 14 * 86400) if seconds else wait_seconds(kind))))
        return handoff

    @staticmethod
    def public(row) -> dict:
        return {'id': row['id'], 'kind': row['kind'], 'state': row['state'], 'request_id': row['request_id'], 'conversation_id': row['conversation_id'], 'action_id': row['action_id'],
                'workflow_id': row['workflow_id'], 'question': row['question'], 'options': json.loads(row['options_json']), 'evidence': json.loads(row['evidence_json']),
                'created_epoch': row['created_epoch'], 'expires_epoch': row['expires_epoch'], 'answered_epoch': row['answered_epoch'], 'wait_seconds': wait_seconds(row['kind'])}

    def pending(self, principal: Principal) -> list[dict]:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            return [self.public(r) for r in con.execute("SELECT * FROM handoffs WHERE account_id=? AND state='waiting' AND expires_epoch>? ORDER BY created_epoch",
                                                        (principal.account_id, int(self.clock())))]

    def answer(self, principal: Principal, handoff_id: str, answer: str) -> dict:
        """The customer answers a question. (An approval is answered through the action or the workflow, which checks the payload hash.)"""
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 2000 or '\x00' in answer:
            raise ValueError('invalid answer')
        with self.coordinator.transaction() as con:
            require(principal, 'task.control', con=con)
            row = con.execute('SELECT * FROM handoffs WHERE account_id=? AND id=?', (principal.account_id, str(handoff_id))).fetchone()
            if not row:
                raise NotFound('unavailable')
            if row['kind'] != 'question' or row['state'] != 'waiting' or row['expires_epoch'] <= self.clock():
                raise Conflict('this is no longer waiting for an answer')
            con.execute("UPDATE handoffs SET state='answered',answer_json=?,answered_epoch=? WHERE account_id=? AND id=?",
                        (json.dumps({'answer': answer.strip()}), int(self.clock()), principal.account_id, row['id']))
            row = con.execute('SELECT * FROM handoffs WHERE account_id=? AND id=?', (principal.account_id, row['id'])).fetchone()
            return self.public(row)

    def settle(self, con, account_id, *, action_id=None, workflow_id=None, answer=None):
        """Inside the caller's transaction: the approval this handoff waited for was given or declined."""
        con.execute(f"UPDATE handoffs SET state='answered',answer_json=?,answered_epoch=? WHERE account_id=? AND state='waiting' AND {'action_id' if action_id else 'workflow_id'}=?",
                    (json.dumps(answer or {}), int(self.clock()), account_id, action_id or workflow_id))

    def expire_due(self) -> list[dict]:
        """Waits that ended without an answer. Nothing is done by default: they are marked expired and returned, so what waited on them can be ended too."""
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM handoffs WHERE state='waiting' AND expires_epoch<=? ORDER BY expires_epoch LIMIT 100", (now,))]
            for r in rows:
                con.execute("UPDATE handoffs SET state='expired',answered_epoch=? WHERE account_id=? AND id=? AND state='waiting'", (now, r['account_id'], r['id']))
        return rows

    def to_resume(self) -> list[dict]:
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM handoffs WHERE state='answered' AND resumed_request_id IS NULL ORDER BY answered_epoch LIMIT 50")]

    def resumed(self, account_id, handoff_id, request_id):
        with self.coordinator.transaction() as con:
            con.execute("UPDATE handoffs SET state='resumed',resumed_request_id=? WHERE account_id=? AND id=? AND state='answered'", (request_id or '', account_id, handoff_id))
