"""Outlook through Microsoft Graph (roadmap Phase 6, #D8), against a fake Graph: signing in (and an organization that needs its administrator), reading folders,
messages and calendars into the neutral model with delta links, and the write cycle of the same kinds of change as Google: a send once under a lost answer, organizing a
conversation and putting it back, events created once, changed with their version, cancelled and answered."""
import base64
import json
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

from agentai_platform import microsoft_hub, microsoft_writes
from agentai_platform.connector_kit import ProviderError
from agentai_platform.google_mail_writes import marker


def jwt(claims):
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return f'h.{part}.s'


class FakeGraph:
    def __init__(self):
        self.folders = {'f-in': ('inbox', 'Inbox'), 'f-sent': ('sentitems', 'Sent Items'), 'f-arch': ('archive', 'Archive'), 'f-del': ('deleteditems', 'Deleted Items'),
                        'f-drafts': ('drafts', 'Drafts'), 'f-junk': ('junkemail', 'Junk Email'), 'f-proj': (None, 'Projects')}
        self.messages = {
            'm1': {'id': 'm1', 'conversationId': 'c1', 'subject': 'Hello', 'from': {'emailAddress': {'name': 'Ann', 'address': 'ann@x.test'}}, 'toRecipients': [{'emailAddress': {'address': 'me@outlook.test'}}],
                   'ccRecipients': [], 'receivedDateTime': '2033-05-17T10:00:00Z', 'bodyPreview': 'Hi there', 'isRead': False, 'flag': {'flagStatus': 'notFlagged'}, 'hasAttachments': True,
                   'parentFolderId': 'f-in', 'categories': ['Clients']},
            'm2': {'id': 'm2', 'conversationId': 'c2', 'subject': 'Plans', 'from': {'emailAddress': {'name': 'Bo', 'address': 'bo@y.test'}}, 'toRecipients': [], 'ccRecipients': [],
                   'receivedDateTime': '2033-05-16T10:00:00Z', 'bodyPreview': 'Plans', 'isRead': True, 'flag': {'flagStatus': 'flagged'}, 'hasAttachments': False, 'parentFolderId': 'f-proj', 'categories': []}}
        self.events = {
            'e1': {'id': 'e1', 'subject': 'Planning', 'start': {'dateTime': '2033-05-20T14:00:00.0000000', 'timeZone': 'UTC'}, 'end': {'dateTime': '2033-05-20T15:00:00.0000000', 'timeZone': 'UTC'},
                   'isAllDay': False, 'type': 'singleInstance', 'isOrganizer': True, 'organizer': {'emailAddress': {'address': 'me@outlook.test'}}, 'responseStatus': {'response': 'organizer'},
                   'attendees': [{'emailAddress': {'address': 'bo@y.test'}, 'type': 'required', 'status': {'response': 'accepted'}}], '@odata.etag': 'W/"1"', 'changeKey': '1', 'location': {'displayName': 'Room'}},
            'm-series': {'id': 'm-series', 'subject': 'Standup', 'type': 'seriesMaster', 'isOrganizer': True, 'start': {'dateTime': '2033-05-16T13:00:00', 'timeZone': 'UTC'},
                         'end': {'dateTime': '2033-05-16T13:30:00', 'timeZone': 'UTC'}, 'recurrence': {'pattern': {'type': 'weekly', 'interval': 1, 'daysOfWeek': ['monday']},
                                                                                                   'range': {'type': 'numbered', 'startDate': '2033-05-16', 'numberOfOccurrences': 6}},
                         '@odata.etag': 'W/"s1"', 'attendees': []},
            'o-2': {'id': 'o-2', 'subject': 'Standup', 'type': 'occurrence', 'seriesMasterId': 'm-series', 'originalStart': '2033-05-23T13:00:00Z', 'isOrganizer': True,
                    'start': {'dateTime': '2033-05-23T13:00:00', 'timeZone': 'UTC'}, 'end': {'dateTime': '2033-05-23T13:30:00', 'timeZone': 'UTC'}, '@odata.etag': 'W/"o2"', 'attendees': []}}
        self.calls, self.sent, self.lose_answer, self.version = [], [], False, 10

    def ok(self, body, status=200):
        return status, {}, json.dumps(body).encode()

    def __call__(self, method, url, headers, data=None):
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        path = unquote(parts.path).replace('/v1.0', '')
        self.calls.append((method, path))
        if parts.netloc == 'login.microsoftonline.com':
            form = {k: v[0] for k, v in parse_qs(data.decode()).items()}
            if form.get('code') == 'admin-needed':
                return 400, {}, json.dumps({'error': 'invalid_grant', 'error_description': 'AADSTS65001: The user or administrator has not consented'}).encode()
            return self.ok({'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600, 'scope': 'https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Calendars.Read openid email offline_access User.Read',
                            'id_token': jwt({'preferred_username': 'Me@Outlook.test'})})
        body = json.loads(data) if data else {}
        if path == '/me':
            return self.ok({'mail': 'me@outlook.test', 'userPrincipalName': 'me@outlook.test'})
        if path.startswith('/me/mailFolders/') and path.count('/') == 3 and method == 'GET':
            wk = path.rsplit('/', 1)[1]
            fid = next((i for i, (k, _) in self.folders.items() if k == wk), None)
            return self.ok({'id': fid, 'displayName': self.folders[fid][1]}) if fid else (404, {}, b'{"error":{"code":"ErrorItemNotFound"}}')
        if path == '/me/mailFolders':
            return self.ok({'value': [{'id': i, 'displayName': n, 'childFolderCount': 0} for i, (_, n) in self.folders.items()]})
        if path.endswith('/messages/delta'):
            fid = path.split('/')[3]
            return self.ok({'value': [m for m in self.messages.values() if m['parentFolderId'] == fid], '@odata.deltaLink': f'https://graph.microsoft.com/v1.0/delta-{fid}-2'})
        if path.startswith('/delta-'):
            return self.ok({'value': [{'id': 'gone-1', '@removed': {'reason': 'deleted'}}], '@odata.deltaLink': url})
        if path.endswith('/messages') and 'singleValueExtendedProperties' in q.get('$filter', ''):
            mark = q['$filter'].split("ep/value eq '")[1].rstrip("')")
            folder = path.split('/')[3]
            fid = next((i for i, (k, _) in self.folders.items() if k == folder), folder)
            return self.ok({'value': [{'id': m['id']} for m in self.messages.values() if m.get('mark') == mark and m['parentFolderId'] == fid]})
        if path.endswith('/events') and 'singleValueExtendedProperties' in q.get('$filter', ''):
            mark = q['$filter'].split("ep/value eq '")[1].rstrip("')")
            return self.ok({'value': [{'id': e['id']} for e in self.events.values() if e.get('mark') == mark]})
        if path == '/me/messages' and method == 'GET' and 'conversationId' in q.get('$filter', ''):
            cid = q['$filter'].split("'")[1]
            return self.ok({'value': [m for m in self.messages.values() if m['conversationId'] == cid]})
        if path == '/me/messages' and method == 'GET':
            return self.ok({'value': [m for m in self.messages.values() if q.get('$search', '').strip('"').lower() in m['subject'].lower()]})
        if path == '/me/messages' and method == 'POST':
            mid = f'd{len(self.messages)}'
            self.messages[mid] = {'id': mid, 'conversationId': 'new-' + mid, 'parentFolderId': 'f-drafts', 'subject': body.get('subject', ''), 'isRead': True, 'flag': {}, 'categories': [],
                                  'toRecipients': body.get('toRecipients', []), 'ccRecipients': body.get('ccRecipients', []), 'mark': body['singleValueExtendedProperties'][0]['value']}
            return self.ok({'id': mid}, 201)
        if path.endswith('/createReply'):
            src = self.messages[path.split('/')[3]]
            mid = f'd{len(self.messages)}'
            self.messages[mid] = {'id': mid, 'conversationId': src['conversationId'], 'parentFolderId': 'f-drafts', 'isRead': True, 'flag': {}, 'categories': [], 'toRecipients': [], 'ccRecipients': []}
            return self.ok({'id': mid}, 201)
        if path.endswith('/send') and method == 'POST':
            m = self.messages[path.split('/')[3]]
            m['parentFolderId'] = 'f-sent'
            self.sent.append(m['id'])
            if self.lose_answer:
                self.lose_answer = False
                raise ProviderError(0, 'unreachable')
            return 202, {}, b''
        if path.endswith('/move'):
            self.messages[path.split('/')[3]]['parentFolderId'] = body['destinationId']
            return self.ok({'id': path.split('/')[3]}, 201)
        if path.startswith('/me/messages/') and method == 'PATCH':
            m = self.messages[path.split('/')[3]]
            m.update({k: v for k, v in body.items() if k not in ('singleValueExtendedProperties',)})
            if body.get('singleValueExtendedProperties'):
                m['mark'] = body['singleValueExtendedProperties'][0]['value']
            return self.ok(m)
        if path.startswith('/me/messages/') and path.endswith('/attachments'):
            return self.ok({'value': [{'id': 'a1', 'name': 'q3.pdf', 'contentType': 'application/pdf', 'size': 2048, 'isInline': False}]})
        if path.startswith('/me/messages/') and '/attachments/' in path:
            return self.ok({'contentBytes': base64.b64encode(b'%PDF-1.4 x').decode()})
        if path.startswith('/me/messages/'):
            m = self.messages.get(path.split('/')[3])
            return self.ok({**m, 'body': {'contentType': 'html', 'content': '<p>Hi there</p>'}}) if m else (404, {}, b'{"error":{"code":"ErrorItemNotFound"}}')
        if path == '/me/calendars':
            return self.ok({'value': [{'id': 'cal-1', 'name': 'Calendar', 'canEdit': True, 'isDefaultCalendar': True, 'owner': {'address': 'me@outlook.test'}},
                                      {'id': 'cal-2', 'name': 'Holidays', 'canEdit': False, 'owner': {'address': 'holidays@outlook.test'}}]})
        if path.endswith('/calendarView/delta'):
            return self.ok({'value': list(self.events.values()) + [{'id': 'x-gone', '@removed': {'reason': 'deleted'}}], '@odata.deltaLink': 'https://graph.microsoft.com/v1.0/cv-delta'})
        if path.startswith('/me/calendars/') and path.endswith('/events') and method == 'POST':
            self.version += 1
            eid = f'ev{len(self.events)}'
            self.events[eid] = {'id': eid, 'subject': body['subject'], 'start': body['start'], 'end': body['end'], 'type': 'singleInstance', 'isOrganizer': True,
                                'attendees': [{**a, 'status': {'response': 'none'}} for a in body.get('attendees', [])], '@odata.etag': f'W/"{self.version}"',
                                'mark': body['singleValueExtendedProperties'][0]['value'], 'location': body.get('location', {})}
            if self.lose_answer:
                self.lose_answer = False
                raise ProviderError(0, 'unreachable')
            return self.ok(self.events[eid], 201)
        if path.startswith('/me/events/'):
            eid, verb = (path.split('/')[3], path.split('/')[4] if path.count('/') > 3 else None)
            e = self.events.get(eid)
            if e is None:
                return 404, {}, b'{"error":{"code":"ErrorItemNotFound"}}'
            if headers.get('If-Match') and headers['If-Match'] != e['@odata.etag']:
                return 412, {}, b'{"error":{"code":"PreconditionFailed"}}'
            if method == 'GET':
                return self.ok(e)
            self.version += 1
            if method == 'PATCH':
                e.update(body); e['@odata.etag'] = f'W/"{self.version}"'
                return self.ok(e)
            if method == 'DELETE' or verb == 'cancel':
                e['isCancelled'] = True
                self.events.pop(eid)
                return 204, {}, b''
            if verb in ('accept', 'decline', 'tentativelyAccept'):
                e['responseStatus'] = {'response': {'accept': 'accepted', 'decline': 'declined', 'tentativelyAccept': 'tentativelyAccepted'}[verb]}
                return 202, {}, b''
        return 404, {}, b'{"error":{"code":"ErrorItemNotFound"}}'


