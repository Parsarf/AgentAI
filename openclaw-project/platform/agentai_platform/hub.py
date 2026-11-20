"""The mail and calendar dashboard's reading side (roadmap #D3 unified inbox, #D4 unified calendar): one list of threads and one calendar across every account a person
connected, whatever the provider.

Everything is read from the provider-neutral tables that hub_sync.py keeps (headers, events). The one thing fetched from a provider here is a message's body, when the
customer opens it or the assistant reads it: it is then kept under the mail-body retention row and not fetched again.

Rules:
* every query is scoped by the account of the verified principal; a row of another account cannot be named, listed or learned of;
* only connections that are still there are shown: removing one deletes its rows (connectors.py), so there is nothing to filter out afterwards;
* a list always says how fresh each account is and whether an account needs its customer; one account's trouble never hides the others;
* nothing here changes anything at a provider. Opening a message does not mark it read there (Phase 6 adds managing);
* no provider is named in this module. What differs between providers is in their capabilities (hub_model.HubCaps), passed through as data.
"""
from __future__ import annotations
import base64
import json
import time

from . import hub_html
from .connector_kit import ConnectorFault
from .hub_model import COMMON_LABELS, hub_caps
from .security import NotFound, require

# A draft whose send has started and was not stopped or failed (#66): it is no longer a draft, and it is never sent twice.
SENDING = "(SELECT 1 FROM actions a WHERE a.account_id=hub_drafts.account_id AND a.id=hub_drafts.sent_action_id AND a.state NOT IN ('failed','declined','expired'))"


def datetime_day(epoch, zone) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(int(epoch), zone).strftime('%Y-%m-%d')


def datetime_local(epoch, zone) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(int(epoch), zone).strftime('%Y-%m-%dT%H:%M')

LIST_LABELS = COMMON_LABELS + ('all',)
HIDDEN_BY_DEFAULT = ('spam', 'trash')
MAX_LIMIT = 100
COLOURS = ('blue', 'green', 'amber', 'red', 'violet', 'teal', 'pink', 'grey')        # names of design tokens, never raw colours: the web app maps them


def _cursor(row) -> str:
    return base64.urlsafe_b64encode(json.dumps([row['last_epoch'], row['connection_id'], row['id']]).encode()).decode().rstrip('=')


def _uncursor(value):
    if not value:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(str(value) + '=' * (-len(str(value)) % 4)))
        if not (isinstance(data, list) and len(data) == 3 and type(data[0]) is int and all(isinstance(d, str) for d in data[1:])):
            raise ValueError
        return data
    except Exception:
        raise ValueError('invalid cursor') from None


def _fragment(key, value) -> str:
    """How `"key": "value"` looks inside the JSON these tables store: what a filter looks for with instr()."""
    return json.dumps({key: value})[1:-1]



def _scopes(raw) -> list:
    try:
        value = json.loads(raw or '[]')
    except ValueError:
        return []
    return [s for s in value if isinstance(s, str)] if isinstance(value, list) else []

