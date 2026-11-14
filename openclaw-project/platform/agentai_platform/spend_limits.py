"""Spending limits the customer sets for themselves (stdlib only, so the worker, the tool relay and the browse adapter can import it).

Lumina applies no spending limit of its own. An account may choose up to three in Settings > Usage: the most one task may cost, the most a day may cost and the
most a billing period may cost. Nothing chosen means no limit. The owner may store a default for every account under `ALL` (manage.py spend_limits); an account's
own row replaces that default entirely, so its own "no limit" is a real choice and not a gap the default fills.

Every task still gets a reservation row, because the rest of the platform looks for one. Its amount is the customer's own task limit, or `NO_LIMIT` when they
have none: a marker, never money. Nothing may charge it, hold it against an allowance or show it as a sum.
"""
from __future__ import annotations
import time

ALL = '*'                              # the all-accounts default; never an account id
NO_LIMIT = 1_000_000_000_000           # micro-dollars: the reservation amount of a task with no limit on it (a marker, never charged)
MAX_LIMIT = 100_000_000_000            # $100,000: the most a limit may be set to (anything above is a typing slip)
FIELDS = ('task', 'daily', 'period')
NONE = {'task': None, 'daily': None, 'period': None}


def _row(con, account_id):
    try:
        return con.execute('SELECT task_microusd,daily_microusd,period_microusd FROM spend_limits WHERE account_id=?', (account_id,)).fetchone()
    except Exception:
        return None                    # no table on this host yet (an older database): no limit, which is the default anyway


def get(con, account_id) -> dict:
    """-> {'task','daily','period'}: micro-dollars or None (no limit). The account's own row, else the all-accounts default, else nothing."""
    row = _row(con, account_id) if account_id != ALL else None
    if row is None:
        row = _row(con, ALL)
    if row is None:
        return dict(NONE)
    return {name: (int(value) if value else None) for name, value in zip(FIELDS, row)}


def own(con, account_id) -> dict | None:
    """What this account itself chose (None: it chose nothing and follows the default)."""
    row = _row(con, account_id)
    return None if row is None else {name: (int(value) if value else None) for name, value in zip(FIELDS, row)}


def clean(limits) -> dict:
    """Validate {'task','daily','period'} -> the same with ints or None. Raises ValueError."""
    if not isinstance(limits, dict) or set(limits) - set(FIELDS):
        raise ValueError('invalid spending limits')
    out = {}
    for name in FIELDS:
        value = limits.get(name)
        if value is None:
            out[name] = None
        elif type(value) is int and 0 < value <= MAX_LIMIT:
            out[name] = value
        else:
            raise ValueError('invalid spending limit')
    return out


def put(con, account_id, limits, now=None):
    """Store the account's choice. All three None is still a choice ("no limit for me, whatever the default says")."""
    limits = clean(limits)
    con.execute('INSERT OR REPLACE INTO spend_limits(account_id,task_microusd,daily_microusd,period_microusd,updated_epoch) VALUES (?,?,?,?,?)',
                (account_id, limits['task'], limits['daily'], limits['period'], int(now if now is not None else time.time())))
    return limits


def clear(con, account_id):
    """Forget the account's choice: it follows the default again."""
    con.execute('DELETE FROM spend_limits WHERE account_id=?', (account_id,))


def task_amount(con, account_id) -> int:
    """The reservation amount of a new task: the customer's task limit, or NO_LIMIT."""
    return get(con, account_id)['task'] or NO_LIMIT


def limited(amount) -> bool:
    """Is this reservation amount a real limit (not the no-limit marker)?"""
    return type(amount) is int and 0 < amount < NO_LIMIT