class SigningIn(unittest.TestCase):
    def test_only_reading_is_asked_first_and_an_organization_that_needs_its_administrator_is_said_plainly(self):
        url = microsoft_hub.authorize_url('cid', 'https://getlumina.pro/v1/hub/link/callback', 'st', 'ch')
        scopes = set(parse_qs(urlsplit(url).query)['scope'][0].split())
        self.assertEqual(scopes, {'Mail.Read', 'Calendars.Read', 'openid', 'email', 'offline_access', 'User.Read'})
        more = set(parse_qs(urlsplit(microsoft_hub.authorize_url('cid', 'r', 'st', 'ch', hint='me@outlook.test', add=['send'])).query)['scope'][0].split())
        self.assertIn('Mail.Send', more)
        g = FakeGraph()
        done = microsoft_hub.exchanger('cid', 'secret', g)('code', 'verifier', 'r')
        self.assertEqual((done.identity, sorted(done.granted_scopes)), ('me@outlook.test', ['Calendars.Read', 'Mail.Read', 'User.Read', 'email', 'offline_access', 'openid']))
        with self.assertRaises(ProviderError) as admin:
            microsoft_hub.exchanger('cid', 'secret', g)('admin-needed', 'verifier', 'r')
        self.assertEqual(admin.exception.code, 'admin_consent_required')