class HubService:
    def __init__(self, store, connectors, client, sync, *, clock=time.time):
        self.store, self.connectors, self.client, self.sync, self.clock = store, connectors, client, sync, clock

    def _enter(self, con, principal, action='connection.read'):
        self.store._authorize(con, principal)
        require(principal, action, con=con)

    # -- accounts ---------------------------------------------------------------------------------------------------------------------------------------
    def accounts(self, principal) -> list[dict]:
        """Every connected mail or calendar account: who it is, whether it works, what it can do, and how fresh each part of it is."""
        with self.store.connect() as con:
            self._enter(con, principal)
            rows = con.execute("SELECT id,service,state,identity_label,needs_reason,granted_scopes FROM connector_connections WHERE account_id=? AND state!='revoked' ORDER BY created_epoch,rowid",
                               (principal.account_id,)).fetchall()
            sync = {}
            for r in con.execute('SELECT * FROM hub_sync WHERE account_id=?', (principal.account_id,)):
                sync.setdefault(r['connection_id'], []).append(r)
            out = []
            for row in rows:
                declaration = self.connectors.declared(row['service'])
                caps = hub_caps(declaration)
                if caps is None:
                    continue
                scope = self.connectors.scope(con, principal.account_id, row['id'])
                parts = sync.get(row['id'], [])

                def part(domain):
                    mine = [p for p in parts if p['domain'] == domain]
                    if not mine:
                        return None
                    last = [p['last_sync_epoch'] for p in mine if p['last_sync_epoch']]
                    errors = sorted({p['last_error'] for p in mine if p['last_error']})
                    return {'synced_epoch': min(last) if len(last) == len(mine) else None, 'filled': all(p['filled'] for p in mine), 'items': sum(p['item_count'] for p in mine),
                            'error': errors[0] if errors else None, 'paused': any(p['state'] == 'paused' for p in mine)}
                out.append({'id': row['id'], 'provider': row['service'], 'provider_label': declaration.label, 'identity': row['identity_label'],
                            'state': 'needs_you' if row['state'] != 'connected' else 'working', 'needs_reason': row['needs_reason'],
                            # What it can do NOW: a write control shows only where the provider can and this connection holds the permission; `missing` names the
                            # permission to ask for (roadmap Phase 6, re-consent), `grants` what each would allow, in words.
                            'capabilities': caps.effective(_scopes(row['granted_scopes'])), 'grants': caps.public()['grants'],
                            'granted': {'mail': any(s[0] in ('mailbox', 'label') for s in scope), 'calendar': any(s[0] == 'calendar' for s in scope)},
                            'mail': part('mail'), 'calendar': part('calendar')})
        return out

    def _connections(self, con, principal, wanted=None) -> list[str]:
        ids = [r['id'] for r in con.execute("SELECT id FROM connector_connections WHERE account_id=? AND state!='revoked' ORDER BY created_epoch,rowid", (principal.account_id,))]
        if wanted is None:
            return ids
        if not isinstance(wanted, (list, tuple)) or len(wanted) > 50 or any(not isinstance(w, str) for w in wanted):
            raise ValueError('invalid accounts')
        return [i for i in ids if i in set(wanted)]

    def refresh(self, principal, connection_id=None) -> dict:
        with self.store.connect() as con:
            self._enter(con, principal, 'connection.use')
            if connection_id is not None and connection_id not in self._connections(con, principal):
                raise NotFound('unavailable')
        self.sync.reconcile(principal.account_id)
        return {'requested': self.sync.request(principal.account_id, connection_id)}

    def pulse(self, principal) -> dict:
        """One cheap answer for an open page to ask every few seconds: `mark` changes whenever any connected account's mail or calendars changed, finished loading, or needs
        its customer. The page reloads what it shows only when the mark differs from the one it has."""
        with self.store.connect() as con:
            self._enter(con, principal)
            row = con.execute("""SELECT coalesce(max(last_change_epoch),0) AS changed,coalesce(sum(item_count),0) AS items,coalesce(sum(filled),0) AS filled,count(*) AS parts,
                coalesce(sum(state='paused'),0) AS paused FROM hub_sync WHERE account_id=?""", (principal.account_id,)).fetchone()
            accounts = con.execute("SELECT count(*) AS n,coalesce(sum(state!='connected'),0) AS needing FROM connector_connections WHERE account_id=? AND state!='revoked'",
                                   (principal.account_id,)).fetchone()
            drafts = con.execute("SELECT count(*) AS n,coalesce(max(updated_epoch),0) AS changed FROM hub_drafts WHERE account_id=? AND state='draft'", (principal.account_id,)).fetchone()
        loading = row['parts'] - row['filled']
        return {'mark': f"{row['changed']}.{row['items']}.{row['filled']}.{row['parts']}.{row['paused']}.{accounts['n']}.{accounts['needing']}.{drafts['n']}.{drafts['changed']}",
                'loading': loading > 0, 'items': row['items']}

    # -- what the customer has open, for a message sent from the dashboard ---------------------------------------------------------------------------
    def looking_at(self, principal, raw) -> dict | None:
        """Check what the page says the customer has open, and reduce it to ids this account really has. Anything else is dropped: the page is not trusted to name a thread or
        an event, and nothing but ids, a mailbox word, two days and a short search text passes. -> the cleaned selection, or None."""
        if not isinstance(raw, dict):
            return None
        kind, text = raw.get('kind'), lambda key, most: raw[key] if isinstance(raw.get(key), str) and 0 < len(raw[key]) <= most else None
        with self.store.connect() as con:
            self._enter(con, principal)
            ids = self._connections(con, principal)
            if kind == 'thread' and text('connection', 64) in ids and text('thread', 300) and con.execute(
                    'SELECT 1 FROM hub_threads WHERE account_id=? AND connection_id=? AND id=?', (principal.account_id, raw['connection'], raw['thread'])).fetchone():
                return {'kind': 'thread', 'connection': raw['connection'], 'thread': raw['thread']}
            if kind == 'event' and text('connection', 64) in ids and text('calendar', 300) and text('event', 400) and con.execute(
                    'SELECT 1 FROM hub_events WHERE account_id=? AND connection_id=? AND calendar_id=? AND id=?',
                    (principal.account_id, raw['connection'], raw['calendar'], raw['event'])).fetchone():
                return {'kind': 'event', 'connection': raw['connection'], 'calendar': raw['calendar'], 'event': raw['event']}
        day = lambda key: text(key, 10) if text(key, 10) and len(raw[key]) == 10 and raw[key][4] == raw[key][7] == '-' and raw[key].replace('-', '').isdigit() else None
        if kind == 'days' and day('start') and day('end') and raw['start'] <= raw['end']:
            return {'kind': 'days', 'start': raw['start'], 'end': raw['end']}
        if kind == 'mail':
            return {'kind': 'mail', **({'label': raw['label']} if raw.get('label') in LIST_LABELS else {}), **({'query': raw['query']} if text('query', 200) else {})}
        return None

    # -- settings ---------------------------------------------------------------------------------------------------------------------------------------
    def settings(self, principal) -> dict:
        with self.store.connect() as con:
            self._enter(con, principal)
            row = con.execute('SELECT timezone,image_senders_json FROM hub_settings WHERE account_id=?', (principal.account_id,)).fetchone()
            from . import mail_limits
            mail = {**mail_limits.mail_settings(con, principal.account_id), 'allowed': mail_limits.limits(con, principal.account_id), 'platform': dict(mail_limits.PLATFORM)}
        return {'timezone': row['timezone'] if row else None, 'image_senders': json.loads(row['image_senders_json']) if row else [], 'mail': mail}

    def set_mail_settings(self, principal, change: dict) -> dict:
        """The customer's own mail settings (#D6, #66): Undo send's wait (0 to 30 seconds), marking read on open, and their own sending limits (only lower)."""
        from . import mail_limits
        from .lifecycle.coordinator import Coordinator
        if not isinstance(change, dict) or set(change) - {'undo_send_seconds', 'mark_read_on_open', 'limits'}:
            raise ValueError('invalid settings')
        if 'undo_send_seconds' in change and (type(change['undo_send_seconds']) is not int or not 0 <= change['undo_send_seconds'] <= 30):
            raise ValueError('Undo send waits 0 to 30 seconds')
        if 'mark_read_on_open' in change and not isinstance(change['mark_read_on_open'], bool):
            raise ValueError('invalid settings')
        limits = mail_limits.clean(change['limits']) if 'limits' in change and change['limits'] is not None else None
        now = int(self.clock())
        with Coordinator(self.store).transaction() as con:
            self._enter(con, principal, 'connection.use')
            con.execute('INSERT INTO hub_settings(account_id,updated_epoch) VALUES (?,?) ON CONFLICT(account_id) DO NOTHING', (principal.account_id, now))
            own = json.loads(con.execute('SELECT mail_json FROM hub_settings WHERE account_id=?', (principal.account_id,)).fetchone()[0] or '{}')
            own.update({k: change[k] for k in ('undo_send_seconds', 'mark_read_on_open') if k in change})
            if 'limits' in change:
                own['limits'] = limits or {}
            con.execute('UPDATE hub_settings SET mail_json=?,updated_epoch=? WHERE account_id=?', (json.dumps(own), now, principal.account_id))
        return self.settings(principal)

    def set_settings(self, principal, *, timezone=..., allow_images_from=None, block_images_from=None) -> dict:
        if timezone is not ... and timezone is not None:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(str(timezone))
            except Exception:
                raise ValueError('unknown timezone') from None
        for address in (allow_images_from, block_images_from):
            if address is not None and (not isinstance(address, str) or not 3 <= len(address) <= 320 or '@' not in address):
                raise ValueError('invalid address')
        now = int(self.clock())
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store).transaction() as con:
            self._enter(con, principal, 'connection.use')
            con.execute('INSERT INTO hub_settings(account_id,updated_epoch) VALUES (?,?) ON CONFLICT(account_id) DO NOTHING', (principal.account_id, now))
            row = con.execute('SELECT timezone,image_senders_json FROM hub_settings WHERE account_id=?', (principal.account_id,)).fetchone()
            senders = set(json.loads(row['image_senders_json']))
            if allow_images_from:
                senders.add(allow_images_from.lower())
            if block_images_from:
                senders.discard(block_images_from.lower())
            con.execute('UPDATE hub_settings SET timezone=?,image_senders_json=?,updated_epoch=? WHERE account_id=?',
                        (row['timezone'] if timezone is ... else (str(timezone) if timezone else None), json.dumps(sorted(senders)[:500]), now, principal.account_id))
        return self.settings(principal)

    # -- mail: the list ---------------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _thread(row) -> dict:
        return {'connection_id': row['connection_id'], 'id': row['id'], 'subject': row['subject'], 'snippet': row['snippet'], 'people': json.loads(row['people_json']),
                'last_epoch': row['last_epoch'], 'message_count': row['message_count'], 'unread': bool(row['unread']), 'starred': bool(row['starred']),
                'has_attachments': bool(row['has_attachments']), 'labels': json.loads(row['labels_json']), 'provider_labels': json.loads(row['provider_labels_json'])}

    def threads(self, principal, *, connections=None, label='inbox', provider_label=None, unread=None, starred=None, attachments=None, person=None, after=None, before=None,
                query=None, cursor=None, limit=50) -> dict:
        """One page of threads across the chosen accounts, newest first. -> {'threads', 'next' (a cursor, or None at the end), 'complete'}.

        `label` is one of the common set, or 'all' (everything but spam and trash). `provider_label` narrows to one of the provider's own labels or folders by its id.
        `query` is searched in subjects, people, previews and the text of messages that were opened: the synced window only (older mail is `search_older`)."""
        if label not in LIST_LABELS:
            raise ValueError('unknown label')
        limit = max(1, min(int(limit or 50), MAX_LIMIT))
        where, args = ['account_id=?'], [principal.account_id]
        position = _uncursor(cursor)
        with self.store.connect() as con:
            self._enter(con, principal)
            ids = self._connections(con, principal, connections)
            if not ids:
                return {'threads': [], 'next': None, 'complete': True}
            where.append(f'connection_id IN ({",".join("?" * len(ids))})'); args += ids
            if label == 'all':
                for hidden in HIDDEN_BY_DEFAULT:
                    where.append('instr(labels_json,?)=0'); args.append(json.dumps(hidden))
            elif label == 'unread':
                where.append('unread=1')
            elif label == 'starred':
                where.append('starred=1')
            else:
                where.append('instr(labels_json,?)>0'); args.append(json.dumps(label))
            if provider_label is not None:
                where.append('instr(provider_labels_json,?)>0'); args.append(_fragment('id', str(provider_label)[:300]))
            for column, value in (('unread', unread), ('starred', starred), ('has_attachments', attachments)):
                if value is not None:
                    where.append(f'{column}=?'); args.append(1 if value else 0)
            if person:
                where.append('instr(people_text,?)>0'); args.append(str(person).lower()[:320])
            if after is not None:
                where.append('last_epoch>=?'); args.append(int(after))
            if before is not None:
                where.append('last_epoch<?'); args.append(int(before))
            for word in [w for w in str(query or '').lower().split() if w][:8]:
                where.append('''(instr(lower(subject),?)>0 OR instr(people_text,?)>0 OR instr(lower(snippet),?)>0 OR EXISTS (SELECT 1 FROM hub_messages m
                    WHERE m.account_id=hub_threads.account_id AND m.connection_id=hub_threads.connection_id AND m.thread_id=hub_threads.id AND m.body_text IS NOT NULL
                    AND instr(lower(m.body_text),?)>0))''')
                args += [word[:100]] * 4
            if position:
                where.append('(last_epoch<? OR (last_epoch=? AND (connection_id>? OR (connection_id=? AND id>?))))')
                args += [position[0], position[0], position[1], position[1], position[2]]
            rows = con.execute(f'SELECT * FROM hub_threads WHERE {" AND ".join(where)} ORDER BY last_epoch DESC,connection_id,id LIMIT ?', (*args, limit + 1)).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        return {'threads': [self._thread(r) for r in rows], 'next': _cursor(rows[-1]) if more else None, 'complete': not more}

    def labels(self, principal, connections=None) -> list[dict]:
        """The providers' own labels or folders that appear in the synced mail, per account: the filter list on the left of the inbox."""
        with self.store.connect() as con:
            self._enter(con, principal)
            ids = self._connections(con, principal, connections)
            out = []
            for connection in ids:
                seen = {}
                for r in con.execute('SELECT provider_labels_json FROM hub_threads WHERE account_id=? AND connection_id=?', (principal.account_id, connection)):
                    for p in json.loads(r['provider_labels_json']):
                        seen.setdefault(p['id'], {'id': p['id'], 'name': p['name'], 'threads': 0})['threads'] += 1
                out.append({'connection_id': connection, 'labels': sorted(seen.values(), key=lambda p: p['name'].lower())[:300]})
        return out

    def counts(self, principal, connections=None) -> dict:
        """Unread threads in the inbox, in all and per account: the badges."""
        with self.store.connect() as con:
            self._enter(con, principal)
            ids = self._connections(con, principal, connections)
            per = {i: 0 for i in ids}
            if ids:
                for r in con.execute(f'''SELECT connection_id,count(*) AS n FROM hub_threads WHERE account_id=? AND connection_id IN ({",".join("?" * len(ids))})
                    AND unread=1 AND instr(labels_json,?)>0 GROUP BY connection_id''', (principal.account_id, *ids, json.dumps('inbox'))):
                    per[r['connection_id']] = r['n']
        return {'unread': sum(per.values()), 'by_account': per}

    # -- mail: a thread and a message -------------------------------------------------------------------------------------------------------------------
    def _message(self, row, *, images, settings) -> dict:
        sender = json.loads(row['sender_json'])
        out = {'id': row['id'], 'thread_id': row['thread_id'], 'subject': row['subject'], 'snippet': row['snippet'], 'sender': sender, 'to': json.loads(row['to_json']),
               'cc': json.loads(row['cc_json']), 'sent_epoch': row['sent_epoch'], 'labels': json.loads(row['labels_json']), 'provider_labels': json.loads(row['provider_labels_json']),
               'unread': bool(row['unread']), 'starred': bool(row['starred']), 'has_attachments': bool(row['has_attachments']), 'body': None}
        if row['body_fetched_epoch'] is not None:
            allowed = images or sender.get('address') in settings['image_senders']
            shown = hub_html.sanitize(row['body_html'], images=allowed) if row['body_html'] else {'html': hub_html.from_text(row['body_text']), 'blocked_images': 0}
            out['body'] = {'html': shown['html'], 'text': row['body_text'] or '', 'blocked_images': shown['blocked_images'], 'images_shown': bool(allowed),
                           'attachments': json.loads(row['attachments_json'] or '[]'), 'fetched_epoch': row['body_fetched_epoch']}
        return out

    def thread(self, principal, connection_id, thread_id, *, open_last=True, images=False) -> dict:
        """A thread with its messages, oldest first. The last message's body is fetched if it was not yet (`open_last`); the others carry a body only if they were opened
        before, and are opened one at a time with `message`. -> {'thread', 'messages', 'problem'}: `problem` is a fault kind when the body could not be fetched."""
        with self.store.connect() as con:
            self._enter(con, principal)
            head = con.execute('SELECT * FROM hub_threads WHERE account_id=? AND connection_id=? AND id=?', (principal.account_id, str(connection_id), str(thread_id))).fetchone()
            if head is None or connection_id not in self._connections(con, principal):
                raise NotFound('unavailable')
            last = con.execute('SELECT id,body_fetched_epoch FROM hub_messages WHERE account_id=? AND connection_id=? AND thread_id=? ORDER BY sent_epoch DESC,id DESC LIMIT 1',
                               (principal.account_id, connection_id, thread_id)).fetchone()
        problem = None
        if open_last and last is not None:
            problem = self._open_body(principal, connection_id, last['id'])
        settings = self.settings(principal)
        with self.store.connect() as con:
            rows = con.execute('SELECT * FROM hub_messages WHERE account_id=? AND connection_id=? AND thread_id=? ORDER BY sent_epoch,id', (principal.account_id, connection_id, thread_id)).fetchall()
        return {'thread': self._thread(head), 'messages': [self._message(r, images=images, settings=settings) for r in rows], 'problem': problem}

    def message(self, principal, connection_id, message_id, *, images=False) -> dict:
        """One message with its body, fetched now if it was not yet."""
        with self.store.connect() as con:
            self._enter(con, principal)
            if connection_id not in self._connections(con, principal) or con.execute('SELECT 1 FROM hub_messages WHERE account_id=? AND connection_id=? AND id=?',
                                                                                    (principal.account_id, str(connection_id), str(message_id))).fetchone() is None:
                raise NotFound('unavailable')
        problem = self._open_body(principal, connection_id, message_id)
        settings = self.settings(principal)
        with self.store.connect() as con:
            row = con.execute('SELECT * FROM hub_messages WHERE account_id=? AND connection_id=? AND id=?', (principal.account_id, connection_id, message_id)).fetchone()
        if row is None:
            raise NotFound('unavailable')
        return {'message': self._message(row, images=images, settings=settings), 'problem': problem}

    def _open_body(self, principal, connection_id, message_id) -> str | None:
        """Make sure a message's body is here, and note that it was opened (its retention runs from the last time). -> None, or the fault kind when it could not be fetched
        (the headers are still shown, with a plain sentence)."""
        now = int(self.clock())
        with self.store.connect() as con:
            row = con.execute('SELECT body_fetched_epoch FROM hub_messages WHERE account_id=? AND connection_id=? AND id=?', (principal.account_id, connection_id, message_id)).fetchone()
            if row is None:
                return 'not_found'
            if row['body_fetched_epoch'] is not None:
                con.execute('UPDATE hub_messages SET body_opened_epoch=? WHERE account_id=? AND connection_id=? AND id=?', (now, principal.account_id, connection_id, message_id))
                return None
        try:
            _row, declaration, adapter, credential = self.client.open(principal, connection_id, 'connection.read')
            found = self.client.call(principal.account_id, declaration, lambda: adapter.mail_body(credential, message_id), where=(connection_id, 'mailbox', '*'))
        except ConnectorFault as fault:
            return fault.kind
        with self.store.connect() as con:
            con.execute('''UPDATE hub_messages SET body_text=?,body_html=?,attachments_json=?,body_fetched_epoch=?,body_opened_epoch=?,has_attachments=CASE WHEN ? THEN 1 ELSE has_attachments END
                WHERE account_id=? AND connection_id=? AND id=?''', (found['text'], found['html'] or None, json.dumps(found['attachments']), now, now, int(bool(found['attachments'])),
                                                                 principal.account_id, connection_id, message_id))
        return None

    def search_older(self, principal, connection_id, query, *, continuation=None) -> dict:
        """Mail older than the synced window, searched live at the provider. Nothing found here is stored; opening a result fetches it like any message. The result always
        says whether it is complete."""
        from .connector_kit import paginate
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError('invalid query')
        try:
            row, declaration, adapter, credential = self.client.open(principal, connection_id, 'connection.read')
        except ConnectorFault as fault:
            if fault.kind == 'not_found':
                raise NotFound('unavailable') from None
            return {'messages': [], 'problem': fault.kind, 'page': None}
        caps = hub_caps(declaration)
        if caps is None or not caps.mail_search:
            return {'messages': [], 'problem': 'unsupported', 'page': None}
        labels = self.sync._labels(principal.account_id, connection_id)
        with self.store.connect() as con:
            if not any(s[0] in ('mailbox', 'label') for s in self.connectors.scope(con, principal.account_id, connection_id)):
                return {'messages': [], 'problem': None, 'page': {'count': 0, 'complete': True, 'total_estimate': 0, 'continuation': None, 'stopped_by': None}}
        try:
            result = paginate(lambda position, limit: self.client.call(principal.account_id, declaration, lambda: adapter.mail_search(credential, query.strip(), labels, position, limit)),
                              style=declaration.paging, caps=declaration.caps, continuation=continuation)
        except ConnectorFault as fault:
            return {'messages': [], 'problem': fault.kind, 'page': None}
        found = [m for m in result.items if labels is None or any(p['id'] in labels for p in m['provider_labels'])]       # narrowed before it left; checked again on the way back
        result.count = len(found)
        return {'messages': [{**m, 'connection_id': connection_id} for m in found], 'problem': None, 'page': result.public()}

    # -- calendars --------------------------------------------------------------------------------------------------------------------------------------
    def calendars(self, principal) -> list[dict]:
        with self.store.connect() as con:
            self._enter(con, principal)
            rows = con.execute('''SELECT c.*,s.last_sync_epoch,s.last_error,s.state AS sync_state,s.filled FROM hub_calendars c LEFT JOIN hub_sync s ON s.account_id=c.account_id
                AND s.connection_id=c.connection_id AND s.domain='calendar' AND s.resource_id=c.id WHERE c.account_id=? ORDER BY c.connection_id,c.is_primary DESC,lower(c.name)''',
                               (principal.account_id,)).fetchall()
            ids = self._connections(con, principal)
        out = []
        for n, r in enumerate(sorted((r for r in rows if r['connection_id'] in ids), key=lambda r: ids.index(r['connection_id']))):       # accounts in the order they were connected
            out.append({'connection_id': r['connection_id'], 'id': r['id'], 'name': r['name'], 'colour': r['colour'] or COLOURS[n % len(COLOURS)], 'timezone': r['timezone'],
                        'access': r['access'], 'primary': bool(r['is_primary']), 'selected': bool(r['selected']), 'synced_epoch': r['last_sync_epoch'],
                        'filled': bool(r['filled']), 'error': r['last_error'], 'paused': r['sync_state'] == 'paused'})
        return out

    def set_calendar(self, principal, connection_id, calendar_id, *, selected=None, colour=None) -> list[dict]:
        """The customer's own choices for one calendar in the dashboard: shown or hidden, and its colour (the name of a design token)."""
        if colour is not None and colour not in COLOURS:
            raise ValueError('unknown colour')
        with self.store.connect() as con:
            self._enter(con, principal, 'connection.use')
            if selected is not None:
                done = con.execute('UPDATE hub_calendars SET selected=? WHERE account_id=? AND connection_id=? AND id=?', (1 if selected else 0, principal.account_id, str(connection_id), str(calendar_id))).rowcount
            if colour is not None:
                done = con.execute('UPDATE hub_calendars SET colour=? WHERE account_id=? AND connection_id=? AND id=?', (colour, principal.account_id, str(connection_id), str(calendar_id))).rowcount
            if (selected is not None or colour is not None) and not done:
                raise NotFound('unavailable')
        return self.calendars(principal)

    @staticmethod
    def _event(row, colour) -> dict:
        busy = row['visibility'] == 'busy'
        return {'connection_id': row['connection_id'], 'calendar_id': row['calendar_id'], 'id': row['id'], 'series_id': row['series_id'], 'title': '' if busy else row['title'],
                'busy_only': busy, 'start_epoch': row['start_epoch'], 'end_epoch': row['end_epoch'], 'all_day': bool(row['all_day']), 'start_date': row['start_date'],
                'end_date': row['end_date'], 'timezone': row['timezone'], 'place': '' if busy else row['place'], 'conference_url': None if busy else row['conference_url'],
                'my_response': row['my_response'], 'exception': bool(row['is_exception']), 'cancelled': bool(row['cancelled']), 'visibility': row['visibility'], 'colour': colour}

    def events(self, principal, start_epoch, end_epoch, *, connections=None, only_selected=True, cancelled=False, limit=2000) -> dict:
        """Every event that touches [start, end) on the chosen accounts' calendars, in order. -> {'events', 'complete'}."""
        start_epoch, end_epoch = int(start_epoch), int(end_epoch)
        if end_epoch <= start_epoch or end_epoch - start_epoch > 400 * 86400:
            raise ValueError('invalid range')
        calendars = [c for c in self.calendars(principal) if (c['selected'] or not only_selected)]
        with self.store.connect() as con:
            ids = set(self._connections(con, principal, connections))
            colours = {(c['connection_id'], c['id']): c['colour'] for c in calendars if c['connection_id'] in ids}
            rows = con.execute('SELECT * FROM hub_events WHERE account_id=? AND start_epoch<? AND end_epoch>? ' + ('' if cancelled else 'AND cancelled=0 ')
                               + 'ORDER BY start_epoch,end_epoch,connection_id,calendar_id,id LIMIT ?', (principal.account_id, end_epoch, start_epoch, limit + 1)).fetchall()
        found = [self._event(r, colours[(r['connection_id'], r['calendar_id'])]) for r in rows if (r['connection_id'], r['calendar_id']) in colours]
        return {'events': found[:limit], 'complete': len(rows) <= limit}

    def event(self, principal, connection_id, calendar_id, event_id) -> dict:
        """One event with everything the inspector shows. An event the connection may only see as busy shows nothing else."""
        with self.store.connect() as con:
            self._enter(con, principal)
            row = con.execute('SELECT * FROM hub_events WHERE account_id=? AND connection_id=? AND calendar_id=? AND id=?',
                              (principal.account_id, str(connection_id), str(calendar_id), str(event_id))).fetchone()
            if row is None or connection_id not in self._connections(con, principal):
                raise NotFound('unavailable')
            sync = con.execute("SELECT last_sync_epoch FROM hub_sync WHERE account_id=? AND connection_id=? AND domain='calendar' AND resource_id=?",
                               (principal.account_id, connection_id, calendar_id)).fetchone()
        colour = next((c['colour'] for c in self.calendars(principal) if c['connection_id'] == connection_id and c['id'] == calendar_id), COLOURS[0])
        out = self._event(row, colour)
        if not out['busy_only']:
            out.update({'description': row['description'], 'organizer': json.loads(row['organizer_json']) if row['organizer_json'] else None,
                        'attendees': json.loads(row['attendees_json']), 'provider_url': row['provider_url'], 'version': row['version']})
        out['synced_epoch'] = sync['last_sync_epoch'] if sync else None
        return out

    # -- availability and conflicts (roadmap Phase 6, #59 and #60) --------------------------------------------------------------------------------
    def availability(self, principal) -> dict:
        """The customer's availability settings (working hours per weekday, notice, buffer, which calendars count, whether tentative and all-day events count)."""
        from .hub_availability import clean_settings
        with self.store.connect() as con:
            self._enter(con, principal)
            row = con.execute('SELECT availability_json FROM hub_settings WHERE account_id=?', (principal.account_id,)).fetchone()
        try:
            return clean_settings(json.loads(row['availability_json']) if row else {})
        except ValueError:
            return clean_settings({})

    def set_availability(self, principal, raw) -> dict:
        from .hub_availability import clean_settings
        from .lifecycle.coordinator import Coordinator
        settings = clean_settings(raw)
        with Coordinator(self.store).transaction() as con:
            self._enter(con, principal, 'connection.use')
            con.execute('INSERT INTO hub_settings(account_id,updated_epoch) VALUES (?,?) ON CONFLICT(account_id) DO NOTHING', (principal.account_id, int(self.clock())))
            con.execute('UPDATE hub_settings SET availability_json=?,updated_epoch=? WHERE account_id=?', (json.dumps(settings), int(self.clock()), principal.account_id))
        return settings

    def _counted(self, principal, settings) -> list:
        """The calendars whose events make the customer busy: those chosen in the settings, else every calendar shown."""
        calendars = self.calendars(principal)
        if settings['busy_calendars'] is not None:
            chosen = {tuple(p) for p in settings['busy_calendars']}
            return [c for c in calendars if (c['connection_id'], c['id']) in chosen]
        return [c for c in calendars if c['selected']]

    def free(self, principal, start_epoch, end_epoch, zone, *, minutes=30) -> dict:
        """Free time between start and end across every calendar that counts: the provider's live free/busy where it has one, the synced copy where it does not or could
        not answer (and that is said), all-day events as busy when the settings say so. -> {'free', 'busy', 'settings', 'sources'}."""
        from collections import defaultdict
        from .connector_kit import Unanswered
        from .hub_availability import all_day_busy, free_intervals, merge
        start_epoch, end_epoch = int(start_epoch), int(end_epoch)
        if end_epoch <= start_epoch or end_epoch - start_epoch > 62 * 86400 or not 5 <= int(minutes) <= 24 * 60:
            raise ValueError('invalid range')
        settings = self.availability(principal)
        counted = self._counted(principal, settings)
        by_connection = defaultdict(list)
        for c in counted:
            by_connection[c['connection_id']].append(c['id'])
        events = [e for e in self.events(principal, start_epoch - 86400, end_epoch + 86400, only_selected=False)['events']
                  if (e['connection_id'], e['calendar_id']) in {(c['connection_id'], c['id']) for c in counted}]
        busy, sources = [], []
        for connection, ids in by_connection.items():
            live = None
            try:
                row, declaration, adapter, credential = self.client.open(principal, connection, 'connection.read')
                caps = hub_caps(declaration)
                if caps is not None and caps.free_busy and hasattr(adapter, 'free_busy'):
                    live = self.client.call(principal.account_id, declaration, lambda: adapter.free_busy(credential, ids, start_epoch, end_epoch))
            except (ConnectorFault, Unanswered):
                live = None
            for cid in ids:
                spans = (live or {}).get(cid)
                if spans is None:
                    spans = [(e['start_epoch'], e['end_epoch']) for e in events if e['connection_id'] == connection and e['calendar_id'] == cid and not e['all_day']
                             and e.get('my_response') != 'declined' and (settings['tentative_busy'] or e.get('my_response') != 'tentative')]
                    sources.append({'account': connection, 'calendar': cid, 'live': False})
                else:
                    sources.append({'account': connection, 'calendar': cid, 'live': True})
                busy += spans
        if settings['all_day_busy']:
            busy += all_day_busy(events, zone)
        busy = merge(busy)
        free = free_intervals(start_epoch, end_epoch, busy, settings, zone, now=int(self.clock()), minutes=int(minutes))
        return {'free': free, 'busy': busy, 'settings': settings, 'sources': sources}

    # -- mail changes from the dashboard and the assistant (#66, #67, #D6) ----------------------------------------------------------------------------------------
    ORGANIZE = {'archive': ('mail.organize', [], ['inbox']), 'inbox': ('mail.organize', ['inbox'], []), 'star': ('mail.organize', ['starred'], []),
                'unstar': ('mail.organize', [], ['starred']), 'read': ('mail.mark', [], ['unread']), 'unread': ('mail.mark', ['unread'], [])}

    def send_payload(self, principal, draft_id) -> tuple:
        """The send of one draft (#66): from the account the draft belongs to, to exactly its people, and what the customer should know before it goes (people never written
        to, a large audience, people outside their organization). -> (connection id, payload). Raises NotFound, or ValueError with a sentence."""
        from . import mail_limits
        with self.store.connect() as con:
            self._enter(con, principal, 'connection.use')
            draft = con.execute(f"SELECT * FROM hub_drafts WHERE account_id=? AND id=? AND state='draft' AND NOT EXISTS {SENDING}", (principal.account_id, str(draft_id))).fetchone()
            if draft is None:
                raise NotFound()
            conn = con.execute("SELECT identity_label FROM connector_connections WHERE account_id=? AND id=? AND state='connected'", (principal.account_id, draft['connection_id'])).fetchone()
            if conn is None or not conn['identity_label']:
                raise NotFound()
            to, cc = json.loads(draft['to_json']), json.loads(draft['cc_json'])
            people = [a.strip().lower() for a in to + cc]
            reason = mail_limits.refusal(con, principal.account_id, len(people), including_this=False, clock=self.clock)
            if reason:
                raise ValueError(reason)
            payload = {'draft': draft['id'], 'from': conn['identity_label'], 'to': to, 'cc': cc, 'subject': draft['subject'], 'body': draft['body']}
            notes = []
            if draft['thread_id']:
                last = con.execute('SELECT id FROM hub_messages WHERE account_id=? AND connection_id=? AND thread_id=? ORDER BY sent_epoch DESC LIMIT 1',
                                   (principal.account_id, draft['connection_id'], draft['thread_id'])).fetchone()
                payload['thread'] = draft['thread_id']
                if last:
                    payload['reply_to'] = last['id']
            new = [a for a in people if not con.execute("""SELECT 1 FROM hub_messages WHERE account_id=? AND connection_id=? AND labels_json LIKE '%"sent"%' AND people_text LIKE ? LIMIT 1""",
                                                        (principal.account_id, draft['connection_id'], '%' + a + '%')).fetchone()]
        if new:
            notes.append(f'You have not written to {", ".join(new[:5])}{" and others" if len(new) > 5 else ""} before (in the mail Lumina can see).')
        if len(people) >= 10:
            notes.append(f'This goes to {len(people)} people.')
        own = conn['identity_label'].rsplit('@', 1)[-1].lower()
        outside = [a for a in people if own not in mail_limits.PUBLIC_MAIL_DOMAINS and a.rsplit('@', 1)[-1] != own]
        if outside:
            notes.append(f'{", ".join(outside[:5])}{" and others" if len(outside) > 5 else ""} {"is" if len(outside) == 1 else "are"} outside your organization.')
        if notes:
            payload['notes'] = notes
        return draft['connection_id'], payload

    def mark_sending(self, principal, draft_id, action_id):
        """The draft is being sent by this change: it stops being listed as a draft (and comes back if the send is stopped or fails)."""
        with self.store.connect() as con:
            con.execute('UPDATE hub_drafts SET sent_action_id=?,updated_epoch=? WHERE account_id=? AND id=?', (str(action_id), int(self.clock()), principal.account_id, str(draft_id)))

    def organize_payload(self, principal, connection_id, threads, op, *, label=None) -> tuple:
        """An organizing change on conversations of the customer's copy (only what they let Lumina read can be touched). -> (kind, payload)."""
        threads = [str(t) for t in threads or []]
        if not 1 <= len(threads) <= 100 or len(set(threads)) != len(threads):
            raise ValueError('choose 1 to 100 conversations')
        with self.store.connect() as con:
            self._enter(con, principal, 'connection.use')
            marks = ','.join('?' for _ in threads)
            found = {r[0] for r in con.execute(f'SELECT id FROM hub_threads WHERE account_id=? AND connection_id=? AND id IN ({marks})', (principal.account_id, connection_id, *threads))}
        if found != set(threads):
            raise NotFound()
        if op in ('trash', 'untrash'):
            return ('mail.trash' if op == 'trash' else 'mail.untrash'), {'threads': threads}
        if op in ('label', 'unlabel', 'move'):
            if not isinstance(label, str) or not label or len(label) > 200:
                raise ValueError('choose a label')
            word = 'label:' + label
            add, remove = ([word], []) if op == 'label' else ([], [word]) if op == 'unlabel' else ([word], ['inbox'])
        elif op in self.ORGANIZE:
            kind, add, remove = self.ORGANIZE[op]
            return kind, {'changes': [{'thread': t, **({'add': add} if add else {}), **({'remove': remove} if remove else {})} for t in threads]}
        else:
            raise ValueError('unknown change')
        return 'mail.organize', {'changes': [{'thread': t, **({'add': add} if add else {}), **({'remove': remove} if remove else {})} for t in threads]}

    # -- meeting scheduling (#65) ------------------------------------------------------------------------------------------------------------------
    MAX_PEOPLE = 20

    def meeting_times(self, principal, connection_id, attendees, minutes, start_epoch, end_epoch, zone_name, *, title='', count=3, request_id=None) -> dict:
        """Two or three times for a meeting: free for the customer (their availability settings, live free/busy) and for every attendee whose free time the provider
        will tell this account (people in the same organization, or who share it): those are `internal`. The others are `external`: they are offered the times by a
        draft email. The result is stored as a proposal, which the Calendar draws for the customer to pick. -> {'proposal', 'options', 'internal', 'external', ...}."""
        import re
        import uuid
        from zoneinfo import ZoneInfo
        from .connector_kit import Unanswered
        from .hub_availability import merge
        zone = ZoneInfo(zone_name)
        people = []
        for a in attendees or []:
            a = str(a).strip().lower()
            if not re.fullmatch(r'[^@\s<>"]{1,64}@[^@\s<>"]{1,255}', a):
                raise ValueError('attendees are email addresses')
            if a not in people:
                people.append(a)
        if len(people) > self.MAX_PEOPLE or not 5 <= int(minutes) <= 8 * 60 or not 1 <= int(count) <= 5 or len(str(title)) > 500:
            raise ValueError('invalid request')
        mine = self.free(principal, start_epoch, end_epoch, zone, minutes=int(minutes))
        row, declaration, adapter, credential = self.client.open(principal, connection_id, 'connection.read')
        caps = hub_caps(declaration)
        own = {str(row['identity_label'] or '').lower()} if 'identity_label' in row.keys() else set()
        others = [a for a in people if a not in own]
        answers = {}
        if others and caps is not None and caps.free_busy and hasattr(adapter, 'free_busy'):
            try:
                answers = self.client.call(principal.account_id, declaration, lambda: adapter.free_busy(credential, others, int(start_epoch), int(end_epoch)))
            except (ConnectorFault, Unanswered):
                answers = {}
        internal = [a for a in others if answers.get(a) is not None]
        external = [a for a in others if answers.get(a) is None]
        busy = merge([span for a in internal for span in answers[a]])
        length, step = int(minutes) * 60, 1800
        candidates = []
        for free_start, free_end in mine['free']:
            t = -(-int(free_start) // step) * step                       # the next full or half hour
            while t + length <= free_end:
                if not any(b0 < t + length and b1 > t for b0, b1 in busy):
                    candidates.append(t)
                t += step
        picked, days = [], set()
        for t in candidates:                                                # one a day first, so the choice is real; then the earliest others
            day = datetime_day(t, zone)
            if day not in days:
                picked.append(t); days.add(day)
            if len(picked) == int(count):
                break
        for t in candidates:
            if len(picked) >= int(count):
                break
            if t not in picked:
                picked.append(t)
        picked.sort()
        local = lambda t: datetime_local(t, zone)
        options = [{'start': local(t), 'end': local(t + length), 'start_epoch': t, 'end_epoch': t + length} for t in picked]
        proposal = None
        if options:
            proposal = uuid.uuid4().hex
            now = int(self.clock())
            with self.store.connect() as con:
                require(principal, 'connection.use', con=con)
                con.execute('''INSERT INTO meeting_proposals(account_id,id,connection_id,title,minutes,attendees_json,internal_json,external_json,options_json,timezone,request_id,
                    created_epoch,updated_epoch) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (principal.account_id, proposal, connection_id, str(title)[:500], int(minutes), json.dumps(people),
                    json.dumps(internal), json.dumps(external), json.dumps(options), zone_name, request_id, now, now))
        s = mine['settings']
        return {'proposal': proposal, 'options': options, 'internal': internal, 'external': external, 'timezone': zone_name, 'minutes': int(minutes),
                'settings': {'working_hours': s.get('hours'), 'notice_minutes': s['notice_minutes'], 'buffer_minutes': s['buffer_minutes']},
                'sources': mine['sources']}

    def proposals(self, principal, start_epoch, end_epoch) -> list:
        """Open meeting proposals with a time in this range: what the Calendar draws as suggestions."""
        with self.store.connect() as con:
            require(principal, 'connection.read', con=con)
            rows = con.execute("SELECT * FROM meeting_proposals WHERE account_id=? AND state='open' ORDER BY created_epoch DESC LIMIT 20", (principal.account_id,)).fetchall()
        out = []
        for r in rows:
            options = [o for o in json.loads(r['options_json']) if o['end_epoch'] > int(start_epoch) and o['start_epoch'] < int(end_epoch)]
            if options:
                out.append({'id': r['id'], 'connection_id': r['connection_id'], 'title': r['title'], 'minutes': r['minutes'], 'attendees': json.loads(r['attendees_json']),
                            'external': json.loads(r['external_json']), 'options': options, 'waiting': bool(r['handoff_id'])})
        return out

    def close_proposal(self, principal, proposal_id, state) -> dict:
        if state not in ('picked', 'dismissed'):
            raise ValueError('invalid state')
        with self.store.connect() as con:
            require(principal, 'connection.use', con=con)
            changed = con.execute("UPDATE meeting_proposals SET state=?,updated_epoch=? WHERE account_id=? AND id=? AND state='open'",
                                  (state, int(self.clock()), principal.account_id, str(proposal_id))).rowcount
            row = con.execute('SELECT handoff_id FROM meeting_proposals WHERE account_id=? AND id=?', (principal.account_id, str(proposal_id))).fetchone()
            if row is None:
                raise NotFound()
            if changed and row['handoff_id']:
                con.execute("UPDATE handoffs SET state='expired',answered_epoch=? WHERE account_id=? AND id=? AND state='waiting'",
                            (int(self.clock()), principal.account_id, row['handoff_id']))
        return {'id': str(proposal_id), 'state': state}

    def wait_for_reply(self, principal, proposal_id, *, request_id=None, draft_id=None) -> dict:
        """The external people were offered the times (a draft email): the work waits, holding nothing, until the customer says which time they answered, or a reply
        arrives. A question for the customer (a handoff) that waits up to two weeks."""
        from .handoff import Handoffs
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM meeting_proposals WHERE account_id=? AND id=? AND state='open'", (principal.account_id, str(proposal_id))).fetchone()
        if row is None:
            raise NotFound()
        options = json.loads(row['options_json'])
        who = ', '.join(json.loads(row['external_json'])) or 'the people invited'
        question = f'Waiting for {who} to answer the times offered for "{row["title"] or "the meeting"}". When they answer, tell me which time works.'[:1000]
        handoffs = Handoffs(self.store, clock=self.clock)
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store, clock=self.clock).transaction() as con:
            require(principal, 'connection.use', con=con)
            handoff = handoffs.create(con, account_id=principal.account_id, actor_id=str(principal.actor_id), kind='question', request_id=request_id, question=question,
                                      options=[f'{o["start"]} to {o["end"][11:]}' for o in options][:5] + ['None of these'],
                                      resume={'meeting_proposal': row['id'], 'draft': draft_id}, seconds=14 * 86400)
            con.execute('UPDATE meeting_proposals SET handoff_id=?,draft_id=coalesce(?,draft_id),updated_epoch=? WHERE account_id=? AND id=?',
                        (handoff, draft_id, int(self.clock()), principal.account_id, row['id']))
        return {'handoff': handoff, 'question': question}

    def conflicts(self, principal, start_local, end_local, zone, *, rule=None) -> dict:
        """Does a proposed time (or each occurrence of a proposed repeat) clash with what is in the calendars that count? Against the synced, expanded instances of every
        such calendar (never a recurrence rule worked out here), with the buffer. -> {'occurrences': [...], 'clashing': count}."""
        from .hub_availability import conflicts, occurrences
        settings = self.availability(principal)
        proposed = occurrences(start_local, end_local, zone, rule)
        low, high = min(p[0] for p in proposed) - 86400, max(p[1] for p in proposed) + 86400
        counted = {(c['connection_id'], c['id']) for c in self._counted(principal, settings)}
        events = []
        for at in range(low, high, 390 * 86400):                 # a long series is read in slices the event query allows
            events += [e for e in self.events(principal, at, min(high, at + 390 * 86400), only_selected=False)['events'] if (e['connection_id'], e['calendar_id']) in counted]
        found = conflicts(proposed, events, settings, zone)
        return {'occurrences': found, 'clashing': sum(1 for o in found if o['conflicts']), 'settings': settings}

    def search_events(self, principal, query, *, connections=None, limit=50) -> dict:
        """Events in the synced window whose title, people, place or notes contain every word of the query, soonest upcoming first, then the past."""
        words = [w for w in str(query or '').lower().split() if w][:8]
        if not words:
            raise ValueError('invalid query')
        limit = max(1, min(int(limit or 50), 200))
        where, args = ["account_id=? AND cancelled=0 AND visibility!='busy'"], [principal.account_id]
        for word in words:
            where.append('(instr(lower(title),?)>0 OR instr(people_text,?)>0 OR instr(lower(place),?)>0 OR instr(lower(description),?)>0)'); args += [word[:100]] * 4
        now = int(self.clock())
        calendars = self.calendars(principal)
        with self.store.connect() as con:
            ids = set(self._connections(con, principal, connections))
            colours = {(c['connection_id'], c['id']): c['colour'] for c in calendars if c['connection_id'] in ids}
            rows = con.execute(f'SELECT * FROM hub_events WHERE {" AND ".join(where)} ORDER BY (end_epoch<?) ,abs(start_epoch-?) LIMIT ?', (*args, now, now, limit + 1)).fetchall()
        found = [self._event(r, colours[(r['connection_id'], r['calendar_id'])]) for r in rows if (r['connection_id'], r['calendar_id']) in colours]
        return {'events': found[:limit], 'complete': len(rows) <= limit}

    # -- attachments (#55) ---------------------------------------------------------------------------------------------------------------------------
    MAX_ATTACHMENT = 25 * 1024 * 1024

    def attachment(self, principal, connection_id, message_id, attachment_id) -> dict:
        """One attachment of a message this person may read: {'name', 'type', 'size', 'data'}. Read from the provider on demand and NOT kept here: the knowledge
        pipeline parses it and keeps the passages under the knowledge rows (the bytes are gone once it has been read)."""
        with self.store.connect() as con:
            self._enter(con, principal)
            if connection_id not in self._connections(con, principal):
                raise NotFound('unavailable')
        problem = self._open_body(principal, connection_id, message_id)
        if problem:
            from .connector_kit import FAULT_KINDS
            raise ConnectorFault(problem if problem in FAULT_KINDS else 'retry_later')
        with self.store.connect() as con:
            row = con.execute('SELECT attachments_json FROM hub_messages WHERE account_id=? AND connection_id=? AND id=?', (principal.account_id, connection_id, message_id)).fetchone()
        files = json.loads(row['attachments_json'] or '[]') if row else []
        found = next((f for f in files if f.get('id') == attachment_id), None)
        if found is None:
            raise NotFound('unavailable')
        _row, declaration, adapter, credential = self.client.open(principal, connection_id, 'connection.read')
        if not hub_caps(declaration).attachments:
            raise NotFound('unavailable')
        data = self.client.call(principal.account_id, declaration, lambda: adapter.mail_attachment(credential, message_id, attachment_id), where=(connection_id, 'mailbox', '*'))
        if not isinstance(data, bytes) or len(data) > self.MAX_ATTACHMENT:
            raise ConnectorFault('invalid')
        return {'name': found.get('name') or 'attachment', 'type': found.get('type') or 'application/octet-stream', 'size': len(data), 'data': data}

    # -- drafts (#57) --------------------------------------------------------------------------------------------------------------------------------
    MAX_DRAFTS = 500

    @staticmethod
    def _draft(row) -> dict:
        return {'id': row['id'], 'account': row['connection_id'], 'thread': row['thread_id'], 'to': json.loads(row['to_json']), 'cc': json.loads(row['cc_json']),
                'subject': row['subject'], 'body': row['body'], 'origin': row['origin'], 'created_epoch': row['created_epoch'], 'updated_epoch': row['updated_epoch']}

    @staticmethod
    def _addresses(value, n=50) -> list:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > n or any(not isinstance(v, str) or not 3 <= len(v.strip()) <= 320 or '@' not in v or any(c in v for c in '\r\n<>') for v in value):
            raise ValueError('invalid addresses')
        return [v.strip() for v in value]

    def drafts(self, principal, *, connections=None, thread_id=None) -> list:
        with self.store.connect() as con:
            self._enter(con, principal)
            ids = self._connections(con, principal, connections)
            if not ids:
                return []
            marks = ','.join('?' for _ in ids)
            extra, args = ('', []) if thread_id is None else (' AND thread_id=?', [str(thread_id)])
            # A draft whose send has started (or is waiting out Undo send) is not a draft any more; if that send was stopped or failed, it is one again.
            rows = con.execute(f"SELECT * FROM hub_drafts WHERE account_id=? AND state='draft' AND NOT EXISTS {SENDING} AND connection_id IN ({marks}){extra} ORDER BY updated_epoch DESC,id LIMIT 200",
                               (principal.account_id, *ids, *args)).fetchall()
        return [self._draft(r) for r in rows]

    def save_draft(self, principal, *, draft_id=None, connection_id=None, thread_id=None, to=None, cc=None, subject=None, body=None, origin='customer', request_id=None) -> dict:
        """Create a draft, or change one. Nothing is created in the mailbox: the customer copies it or opens it in their mail service's own compose screen."""
        if origin not in ('customer', 'assistant'):
            raise ValueError('invalid origin')
        if subject is not None and (not isinstance(subject, str) or len(subject) > 500):
            raise ValueError('invalid subject')
        if body is not None and (not isinstance(body, str) or len(body) > 40000):
            raise ValueError('invalid body')
        now = int(self.clock())
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store, clock=self.clock).transaction() as con:
            self._enter(con, principal, 'connection.use')
            if draft_id is not None:
                row = con.execute("SELECT * FROM hub_drafts WHERE account_id=? AND id=? AND state='draft'", (principal.account_id, str(draft_id))).fetchone()
                if row is None:
                    raise NotFound('unavailable')
                con.execute('UPDATE hub_drafts SET to_json=?,cc_json=?,subject=?,body=?,updated_epoch=? WHERE account_id=? AND id=?',
                            (json.dumps(self._addresses(to)) if to is not None else row['to_json'], json.dumps(self._addresses(cc)) if cc is not None else row['cc_json'],
                             subject if subject is not None else row['subject'], body if body is not None else row['body'], now, principal.account_id, row['id']))
                return self._draft(con.execute('SELECT * FROM hub_drafts WHERE account_id=? AND id=?', (principal.account_id, row['id'])).fetchone())
            if connection_id not in self._connections(con, principal):
                raise NotFound('unavailable')
            if thread_id is not None and not con.execute('SELECT 1 FROM hub_threads WHERE account_id=? AND connection_id=? AND id=?', (principal.account_id, connection_id, str(thread_id))).fetchone():
                raise NotFound('unavailable')
            if con.execute("SELECT count(*) FROM hub_drafts WHERE account_id=? AND state='draft'", (principal.account_id,)).fetchone()[0] >= self.MAX_DRAFTS:
                from .lifecycle.types import Conflict
                raise Conflict('too many drafts')
            import uuid
            draft = uuid.uuid4().hex
            con.execute('''INSERT INTO hub_drafts(account_id,id,connection_id,thread_id,to_json,cc_json,subject,body,origin,request_id,state,created_epoch,updated_epoch)
                VALUES (?,?,?,?,?,?,?,?,?,?,'draft',?,?)''', (principal.account_id, draft, connection_id, thread_id, json.dumps(self._addresses(to)), json.dumps(self._addresses(cc)),
                                                            subject or '', body or '', origin, request_id, now, now))
            return self._draft(con.execute('SELECT * FROM hub_drafts WHERE account_id=? AND id=?', (principal.account_id, draft)).fetchone())

    def discard_draft(self, principal, draft_id) -> dict:
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store, clock=self.clock).transaction() as con:
            self._enter(con, principal, 'connection.use')
            gone = con.execute("DELETE FROM hub_drafts WHERE account_id=? AND id=?", (principal.account_id, str(draft_id))).rowcount
        if not gone:
            raise NotFound('unavailable')
        return {'discarded': str(draft_id)}

    def compose_link(self, principal, draft_id) -> dict:
        """Where the customer sends a draft themselves: the provider's compose screen with the draft filled in, or nothing when the provider has none (then: Copy)."""
        with self.store.connect() as con:
            self._enter(con, principal)
            row = con.execute("SELECT * FROM hub_drafts WHERE account_id=? AND id=? AND state='draft'", (principal.account_id, str(draft_id))).fetchone()
            if row is None or row['connection_id'] not in self._connections(con, principal):
                raise NotFound('unavailable')
        draft = self._draft(row)
        _r, declaration, adapter, _c = self.client.open(principal, row['connection_id'], 'connection.read')
        link = adapter.compose_link(draft['to'], draft['cc'], draft['subject'], draft['body']) if hub_caps(declaration).compose_link and hasattr(adapter, 'compose_link') else None
        return {'draft': draft, 'link': link}
