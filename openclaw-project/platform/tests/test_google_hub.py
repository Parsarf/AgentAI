"""Google as a mail and calendar provider, against a fake Google that answers like the real REST APIs (the shapes are from Google's own documentation). Proves the
conversion, the sign-in, the first fill, the incremental sync, the resync, the picker, and that nothing but reading is ever asked of Google."""
import base64
import json
import unittest
from urllib.parse import parse_qs, parse_qsl, urlsplit

from agentai_platform import google_hub
from agentai_platform.connector_kit import ProviderError
from agentai_platform.connector_refresh import ConnectorRefresher, RefreshFault
from agentai_platform.connectors import ConnectorError
from agentai_platform.google_hub import GoogleAdapter, to_body, to_calendar, to_event, to_message
from tests.hub_fixture import DAY, HubBase

b64 = lambda text: base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')
SCOPES = f'{google_hub.MAIL_SCOPE} {google_hub.CALENDAR_SCOPE} openid https://www.googleapis.com/auth/userinfo.email'


class FakeGoogle:
    """One Google account. `calls` records every request (method and path): the proof of what was asked."""
    def __init__(self, email='dana@gmail.test', now=2000000000):
        self.email, self.now = email, now
        self.messages, self.history, self.history_id, self.oldest_history = {}, [], 1000, 0
        self.labels = [{'id': 'INBOX', 'name': 'INBOX', 'type': 'system'}, {'id': 'SENT', 'name': 'SENT', 'type': 'system'}, {'id': 'UNREAD', 'name': 'UNREAD', 'type': 'system'},
                       {'id': 'STARRED', 'name': 'STARRED', 'type': 'system'}, {'id': 'CATEGORY_UPDATES', 'name': 'CATEGORY_UPDATES', 'type': 'system'},
                       {'id': 'Label_7', 'name': 'Clients/Northwind', 'type': 'user'}]
        self.calendars = [{'id': email, 'summary': email, 'timeZone': 'America/New_York', 'accessRole': 'owner', 'primary': True},
                          {'id': 'team@group.calendar.google.com', 'summary': 'Team', 'accessRole': 'reader'}]
        self.events, self.sync_tokens, self.event_version = {}, {}, 0
        self.access, self.refresh, self.scope = 'at-1', 'rt-1', SCOPES
        self.calls, self.fail, self.gone = [], [], False

    # -- filling ------------------------------------------------------------------------------------------------------------------------------
    def mail(self, n, *, thread=None, labels=('INBOX', 'UNREAD'), age_days=1, subject=None, sender='Ann Lee <ann@x.test>', files=()):
        mid = f'18c{n:05x}'
        parts = [{'mimeType': 'text/plain', 'body': {'data': b64(f'Plain text of {mid}')}}, {'mimeType': 'text/html', 'body': {'data': b64(f'<p>Markup of <b>{mid}</b></p>')}}]
        parts += [{'mimeType': 'application/pdf', 'filename': name, 'body': {'attachmentId': 'att-' + name, 'size': 2048}} for name in files]
        self.messages[mid] = {'id': mid, 'threadId': thread or mid, 'labelIds': list(labels), 'snippet': f'Preview of {n} &amp; more', 'internalDate': str((self.now - int(age_days * DAY)) * 1000),
                              'payload': {'mimeType': 'multipart/mixed', 'headers': [{'name': 'From', 'value': sender}, {'name': 'To', 'value': f'Dana <{self.email}>, "Lee, Bo" <bo@y.test>'},
                                                                                     {'name': 'Subject', 'value': subject or f'Subject {n}'}, {'name': 'Date', 'value': 'Tue, 17 May 2033 10:00:00 +0000'}],
                                          'parts': parts}}
        self.note('messagesAdded', mid)
        return mid

    def note(self, kind, mid):
        self.history_id += 1
        self.history.append({'id': str(self.history_id), kind: [{'message': {'id': mid}}]})

    def event(self, eid, calendar=None, **fields):
        self.event_version += 1
        raw = {'id': eid, 'status': 'confirmed', 'etag': f'"{self.event_version}"', 'htmlLink': 'https://www.google.com/calendar/event?eid=' + eid, 'updated': '2033-05-17T09:00:00.000Z',
               'creator': {'email': self.email}, 'organizer': {'email': self.email, 'self': True}, **fields, '_v': self.event_version}
        self.events.setdefault(calendar or self.email, {})[eid] = raw
        return raw

    # -- answering ----------------------------------------------------------------------------------------------------------------------------
    def __call__(self, method, url, headers, data=None):
        parts = urlsplit(url)
        self.calls.append((method, parts.netloc + parts.path))
        if self.fail:
            return self.fail.pop(0)
        if parts.netloc == 'oauth2.googleapis.com':
            return self._token(dict(parse_qsl(data.decode())))
        if headers.get('Authorization') != 'Bearer ' + self.access:
            return self._error(401, 'authError')
        query = parse_qs(parts.query)
        one = lambda key, default=None: query.get(key, [default])[0]
        path = parts.path
        if path.endswith('/users/me/profile'):
            return self._ok({'emailAddress': self.email, 'historyId': str(self.history_id)})
        if path.endswith('/users/me/labels'):
            return self._ok({'labels': self.labels})
        if path.endswith('/users/me/messages'):
            return self._list(one('q', ''), query.get('labelIds', []), int(one('maxResults', 100)), one('pageToken'))
        if '/users/me/messages/' in path:
            raw = self.messages.get(path.rsplit('/', 1)[1])
            if raw is None:
                return self._error(404, 'notFound')
            if one('format') == 'metadata':
                wanted = {h.lower() for h in query.get('metadataHeaders', [])}
                return self._ok({**raw, 'payload': {'mimeType': raw['payload']['mimeType'], 'headers': [h for h in raw['payload']['headers'] if h['name'].lower() in wanted],
                                                    'parts': [{'filename': p.get('filename', ''), 'body': {k: v for k, v in p['body'].items() if k != 'data'}} for p in raw['payload']['parts']]}})
            return self._ok(raw)
        if path.endswith('/users/me/history'):
            start = int(one('startHistoryId'))
            if start < self.oldest_history:
                return self._error(404, 'notFound')
            return self._ok({'history': [h for h in self.history if int(h['id']) > start], 'historyId': str(self.history_id)})
        if path.endswith('/users/me/calendarList'):
            return self._ok({'items': self.calendars})
        if path.endswith('/events'):
            calendar = path.split('/calendars/')[1].rsplit('/', 1)[0].replace('%40', '@')
            if calendar not in [c['id'] for c in self.calendars]:
                return self._error(404, 'notFound')
            if one('syncToken'):
                if self.gone:
                    self.gone = False
                    return self._error(410, 'fullSyncRequired')
                if one('timeMin') or one('timeMax'):
                    return self._error(400, 'badRequest')                    # as Google does: no time bounds together with a sync token
                since = self.sync_tokens[one('syncToken')]
                items = [e for e in self.events.get(calendar, {}).values() if e['_v'] > since]
            else:
                if one('singleEvents') != 'true' or one('showDeleted') != 'true':
                    return self._error(400, 'badRequest')
                items = [e for e in self.events.get(calendar, {}).values() if e['status'] != 'cancelled' or e.get('recurringEventId')]
            token = f'sync-{len(self.sync_tokens)}'
            self.sync_tokens[token] = self.event_version
            return self._ok({'items': [{k: v for k, v in e.items() if k != '_v'} for e in items], 'nextSyncToken': token})
        return self._error(404, 'notFound')

    def _list(self, q, labels, size, token):
        found = sorted(self.messages.values(), key=lambda m: m['id'])
        if q.startswith('{after:'):
            after = int(q.split('after:')[1].split()[0])
            found = [m for m in found if int(m['internalDate']) // 1000 >= after or 'STARRED' in m['labelIds']]
        elif q:
            words = q.split(' {')[0].lower()
            found = [m for m in found if words in (m['payload']['headers'][2]['value'] + ' ' + m['snippet']).lower()]
            if ' {label:' in q:
                names = {'label:' + google_hub._search_label(l['id'], {x['id']: x['name'] for x in self.labels if x['type'] == 'user'}): l['id'] for l in self.labels}
                wanted = {names.get(part) for part in q.split('{')[1].rstrip('}').split()}
                found = [m for m in found if wanted & set(m['labelIds'])]
        for label in labels:
            found = [m for m in found if label in m['labelIds']]
        start = int(token or 0)
        part = found[start:start + min(size, 2)]
        return self._ok({'messages': [{'id': m['id'], 'threadId': m['threadId']} for m in part], 'resultSizeEstimate': len(found),
                         **({'nextPageToken': str(start + len(part))} if start + len(part) < len(found) else {})})

    def _token(self, form):
        if form.get('client_id') != 'client-1' or form.get('client_secret') != 'secret-1':
            return self._error(401, 'invalid_client', oauth=True)
        if form['grant_type'] == 'authorization_code':
            if form.get('code') != 'good-code' or not form.get('code_verifier') or form.get('redirect_uri') != 'https://app.test/v1/hub/link/callback':
                return self._error(400, 'invalid_grant', oauth=True)
            claims = b64(json.dumps({'email': self.email, 'email_verified': True, 'iss': 'https://accounts.google.com'}))
            return self._ok({'access_token': self.access, 'refresh_token': self.refresh, 'expires_in': 3599, 'scope': self.scope, 'token_type': 'Bearer', 'id_token': f'h.{claims}.s'})
        if form.get('refresh_token') != self.refresh:
            return self._error(400, 'invalid_grant', oauth=True)
        self.access = 'at-' + str(int(self.access.split('-')[1]) + 1)
        return self._ok({'access_token': self.access, 'expires_in': 3599, 'scope': self.scope, 'token_type': 'Bearer'})

    @staticmethod
    def _ok(body):
        return 200, {}, json.dumps(body).encode()

    @staticmethod
    def _error(status, reason, oauth=False):
        return status, {}, json.dumps({'error': reason} if oauth else {'error': {'code': status, 'errors': [{'reason': reason}], 'message': 'text a customer must never see'}}).encode()


class Conversion(unittest.TestCase):
    def test_a_message_becomes_the_neutral_message(self):
        g = FakeGoogle(); mid = g.mail(1, labels=('INBOX', 'UNREAD', 'STARRED', 'CATEGORY_UPDATES', 'Label_7'), files=['q3.pdf'])
        m = to_message(g.messages[mid], {'Label_7': 'Clients/Northwind'})
        self.assertEqual((m['subject'], m['snippet'], m['sender'], m['unread'], m['starred'], m['has_attachments']),
                         ('Subject 1', 'Preview of 1 & more', {'name': 'Ann Lee', 'address': 'ann@x.test'}, True, True, True))
        self.assertEqual(m['to'], [{'name': 'Dana', 'address': 'dana@gmail.test'}, {'name': 'Lee, Bo', 'address': 'bo@y.test'}])        # a comma inside a quoted name is one person
        self.assertEqual((m['labels'], m['provider_labels']), (['inbox', 'starred', 'unread'], [{'id': 'INBOX', 'name': 'Inbox'}, {'id': 'Label_7', 'name': 'Clients/Northwind'}]))
        self.assertEqual(m['sent_epoch'], g.now - DAY)
        archived = to_message({**g.messages[mid], 'labelIds': ['Label_7']})
        self.assertEqual(archived['labels'], ['archive'])
        self.assertEqual(to_message({'id': 'x', 'payload': {'headers': [{'name': 'Date', 'value': 'Tue, 17 May 2033 10:00:00 +0000'}]}})['sent_epoch'], 1999936800)      # no internal date: the Date header

    def test_a_body_is_its_text_its_markup_and_the_names_of_its_files(self):
        g = FakeGoogle(); mid = g.mail(2, files=['a.pdf', 'b.pdf'])
        found = to_body(g.messages[mid])
        self.assertEqual((found['text'], found['html']), (f'Plain text of {mid}', f'<p>Markup of <b>{mid}</b></p>'))
        self.assertEqual([(f['name'], f['size'], f['id']) for f in found['attachments']], [('a.pdf', 2048, 'att-a.pdf'), ('b.pdf', 2048, 'att-b.pdf')])
        nested = {'payload': {'mimeType': 'multipart/mixed', 'parts': [{'mimeType': 'multipart/alternative', 'parts': [{'mimeType': 'text/html', 'body': {'data': b64('<p>ünï</p>')}}]}]}}
        self.assertEqual(to_body(nested)['html'], '<p>ünï</p>')

    def test_events_timed_all_day_recurring_cancelled_and_busy_only(self):
        timed = to_event({'id': 'e1', 'summary': 'Standup', 'etag': '"3"', 'start': {'dateTime': '2033-05-18T09:00:00-04:00', 'timeZone': 'America/New_York'},
                          'end': {'dateTime': '2033-05-18T09:30:00-04:00'}, 'location': 'Room 4', 'hangoutLink': 'https://meet.google.com/abc', 'creator': {},
                          'organizer': {'email': 'ann@x.test', 'displayName': 'Ann'}, 'attendees': [{'email': 'dana@gmail.test', 'self': True, 'responseStatus': 'tentative'},
                                                                                                   {'email': 'bo@y.test', 'responseStatus': 'needsAction', 'optional': True}]}, 'cal')
        self.assertEqual((timed['start_epoch'], timed['end_epoch'] - timed['start_epoch'], timed['timezone'], timed['my_response'], timed['conference_url'], timed['version']),
                         (2000034000, 1800, 'America/New_York', 'tentative', 'https://meet.google.com/abc', '"3"'))
        self.assertEqual([(a['response'], a['optional']) for a in timed['attendees']], [('tentative', False), ('needs_action', True)])
        day = to_event({'id': 'e2', 'summary': 'Offsite', 'creator': {}, 'start': {'date': '2033-05-20'}, 'end': {'date': '2033-05-22'}}, 'cal')
        self.assertEqual((day['all_day'], day['start_date'], day['end_date']), (True, '2033-05-20', '2033-05-22'))
        moved = to_event({'id': 'e3_1', 'recurringEventId': 'e3', 'summary': 'Review', 'creator': {}, 'originalStartTime': {'dateTime': '2033-05-19T10:00:00Z'},
                          'start': {'dateTime': '2033-05-19T14:00:00Z'}, 'end': {'dateTime': '2033-05-19T15:00:00Z'}}, 'cal')
        usual = to_event({'id': 'e3_2', 'recurringEventId': 'e3', 'summary': 'Review', 'creator': {}, 'originalStartTime': {'dateTime': '2033-05-26T10:00:00Z'},
                          'start': {'dateTime': '2033-05-26T10:00:00Z'}, 'end': {'dateTime': '2033-05-26T11:00:00Z'}}, 'cal')
        gone = to_event({'id': 'e3_3', 'recurringEventId': 'e3', 'status': 'cancelled', 'originalStartTime': {'dateTime': '2033-06-02T10:00:00Z'}}, 'cal')
        self.assertEqual([(e['series_id'], e['exception'], e['cancelled']) for e in (moved, usual, gone)], [('e3', True, False), ('e3', False, False), ('e3', True, True)])
        self.assertIsNone(to_event({'id': 'e4', 'status': 'cancelled'}, 'cal'))                    # a plain deleted event is simply removed
        busy = to_event({'id': 'e5', 'start': {'dateTime': '2033-05-18T15:00:00Z'}, 'end': {'dateTime': '2033-05-18T16:00:00Z'}}, 'cal')
        self.assertEqual((busy['visibility'], busy['title']), ('busy', ''))
        self.assertEqual(to_calendar({'id': 'c', 'summary': 'Shared', 'summaryOverride': 'My name for it', 'accessRole': 'freeBusyReader'})['name'], 'My name for it')
        self.assertEqual(to_calendar({'id': 'c', 'accessRole': 'freeBusyReader'})['access'], 'busy')


class Connected(HubBase):
    """The whole path with the real engine and service, a fake Google and (always) a second, different provider beside it."""
    def setUp(self):
        super().setUp()
        self.g = FakeGoogle(now=self.now)
        google_hub.register(self.registry, self.g)
        self.connectors.catalog['google'] = None                      # the service built its catalogue before this provider was registered; `declared` reads the registry
        self.exchange = google_hub.exchanger('client-1', 'secret-1', self.g)
        self.redirect = 'https://app.test/v1/hub/link/callback'

    def sign_in(self, who=None, grants=(('mailbox', '*'), ('calendar', '*'))):
        who = who or self.a
        started = self.connectors.start_link(who, 'google', self.redirect)
        url = google_hub.authorize_url('client-1', self.redirect, started['state'], started['challenge'])
        connection = self.connectors.finish_link(who, started['state'], 'good-code', self.redirect, self.exchange, needs_any=(google_hub.MAIL_SCOPE, google_hub.CALENDAR_SCOPE))
        if grants:
            self.connectors.set_grants(who, connection, [{'kind': k, 'id': i} for k, i in grants])
        return connection, url

    def test_signing_in_asks_only_to_read_and_records_which_account_it_is(self):
        connection, url = self.sign_in(grants=())
        asked = parse_qs(urlsplit(url).query)
        self.assertEqual(asked['scope'], [f'{google_hub.MAIL_SCOPE} {google_hub.CALENDAR_SCOPE} openid email'])
        self.assertEqual((asked['access_type'], asked['prompt'], asked['code_challenge_method'], asked['response_type']), (['offline'], ['consent'], ['S256'], ['code']))
        for word in ('send', 'modify', 'compose', 'insert', 'calendar.events', 'mail.google.com'):
            self.assertNotIn(word, asked['scope'][0])
        row = self.rows('SELECT identity_label,state,granted_scopes,expires_epoch,secret_ref FROM connector_connections WHERE id=?', (connection,))[0]
        self.assertEqual((row['identity_label'], row['state'], row['expires_epoch']), ('dana@gmail.test', 'connected', self.now + 3599))
        self.assertNotIn('at-1', json.dumps(self.rows('SELECT * FROM connector_connections')))               # the tokens are in custody, not in a row a view reads
        self.assertEqual(self.rows('SELECT 1 FROM connector_grants WHERE connection_id=?', (connection,)), [])    # and it can reach nothing until its customer chooses
        self.run_sync()
        self.assertEqual([c for c in self.g.calls if 'gmail' in c[1] or 'calendar' in c[1]], [])

    def test_a_sign_in_cannot_be_replayed_used_by_someone_else_or_finished_with_a_bad_code(self):
        started = self.connectors.start_link(self.a, 'google', self.redirect)
        for who, state, code, redirect in ((self.b, started['state'], 'good-code', self.redirect), (self.a, 'another-state', 'good-code', self.redirect)):
            with self.assertRaises(ConnectorError):
                self.connectors.finish_link(who, state, code, redirect, self.exchange)
        with self.assertRaises(ConnectorError):
            self.connectors.finish_link(self.a, started['state'], 'bad-code', self.redirect, self.exchange)
        with self.assertRaises(ConnectorError):                                                              # the state was burnt by the failed attempt
            self.connectors.finish_link(self.a, started['state'], 'good-code', self.redirect, self.exchange)
        self.assertEqual(self.rows('SELECT 1 FROM connector_connections'), [])
        self.g.scope = 'openid https://www.googleapis.com/auth/userinfo.email'                               # the customer unticked both boxes at Google
        again = self.connectors.start_link(self.a, 'google', self.redirect)
        with self.assertRaises(ConnectorError):
            self.connectors.finish_link(self.a, again['state'], 'good-code', self.redirect, self.exchange, needs_any=(google_hub.MAIL_SCOPE, google_hub.CALENDAR_SCOPE))
        self.g.scope = SCOPES + ' https://mail.google.com/'                                                  # more than was declared is refused, never stored
        wide = self.connectors.start_link(self.a, 'google', self.redirect)
        with self.assertRaises(ConnectorError):
            self.connectors.finish_link(self.a, wide['state'], 'good-code', self.redirect, self.exchange)
        self.assertEqual(self.rows('SELECT 1 FROM connector_connections'), [])

    def test_the_picker_offers_all_mail_the_customers_labels_and_each_calendar(self):
        connection, _ = self.sign_in(grants=())
        offered = [(r['kind'], r['id'], r['name']) for r in self.client.resources(self.a, connection)]
        self.assertEqual(offered, [('mailbox', '*', 'All mail'), ('label', 'INBOX', 'Inbox'), ('label', 'SENT', 'Sent'), ('label', 'Label_7', 'Clients/Northwind'),
                                   ('calendar', 'dana@gmail.test', 'dana@gmail.test'), ('calendar', 'team@group.calendar.google.com', 'Team')])

    def test_mail_and_calendars_fill_follow_changes_and_show_beside_another_provider(self):
        for n in range(1, 6):
            self.g.mail(n, age_days=n)
        self.g.mail(6, age_days=300); self.g.mail(7, age_days=300, labels=('INBOX', 'STARRED'))
        self.g.mail(8, thread='18c00001', age_days=0.5, labels=('SENT',), sender='Dana <dana@gmail.test>')
        self.g.event('e1', summary='Standup', start={'dateTime': '2033-05-18T13:00:00Z'}, end={'dateTime': '2033-05-18T13:30:00Z'})
        self.g.event('b1', 'team@group.calendar.google.com', start={'dateTime': '2033-05-18T15:00:00Z'}, end={'dateTime': '2033-05-18T16:00:00Z'})
        del self.g.events['team@group.calendar.google.com']['b1']['creator']
        connection, _ = self.sign_in()
        other, world = self.postbox()
        self.postbox_mail(world, 1, age_days=0.2)
        self.run_sync()
        listed = self.hub.threads(self.a, label='all')['threads']
        self.assertEqual([t['id'] for t in listed], ['conv:1', '18c00001', '18c00002', '18c00003', '18c00004', '18c00005', '18c00006', '18c00007'])       # one list, newest first, however old
        first = listed[1]
        self.assertEqual((first['message_count'], first['labels'], first['people'][0]), (2, ['inbox', 'sent', 'unread'], {'name': 'Ann Lee', 'address': 'ann@x.test'}))
        self.assertEqual([c['name'] for c in self.hub.calendars(self.a) if c['connection_id'] == connection], ['dana@gmail.test', 'Team'])
        day = self.hub.events(self.a, self.now, self.now + DAY, connections=[connection])['events']
        self.assertEqual([(e['title'], e['busy_only']) for e in day], [('Standup', False), ('', True)])
        # changes: a new message, a deleted one, one archived (its label removed), a moved event and a deleted event
        new = self.g.mail(9, age_days=0)
        del self.g.messages['18c00002']; self.g.note('messagesDeleted', '18c00002')
        self.g.messages['18c00003']['labelIds'] = ['Label_7']; self.g.note('labelsRemoved', '18c00003')
        self.g.event('e1', summary='Standup (moved)', start={'dateTime': '2033-05-18T14:00:00Z'}, end={'dateTime': '2033-05-18T14:30:00Z'})
        self.g.event('e2', summary='Lunch', start={'dateTime': '2033-05-18T16:00:00Z'}, end={'dateTime': '2033-05-18T17:00:00Z'})
        calls = len(self.g.calls)
        self.run_sync()
        ids = [t['id'] for t in self.hub.threads(self.a, label='inbox', connections=[connection])['threads']]
        self.assertEqual(ids, [new, '18c00001', '18c00004', '18c00005', '18c00006', '18c00007'])
        self.assertEqual([t['id'] for t in self.hub.threads(self.a, label='archive', connections=[connection])['threads']], ['18c00003'])
        self.assertEqual([e['title'] for e in self.hub.events(self.a, self.now, self.now + DAY, connections=[connection])['events']], ['Standup (moved)', '', 'Lunch'])
        used = [c[1].rsplit('/', 1)[-1] for c in self.g.calls[calls:]]
        self.assertIn('history', used); self.assertNotIn('profile', used)                         # the change was read from the history, not by listing the mailbox again
        self.g.event('e2', status='cancelled')
        self.run_sync()
        self.assertEqual([e['title'] for e in self.hub.events(self.a, self.now, self.now + DAY, connections=[connection])['events']], ['Standup (moved)', ''])
        self.assertEqual(self.run_sync()['changed'], 0)                                           # and a sync with nothing new changes nothing

    def test_only_the_chosen_labels_are_ever_asked_for(self):
        self.g.mail(1, labels=('INBOX',)); self.g.mail(2, labels=('Label_7',)); self.g.mail(3, labels=('SENT',))
        connection, _ = self.sign_in(grants=(('label', 'Label_7'),))
        self.run_sync()
        self.assertEqual([t['id'] for t in self.hub.threads(self.a, label='all')['threads']], ['18c00002'])
        read = [c[1] for c in self.g.calls if '/messages/' in c[1]]
        self.assertEqual(read, ['gmail.googleapis.com/gmail/v1/users/me/messages/18c00002'])      # the other two were never read from Google, not even their headers
        self.assertFalse(any('calendar' in c[1] for c in self.g.calls))                           # and no calendar was granted, so none was asked for
        self.g.mail(4, labels=('INBOX',)); self.g.mail(5, labels=('Label_7', 'UNREAD'), age_days=0)
        self.run_sync()
        self.assertEqual([t['id'] for t in self.hub.threads(self.a, label='all')['threads']], ['18c00005', '18c00002'])
        self.assertEqual(self.rows("SELECT 1 FROM hub_messages WHERE id='18c00004'"), [])

    def test_an_expired_history_or_sync_token_refills_cleanly(self):
        for n in (1, 2, 3):
            self.g.mail(n)
        self.g.event('e1', summary='Standup', start={'dateTime': '2033-05-18T13:00:00Z'}, end={'dateTime': '2033-05-18T13:30:00Z'})
        connection, _ = self.sign_in()
        self.run_sync()
        self.g.oldest_history, self.g.gone = self.g.history_id + 100, True
        self.g.mail(4); self.g.event('e2', summary='New', start={'dateTime': '2033-05-18T18:00:00Z'}, end={'dateTime': '2033-05-18T19:00:00Z'})
        self.run_sync(2)
        self.assertEqual(len(self.hub.threads(self.a, label='all')['threads']), 4)
        self.assertEqual(len(self.rows('SELECT 1 FROM hub_messages')), 4)
        self.assertEqual([e['title'] for e in self.hub.events(self.a, self.now, self.now + DAY)['events']], ['Standup', 'New'])
        self.assertEqual(self.rows('SELECT last_error FROM hub_sync WHERE last_error IS NOT NULL'), [])

    def test_opening_a_message_and_searching_older_mail(self):
        mid = self.g.mail(1, files=['q3.pdf']); self.g.mail(2, subject='Old invoice 2031', age_days=700); self.g.mail(3, subject='Old invoice 2030', age_days=900, labels=('Label_7',))
        connection, _ = self.sign_in()
        self.run_sync()
        opened = self.hub.thread(self.a, connection, mid)['messages'][0]['body']
        self.assertEqual((opened['html'], [f['name'] for f in opened['attachments']]), (f'<p>Markup of <b>{mid}</b></p>', ['q3.pdf']))
        found = self.hub.search_older(self.a, connection, 'old invoice')
        self.assertEqual((sorted(m['subject'] for m in found['messages']), found['page']['complete']), (['Old invoice 2030', 'Old invoice 2031'], True))
        self.connectors.set_grants(self.a, connection, [{'kind': 'label', 'id': 'Label_7'}])
        self.assertEqual([m['subject'] for m in self.hub.search_older(self.a, connection, 'old invoice')['messages']], ['Old invoice 2030'])       # held to what was chosen

    def test_faults_become_the_six_kinds_and_never_carry_googles_text(self):
        self.g.mail(1)
        connection, _ = self.sign_in()
        self.run_sync()
        self.g.fail = [(429, {'Retry-After': '30'}, b'{"error":{"errors":[{"reason":"rateLimitExceeded"}],"message":"secret words"}}')]
        self.run_sync()
        self.assertEqual([(r['last_error'], r['state']) for r in self.rows('SELECT last_error,state FROM hub_sync WHERE last_error IS NOT NULL')], [('retry_later', 'waiting')])
        self.g.access = 'at-revoked-9'                                                             # Google no longer accepts the token
        self.run_sync()
        self.assertEqual(self.hub.accounts(self.a)[0]['state'], 'needs_you')
        self.assertNotIn('secret words', json.dumps(self.rows('SELECT * FROM hub_sync') + self.rows('SELECT * FROM connector_freshness')))
        with self.assertRaises(ProviderError):
            google_hub.default_http('GET', 'https://evil.test/gmail/v1/users/me/profile', {})      # the adapter speaks to Google's hosts only
        with self.assertRaises(ProviderError):
            google_hub.default_http('GET', 'http://gmail.googleapis.com/x', {})

    def test_the_access_token_is_renewed_before_it_ends_and_a_withdrawn_grant_ends_the_connection(self):
        connection, _ = self.sign_in()
        refresh = google_hub.refresher('client-1', 'secret-1', self.g)
        refresher = ConnectorRefresher(self.store, self.connectors, {'google': refresh}, clock=lambda: self.now)
        self.now += 3200                                                                           # inside the last ten minutes of the hour
        self.assertEqual([refresher.refresh(row) for row in refresher.due()], ['refreshed'])
        self.g.mail(1)
        self.run_sync()
        self.assertEqual(len(self.hub.threads(self.a, label='all')['threads']), 1)                 # the new token works
        self.g.refresh = 'rt-withdrawn'
        with self.assertRaises(RefreshFault) as caught:
            refresh({'refresh_token': 'rt-1'})
        self.assertEqual(caught.exception.kind, 'revoked')

    def test_mail_is_set_up_even_when_the_calendars_cannot_be_listed_right_now(self):
        self.g.mail(1)
        connection, _ = self.sign_in()
        self.g.fail = [(503, {}, b'{}')]                                                             # the first call, the calendar list, fails
        self.run_sync()
        self.assertEqual(len(self.hub.threads(self.a, label='all')['threads']), 1)
        self.assertEqual(self.hub.calendars(self.a), [])
        self.run_sync()                                                                            # and the calendars arrive on the next pass
        self.assertEqual(len(self.hub.calendars(self.a)), 2)

    def test_a_large_mailbox_fills_newest_first_in_pages_read_several_at_a_time(self):
        for n in range(1, 131):
            self.g.mail(n, age_days=n * 20)                                                        # ten years of mail
        connection, _ = self.sign_in(grants=(('mailbox', '*'),))
        self.run_sync(8)
        self.assertEqual(self.rows('SELECT count(*) AS n FROM hub_messages')[0]['n'], 130)         # all of it, however old
        self.assertEqual(self.rows("SELECT filled FROM hub_sync WHERE domain='mail'")[0]['filled'], 1)
        self.assertEqual(self.hub.threads(self.a, label='all', limit=1)['threads'][0]['id'], '18c00001')      # the newest is first

    def test_google_is_reached_over_ipv4_first(self):
        import socket
        from unittest.mock import patch
        asked = []

        def lookup(host, port, family=0, *rest, **more):
            asked.append(family)
            raise OSError('stop here')
        with patch('socket.getaddrinfo', lookup), self.assertRaises(ProviderError):
            google_hub.default_http('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/profile', {})
        self.assertEqual(asked[0], socket.AF_INET)                                                 # the first thing tried is an IPv4 address

    def test_nothing_but_reading_is_ever_asked_of_google(self):
        self.g.mail(1, files=['a.pdf']); self.g.event('e1', summary='S', start={'dateTime': '2033-05-18T13:00:00Z'}, end={'dateTime': '2033-05-18T13:30:00Z'})
        connection, _ = self.sign_in()
        self.run_sync(2)
        self.hub.thread(self.a, connection, '18c00001'); self.hub.search_older(self.a, connection, 'subject'); self.client.resources(self.a, connection)
        methods = {(method, where) for method, where in self.g.calls if method != 'GET'}
        self.assertEqual(methods, {('POST', 'oauth2.googleapis.com/token')})                       # the only POST is the sign-in itself
        self.assertEqual(self.g.messages['18c00001']['labelIds'], ['INBOX', 'UNREAD'])             # opening it did not mark it read at Google
        self.assertEqual(google_hub.DECLARATION.write_kinds, ())
        caps = google_hub.DECLARATION.hub
        self.assertFalse(caps.send or caps.organize or caps.mark_read or caps.event_write or caps.respond)


if __name__ == '__main__':
    unittest.main()


class ReadsArePaced(unittest.TestCase):
    """Gmail allows about 50 header reads a second per user. Unpaced, eight in flight made over 100 a second and Google refused the first fill (production, 2026-11-16)."""
    def test_reads_start_no_faster_than_the_rate(self):
        from agentai_platform.google_hub import Pace
        waits = []
        pace = Pace(40, clock=lambda: 0.0, sleep=waits.append)          # time stands still: each wait says how far after the first read this one may start
        for _ in range(41):
            pace.wait()
        self.assertEqual(len(waits), 40)                                  # the first read starts at once
        self.assertAlmostEqual(waits[-1], 1.0, places=6)                  # the 41st a full second after the first: 40 a second

    def test_the_real_network_is_paced_and_a_test_fake_is_not(self):
        from agentai_platform import google_hub
        self.assertIs(google_hub.GoogleAdapter().pace, google_hub._READS)
        self.assertIsNone(google_hub.GoogleAdapter(lambda *a, **k: (200, {}, b'{}')).pace)
        self.assertLessEqual(google_hub.READS_PER_SECOND * 5, 250)      # a header read costs 5 of Gmail's 250 units a second per user