class Reading(unittest.TestCase):
    def setUp(self):
        self.g = FakeGraph()
        self.a = microsoft_hub.MicrosoftAdapter(self.g)
        self.cred = {'access_token': 'at'}

    def test_folders_messages_and_calendars_in_the_neutral_shape_with_delta_links(self):
        page = self.a.mail_changes(self.cred, None, 0, None, 50)
        by_id = {m['id']: m for m in page.items}
        self.assertEqual(sorted(by_id), ['m1', 'm2'])                                        # inbox, sent, archive and own folders; not junk, the bin or drafts
        self.assertEqual((sorted(by_id['m1']['labels']), by_id['m1']['thread_id']), (['inbox', 'unread'], 'c1'))
        self.assertIn({'id': 'category:Clients', 'name': 'Clients'}, by_id['m1']['provider_labels'])
        self.assertEqual(sorted(by_id['m2']['labels']), ['archive', 'starred'])                 # an own folder: archived, with the folder as its label
        again = self.a.mail_changes(self.cred, page.cursor, 0, None, 50)
        self.assertIn('gone-1', again.removed)
        content = self.a.mail_body(self.cred, 'm1')
        self.assertEqual((content['html'], content['attachments'][0]['name']), ('<p>Hi there</p>', 'q3.pdf'))
        self.assertEqual(self.a.mail_attachment(self.cred, 'm1', 'a1')[:5], b'%PDF-')
        self.assertEqual([m['id'] for m in self.a.mail_search(self.cred, 'plans', None, None, 10).items], ['m2'])
        cals = {c['id']: c for c in self.a.calendars(self.cred)}
        self.assertEqual((cals['cal-1']['access'], cals['cal-1']['primary'], cals['cal-2']['access']), ('owner', True, 'read'))
        events = self.a.event_changes(self.cred, 'cal-1', None, 0, 2100000000, 50)
        self.assertEqual(sorted(e['id'] for e in events.items), ['e1', 'o-2'])                # occurrences, never the series master
        self.assertEqual([e['series_id'] for e in events.items if e['id'] == 'o-2'], ['m-series'])
        self.assertEqual(events.removed, ['x-gone'])


