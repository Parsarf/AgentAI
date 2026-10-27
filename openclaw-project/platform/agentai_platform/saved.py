"""What a customer asked Lumina to remember for next time, by field (size -> M). Plain words only, scoped to the account; secrets never live here.

The browser run receives these as `prefs` and uses one without asking only when it matches an option the page offers. The customer can see and delete every one."""
from __future__ import annotations
import re
import time

MAX_SAVED = 100
FIELD = re.compile(r'^[a-z0-9 ]{1,30}$')


def clean_field(field):
    field = re.sub(r'[^a-z0-9 ]+', '', str(field or '').lower()).strip()
    return field if FIELD.fullmatch(field) else ''


def choices(con, account_id):
    return {r[0]: r[1] for r in con.execute('SELECT field,value FROM saved_choices WHERE account_id=? ORDER BY field', (account_id,)).fetchall()}


def remember(con, account_id, field, value, *, now=None):
    field, value = clean_field(field), str(value or '').strip()[:80]
    if not field or not value:
        raise ValueError('nothing to remember')
    if field not in choices(con, account_id) and len(choices(con, account_id)) >= MAX_SAVED:
        raise ValueError('saved list is full')
    now = int(now if now is not None else time.time())
    con.execute('''INSERT INTO saved_choices(account_id,field,value,created_epoch,updated_epoch) VALUES (?,?,?,?,?)
        ON CONFLICT(account_id,field) DO UPDATE SET value=excluded.value,updated_epoch=excluded.updated_epoch''', (account_id, field, value, now, now))
    return field


def forget(con, account_id, field):
    con.execute('DELETE FROM saved_choices WHERE account_id=? AND field=?', (account_id, clean_field(field)))
