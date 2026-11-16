"""The dashboard's background sync (roadmap #D2): a bounded copy of each connected account's mail headers and calendar events, kept current.

What is copied. Mail: headers and a short snippet of ALL the mail the customer granted (the owner's decision of 2026-11-16; the retention table's row is the window, and it
can be a number of days again). A body is never fetched here; hub.py fetches one when it is opened. Calendars: the provider's expanded instances, every past one and two
years ahead. It is kept live by asking each provider, every few seconds, what changed since last time (one cheap call).

One row of `hub_sync` per thing that is synced (a connection's mail, or one calendar). A run takes a lease on its row, pages through the provider's changes with a
checkpoint after every page (so a crash loses one page of work, never more), and gives the lease back. A run that is repeated changes nothing: the tables' uniqueness
rules are the correctness, not a cache.

Faults are the six kinds of the connector contract. `needs_customer` and `refused` pause the row (the connection shows "needs you" and what was synced stays visible with
its age); the others are tried again later with a growing pause. One account failing never touches another's rows.

Nothing here names a provider: it speaks to adapters through the hub interface (hub_model.py).
"""
from __future__ import annotations
import hashlib
import json
import logging
import time

from . import retention
from .connector_kit import ConnectorFault
from .hub_model import CALENDAR_RESOURCE, MAIL_RESOURCES, ResyncRequired, hub_caps, people_text

log = logging.getLogger('agentai.hub')
DAY = 86400
BACKOFF = (60, 300, 900, 3600)
PAUSING = ('needs_customer', 'refused')


def mail_window_days():
    """How far back mail is copied, in days; None = all of it (the retention row decides)."""
    days = retention.BY_KEY['mail_headers'].days
    return None if days is None else int(days)


def events_back_days():
    """How far back events are copied, in days; None = every past event."""
    days = retention.BY_KEY['calendar_events'].days
    return None if days is None else int(days)


EVENTS_AHEAD_DAYS = 731                # two years ahead
WINDOW_SLIP_DAYS = 30                  # a calendar's window is moved forward (a clean refill) once it has slipped this far
LIST_INTERVAL = 1800                   # how often an account's list of calendars is read again


def _grant_key(parts) -> str:
    return hashlib.sha256(json.dumps(sorted(parts)).encode()).hexdigest()[:24]


