"""The states of a customer request, and the one rule for "the run a tool may act for" (stdlib only).

`customer_requests.state` is written only by request_queue.py (the state machine lives there). Everything else READS it, and used to spell the lists out by hand
in a dozen places. They are named here so a reader in any module means the same thing.

    waiting ──claim──▶ starting ──▶ running ──finish──▶ completed | failed | cancelled
                           └────────────┴──lease lost──▶ uncertain ──reconcile──▶ (running | a final state)

    ACTIVE    not finished yet: what "busy" means for the customer (model settings are locked, restore refuses, the app polls faster)
    CLAIMED   a worker holds or held it: these may still have effects in flight
    LIVE      a run is in progress right now
    FINAL     over

Two flags refine `LIVE`: `closing` (the driver has begun settling) and `cancel_requested` (the customer pressed Stop). A run that is closing or being stopped must
not start new effects, so tools (browser, progress, location, own-model relay, steering) only ever act for a LIVE RUN: `live_run()` below.

Callers add what is specific to them on top of that one clause, and say so by name:
    funded           the task's reservation is still active (anything that costs money or needs the budget row)
    active_account   the account is not suspended
"""

WAITING, STARTING, RUNNING, UNCERTAIN = 'waiting', 'starting', 'running', 'uncertain'
COMPLETED, FAILED, CANCELLED = 'completed', 'failed', 'cancelled'

ACTIVE = (WAITING, STARTING, RUNNING, UNCERTAIN)
CLAIMED = (STARTING, RUNNING, UNCERTAIN)
LIVE = (STARTING, RUNNING)
FINAL = (COMPLETED, FAILED, CANCELLED)


def sql_list(states) -> str:
    """`('a','b')` for an SQL IN. Only ever called with the constants above (never with outside input)."""
    return '(' + ','.join(f"'{s}'" for s in states) + ')'


def live_run(alias='r') -> str:
    """SQL for "this request row is a run that may still start effects". `alias` is the customer_requests alias ('' for none)."""
    p = f'{alias}.' if alias else ''
    return f"{p}state IN {sql_list(LIVE)} AND {p}closing=0 AND {p}cancel_requested=0"


def run_ended(row) -> bool:
    """The same rule for a row already read (needs state, closing, cancel_requested). No row counts as ended."""
    return row is None or bool(row['cancel_requested']) or bool(row['closing']) or row['state'] not in LIVE


def live_runs(con, account_id, request_id=None, *, funded=False, active_account=False, limit=2) -> list[str]:
    """Ids of the account's live runs (optionally only `request_id`), newest first. Callers that need exactly one check `len(...) == 1`: an account
    has one run at a time today, and a tool must never guess between two."""
    joins, where = '', ''
    if active_account:
        joins += ' JOIN accounts a ON a.id=r.account_id'
        where += " AND a.status='active'"
    if funded:
        joins += ' JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id'
        where += " AND v.state='active'"
    rows = con.execute(f"""SELECT r.id FROM customer_requests r{joins}
        WHERE r.account_id=? AND {live_run()}{where} AND (? IS NULL OR r.id=?) ORDER BY r.sequence DESC LIMIT ?""",
                       (account_id, request_id, request_id, limit)).fetchall()
    return [row[0] for row in rows]


def is_live_run(con, account_id, request_id, *, funded=False, active_account=False) -> bool:
    return bool(live_runs(con, account_id, request_id, funded=funded, active_account=active_account, limit=1))
