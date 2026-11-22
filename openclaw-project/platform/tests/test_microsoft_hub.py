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
        self.forms, self.token_error = [], None
        self.scope = 'https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Calendars.Read openid email offline_access User.Read'

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
            self.forms.append(form)
            if self.token_error:
                return self.token_error[0], {}, json.dumps(self.token_error[1]).encode()
            return self.ok({'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600, 'scope': self.scope, 'id_token': jwt({'preferred_username': 'Me@Outlook.test'})})
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


class TheRealNetwork(unittest.TestCase):
    """Production, 2026-11-21: no Microsoft account could be connected ("The account could not be connected"). Microsoft's module sent its requests through Google's
    network function, which allows only Google's hosts, so the exchange of the sign-in code was refused inside Lumina before anything was sent. Every other test here
    hands the adapter a fake `http`, so none of them ran that function. These do: the real function, with only the socket replaced."""
    def setUp(self):
        from unittest.mock import patch
        from agentai_platform import google_hub
        self.google, self.asked = google_hub, []
        test = self

        class Answer:
            status, will_close, headers = 200, True, {}
            def __init__(self, body):
                self.body = body
            def read(self, n):
                return self.body
            def isclosed(self):
                return True

        class Con:
            def __init__(self, host):
                self.host, self.sock, self.timeout = host, None, None
            def request(self, method, target, body=None, headers=None):
                test.asked.append((method, self.host, target.split('?')[0]))
            def getresponse(self):
                if self.host == 'login.microsoftonline.com':
                    return Answer(json.dumps({'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600, 'scope': 'openid profile email Mail.Read Calendars.Read User.Read'}).encode())
                return Answer(b'{"mail":"me@outlook.test"}')
            def close(self):
                pass
        patcher = patch.object(google_hub, '_POOL', google_hub._Pool(Con)); patcher.start(); self.addCleanup(patcher.stop)

    def test_microsofts_own_hosts_are_reached_and_no_other(self):
        microsoft_hub.default_http('POST', microsoft_hub.TOKEN_URL, {}, b'grant_type=authorization_code')
        self.assertEqual(microsoft_hub.MicrosoftAdapter()._me({'access_token': 'at'}), 'me@outlook.test')
        self.assertEqual(self.asked, [('POST', 'login.microsoftonline.com', '/common/oauth2/v2.0/token'), ('GET', 'graph.microsoft.com', '/v1.0/me')])
        for url in ('https://gmail.googleapis.com/gmail/v1/users/me/profile', 'https://evil.test/v1.0/me', 'http://graph.microsoft.com/v1.0/me', 'https://graph.microsoft.com:8443/v1.0/me'):
            with self.assertRaises(ProviderError) as refused:
                microsoft_hub.default_http('GET', url, {})
            self.assertEqual(refused.exception.code, 'host_not_allowed')
        with self.assertRaises(ProviderError):                                    # and Google's function still reaches only Google
            self.google.default_http('GET', 'https://graph.microsoft.com/v1.0/me', {})
        self.assertEqual(len(self.asked), 2)

    def test_every_provider_reaches_each_host_it_declares_through_its_own_network_function(self):
        for module in (self.google, microsoft_hub):
            for host in module.DECLARATION.hosts:
                self.asked.clear()
                module.default_http('GET', f'https://{host}/', {})
                self.assertEqual(self.asked, [('GET', host, '/')], (module.PROVIDER, host))

    def test_the_whole_sign_in_through_the_real_function(self):
        done = microsoft_hub.exchanger('cid', 'secret')('code', 'verifier', 'https://getlumina.pro/v1/hub/link/callback')
        self.assertEqual(done.identity, 'me@outlook.test')
        self.assertEqual([a[:2] for a in self.asked], [('POST', 'login.microsoftonline.com'), ('GET', 'graph.microsoft.com')])


class SigningInAsMicrosoftAnswers(unittest.TestCase):
    """The sign-in with answers shaped like Microsoft's own, through the connector service that decides whether a connection is made."""
    def setUp(self):
        from tests.hub_fixture import HubBase
        base = HubBase('setUp'); base.setUp(); self.addCleanup(base.tmp.cleanup)
        self.base, self.g = base, FakeGraph()
        microsoft_hub.register(base.registry, self.g)
        from agentai_platform.connectors import Service
        d = microsoft_hub.DECLARATION
        base.connectors.catalog['microsoft'] = Service('microsoft', d.label, 'researcher', frozenset(d.scopes), needs_selection=False,
                                                       writable_kinds=frozenset(w.name for w in d.write_kinds), disclosure=d.disclosure)
        self.exchange = microsoft_hub.exchanger('cid', 'secret', self.g)
        self.redirect = 'https://getlumina.pro/v1/hub/link/callback'

    def finish(self, code='good'):
        started = self.base.connectors.start_link(self.base.a, 'microsoft', self.redirect)
        return self.base.connectors.finish_link(self.base.a, started['state'], code, self.redirect, self.exchange, needs_any=(microsoft_hub.MAIL_SCOPE, microsoft_hub.CALENDAR_SCOPE))

    def scopes(self, connection):
        with self.base.store.connect() as con:
            return json.loads(con.execute('SELECT granted_scopes FROM connector_connections WHERE id=?', (connection,)).fetchone()[0])

    def test_profile_added_by_microsoft_lowercase_names_and_no_offline_access_in_the_answer_still_connect(self):
        # What a real answer looks like: `profile` although it was not asked for, Graph's address in front, `offline_access` left out, and (in Microsoft's own examples) lower case.
        self.g.scope = 'openid profile email https://graph.microsoft.com/mail.read https://graph.microsoft.com/Calendars.Read https://graph.microsoft.com/User.Read'
        connection = self.finish()
        self.assertEqual(self.scopes(connection), ['Calendars.Read', 'Mail.Read', 'User.Read', 'email', 'openid', 'profile'])
        accounts = self.base.hub.accounts(self.base.a)
        self.assertEqual([(a['provider'], a['identity'], a['state']) for a in accounts], [('microsoft', 'me@outlook.test', 'working')])

    def test_each_way_a_sign_in_connects_nothing_has_its_own_reason(self):
        from agentai_platform.connectors import LinkFailed

        def reason(**answer):
            self.g.token_error, self.g.scope = answer.pop('error', None), answer.pop('scope', FakeGraph().scope)
            with self.assertRaises(LinkFailed) as failed:
                self.finish()
            return failed.exception.reason, failed.exception.reference

        self.assertEqual(reason(error=(401, {'error': 'invalid_client', 'error_description': 'AADSTS7000215: Invalid client secret provided. Trace ID: 1'})), ('provider_setup', 'AADSTS7000215'))
        self.assertEqual(reason(error=(400, {'error': 'invalid_grant', 'error_description': 'AADSTS70008: The provided authorization code or refresh token has expired'})), ('expired', 'AADSTS70008'))
        self.assertEqual(reason(error=(400, {'error': 'invalid_grant', 'error_description': 'AADSTS65001: The user or administrator has not consented'})), ('admin_consent', 'AADSTS65001'))
        self.assertEqual(reason(error=(503, {})), ('provider_unreachable', ''))
        self.assertEqual(reason(scope='openid profile email User.Read'), ('no_access', ''))                              # signed in, mail and calendars both unticked
        self.assertEqual(reason(scope=FakeGraph().scope + ' Files.ReadWrite.All'), ('unexpected_access', ''))             # more than Lumina declares is refused, never stored
        with self.assertRaises(LinkFailed) as replay:
            self.base.connectors.finish_link(self.base.a, 'a-state-nobody-started', 'good', self.redirect, self.exchange)
        self.assertEqual(replay.exception.reason, 'expired')
        with self.base.store.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM connector_connections').fetchone()[0], 0)

    def test_connecting_again_keeps_the_same_connection_and_never_asks_for_less_than_it_held(self):
        connection = self.finish()
        self.base.connectors.needs_customer('a', connection)
        started = self.base.connectors.start_link(self.base.a, 'microsoft', self.redirect, upgrade=connection)
        self.assertEqual(started['identity'], 'me@outlook.test')
        again = self.base.connectors.finish_link(self.base.a, started['state'], 'good', self.redirect, self.exchange)
        self.assertEqual(again, connection)
        with self.base.store.connect() as con:
            self.assertEqual(tuple(con.execute('SELECT state,needs_reason FROM connector_connections WHERE id=?', (connection,)).fetchone()), ('connected', None))

    def test_a_renewal_asks_for_what_is_held_and_always_for_lasting_access(self):
        renewed = microsoft_hub.refresher('cid', 'secret', self.g)({'refresh_token': 'rt', 'scope': 'Calendars.Read Mail.Read User.Read email openid profile'})
        self.assertEqual(set(self.g.forms[-1]['scope'].split()), {'Calendars.Read', 'Mail.Read', 'User.Read', 'email', 'openid', 'offline_access'})
        self.assertEqual(renewed['tokens']['access_token'], 'at')


class WhichSignIn(unittest.TestCase):
    def test_a_personal_and_a_work_account_each_go_to_their_own_sign_in(self):
        at = lambda **more: urlsplit(microsoft_hub.authorize_url('cid', 'r', 'st', 'ch', **more)).path
        self.assertEqual((at(), at(kind='personal'), at(kind='work')),
                         ('/common/oauth2/v2.0/authorize', '/consumers/oauth2/v2.0/authorize', '/organizations/oauth2/v2.0/authorize'))
        with self.assertRaises(ValueError):
            microsoft_hub.authorize_url('cid', 'r', 'st', 'ch', kind='anything-else')
        asked = set(parse_qs(urlsplit(microsoft_hub.authorize_url('cid', 'r', 'st', 'ch', kind='personal')).query)['scope'][0].split())
        self.assertNotIn('profile', asked)                                           # accepted when Microsoft adds it, never asked for


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
