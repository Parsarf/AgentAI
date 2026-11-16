"""The mail and calendar dashboard over HTTP (roadmap #D2 to #D4): off until the owner's switch is on, scoped to the signed-in account, read-only, and one list from two
different providers."""
import os
import tempfile
from unittest.mock import patch

from django.db import connection
from django.test import override_settings

from agentai_platform.connector_kit import Registry
from agentai_platform.security import Principal
from agentai_platform.vault import Keyring
from tests.hub_fixture import ALPHA, POSTBOX, Alpha, Postbox, World
from . import wiring
from .test_chat import ChatHTTPChecks

DAY = 86400


class Base(ChatHTTPChecks):
    ON = {'mail_calendar_dashboard'}

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        key = os.path.join(self.tmp.name, 'connector.key')
        with open(os.open(key, os.O_WRONLY | os.O_CREAT, 0o600), 'w') as handle:
            handle.write(Keyring.generate() + '\n')
        override = override_settings(CONNECTOR_KEY_FILE=key)
        override.enable(); self.addCleanup(override.disable)
        real = wiring.switch_on
        switch = patch.object(wiring, 'switch_on', lambda name: name in self.ON or real(name))
        switch.start(); self.addCleanup(switch.stop)
        self.alpha_worlds, self.postbox_worlds = {}, {}

        def registry(db=None):
            made = Registry()
            made.register(ALPHA, lambda: Alpha(self.alpha_worlds))
            made.register(POSTBOX, lambda: Postbox(self.postbox_worlds))
            return made
        fake = patch.object(wiring, 'connector_registry', registry)
        fake.start(); self.addCleanup(fake.stop)
        self.a, self.b = self.clients

    def rows(self, sql, args=()):
        with connection.cursor() as c:
            c.execute(sql, args)
            return c.fetchall()

    def principal(self, index=0):
        account = self.account_ids[index]
        return Principal(account, self.rows("SELECT actor_id FROM memberships WHERE account_id=%s AND status='active'", [account])[0][0], 'customer')

    def link(self, provider, identity, index=0):
        who, connectors = self.principal(index), wiring.connector_service()
        if provider == 'alpha':
            world = self.alpha_worlds.setdefault(identity, World())
            made = connectors.connect_declared(who, 'alpha', identity, tokens={'token': 'alpha-ok', 'who': identity}, scopes=('mail', 'calendar'))
        else:
            world = self.postbox_worlds.setdefault(identity, World())
            made = connectors.connect_declared(who, 'postbox', identity, tokens={'secret': 'postbox-ok', 'owner': identity}, scopes=('mail', 'calendar'))
        connectors.set_grants(who, made, [{'kind': 'mailbox', 'id': '*'}, {'kind': 'calendar', 'id': '*'}])
        return made, world

    def fill(self):
        import time
        now = int(time.time())
        self.ca, wa = self.link('alpha', 'me@alpha.test')
        self.cp, wp = self.link('postbox', 'ich@postbox.test')
        for n in (1, 2, 3):
            mid = f'm-{n:04d}'
            wa.mail[mid] = {'id': mid, 'threadId': f't-{n:04d}', 'subject': f'Alpha subject {n}', 'snippet': f'alpha preview {n}', 'from': {'name': 'Ann', 'email': 'ann@x.test'},
                            'to': [{'name': 'Me', 'email': 'me@alpha.test'}], 'internalDate': (now - n * DAY) * 1000, 'labelIds': ['L_IN', 'L_NEW'], 'files': []}
            uid = f'{n}@postbox'
            wp.mail[uid] = {'uid': uid, 'conversation': f'conv:{n}', 'title': f'Postbox Betreff {n}', 'preview': f'postbox vorschau {n}', 'sender': 'Bernd <bernd@y.test>',
                            'recipients': ['Ich <ich@postbox.test>'], 'received': now - n * DAY - 3600, 'folder': 'Posteingang', 'seen': False, 'flagged': False, 'attachment_count': 0}
        wa.calendars = {'work': {'summary': 'Work', 'role': 'owner', 'primary': True}}
        wa.events = {'work': {'e1': {'id': 'e1', 'summary': 'Standup', 'start': {'epoch': now + 3600}, 'end': {'epoch': now + 5400}, 'description': 'Daily'}}}
        wp.events = {'main': {'k1': {'key': 'k1', 'name': 'Zahnarzt', 'begin': now + 7200, 'finish': now + 9000, 'whole_day': False}}}
        wp.bodies['1@postbox'] = {'html': '<p>Hallo<script>x()</script><img src="https://track.test/p.gif"></p>'}
        sync = wiring.hub_services()[2]
        for _ in range(4):
            sync.tick(limit=50)
        self.now, self.wa, self.wp = now, wa, wp


