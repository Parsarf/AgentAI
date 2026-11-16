"""Two fake mail and calendar providers that differ in everything a provider can differ in, and a database with both registered (shared by the dashboard tests).

The dashboard's model is provider-neutral (roadmap #D1). These two are how that is proven before a second real provider exists: every engine and service test runs with one
account of each connected together.

                      'alpha'                                   'postbox'
ids                   'm-0001', threads 't-...'                 '<n>@postbox', conversations 'conv:<n>'
labels                several per message, own ids ('L_IN')     one folder per message, own names ('Posteingang')
people                {'name', 'email'}                         'Name <address>' strings
first fill            page tokens                               offsets
changes               a history number                          a list of change numbers kept only for a while (then: resync)
calendars             several                                   exactly one
all-day events        'date' fields                             midnight-to-midnight timestamps with a flag
"""
import json
import tempfile
import unittest
from pathlib import Path

from agentai_platform.connector_custody import SealedCustody
from agentai_platform.connector_kit import Caps, ConnectorClient, Declaration, Page, ProviderError, Registry
from agentai_platform.connectors import ConnectorService
from agentai_platform.hub import HubService
from agentai_platform.hub_model import Changes, HubCaps, ResyncRequired, body, calendar, event, message
from agentai_platform.hub_sync import HubSync
from agentai_platform.security import Principal
from agentai_platform.store import Store
from agentai_platform.vault import Keyring

DAY = 86400


class World:
    """What one fake provider holds for one mailbox owner."""
    def __init__(self):
        self.mail, self.bodies, self.calendars, self.events = {}, {}, {}, {}
        self.mail_log, self.event_log = [], {}          # [(number, id)] ; calendar -> [(number, id)]
        self.number = 0
        self.expire_cursors = False
        self.fail = []                                  # ProviderError (or other exceptions) raised by the next calls, in order
        self.calls = []

    def bump(self):
        self.number += 1
        return self.number

    def enter(self, name):
        self.calls.append(name)
        if self.fail:
            raise self.fail.pop(0)


