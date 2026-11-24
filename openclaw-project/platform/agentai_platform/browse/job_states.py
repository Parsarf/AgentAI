"""The states of one browser job, and what is recorded about it (stdlib only).

The browse service decides a job's state; everything else reads it. The lists used to be written out in the service, the tool adapter, the web routes, the chat driver
and the web client, and they had drifted (the client did not know `asking`). They are named here once.

    queued ──▶ running ──▶ done | stopped | blocked | budget | error | cancelled | stuck | max_steps | deadline
                 │  ▲
                 ▼  │           paused    the customer has the wheel
               asking           a question is waiting for the customer
                 │
                 ▼
              handoff           the loop is over and the page is held open for the customer for a while

    interrupted                 the browse service restarted (or lost the job) while it was unfinished. Nothing is resumed: what was done is kept, and the customer is told.
                                This is NOT the same as waiting for the customer, which is intended and keeps the task.

    LIVE       the page is alive: worth showing live, and controls may be accepted
    WAITING    live, and it is the customer's move
    FINAL      the loop is over (handoff is both: over for the loop, still live for the customer)
    OVER       nothing is left running or held: the request may let go of its browser
"""

LIVE = ('queued', 'running', 'handoff', 'paused', 'asking')
WAITING = ('handoff', 'paused', 'asking')
INTERRUPTED = 'interrupted'
FINAL = ('done', 'handoff', 'stopped', 'blocked', 'budget', 'error', 'cancelled', 'stuck', 'max_steps', 'deadline', INTERRUPTED)
OVER = tuple(s for s in FINAL if s != 'handoff')
FAILED_ATTEMPT = ('error', 'failed', 'deadline')        # endings that count against retrying the same browser task (an interruption does not: it was not the task's fault)
# The reason a job carries when the request that handed a page to its assistant ended with its answer and no step was coming (service.agent_release). The job was no
# longer needed: that is not the browser failing, whatever state the loop ended in (`stopped` or `cancelled`).
RELEASED_REASON = 'the assistant went on without this page'
INTERRUPTED_REASON = ('The browser task was interrupted because the browser service restarted. What it had done up to then is kept, and it was not resumed. '
                      'Start it again if you still want it.')
SETTLE_SECONDS = 30                                     # a row this young may belong to a job that is still being started: never called interrupted


def sql_list(states) -> str:
    """`('a','b')` for an SQL IN. Only ever called with the constants above."""
    return '(' + ','.join(f"'{s}'" for s in states) + ')'


def record(con, account_id, request_id, polled, *, offset=0, spent_before=0, now=0):
    """Write what the service reported about a job into the request's browser record (browse_runs, browse_steps). Idempotent: steps are keyed by number.
    Called by whoever is looking: the tool call that follows the job, and the web app when a customer opens the task. `con` is inside a transaction.
    `spent_before=None` leaves the recorded cost as it is (the caller does not know what earlier sessions of the request spent)."""
    import json
    jev = polled.get('jev') or {}
    con.execute('''UPDATE browse_runs SET status=?,url=?,answer=?,reason=?,pending_json=?,jev_asked=?,jev_agree=?,estimated_cost_microusd=COALESCE(?,estimated_cost_microusd),updated_epoch=?,
        takeover_until=CASE WHEN ? THEN ? ELSE takeover_until END WHERE account_id=? AND request_id=?''',
                (polled['state'], polled.get('url'), polled.get('answer'), polled.get('reason'),
                 json.dumps(polled['pending_action']) if polled.get('pending_action') else None, jev.get('jev_calls', jev.get('jev_asked', 0)), jev.get('jev_acted', jev.get('jev_agree', 0)),
                 None if spent_before is None else int(spent_before) + int(polled.get('cost_microusd') or 0), now, 1 if polled.get('takeover') else 0, now + 600, account_id, request_id))
    for e in polled.get('events') or []:
        con.execute('INSERT OR IGNORE INTO browse_steps(account_id,request_id,n,kind,data_json,created_epoch) VALUES (?,?,?,?,?,?)',
                    (account_id, request_id, e['n'] + offset, e['kind'], json.dumps({k: v for k, v in e.items() if k not in ('n', 'kind')}), now))


ORPHAN_SECONDS = 900             # longer than any wait a job may still be in after its request ended (a hand-off window is ten minutes)
ORPHAN_REASON = 'The browser was stopped because the task had ended.'


def close_orphans(con, *, now, settle=ORPHAN_SECONDS) -> int:
    """End every browser record that is still marked alive although its request ended more than `settle` seconds ago. -> how many were ended.

    A record is the request's copy of what the browse service last said, written by whoever was looking. When the request ended and nobody looked again (a stop that did
    not reach the job's record, a worker that died between the two), the copy said `running` for ever: production held eight of these, the oldest three weeks old, and the
    live page of such a task showed a browser that was not there. The request is over, so no job can still be working for it: the record ends as `cancelled` with a reason
    that says why, and its history is untouched. Run by the request worker every few minutes; it is a safety net, not the way a job normally ends."""
    import json
    rows = con.execute(f"""SELECT b.account_id,b.request_id FROM browse_runs b JOIN customer_requests r ON r.account_id=b.account_id AND r.id=b.request_id
        WHERE b.status IN {sql_list(LIVE)} AND b.updated_epoch<=? AND r.state IN ('completed','failed','cancelled')""", (now - settle,)).fetchall()
    for account_id, request_id in rows:
        con.execute(f'UPDATE browse_runs SET status=?,reason=?,pending_json=NULL,updated_epoch=? WHERE account_id=? AND request_id=? AND status IN {sql_list(LIVE)}',
                    ('cancelled', ORPHAN_REASON, now, account_id, request_id))
        n = int(con.execute('SELECT COALESCE(MAX(n),0) FROM browse_steps WHERE account_id=? AND request_id=?', (account_id, request_id)).fetchone()[0]) + 1
        con.execute('INSERT OR IGNORE INTO browse_steps(account_id,request_id,n,kind,data_json,created_epoch) VALUES (?,?,?,?,?,?)',
                    (account_id, request_id, n, 'status', json.dumps({'state': 'cancelled', 'reason': ORPHAN_REASON}), now))
    return len(rows)


def mark_interrupted(con, account_id, request_id, *, now) -> bool:
    """The service no longer knows a job the record says is alive: it restarted. The record ends as `interrupted` with its history untouched. -> True when it was changed.
    Never touches a finished record, or one young enough to be a job that is still being started."""
    import json
    changed = con.execute(f"UPDATE browse_runs SET status=?,reason=?,updated_epoch=? WHERE account_id=? AND request_id=? AND status IN {sql_list(LIVE)} AND updated_epoch<=?",
                          (INTERRUPTED, INTERRUPTED_REASON, now, account_id, request_id, now - SETTLE_SECONDS)).rowcount
    if changed:
        n = int(con.execute('SELECT COALESCE(MAX(n),0) FROM browse_steps WHERE account_id=? AND request_id=?', (account_id, request_id)).fetchone()[0]) + 1
        con.execute('INSERT OR IGNORE INTO browse_steps(account_id,request_id,n,kind,data_json,created_epoch) VALUES (?,?,?,?,?,?)',
                    (account_id, request_id, n, 'status', json.dumps({'state': INTERRUPTED, 'reason': INTERRUPTED_REASON}), now))
    return bool(changed)