class Writing(unittest.TestCase):
    def setUp(self):
        self.g = FakeGraph()
        self.a = microsoft_hub.MicrosoftAdapter(self.g)
        self.cred = {'access_token': 'at'}

    def test_a_draft_is_sent_once_even_when_the_answer_is_lost_and_a_reply_joins_its_conversation(self):
        payload = {'draft': 'dr-1', 'from': 'me@outlook.test', 'to': ['bo@y.test'], 'cc': [], 'subject': 'Hi', 'body': 'Hello'}
        microsoft_writes.check('mail.send', payload)
        self.g.lose_answer = True
        with self.assertRaises(Exception):
            self.a.write(self.cred, 'mail.send', payload, idempotency_key='k')
        found = self.a.find_effect(self.cred, 'mail.send', payload, 'k')                        # found in Sent Items by its marker, never sent again
        self.assertIsNotNone(found)
        again = self.a.write(self.cred, 'mail.send', payload, idempotency_key='k')
        self.assertEqual((len(self.g.sent), again['record']['data']['labels']), (1, ['SENT']))
        ok, _ = microsoft_writes.verify('mail.send', payload, again['record'])
        self.assertTrue(ok)
        reply = self.a.write(self.cred, 'mail.send', {**payload, 'draft': 'dr-2', 'reply_to': 'm1', 'thread': 'c1'}, idempotency_key='k2')
        self.assertEqual(self.g.messages[reply['record']['id']]['conversationId'], 'c1')

    def test_a_conversation_is_archived_starred_binned_and_each_time_put_back_exactly(self):
        for kind, change in (('mail.organize', {'changes': [{'thread': 'c1', 'remove': ['inbox']}]}), ('mail.organize', {'changes': [{'thread': 'c1', 'add': ['starred']}]}),
                             ('mail.mark', {'changes': [{'thread': 'c1', 'remove': ['unread']}]}), ('mail.trash', {'threads': ['c1']})):
            before = self.a.read(self.cred, *self.a.target_of(kind, change))
            had = dict(self.g.messages['m1'])
            undo = microsoft_writes.undo_payload(kind, change, before)
            self.a.write(self.cred, kind, change)
            after = self.a.read(self.cred, *self.a.target_of(kind, change))
            self.assertTrue(microsoft_writes.verify(kind, change, after)[0], kind)
            self.a.write(self.cred, 'mail.organize', undo)
            now = self.g.messages['m1']
            self.assertEqual((now['parentFolderId'], now['isRead'], now['flag'].get('flagStatus')), (had['parentFolderId'], had['isRead'], had['flag'].get('flagStatus')), kind)

    def test_events_created_once_changed_with_their_version_cancelled_and_answered(self):
        new = {'calendar': 'cal-1', 'title': 'Review', 'start': '2033-05-21T10:00', 'end': '2033-05-21T11:00', 'timezone': 'UTC', 'attendees': ['bo@y.test']}
        with self.assertRaises(ValueError):                                                     # Outlook always tells the people invited
            microsoft_writes.check('event.create', {**new, 'notify': False})
        self.g.lose_answer = True
        with self.assertRaises(Exception):
            self.a.write(self.cred, 'event.create', new, idempotency_key='key-1')
        found = self.a.find_effect(self.cred, 'event.create', new, 'key-1')
        self.assertIsNotNone(found)
        self.a.write(self.cred, 'event.create', new, idempotency_key='key-1')
        self.assertEqual(len([e for e in self.g.events.values() if e.get('subject') == 'Review']), 1)
        before = self.a.read(self.cred, 'event', 'cal-1|e1')
        changed = self.a.write(self.cred, 'event.update', {'event': 'cal-1|e1', 'title': 'Planning (new)'}, precondition=before['version'])
        self.assertEqual(changed['record']['title'], 'Planning (new)')
        with self.assertRaises(ProviderError) as stale:
            self.a.write(self.cred, 'event.update', {'event': 'cal-1|e1', 'title': 'Older'}, precondition=before['version'])
        self.assertEqual(stale.exception.status, 412)
        self.a.write(self.cred, 'event.delete', {'event': 'cal-1|e1', 'notify': True}, precondition=changed['record']['version'])
        self.assertIn(('POST', '/me/events/e1/cancel'), self.g.calls)                          # organizer with people: a cancellation is sent to them
        self.g.events['inv'] = {**self.g.events['o-2'], 'id': 'inv', 'type': 'singleInstance', 'isOrganizer': False, 'responseStatus': {'response': 'notResponded'}, '@odata.etag': 'W/"i"'}
        answered = self.a.write(self.cred, 'event.respond', {'event': 'cal-1|inv', 'response': 'tentative'})
        self.assertEqual(answered['record']['data']['my_response'], 'tentative')

    def test_the_rest_of_a_series_is_ended_and_put_back_and_one_occurrence_cannot_be_brought_back(self):
        before = self.a.read(self.cred, 'event', 'cal-1|m-series')
        ended = self.a.write(self.cred, 'event.end_series', {'event': 'cal-1|o-2', 'series': 'cal-1|m-series'}, precondition=before['version'])
        self.assertEqual(self.g.events['m-series']['recurrence']['range'], {'type': 'endDate', 'startDate': '2033-05-16', 'endDate': '2033-05-22'})
        undo = microsoft_writes.undo_payload('event.end_series', {'event': 'cal-1|o-2', 'series': 'cal-1|m-series'}, before)
        self.a.write(self.cred, 'event.update', undo, precondition=ended['record']['version'])
        self.assertEqual(self.g.events['m-series']['recurrence']['range']['type'], 'numbered')
        kind = next(k for k in microsoft_writes.WRITE_KINDS if k.name == 'event.cancel_one')
        self.assertTrue(kind.undo is None and 'cannot bring back' in kind.irreversible_reason)

    def test_every_kind_is_off_for_customers_until_proven_on_a_real_microsoft_account(self):
        caps = microsoft_hub.DECLARATION.hub.effective(list(microsoft_hub.WRITE_SCOPES) + ['Mail.Read', 'Calendars.Read'])
        self.assertFalse(any(caps[k] for k in ('send', 'organize', 'mark_read', 'event_write', 'respond', 'event_change', 'event_series')))
        self.assertTrue(all(len(k.name) <= 20 for k in microsoft_writes.WRITE_KINDS))