class HubSync:
    def __init__(self, store, connectors, client, *, clock=time.time, page=100, pages_per_run=10, interval=20, calendar_interval=60, lease=180):
        self.store, self.connectors, self.client, self.clock = store, connectors, client, clock
        # `interval`: how soon a mailbox that is up to date is asked again for what changed (one cheap call). Calendars a little less often. This is what makes the
        # dashboard live without the provider having to call Lumina.
        self.page, self.pages_per_run, self.interval, self.calendar_interval, self.lease = page, pages_per_run, interval, calendar_interval, lease

    # -- which rows exist: follows the connection and its grants ----------------------------------------------------------------------------------------
    def _hub_connections(self, con, account_id=None):
        rows = con.execute("SELECT account_id,id,service FROM connector_connections WHERE state='connected'" + (' AND account_id=?' if account_id else ''),
                           (account_id,) if account_id else ()).fetchall()
        return [r for r in rows if hub_caps(self.connectors.declared(r['service']))]

    def reconcile(self, account_id=None) -> int:
        """Make the sync rows match the connections and their grants. Cheap (no provider call) unless something changed. -> how many connections were set up again."""
        changed = 0
        with self.store.connect() as con:
            connections = self._hub_connections(con, account_id)
            wanted = {}
            for c in connections:
                scope = self.connectors.scope(con, c['account_id'], c['id'])
                mail, calendars = [s for s in scope if s[0] in MAIL_RESOURCES], [s for s in scope if s[0] == CALENDAR_RESOURCE]
                caps = hub_caps(self.connectors.declared(c['service']))
                wanted[(c['account_id'], c['id'])] = (_grant_key(mail) if mail and caps.mail else None, _grant_key(calendars) if calendars and caps.calendar else None)
            have = {}
            for r in con.execute('SELECT account_id,connection_id,domain,grant_key,state FROM hub_sync' + (' WHERE account_id=?' if account_id else ''), (account_id,) if account_id else ()):
                have.setdefault((r['account_id'], r['connection_id']), {}).setdefault(r['domain'], set()).add(r['grant_key'])
            # A connection that works again takes its paused rows back.
            con.execute("""UPDATE hub_sync SET state='waiting',next_epoch=0 WHERE state='paused' AND EXISTS (SELECT 1 FROM connector_connections c
                WHERE c.account_id=hub_sync.account_id AND c.id=hub_sync.connection_id AND c.state='connected')""")
        for key, (mail_key, calendar_key) in wanted.items():
            seen = have.get(key, {})
            # A part that should be synced and is not set up, one set up for other grants, or one that should no longer be there.
            if seen.get('mail') != ({mail_key} if mail_key else None) or seen.get('calendar') != ({calendar_key} if calendar_key else None):
                try:
                    self.ensure(*key)
                    changed += 1
                except ConnectorFault:
                    pass                                   # recorded where it happened; the next tick tries again
        return changed

    def ensure(self, account_id, connection_id) -> None:
        """Set up (or take down) the sync rows of one connection from what it is and what its customer granted. Called when a connection is made or its grants change."""
        row, declaration, adapter, credential = self.client.open_for_sync(account_id, connection_id)
        caps = hub_caps(declaration)
        if caps is None:
            return
        with self.store.connect() as con:
            scope = self.connectors.scope(con, account_id, connection_id)
        mail = [s for s in scope if s[0] in MAIL_RESOURCES]
        calendars = [s for s in scope if s[0] == CALENDAR_RESOURCE]
        found, trouble = [], None
        if caps.calendar and calendars:
            try:
                found = self.client.call(account_id, declaration, lambda: adapter.calendars(credential), where=(connection_id, CALENDAR_RESOURCE, '*'))
            except ConnectorFault as fault:
                trouble = fault                               # the calendars could not be listed now: mail is still set up, and the calendars are tried again later
        now = int(self.clock())
        every = any(s[1] == '*' for s in calendars)
        chosen = {s[1] for s in calendars}
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store).transaction() as con:
            key = _grant_key(mail)
            if caps.mail and mail:
                old = con.execute("SELECT grant_key FROM hub_sync WHERE account_id=? AND connection_id=? AND domain='mail' AND resource_id='*'", (account_id, connection_id)).fetchone()
                if old is None:
                    con.execute("INSERT INTO hub_sync(account_id,connection_id,domain,resource_id,grant_key) VALUES (?,?,'mail','*',?)", (account_id, connection_id, key))
                elif old['grant_key'] != key:               # what may be read changed: start again from nothing, so nothing outside the new grant stays
                    self._clear_mail(con, account_id, connection_id)
                    con.execute("""UPDATE hub_sync SET grant_key=?,cursor=NULL,filled=0,next_epoch=0,item_count=0,state='waiting',lease_epoch=NULL
                        WHERE account_id=? AND connection_id=? AND domain='mail'""", (key, account_id, connection_id))
            else:
                self._clear_mail(con, account_id, connection_id)
                con.execute("DELETE FROM hub_sync WHERE account_id=? AND connection_id=? AND domain='mail'", (account_id, connection_id))
            if trouble is None:                               # (an exception inside this block would undo the mail set-up above, so the fault is raised after it)
                key = _grant_key(calendars)
                keep = [c for c in found if every or c['id'] in chosen] if caps.calendar and calendars else []
                ids = {c['id'] for c in keep}
                for old in con.execute('SELECT id FROM hub_calendars WHERE account_id=? AND connection_id=?', (account_id, connection_id)).fetchall():
                    if old['id'] not in ids:
                        con.execute('DELETE FROM hub_events WHERE account_id=? AND connection_id=? AND calendar_id=?', (account_id, connection_id, old['id']))
                        con.execute('DELETE FROM hub_calendars WHERE account_id=? AND connection_id=? AND id=?', (account_id, connection_id, old['id']))
                        con.execute("DELETE FROM hub_sync WHERE account_id=? AND connection_id=? AND domain='calendar' AND resource_id=?", (account_id, connection_id, old['id']))
                for c in keep:
                    con.execute('''INSERT INTO hub_calendars(account_id,connection_id,id,name,provider_colour,timezone,access,is_primary,updated_epoch) VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(account_id,connection_id,id) DO UPDATE SET name=excluded.name,provider_colour=excluded.provider_colour,timezone=excluded.timezone,
                        access=excluded.access,is_primary=excluded.is_primary,updated_epoch=excluded.updated_epoch''',
                                (account_id, connection_id, c['id'], c['name'], c['colour'], c['timezone'], c['access'], int(c['primary']), now))
                    con.execute("""INSERT INTO hub_sync(account_id,connection_id,domain,resource_id,grant_key) VALUES (?,?,'calendar',?,?)
                        ON CONFLICT(account_id,connection_id,domain,resource_id) DO UPDATE SET grant_key=excluded.grant_key""", (account_id, connection_id, c['id'], key))
                # The list of calendars is itself something that is kept current ('*'): a calendar the customer adds at the provider shows up, one they remove goes.
                if caps.calendar and calendars:
                    con.execute("""INSERT INTO hub_sync(account_id,connection_id,domain,resource_id,grant_key,filled,last_sync_epoch,next_epoch) VALUES (?,?,'calendar','*',?,1,?,?)
                        ON CONFLICT(account_id,connection_id,domain,resource_id) DO UPDATE SET grant_key=excluded.grant_key,last_sync_epoch=excluded.last_sync_epoch,
                        next_epoch=excluded.next_epoch,failures=0,last_error=NULL,last_error_epoch=NULL""", (account_id, connection_id, key, now, now + LIST_INTERVAL))
                else:
                    con.execute("DELETE FROM hub_sync WHERE account_id=? AND connection_id=? AND domain='calendar' AND resource_id='*'", (account_id, connection_id))
        if trouble is not None:
            raise trouble

    @staticmethod
    def _clear_mail(con, account_id, connection_id):
        con.execute('DELETE FROM hub_messages WHERE account_id=? AND connection_id=?', (account_id, connection_id))
        con.execute('DELETE FROM hub_threads WHERE account_id=? AND connection_id=?', (account_id, connection_id))

    # -- running ----------------------------------------------------------------------------------------------------------------------------------------
    def request(self, account_id, connection_id=None) -> int:
        """"Refresh": make this account's rows due now. -> how many."""
        with self.store.connect() as con:
            return con.execute("UPDATE hub_sync SET next_epoch=0 WHERE account_id=? AND state!='paused'" + (' AND connection_id=?' if connection_id else ''),
                               (account_id, connection_id) if connection_id else (account_id,)).rowcount

    def due(self, limit=10) -> list[dict]:
        now = int(self.clock())
        with self.store.connect() as con:
            return [dict(r) for r in con.execute("""SELECT * FROM hub_sync WHERE (state='waiting' AND next_epoch<=?) OR (state='running' AND coalesce(lease_epoch,0)<?)
                ORDER BY next_epoch LIMIT ?""", (now, now - self.lease, limit))]

    def tick(self, limit=10) -> dict:
        """One pass: follow connections and grants, then run what is due. -> {'ran', 'changed', 'failed'}."""
        report = {'ran': 0, 'changed': 0, 'failed': 0}
        try:
            self.reconcile()
        except Exception as error:                          # one connection's trouble must not stop the others' sync
            log.warning('hub_reconcile_error where=%s', type(error).__name__)
        for row in self.due(limit):
            outcome = self.run(row)
            if outcome is None:
                continue
            report['ran'] += 1
            report['failed' if outcome == 'failed' else 'changed'] += 0 if outcome == 'same' else 1
        return report

    def _take(self, row) -> bool:
        now = int(self.clock())
        with self.store.connect() as con:
            return con.execute("""UPDATE hub_sync SET state='running',lease_epoch=? WHERE account_id=? AND connection_id=? AND domain=? AND resource_id=?
                AND (state='waiting' OR (state='running' AND coalesce(lease_epoch,0)<?))""",
                               (now, row['account_id'], row['connection_id'], row['domain'], row['resource_id'], now - self.lease)).rowcount == 1

    def run(self, row) -> str | None:
        """Sync one row once. -> 'changed' | 'same' | 'failed', or None when another worker has it."""
        if not self._take(row):
            return None
        account, connection, domain, resource = row['account_id'], row['connection_id'], row['domain'], row['resource_id']
        where = (connection, 'mailbox' if domain == 'mail' else CALENDAR_RESOURCE, resource)
        now = int(self.clock())
        try:
            if domain == 'calendar' and resource == '*':      # the list of calendars: `ensure` reads it and records that it did
                self.ensure(account, connection)
                with self.store.connect() as con:
                    con.execute("UPDATE hub_sync SET state='waiting',lease_epoch=NULL WHERE account_id=? AND connection_id=? AND domain='calendar' AND resource_id='*'", (account, connection))
                return 'same'
            _row, declaration, adapter, credential = self.client.open_for_sync(account, connection)
            changed, more = (self._mail if domain == 'mail' else self._calendar)(account, connection, resource, declaration, adapter, credential, where)
        except ConnectorFault as fault:
            self._failed(row, fault.kind, fault.retry_at)
            return 'failed'
        except Exception as error:                          # an adapter bug: recorded by where, never by its text (it could carry mail)
            log.warning('hub_sync_error domain=%s where=%s', domain, type(error).__name__)
            self._failed(row, 'retry_later', None)
            return 'failed'
        with self.store.connect() as con:
            con.execute("""UPDATE hub_sync SET state='waiting',lease_epoch=NULL,last_sync_epoch=?,last_change_epoch=CASE WHEN ? THEN ? ELSE last_change_epoch END,
                next_epoch=?,failures=0,last_error=NULL,last_error_epoch=NULL WHERE account_id=? AND connection_id=? AND domain=? AND resource_id=?""",
                        (now, int(changed), now, now if more else now + (self.interval if domain == 'mail' else self.calendar_interval), account, connection, domain, resource))
        try:
            self.client.freshness.read(account, connection, where[1], resource, complete=not more)
        except Exception:
            pass
        return 'changed' if changed else 'same'

    def _failed(self, row, kind, retry_at):
        now = int(self.clock())
        pause = BACKOFF[min(row['failures'], len(BACKOFF) - 1)]
        # When the provider said when to come back (a rate limit), that is when: its limits are counted per minute, and a growing pause turned a first fill that is
        # refused every few hundred messages into one page an hour (production, 2026-11-16). Anything else waits longer each time it fails again.
        when = now + max(1, min(3600, int(retry_at - time.time()))) if retry_at else now + pause      # retry_at is on the wall clock; `now` may be a test's
        with self.store.connect() as con:
            con.execute("""UPDATE hub_sync SET state=?,lease_epoch=NULL,failures=failures+1,last_error=?,last_error_epoch=?,next_epoch=?
                WHERE account_id=? AND connection_id=? AND domain=? AND resource_id=?""",
                        ('paused' if kind in PAUSING else 'waiting', kind, now, when, row['account_id'], row['connection_id'], row['domain'], row['resource_id']))

    def _state(self, account, connection, domain, resource):
        with self.store.connect() as con:
            return dict(con.execute('SELECT * FROM hub_sync WHERE account_id=? AND connection_id=? AND domain=? AND resource_id=?', (account, connection, domain, resource)).fetchone())

    # -- mail -------------------------------------------------------------------------------------------------------------------------------------------
    def _labels(self, account, connection):
        """None when all mail was granted, else the provider label ids that were."""
        with self.store.connect() as con:
            scope = [s for s in self.connectors.scope(con, account, connection) if s[0] in MAIL_RESOURCES]
        if any(s[0] == 'mailbox' or s[1] == '*' for s in scope):
            return None
        return sorted(s[1] for s in scope)

    def _mail(self, account, connection, resource, declaration, adapter, credential, where):
        labels = self._labels(account, connection)
        days = mail_window_days()
        since = 0 if days is None else int(self.clock()) - days * DAY      # 0: all the mail that was granted
        changed, more, resynced = False, True, False
        for _ in range(self.pages_per_run):
            state = self._state(account, connection, 'mail', resource)
            try:
                changes = self.client.call(account, declaration, lambda: adapter.mail_changes(credential, state['cursor'], since, labels, self.page), where=where)
            except ResyncRequired:
                if resynced:
                    raise ConnectorFault('retry_later') from None
                resynced = True
                self._reset(account, connection, 'mail', resource)
                continue
            keep = [m for m in changes.items if (m['sent_epoch'] >= since or m['starred'])
                    and (labels is None or any(p['id'] in labels for p in m['provider_labels']))]
            gone = list(changes.removed) + [m['id'] for m in changes.items if m not in keep]
            changed |= self._apply_mail(account, connection, keep, gone, changes.cursor, filled=not changes.more or bool(state['filled']))
            more = changes.more
            if not more:
                break
        return changed, more

    def _reset(self, account, connection, domain, resource):
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store).transaction() as con:
            if domain == 'mail':
                self._clear_mail(con, account, connection)
            else:
                con.execute('DELETE FROM hub_events WHERE account_id=? AND connection_id=? AND calendar_id=?', (account, connection, resource))
            con.execute('UPDATE hub_sync SET cursor=NULL,filled=0,item_count=0 WHERE account_id=? AND connection_id=? AND domain=? AND resource_id=?', (account, connection, domain, resource))

    def _apply_mail(self, account, connection, messages, removed, cursor, *, filled) -> bool:
        now, threads, changed = int(self.clock()), set(), False
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store).transaction() as con:
            for m in messages:
                row = (m['thread_id'], m['subject'], m['snippet'], json.dumps(m['sender']), json.dumps(m['to']), json.dumps(m['cc']), people_text(m['sender'], m['to'], m['cc']),
                       m['sent_epoch'], json.dumps(m['labels']), json.dumps(m['provider_labels']), int(m['unread']), int(m['starred']), int(m['has_attachments']))
                old = con.execute('''SELECT thread_id,subject,snippet,sender_json,to_json,cc_json,people_text,sent_epoch,labels_json,provider_labels_json,unread,starred,has_attachments
                    FROM hub_messages WHERE account_id=? AND connection_id=? AND id=?''', (account, connection, m['id'])).fetchone()
                if old is not None and tuple(old) == row:
                    continue                                  # the same message again: nothing changes
                changed = True
                threads.add(m['thread_id'])
                if old is not None:
                    threads.add(old['thread_id'])
                con.execute('''INSERT INTO hub_messages(account_id,connection_id,id,thread_id,subject,snippet,sender_json,to_json,cc_json,people_text,sent_epoch,labels_json,
                    provider_labels_json,unread,starred,has_attachments,synced_epoch) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(account_id,connection_id,id) DO UPDATE SET thread_id=excluded.thread_id,subject=excluded.subject,snippet=excluded.snippet,
                    sender_json=excluded.sender_json,to_json=excluded.to_json,cc_json=excluded.cc_json,people_text=excluded.people_text,sent_epoch=excluded.sent_epoch,
                    labels_json=excluded.labels_json,provider_labels_json=excluded.provider_labels_json,unread=excluded.unread,starred=excluded.starred,
                    has_attachments=excluded.has_attachments,synced_epoch=excluded.synced_epoch''', (account, connection, m['id'], *row, now))
            for mid in removed:
                old = con.execute('SELECT thread_id FROM hub_messages WHERE account_id=? AND connection_id=? AND id=?', (account, connection, str(mid))).fetchone()
                if old is not None:
                    changed = True
                    threads.add(old['thread_id'])
                    con.execute('DELETE FROM hub_messages WHERE account_id=? AND connection_id=? AND id=?', (account, connection, str(mid)))
            for thread in threads:
                rebuild_thread(con, account, connection, thread)
            count = con.execute('SELECT count(*) FROM hub_messages WHERE account_id=? AND connection_id=?', (account, connection)).fetchone()[0]
            con.execute("UPDATE hub_sync SET cursor=?,filled=?,item_count=?,lease_epoch=? WHERE account_id=? AND connection_id=? AND domain='mail'",
                        (cursor, int(filled), count, now, account, connection))
        return changed

    # -- calendars --------------------------------------------------------------------------------------------------------------------------------------
    def _calendar(self, account, connection, calendar_id, declaration, adapter, credential, where):
        now = int(self.clock())
        back = events_back_days()
        start, end = (0 if back is None else now - back * DAY), now + EVENTS_AHEAD_DAYS * DAY      # 0: every past event
        changed, more, resynced = False, True, False
        state = self._state(account, connection, 'calendar', calendar_id)
        if state['window_end_epoch'] is None or end - state['window_end_epoch'] > WINDOW_SLIP_DAYS * DAY:
            # A provider's change cursor belongs to the window it was made for: when the window has slipped, fill the new one cleanly.
            if state['window_end_epoch'] is not None:
                self._reset(account, connection, 'calendar', calendar_id)
            with self.store.connect() as con:
                con.execute("UPDATE hub_sync SET window_start_epoch=?,window_end_epoch=? WHERE account_id=? AND connection_id=? AND domain='calendar' AND resource_id=?",
                            (start, end, account, connection, calendar_id))
        for _ in range(self.pages_per_run):
            state = self._state(account, connection, 'calendar', calendar_id)
            try:
                changes = self.client.call(account, declaration, lambda: adapter.event_changes(credential, calendar_id, state['cursor'], state['window_start_epoch'],
                                                                                              state['window_end_epoch'], self.page), where=where)
            except ResyncRequired:
                if resynced:
                    raise ConnectorFault('retry_later') from None
                resynced = True
                self._reset(account, connection, 'calendar', calendar_id)
                continue
            keep = [e for e in changes.items if e['calendar_id'] == calendar_id and e['end_epoch'] >= state['window_start_epoch'] and e['start_epoch'] <= state['window_end_epoch']]
            gone = list(changes.removed) + [e['id'] for e in changes.items if e not in keep]
            changed |= self._apply_events(account, connection, calendar_id, keep, gone, changes.cursor, filled=not changes.more or bool(state['filled']))
            more = changes.more
            if not more:
                break
        return changed, more

    def _apply_events(self, account, connection, calendar_id, events, removed, cursor, *, filled) -> bool:
        now, changed = int(self.clock()), False
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store).transaction() as con:
            for e in events:
                row = (e['series_id'], e['title'], e['start_epoch'], e['end_epoch'], int(e['all_day']), e['start_date'], e['end_date'], e['timezone'], e['place'], e['conference_url'],
                       json.dumps(e['organizer']) if e['organizer'] else None, json.dumps(e['attendees']), people_text(e['organizer'] or {}, e['attendees']), e['my_response'],
                       int(e['exception']), int(e['cancelled']), e['visibility'], e['version'], e['description'], e['provider_url'], e['updated_epoch'])
                old = con.execute('''SELECT series_id,title,start_epoch,end_epoch,all_day,start_date,end_date,timezone,place,conference_url,organizer_json,attendees_json,people_text,
                    my_response,is_exception,cancelled,visibility,version,description,provider_url,updated_epoch FROM hub_events
                    WHERE account_id=? AND connection_id=? AND calendar_id=? AND id=?''', (account, connection, calendar_id, e['id'])).fetchone()
                if old is not None and tuple(old) == row:
                    continue
                changed = True
                con.execute('''INSERT INTO hub_events(account_id,connection_id,calendar_id,id,series_id,title,start_epoch,end_epoch,all_day,start_date,end_date,timezone,place,
                    conference_url,organizer_json,attendees_json,people_text,my_response,is_exception,cancelled,visibility,version,description,provider_url,updated_epoch,synced_epoch)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(account_id,connection_id,calendar_id,id) DO UPDATE SET series_id=excluded.series_id,title=excluded.title,start_epoch=excluded.start_epoch,
                    end_epoch=excluded.end_epoch,all_day=excluded.all_day,start_date=excluded.start_date,end_date=excluded.end_date,timezone=excluded.timezone,place=excluded.place,
                    conference_url=excluded.conference_url,organizer_json=excluded.organizer_json,attendees_json=excluded.attendees_json,people_text=excluded.people_text,
                    my_response=excluded.my_response,is_exception=excluded.is_exception,cancelled=excluded.cancelled,visibility=excluded.visibility,version=excluded.version,
                    description=excluded.description,provider_url=excluded.provider_url,updated_epoch=excluded.updated_epoch,synced_epoch=excluded.synced_epoch''',
                            (account, connection, calendar_id, e['id'], *row, now))
            for eid in removed:
                changed |= con.execute('DELETE FROM hub_events WHERE account_id=? AND connection_id=? AND calendar_id=? AND id=?', (account, connection, calendar_id, str(eid))).rowcount > 0
            count = con.execute('SELECT count(*) FROM hub_events WHERE account_id=? AND connection_id=? AND calendar_id=?', (account, connection, calendar_id)).fetchone()[0]
            con.execute("UPDATE hub_sync SET cursor=?,filled=?,item_count=?,lease_epoch=? WHERE account_id=? AND connection_id=? AND domain='calendar' AND resource_id=?",
                        (cursor, int(filled), count, now, account, connection, calendar_id))
        return changed


