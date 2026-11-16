"""What the customer has selected in the page the assistant panel sits beside (UI remodel, phase 2).

The web app's assistant panel is the same assistant on every page. A message sent from it carries what is selected (a mail thread, an event, a range of days, a file, a folder,
a task, or just which page is open) as ids. The page is not trusted: every id is checked here against the account's own rows, and only ids, a few fixed words and short names
read back from the account's own records pass. Mail and calendar selections are checked by the hub service (`hub.looking_at`), which also needs that feature to be on.
"""
from __future__ import annotations

from .security import Principal, require

PAGES = ('home', 'inbox', 'calendar', 'files', 'activity', 'settings')
HUB_KINDS = ('thread', 'event', 'days', 'mail')


def _text(raw: dict, key: str, most: int):
    value = raw.get(key)
    return value if isinstance(value, str) and 0 < len(value) <= most else None


def check(store, principal: Principal, raw, *, hub=None) -> dict | None:
    """-> the cleaned selection, or None when there is nothing the account really has. `hub` is the hub service when mail and calendars are on for this account."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get('kind')
    if kind in HUB_KINDS:
        return hub.looking_at(principal, raw) if hub is not None else None
    if kind == 'page':
        return {'kind': 'page', 'page': raw['page']} if raw.get('page') in PAGES else None
    if kind not in ('file', 'folder', 'task'):
        return None
    ident = _text(raw, 'id', 64)
    if not ident:
        return None
    with store.connect() as con:
        store._authorize(con, principal)
        if kind == 'task':
            row = con.execute('SELECT id,message,state FROM customer_requests WHERE account_id=? AND id=?', (principal.account_id, ident)).fetchone()
            return {'kind': 'task', 'id': row['id'], 'title': (row['message'] or '')[:200], 'state': row['state']} if row else None
        require(principal, 'file.read', con=con)
        if kind == 'folder':
            row = con.execute('SELECT id,name FROM file_folders WHERE account_id=? AND id=?', (principal.account_id, ident)).fetchone()
            return {'kind': 'folder', 'id': row['id'], 'name': row['name'][:120]} if row else None
        source = raw.get('source')
        if source == 'upload':
            row = con.execute('SELECT id,display_name,media_type FROM project_files WHERE account_id=? AND id=?', (principal.account_id, ident)).fetchone()
        elif source == 'made':
            row = con.execute('SELECT id,display_name,media_type FROM artifacts WHERE account_id=? AND id=? ORDER BY version DESC LIMIT 1', (principal.account_id, ident)).fetchone()
        else:
            return None
        if not row:
            return None
        placed = con.execute('SELECT name FROM file_places WHERE account_id=? AND kind=? AND object_id=?', (principal.account_id, source, ident)).fetchone()
        return {'kind': 'file', 'source': source, 'id': row['id'], 'name': ((placed['name'] if placed and placed['name'] else None) or row['display_name'] or '')[:160],
                'media_type': (row['media_type'] or '')[:100]}