class Dashboard(Base):
    def test_one_inbox_and_one_calendar_from_two_providers(self):
        self.fill()
        seen = self.a.get('/v1/hub', secure=True).json()
        self.assertEqual([(x['identity'], x['state'], x['mail']['filled'], x['capabilities']['labels']) for x in seen['accounts']],
                         [('me@alpha.test', 'working', True, 'labels'), ('ich@postbox.test', 'working', True, 'folders')])
        self.assertEqual((seen['counts']['unread'], seen['read_only'], [c['name'] for c in seen['calendars']]), (6, True, ['Work', 'Kalender']))
        page = self.a.get('/v1/hub/mail/threads?label=inbox&limit=4', secure=True).json()
        self.assertEqual([t['id'] for t in page['threads']], ['t-0001', 'conv:1', 't-0002', 'conv:2'])
        rest = self.a.get('/v1/hub/mail/threads', {'label': 'inbox', 'limit': 4, 'cursor': page['next']}, secure=True).json()
        self.assertEqual(([t['id'] for t in rest['threads']], rest['complete']), (['t-0003', 'conv:3'], True))
        only = self.a.get('/v1/hub/mail/threads', {'accounts': self.cp, 'q': 'betreff 2'}, secure=True).json()
        self.assertEqual([t['id'] for t in only['threads']], ['conv:2'])
        events = self.a.get('/v1/hub/events', {'start': self.now, 'end': self.now + DAY}, secure=True).json()
        self.assertEqual([e['title'] for e in events['events']], ['Standup', 'Zahnarzt'])
        one = self.a.get('/v1/hub/event', {'connection': self.ca, 'calendar': 'work', 'id': 'e1'}, secure=True).json()['event']
        self.assertEqual((one['title'], one['description']), ('Standup', 'Daily'))
        self.assertEqual([e['title'] for e in self.a.get('/v1/hub/events/search', {'q': 'zahn'}, secure=True).json()['events']], ['Zahnarzt'])

    def test_opening_a_thread_fetches_its_body_made_safe_and_ids_with_any_character_work(self):
        self.fill()
        opened = self.a.get('/v1/hub/mail/thread', {'connection': self.cp, 'id': 'conv:1'}, secure=True).json()
        body = opened['messages'][0]['body']
        self.assertEqual((body['html'], body['blocked_images'], opened['problem']), ('<p>Hallo</p>', 1, None))
        shown = self.a.get('/v1/hub/mail/message', {'connection': self.cp, 'id': '1@postbox', 'images': '1'}, secure=True).json()['message']['body']
        self.assertIn('track.test', shown['html'])
        self.assertEqual(self.post(self.a, '/v1/hub/settings', {'timezone': 'Europe/Berlin', 'allow_images_from': 'bernd@y.test'}).json()['settings'],
                         {'timezone': 'Europe/Berlin', 'image_senders': ['bernd@y.test']})
        self.assertEqual(self.post(self.a, '/v1/hub/settings', {'timezone': 'Mars/Olympus'}).status_code, 400)

    def test_another_account_gets_nothing_and_not_found(self):
        self.fill()
        self.assertEqual(self.b.get('/v1/hub', secure=True).json()['accounts'], [])
        self.assertEqual(self.b.get('/v1/hub/mail/threads?label=all', secure=True).json()['threads'], [])
        self.assertEqual(self.b.get('/v1/hub/mail/threads', {'label': 'all', 'accounts': self.ca}, secure=True).json()['threads'], [])
        self.assertEqual(self.b.get('/v1/hub/events', {'start': self.now, 'end': self.now + DAY}, secure=True).json()['events'], [])
        for path, query in (('/v1/hub/mail/thread', {'connection': self.ca, 'id': 't-0001'}), ('/v1/hub/mail/message', {'connection': self.ca, 'id': 'm-0001'}),
                            ('/v1/hub/event', {'connection': self.ca, 'calendar': 'work', 'id': 'e1'}), ('/v1/hub/mail/search-older', {'connection': self.ca, 'q': 'alpha'})):
            self.assertEqual(self.b.get(path, query, secure=True).status_code, 404, path)
        self.assertEqual(self.post(self.b, '/v1/hub/calendars', {'connection_id': self.ca, 'calendar_id': 'work', 'selected': False}).status_code, 404)
        self.assertEqual(self.post(self.b, '/v1/hub/refresh', {'connection_id': self.ca}).status_code, 404)

    def test_the_customers_own_choices_and_refresh(self):
        self.fill()
        changed = self.post(self.a, '/v1/hub/calendars', {'connection_id': self.cp, 'calendar_id': 'main', 'selected': False, 'colour': 'teal'})
        self.assertEqual([(c['selected'], c['colour']) for c in changed.json()['calendars'] if c['id'] == 'main'], [(False, 'teal')])
        self.assertEqual(self.post(self.a, '/v1/hub/calendars', {'connection_id': self.cp, 'calendar_id': 'main', 'colour': 'url(x)'}).status_code, 400)
        self.assertEqual(self.post(self.a, '/v1/hub/refresh', {}).json(), {'requested': 4})
        self.assertEqual(self.a.get('/v1/hub/events', {'start': 5, 'end': 1}, secure=True).status_code, 400)
        self.assertEqual(self.a.get('/v1/hub/mail/threads?label=nonsense', secure=True).status_code, 400)

    def test_nothing_in_the_dashboard_can_change_a_mailbox_or_a_calendar(self):
        self.fill()
        calls = (list(self.wa.calls), list(self.wp.calls))
        for path, body in (('/v1/hub/refresh', {}), ('/v1/hub/settings', {'timezone': 'UTC'}), ('/v1/hub/calendars', {'connection_id': self.ca, 'calendar_id': 'work', 'selected': True})):
            self.post(self.a, path, body)
        self.a.get('/v1/hub/mail/thread', {'connection': self.ca, 'id': 't-0001'}, secure=True)
        reads = {'calendars', 'mail_changes', 'event_changes', 'mail_body', 'mail_search'}
        self.assertLessEqual(set(self.wa.calls) | set(self.wp.calls), reads)                  # the adapters were asked only to read
        self.assertTrue(all(m['labelIds'] == ['L_IN', 'L_NEW'] for m in self.wa.mail.values()))      # opening a message did not mark it read at the provider
        self.assertEqual(ALPHA.hub.send or ALPHA.hub.organize or ALPHA.hub.event_write, False)
        del calls


class Off(Base):
    ON = set()

    def test_every_route_answers_feature_off_until_the_owner_switch_is_on(self):
        for path in ('/v1/hub', '/v1/hub/mail/threads', '/v1/hub/mail/labels', '/v1/hub/mail/thread', '/v1/hub/mail/message', '/v1/hub/mail/search-older', '/v1/hub/events',
                     '/v1/hub/event', '/v1/hub/events/search'):
            self.assertEqual(self.a.get(path, secure=True).status_code, 503, path)
        for path in ('/v1/hub/refresh', '/v1/hub/settings', '/v1/hub/calendars'):
            self.assertEqual(self.post(self.a, path, {}).status_code, 503, path)
        self.assertFalse(self.a.get('/v1/app', secure=True).json()['features']['dashboard'])