def rebuild_thread(con, account, connection, thread_id) -> None:
    """A thread row is made from its messages, here and only here: the subject of the first, the snippet and time of the last, everyone in it, and the marks of any."""
    rows = con.execute('''SELECT subject,snippet,sender_json,to_json,cc_json,sent_epoch,labels_json,provider_labels_json,unread,starred,has_attachments FROM hub_messages
        WHERE account_id=? AND connection_id=? AND thread_id=? ORDER BY sent_epoch,id''', (account, connection, thread_id)).fetchall()
    if not rows:
        con.execute('DELETE FROM hub_threads WHERE account_id=? AND connection_id=? AND id=?', (account, connection, thread_id))
        return
    people, seen, labels, own = [], set(), set(), {}
    for r in rows:
        for p in [json.loads(r['sender_json'])] + json.loads(r['to_json']) + json.loads(r['cc_json']):
            key = p.get('address') or p.get('name')
            if key and key not in seen and len(people) < 12:
                seen.add(key); people.append(p)
        labels.update(json.loads(r['labels_json']))
        for p in json.loads(r['provider_labels_json']):
            own[p['id']] = p
    last = rows[-1]
    values = (rows[0]['subject'], last['snippet'], json.dumps(people), people_text(people), last['sent_epoch'], len(rows), int(any(r['unread'] for r in rows)),
              int(any(r['starred'] for r in rows)), int(any(r['has_attachments'] for r in rows)), json.dumps(sorted(labels)), json.dumps(sorted(own.values(), key=lambda p: p['id'])))
    con.execute('''INSERT INTO hub_threads(account_id,connection_id,id,subject,snippet,people_json,people_text,last_epoch,message_count,unread,starred,has_attachments,labels_json,
        provider_labels_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(account_id,connection_id,id) DO UPDATE SET subject=excluded.subject,snippet=excluded.snippet,people_json=excluded.people_json,people_text=excluded.people_text,
        last_epoch=excluded.last_epoch,message_count=excluded.message_count,unread=excluded.unread,starred=excluded.starred,has_attachments=excluded.has_attachments,
        labels_json=excluded.labels_json,provider_labels_json=excluded.provider_labels_json''', (account, connection, thread_id, *values))


