"""Waiting for the customer inside a tool call (reliability plan, Part 6): the call stays open, the driver parks the run (no running slot, the workspace kept), and the
customer's answer or decision comes back to the same run. Used by the question tool (owner switch `ask_in_place`) and by every change that waits for the customer's
approval (owner switch `approve_in_place`): a change in a connected service, several at once, a mail or a calendar change.

The wait is a hand-off row (handoff.py) marked `in_place` with the moment the window ends (`until`) and the last time the waiting call said it is still there (`seen`).
While those hold, the driver parks the run (handoff.waiting_in_place) and the action runner leaves the row alone. When the window ends, the call is dropped, or the relay
restarts, the marks go (or go stale within `SEEN_SECONDS`) and the row is an ordinary hand-off again: the work resumes as a new turn when it is answered, as before.
"""
from __future__ import annotations
import json
import time

from .handoff import IN_PLACE_SECONDS, SEEN_SECONDS
from .lifecycle.coordinator import Coordinator

MARKS = ('in_place', 'until', 'seen')


def window(store, account, request_id, allowed, now) -> int:
    """How long a call may wait in place: 0 when the owner's switch is off, for a scheduled run (nobody is there to answer), or when the runtime's own limit on this run is
    too close; otherwise up to IN_PLACE_SECONDS."""
    try:
        if not allowed(account):
            return 0
    except Exception:
        return 0
    from .lifecycle.cell_config import RUN_BACKSTOP_SECONDS
    with store.connect() as con:
        row = con.execute('SELECT context_json FROM customer_requests WHERE account_id=? AND id=?', (account, request_id)).fetchone()
        started = con.execute("SELECT max(created_epoch) FROM chat_deliveries WHERE account_id=? AND request_id=? AND kind!='steer'", (account, request_id)).fetchone()[0]
    try:
        context = json.loads(row['context_json'] or '{}') if row else None
    except (ValueError, TypeError):
        context = None
    if not isinstance(context, dict) or context.get('unattended'):
        return 0
    left = min(IN_PLACE_SECONDS, RUN_BACKSTOP_SECONDS - (int(now) - int(started or now)) - 90)
    return left if left >= 60 else 0


def marks(seconds, now) -> dict:
    return {'in_place': True, 'until': int(now) + int(seconds), 'seen': int(now)}


def request_over(store, account, request_id) -> bool:
    from . import request_states
    with store.connect() as con:
        row = con.execute('SELECT state,cancel_requested FROM customer_requests WHERE account_id=? AND id=?', (account, request_id)).fetchone()
    return row is None or bool(row['cancel_requested']) or row['state'] in request_states.FINAL


def hold(store, *, clock=time.time, sleep=time.sleep, poll=1.0, account, request_id, handoff_id, closed, ready, withdraw_on_stop):
    """Hold the call until `ready(con, row, claim)` gives a value, the window ends, the call is dropped, or the task is over. Reads are plain reads; only the mark that the
    call is still here (every few seconds) and the ending are written.

    -> ('ready', value) | ('open', row): the window ended or the runtime gave up on the call, and the row stays an ordinary hand-off | ('stopped', row): the task is over
    (a question is then withdrawn when `withdraw_on_stop`) | ('gone', row): the row ended some other way (it expired, or another turn took it)."""
    coordinator = Coordinator(store, clock=clock)
    read = lambda con: con.execute('SELECT * FROM handoffs WHERE account_id=? AND id=?', (account, handoff_id)).fetchone()
    marked = int(clock())
    while True:
        stopped = request_over(store, account, request_id)
        now = int(clock())
        with store.connect() as con:
            row = read(con)
            soon = ready(con, row, False) is not None
        ending = stopped or closed() or now >= int(json.loads(row['resume_json'] or '{}').get('until') or 0)
        if soon or row['state'] not in ('waiting', 'answered') or ending or now - marked >= SEEN_SECONDS // 4:
            with coordinator.transaction() as con:
                row = read(con)
                value = ready(con, row, True)
                if value is not None:
                    return 'ready', value
                if row['state'] not in ('waiting', 'answered'):
                    return 'gone', row
                current = json.loads(row['resume_json'] or '{}')
                plain = json.dumps({k: v for k, v in current.items() if k not in MARKS})          # what the row keeps once nobody waits in place
                if stopped:
                    con.execute("UPDATE handoffs SET resume_json=?,state=CASE WHEN ? AND state='waiting' THEN 'cancelled' ELSE state END WHERE account_id=? AND id=?",
                                (plain, 1 if withdraw_on_stop else 0, account, handoff_id))
                    return 'stopped', row
                if ending:
                    con.execute('UPDATE handoffs SET resume_json=? WHERE account_id=? AND id=?', (plain, account, handoff_id))
                    return 'open', row
                con.execute('UPDATE handoffs SET resume_json=? WHERE account_id=? AND id=?', (json.dumps({**current, 'seen': now}), account, handoff_id))      # still here
                marked = now
        sleep(poll)