class Alpha:
    """Labels, page tokens, a history number."""
    PROVIDER = 'alpha'
    LABELS = {'L_IN': 'inbox', 'L_SENT': 'sent', 'L_STAR': 'starred', 'L_NEW': 'unread', 'L_BIN': 'trash'}

    def __init__(self, worlds):
        self.worlds = worlds

    def world(self, credential) -> World:
        if credential.get('token') != 'alpha-ok':
            raise ProviderError(401, 'bad_token')
        return self.worlds[credential['who']]

    # -- conversion: the only place this provider's shapes are known ----------------------------------------------------------------------------
    @classmethod
    def to_message(cls, raw):
        marks = [cls.LABELS[label] for label in raw['labelIds'] if label in cls.LABELS]
        if not {'L_IN', 'L_SENT', 'L_BIN'} & set(raw['labelIds']):
            marks.append('archive')
        return message(raw['id'], raw['threadId'], subject=raw['subject'], sender={'name': raw['from']['name'], 'address': raw['from']['email']},
                       to=[{'name': p['name'], 'address': p['email']} for p in raw['to']], sent_epoch=raw['internalDate'] // 1000, snippet=raw['snippet'], labels=marks,
                       provider_labels=[{'id': label, 'name': label.replace('L_', '').title()} for label in raw['labelIds']], has_attachments=bool(raw.get('files')))

    @staticmethod
    def to_event(raw, calendar_id):
        if 'date' in raw['start']:
            from datetime import datetime, timezone
            stamp = lambda d: int(datetime.strptime(d, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
            when = {'all_day': True, 'start_date': raw['start']['date'], 'end_date': raw['end']['date'], 'start_epoch': stamp(raw['start']['date']), 'end_epoch': stamp(raw['end']['date'])}
        else:
            when = {'start_epoch': raw['start']['epoch'], 'end_epoch': raw['end']['epoch'], 'timezone': raw['start'].get('zone')}
        return event(raw['id'], calendar_id, title=raw.get('summary', ''), series_id=raw.get('recurringEventId'), exception=bool(raw.get('originalStart')),
                     cancelled=raw.get('status') == 'cancelled', place=raw.get('location', ''), version=raw.get('etag'),
                     attendees=[{'name': a.get('name', ''), 'address': a['email'], 'response': a.get('response'), 'self': a.get('self', False)} for a in raw.get('attendees', [])],
                     my_response=next((a.get('response') for a in raw.get('attendees', []) if a.get('self')), None), description=raw.get('description', ''),
                     visibility='busy' if raw.get('freeBusyOnly') else 'default', **when)

    # -- the hub interface ----------------------------------------------------------------------------------------------------------------------
    def calendars(self, credential):
        world = self.world(credential); world.enter('calendars')
        return [calendar(cid, name=c['summary'], timezone=c.get('zone'), access=c.get('role', 'read'), primary=c.get('primary', False)) for cid, c in sorted(world.calendars.items())]

    def mail_changes(self, credential, cursor, since_epoch, labels, limit):
        world = self.world(credential); world.enter('mail_changes')
        state = json.loads(cursor) if cursor else {'page': 0, 'history': world.number}
        if world.expire_cursors and cursor:
            world.expire_cursors = False
            raise ResyncRequired()
        wanted = lambda raw: labels is None or bool(set(labels) & set(raw['labelIds']))
        if 'page' in state:                             # the first fill: every message in the window, a page at a time
            every = sorted((m for m in world.mail.values() if m['internalDate'] // 1000 >= since_epoch or 'L_STAR' in m['labelIds']), key=lambda m: m['id'])
            every = [m for m in every if wanted(m)]
            size = min(limit, 3)
            part = every[state['page'] * size:(state['page'] + 1) * size]
            done = (state['page'] + 1) * size >= len(every)
            return Changes([self.to_message(m) for m in part], [], json.dumps({'history': state['history']} if done else {'page': state['page'] + 1, 'history': state['history']}), not done)
        changed = sorted({mid for number, mid in world.mail_log if number > state['history']})
        return Changes([self.to_message(world.mail[m]) for m in changed if m in world.mail and wanted(world.mail[m])],
                       [m for m in changed if m not in world.mail or not wanted(world.mail[m])], json.dumps({'history': world.number}), False)

    def mail_body(self, credential, message_id):
        world = self.world(credential); world.enter('mail_body')
        if message_id not in world.mail:
            raise ProviderError(404)
        raw = world.bodies.get(message_id, {})
        return body(raw.get('text', 'Body of ' + message_id), raw.get('html', ''), [{'id': f['id'], 'name': f['name'], 'type': f['type'], 'size': f['size']} for f in world.mail[message_id].get('files', [])])

    def mail_search(self, credential, query, labels, position, limit):
        world = self.world(credential); world.enter('mail_search')
        found = sorted((m for m in world.mail.values() if query.lower() in (m['subject'] + ' ' + m['snippet']).lower() and (labels is None or set(labels) & set(m['labelIds']))),
                       key=lambda m: m['id'])
        start = int(position or 0)
        part = found[start:start + min(limit, 2)]
        return Page([self.to_message(m) for m in part], next=str(start + len(part)) if start + len(part) < len(found) else None, total=len(found))

    def event_changes(self, credential, calendar_id, cursor, start_epoch, end_epoch, limit):
        world = self.world(credential); world.enter('event_changes')
        if calendar_id not in world.calendars:
            raise ProviderError(404)
        if world.expire_cursors and cursor:
            world.expire_cursors = False
            raise ResyncRequired()
        state = json.loads(cursor) if cursor else None
        events = world.events.get(calendar_id, {})
        if state is None:
            return Changes([self.to_event(e, calendar_id) for e in events.values()], [], json.dumps({'n': world.number}), False)
        changed = sorted({eid for number, eid in world.event_log.get(calendar_id, []) if number > state['n']})
        return Changes([self.to_event(events[e], calendar_id) for e in changed if e in events], [e for e in changed if e not in events], json.dumps({'n': world.number}), False)


class Postbox:
    """Folders, offsets, a short change list, one calendar."""
    PROVIDER = 'postbox'
    FOLDERS = {'Posteingang': 'inbox', 'Gesendet': 'sent', 'Ablage': 'archive', 'Papierkorb': 'trash'}

    def __init__(self, worlds):
        self.worlds = worlds

    def world(self, credential) -> World:
        if credential.get('secret') != 'postbox-ok':
            raise ProviderError(401, 'bad_token')
        return self.worlds[credential['owner']]

    @staticmethod
    def _who(text):
        name, _, rest = text.partition('<')
        return {'name': name.strip(), 'address': rest.rstrip('>').strip() or name.strip()}

    @classmethod
    def to_message(cls, raw):
        marks = [cls.FOLDERS.get(raw['folder'], 'archive')] + (['unread'] if not raw['seen'] else []) + (['starred'] if raw['flagged'] else [])
        return message(raw['uid'], raw['conversation'], subject=raw['title'], sender=cls._who(raw['sender']), to=[cls._who(t) for t in raw['recipients']],
                       sent_epoch=raw['received'], snippet=raw['preview'], labels=marks, provider_labels=[{'id': 'folder/' + raw['folder'], 'name': raw['folder']}],
                       has_attachments=raw['attachment_count'] > 0)

    @staticmethod
    def to_event(raw, calendar_id):
        from datetime import datetime, timezone
        day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%d')
        when = ({'all_day': True, 'start_date': day(raw['begin']), 'end_date': day(raw['finish'])} if raw['whole_day'] else {'timezone': raw.get('tz')})
        return event(raw['key'], calendar_id, title=raw['name'], start_epoch=raw['begin'], end_epoch=raw['finish'], series_id=raw.get('series'), exception=raw.get('moved', False),
                     cancelled=raw.get('deleted', False), place=raw.get('where', ''), version=str(raw.get('rev', '')),
                     attendees=[{**Postbox._who(p), 'response': 'accepted' if p in raw.get('yes', []) else 'needs_action'} for p in raw.get('people', [])], **when)

    def calendars(self, credential):
        world = self.world(credential); world.enter('calendars')
        return [calendar('main', name='Kalender', access='owner', primary=True)]

    def mail_changes(self, credential, cursor, since_epoch, labels, limit):
        world = self.world(credential); world.enter('mail_changes')
        folders = None if labels is None else {label.split('/', 1)[1] for label in labels}
        wanted = lambda raw: folders is None or raw['folder'] in folders
        kind, _, rest = (cursor or 'fill:0:%d' % world.number).partition(':')
        if world.expire_cursors and cursor:
            world.expire_cursors = False
            raise ResyncRequired()
        if kind == 'fill':
            offset, number = (int(x) for x in rest.split(':'))
            every = [m for m in sorted(world.mail.values(), key=lambda m: m['uid']) if (m['received'] >= since_epoch or m['flagged']) and wanted(m)]
            part = every[offset:offset + min(limit, 2)]
            done = offset + len(part) >= len(every)
            return Changes([self.to_message(m) for m in part], [], f'seq:{number}' if done else f'fill:{offset + len(part)}:{number}', not done)
        changed = sorted({uid for number, uid in world.mail_log if number > int(rest)})
        return Changes([self.to_message(world.mail[u]) for u in changed if u in world.mail and wanted(world.mail[u])],
                       [u for u in changed if u not in world.mail or not wanted(world.mail[u])], f'seq:{world.number}', False)

    def mail_body(self, credential, message_id):
        world = self.world(credential); world.enter('mail_body')
        if message_id not in world.mail:
            raise ProviderError(404)
        raw = world.bodies.get(message_id, {})
        return body(raw.get('text', ''), raw.get('html', '<p>Inhalt von ' + message_id + '</p>'), [])

    def mail_search(self, credential, query, labels, position, limit):
        raise ProviderError(404, 'unsupported')

    def event_changes(self, credential, calendar_id, cursor, start_epoch, end_epoch, limit):
        world = self.world(credential); world.enter('event_changes')
        events = world.events.get('main', {})
        # This provider has no "what changed since": every sync reads the window again, and says what is gone by leaving it out. The adapter works out the removals.
        known = set(json.loads(cursor)) if cursor else set()
        now = {e['key'] for e in events.values() if e['finish'] >= start_epoch and e['begin'] <= end_epoch}
        return Changes([self.to_event(e, calendar_id) for e in events.values() if e['key'] in now], sorted(known - now), json.dumps(sorted(now)), False)


def declaration(provider, label, caps):
    return Declaration(provider=provider, label=label, auth='token', scopes=('mail', 'calendar'), resource_kinds=('mailbox', 'label', 'calendar'), record_kinds=(),
                       read_operations=(), write_kinds=(), paging='offset', implementation='first_party', reason='A fake provider for tests.',
                       caps=Caps(pages=5, items=50, bytes=200_000, seconds=10.0), hub=caps, several_accounts=True)


ALPHA = declaration('alpha', 'Alpha Mail', HubCaps(mail=True, calendar=True, mail_search=True, labels='labels'))
POSTBOX = declaration('postbox', 'Postbox', HubCaps(mail=True, calendar=True, mail_search=False, incremental=False, labels='folders'))


class HubBase(unittest.TestCase):
    ACCOUNTS = ('a', 'b')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize(); self.now = 2000000000
        clock = lambda: self.now
        with self.store.connect() as con:
            for a in self.ACCOUNTS:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
        key = Keyring.generate().split(':', 1)
        self.custody = SealedCustody(self.store, Keyring({key[0]: __import__('base64').urlsafe_b64decode(key[1] + '=' * (-len(key[1]) % 4))}, key[0]), clock=clock)
        self.alpha_worlds, self.postbox_worlds = {}, {}
        self.registry = Registry()
        self.registry.register(ALPHA, lambda: Alpha(self.alpha_worlds))
        self.registry.register(POSTBOX, lambda: Postbox(self.postbox_worlds))
        self.connectors = ConnectorService(self.store, custody=self.custody, registry=self.registry, clock=clock)
        self.client = ConnectorClient(self.store, self.connectors, self.registry, clock=clock, sleep=lambda s: None)
        self.sync = HubSync(self.store, self.connectors, self.client, clock=clock, page=50, pages_per_run=20, interval=300)
        self.hub = HubService(self.store, self.connectors, self.client, self.sync, clock=clock)
        self.a, self.b = (Principal(x, 'actor-' + x, 'customer') for x in self.ACCOUNTS[:2])

    # -- connecting ---------------------------------------------------------------------------------------------------------------------------------
    def alpha(self, who=None, identity='me@alpha.test', grants=(('mailbox', '*'), ('calendar', '*'))) -> tuple:
        who = who or self.a
        world = self.alpha_worlds.setdefault(identity, World())
        connection = self.connectors.connect_declared(who, 'alpha', identity, tokens={'token': 'alpha-ok', 'who': identity}, scopes=('mail', 'calendar'))
        if grants:
            self.connectors.set_grants(who, connection, [{'kind': k, 'id': i} for k, i in grants])
        return connection, world

    def postbox(self, who=None, identity='ich@postbox.test', grants=(('mailbox', '*'), ('calendar', '*'))) -> tuple:
        who = who or self.a
        world = self.postbox_worlds.setdefault(identity, World())
        connection = self.connectors.connect_declared(who, 'postbox', identity, tokens={'secret': 'postbox-ok', 'owner': identity}, scopes=('mail', 'calendar'))
        if grants:
            self.connectors.set_grants(who, connection, [{'kind': k, 'id': i} for k, i in grants])
        return connection, world

    # -- filling the fake providers ---------------------------------------------------------------------------------------------------------------------
    def alpha_mail(self, world, n, *, thread=None, subject=None, labels=('L_IN', 'L_NEW'), age_days=1, sender=('Ann', 'ann@x.test'), files=()):
        mid = f'm-{n:04d}'
        world.mail[mid] = {'id': mid, 'threadId': thread or f't-{n:04d}', 'subject': subject or f'Alpha subject {n}', 'snippet': f'alpha preview {n}',
                           'from': {'name': sender[0], 'email': sender[1]}, 'to': [{'name': 'Me', 'email': 'me@alpha.test'}], 'internalDate': (self.now - age_days * DAY) * 1000,
                           'labelIds': list(labels), 'files': list(files)}
        world.mail_log.append((world.bump(), mid))
        return mid

    def postbox_mail(self, world, n, *, conversation=None, title=None, folder='Posteingang', age_days=1, seen=False, flagged=False, sender='Bernd <bernd@y.test>'):
        uid = f'{n}@postbox'
        world.mail[uid] = {'uid': uid, 'conversation': conversation or f'conv:{n}', 'title': title or f'Postbox Betreff {n}', 'preview': f'postbox vorschau {n}', 'sender': sender,
                           'recipients': ['Ich <ich@postbox.test>'], 'received': self.now - age_days * DAY, 'folder': folder, 'seen': seen, 'flagged': flagged, 'attachment_count': 0}
        world.mail_log.append((world.bump(), uid))
        return uid

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]

    def run_sync(self, times=1):
        out = None
        for _ in range(times):
            with self.store.connect() as con:
                con.execute('UPDATE hub_sync SET next_epoch=0')
            out = self.sync.tick(limit=50)
        return out