def sweep(con, now) -> dict:
    """Retention for the dashboard's copies, run by the one sweeper (retention.py) inside its transaction: mail headers past the window (starred mail stays), opened bodies
    past theirs (the headers stay; the body is fetched again if it is opened again), events that ended before the window."""
    done = {}
    if mail_window_days() is not None:                       # a limit on how far back mail is kept (None: all of it stays until the account is removed)
        cutoff = now - mail_window_days() * DAY
        old = con.execute('SELECT DISTINCT account_id,connection_id,thread_id FROM hub_messages WHERE sent_epoch<? AND starred=0', (cutoff,)).fetchall()
        done['mail_headers'] = con.execute('DELETE FROM hub_messages WHERE sent_epoch<? AND starred=0', (cutoff,)).rowcount
        for r in old:
            rebuild_thread(con, r['account_id'], r['connection_id'], r['thread_id'])
    done['mail_bodies'] = con.execute('''UPDATE hub_messages SET body_text=NULL,body_html=NULL,attachments_json=NULL,body_fetched_epoch=NULL,body_opened_epoch=NULL
        WHERE body_fetched_epoch IS NOT NULL AND coalesce(body_opened_epoch,body_fetched_epoch)<?''', (now - int(retention.BY_KEY['mail_bodies'].days) * DAY,)).rowcount
    if events_back_days() is not None:
        done['calendar_events'] = con.execute('DELETE FROM hub_events WHERE end_epoch<?', (now - events_back_days() * DAY,)).rowcount
    return done