# -- the outcome of a change the customer decided on ------------------------------------------------------------------------------------------------
FINAL = ('done', 'failed', 'declined', 'expired', 'undone', 'compensated')


def outcome_of(con, handoff, report_words=None):
    """-> (text for the assistant, line shown in the chat), or None while what it waited for is still being decided or carried out. One wording for both ways the work
    hears it: the same run (in place) and a new turn (action_runner)."""
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
    if report_words is None:
        from .workflows import WorkflowService
        report_words = WorkflowService.report_words
    words = report_words(json.loads(row['report_json'] or '{}'), row['state']) if row['report_json'] else 'It ended.'
    return (f'The workflow you prepared ("{row["title"]}") was approved and run by Lumina. {words}\nTell the customer exactly what happened, including anything that could not be reversed.',
            ('Done: ' if row['state'] == 'done' else 'Stopped and reversed: ' if row['state'] == 'reversed' else 'Stopped, partly reversed: ') + row['title'])


def hold_approval(store, *, clock=time.time, sleep=time.sleep, poll=1.0, allowed, account, request_id, closed, action_id=None, workflow_id=None):
    """A change was just prepared for the customer's approval: with the owner's switch on, wait in place for their decision and for Lumina to carry it out, and give the
    run its outcome. -> (text, None) with the outcome, (text, 'stopped') when the task ended meanwhile, or None when it does not wait (the caller says what it says today:
    end the turn; you will be given the outcome)."""
    now = int(clock())
    seconds = window(store, account, request_id, allowed, now)
    if not seconds or not request_id:
        return None
    column, ref = ('action_id', action_id) if action_id else ('workflow_id', workflow_id)
    with Coordinator(store, clock=clock).transaction() as con:
        row = con.execute(f"SELECT * FROM handoffs WHERE account_id=? AND {column}=? AND state='waiting' ORDER BY created_epoch DESC LIMIT 1", (account, ref)).fetchone()
        if row is None:
            return None
        con.execute('UPDATE handoffs SET resume_json=? WHERE account_id=? AND id=?', (json.dumps({**json.loads(row['resume_json'] or '{}'), **marks(seconds, now)}), account, row['id']))

    def ready(con, row, claim):
        if row['state'] != 'answered' or row['resumed_request_id']:
            return None
        said = outcome_of(con, row)
        if said is None or not claim:
            return None if said is None else said[0]
        taken = con.execute("UPDATE handoffs SET state='resumed',resumed_request_id=? WHERE account_id=? AND id=? AND state='answered' AND resumed_request_id IS NULL",
                            (request_id, account, row['id'])).rowcount           # this run has the outcome: the action runner starts no turn for it
        return said[0] if taken else None

    how, value = hold(store, clock=clock, sleep=sleep, poll=poll, account=account, request_id=request_id, handoff_id=row['id'], closed=closed, ready=ready, withdraw_on_stop=False)
    if how == 'ready':
        return value, None
    if how == 'stopped':
        return 'The task was stopped. The change you prepared is still waiting for the customer\'s decision; nothing was sent by this call.', 'stopped'
    if how == 'open' and value['state'] == 'answered':
        return 'The customer has decided and Lumina is carrying it out now. Tell them in one sentence, then END YOUR TURN: you will be given the outcome.', None
    return ('NOT DONE YET. The customer has not decided. It stays waiting for their approval of exactly this. Tell them in one sentence what you prepared, then END YOUR TURN. '
            'You will be given the outcome when they have decided. Do not prepare it again.'), None


def waiting(con, account, request_id, now):
    """What a call of this request's run is waiting for in place, or None: 'customer_question' (an answer), 'customer_approval' (a permission, then its outcome).
    The driver parks the run while one does."""
    from .handoff import in_place
    for row in con.execute("SELECT kind,resume_json FROM handoffs WHERE account_id=? AND request_id=? AND state IN ('waiting','answered')", (account, request_id)):
        if in_place(row, now):
            return 'customer_question' if row['kind'] == 'question' else 'customer_approval'
    if con.execute("SELECT 1 FROM mcp_calls WHERE account_id=? AND request_id=? AND state='pending' AND wait_until>? AND wait_seen>=?",
                   (account, request_id, int(now), int(now) - SEEN_SECONDS)).fetchone():
        return 'customer_approval'
    return None
