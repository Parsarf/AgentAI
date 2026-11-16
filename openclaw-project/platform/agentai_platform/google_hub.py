"""Google as a mail and calendar provider for the dashboard (roadmap #49 to #56): Gmail and Google Calendar, READ ONLY.

This file is the only place that knows Google's shapes. Everything it returns is the provider-neutral model (hub_model.py); the sync engine, the service, the tools and
the pages never see a Google field. A second provider is a second file like this one and nothing else.

Scopes asked for: `gmail.readonly` and `calendar.readonly`, plus `openid email` to learn which account was connected. Nothing here can send, change, label, mark as read
or delete: no call uses a method other than GET, except the two POSTs to Google's token endpoint (exchange and refresh).

Implementation: first-party calls to the Gmail and Calendar REST APIs. A dashboard needs incremental sync (Gmail's history id, Calendar's sync token), which a tool-call
interface does not offer; that is why this is not a wrapper around a remote tool server.

Network: `http(method, url, headers, body) -> (status, headers, bytes)`. The default one speaks HTTPS to the three hosts below only, follows no redirect, and reads a
bounded answer. Tests pass their own.

Tokens come from custody as `credential` and are never logged, returned or put in an error. A Google error becomes a ProviderError with its status and reason code only.
"""
from __future__ import annotations
import base64
import http.client
import json
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from urllib.parse import quote, urlencode, urlsplit

from .connector_kit import Caps, Declaration, Page, ProviderError
from .hub_model import Changes, HubCaps, ResyncRequired, body, calendar, event, message

PROVIDER = 'google'
MAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar.readonly'
IDENTITY_SCOPES = ('openid', 'email', 'https://www.googleapis.com/auth/userinfo.email')
AUTHORIZE_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
GMAIL = 'https://gmail.googleapis.com/gmail/v1/users/me'
CALENDAR = 'https://www.googleapis.com/calendar/v3'
HOSTS = ('gmail.googleapis.com', 'www.googleapis.com', 'oauth2.googleapis.com')
MAX_ANSWER = 12_000_000
MAIL_PAGE = 100                        # messages listed per page; their headers are then read several at a time
PARALLEL = 8                           # header reads in flight at once (latency hides behind them); how many a second is set by READS_PER_SECOND
READS_PER_SECOND = 40                  # Gmail allows 250 quota units a second per user and a header read costs 5: 50 a second. Eight in flight at this host's latency made
                                       # well over 100 a second; Google answered "rate limit", and the first fill stopped after 300 messages and backed off for up to an hour
                                       # (production, 2026-11-16).
EVENT_PAGE = 250

DECLARATION = Declaration(
    provider=PROVIDER, label='Google', auth='oauth', scopes=(MAIL_SCOPE, CALENDAR_SCOPE) + IDENTITY_SCOPES,
    resource_kinds=('mailbox', 'label', 'calendar'), record_kinds=(), read_operations=(), write_kinds=(),
    change_tokens=True, version_token='etag', paging='page_token',
    error_map={'rateLimitExceeded': 'retry_later', 'userRateLimitExceeded': 'retry_later', 'quotaExceeded': 'retry_later', 'dailyLimitExceeded': 'retry_later',
               'insufficientPermissions': 'needs_customer', 'ACCESS_TOKEN_SCOPE_INSUFFICIENT': 'needs_customer', 'authError': 'needs_customer', 'invalid_grant': 'needs_customer',
               403: 'refused'},
    implementation='first_party', reason='The dashboard needs incremental sync (a history id for mail, a sync token for calendars), which only the REST APIs offer.',
    hosts=HOSTS, freshness_seconds={'mailbox': 900, 'calendar': 900}, caps=Caps(pages=4, items=100, bytes=2_000_000, seconds=25.0),
    disclosure='Reads your mail and calendars. It cannot send, change or delete anything.',
    hub=HubCaps(mail=True, calendar=True, mail_search=True, incremental=True, push=False, labels='labels'), several_accounts=True)

# Gmail's system labels in the common set. Everything else is the customer's own label and is kept by its name.
SYSTEM_LABELS = {'INBOX': 'inbox', 'SENT': 'sent', 'DRAFT': 'drafts', 'SPAM': 'spam', 'TRASH': 'trash', 'STARRED': 'starred', 'UNREAD': 'unread'}
HIDDEN_LABELS = ('CATEGORY_', 'CHAT', 'IMPORTANT', 'UNREAD', 'STARRED')
LABEL_NAMES = {'INBOX': 'Inbox', 'SENT': 'Sent', 'DRAFT': 'Drafts', 'SPAM': 'Spam', 'TRASH': 'Trash'}
ACCESS = {'freeBusyReader': 'busy', 'reader': 'read', 'writer': 'write', 'owner': 'owner'}
RESPONSES = {'accepted': 'accepted', 'declined': 'declined', 'tentative': 'tentative', 'needsAction': 'needs_action'}


# -- the network -----------------------------------------------------------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class _V4First(http.client.HTTPSConnection):
    """Connect over IPv4 when the host has an IPv4 address. Google's hosts list several IPv6 addresses first; on a server with no working IPv6 route every one of them is
    tried and waited for before IPv4 is, which made each request take about 25 seconds (measured on the production host, 2026-11-16). The certificate is still checked
    against the host's name."""
    def connect(self):
        try:
            found = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            found = []
        if not found:
            return super().connect()
        sock = socket.create_connection(found[0][4][:2], self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _V4Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_V4First, req, context=ssl.create_default_context())


def default_http(method, url, headers, data=None, timeout=20):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.port not in (None, 443):
        raise ProviderError(0, 'host_not_allowed')
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect(), _V4Handler())
    try:
        with opener.open(request, timeout=timeout) as answer:
            return answer.status, dict(answer.headers), answer.read(MAX_ANSWER + 1)[:MAX_ANSWER]
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read(200_000)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError(0, 'unreachable') from None


def _failure(status, headers, raw) -> ProviderError:
    code = ''
    try:
        data = json.loads(raw or b'{}')
        error = data.get('error')
        if isinstance(error, dict):
            code = str((error.get('errors') or [{}])[0].get('reason') or error.get('status') or '')
        elif isinstance(error, str):
            code = error
    except (ValueError, AttributeError, IndexError, TypeError):
        pass
    retry = next((v for k, v in (headers or {}).items() if k.lower() == 'retry-after'), None)
    if status == 403 and code in ('rateLimitExceeded', 'userRateLimitExceeded'):
        status = 429
    return ProviderError(status, code, retry_after=retry)


# -- conversion: pure functions, Google's payload in, the neutral model out ---------------------------------------------------------------------------------
def _header(raw, name) -> str:
    for h in ((raw.get('payload') or {}).get('headers') or []):
        if str(h.get('name', '')).lower() == name:
            return str(h.get('value') or '')
    return ''


def _addresses(value) -> list:
    return [{'name': name, 'address': address} for name, address in getaddresses([value or '']) if name or address]


def to_message(raw, label_names=None) -> dict:
    """A Gmail message (format=metadata or full) as the neutral message. `label_names`: {label id: the customer's name for it}."""
    ids = [str(i) for i in (raw.get('labelIds') or [])]
    marks = [SYSTEM_LABELS[i] for i in ids if i in SYSTEM_LABELS]
    if not {'INBOX', 'SENT', 'DRAFT', 'SPAM', 'TRASH'} & set(ids):
        marks.append('archive')
    names = label_names or {}
    own = [{'id': i, 'name': LABEL_NAMES.get(i) or names.get(i) or i} for i in ids if not i.startswith(HIDDEN_LABELS)]
    sender = _addresses(_header(raw, 'from'))
    try:
        sent = int(raw.get('internalDate')) // 1000
    except (TypeError, ValueError):
        try:
            sent = int(parsedate_to_datetime(_header(raw, 'date')).timestamp())
        except (TypeError, ValueError):
            sent = 0
    return message(raw['id'], raw.get('threadId') or raw['id'], subject=_header(raw, 'subject'), sender=sender[0] if sender else None, to=_addresses(_header(raw, 'to')),
                   cc=_addresses(_header(raw, 'cc')), sent_epoch=sent, snippet=_unescape(raw.get('snippet', '')), labels=marks, provider_labels=own,
                   has_attachments=_has_files(raw.get('payload') or {}))


def _unescape(text) -> str:
    from html import unescape
    return unescape(str(text or ''))


def _has_files(part) -> bool:
    if part.get('filename') and (part.get('body') or {}).get('attachmentId'):
        return True
    return any(_has_files(p) for p in (part.get('parts') or []))


def _decode(data) -> str:
    try:
        return base64.urlsafe_b64decode(str(data or '') + '=' * (-len(str(data or '')) % 4)).decode('utf-8', 'replace')
    except (ValueError, TypeError):
        return ''


def to_body(raw) -> dict:
    """A Gmail message (format=full) as the neutral body: its plain text, its markup, and the names of its attachments (their bytes are not fetched)."""
    found = {'text/plain': [], 'text/html': []}
    files = []

    def walk(part):
        kind = str(part.get('mimeType') or '')
        inner = part.get('body') or {}
        if part.get('filename') and inner.get('attachmentId'):
            files.append({'id': inner['attachmentId'], 'name': part['filename'], 'type': kind, 'size': inner.get('size') or 0})
        elif kind in found and inner.get('data'):
            found[kind].append(_decode(inner['data']))
        for child in (part.get('parts') or []):
            walk(child)
    walk(raw.get('payload') or {})
    return body('\n'.join(found['text/plain']), '\n'.join(found['text/html']), files)


def _instant(value):
    """An RFC 3339 time as epoch seconds."""
    text = str(value or '')
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    return int(datetime.fromisoformat(text).timestamp())


def _midnight(day) -> int:
    return int(datetime.strptime(str(day), '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())


def to_event(raw, calendar_id):
    """A Calendar event instance (singleEvents=true) as the neutral event, or None when it says nothing that can be shown (a deleted event that was never an exception)."""
    cancelled = raw.get('status') == 'cancelled'
    start, end = raw.get('start') or raw.get('originalStartTime') or {}, raw.get('end') or raw.get('originalStartTime') or {}
    if not start:
        return None
    if cancelled and not raw.get('recurringEventId'):
        return None                                        # a plain deleted event: it is simply gone
    if 'date' in start:
        when = {'all_day': True, 'start_date': start['date'], 'end_date': end.get('date') or start['date'], 'start_epoch': _midnight(start['date']),
                'end_epoch': _midnight(end.get('date') or start['date'])}
    else:
        when = {'start_epoch': _instant(start.get('dateTime')), 'end_epoch': _instant(end.get('dateTime') or start.get('dateTime')), 'timezone': start.get('timeZone')}
    people = [{'name': a.get('displayName', ''), 'address': a.get('email', ''), 'response': RESPONSES.get(a.get('responseStatus')), 'self': bool(a.get('self')),
               'optional': bool(a.get('optional'))} for a in (raw.get('attendees') or []) if isinstance(a, dict)]
    mine = next((p['response'] for p in people if p['self']), None)
    organizer = raw.get('organizer') or {}
    call = raw.get('hangoutLink') or next((p.get('uri') for p in ((raw.get('conferenceData') or {}).get('entryPoints') or []) if p.get('entryPointType') == 'video'), None)
    busy_only = 'summary' not in raw and 'creator' not in raw and not cancelled        # a calendar shared as "free/busy only" gives times and nothing else
    try:
        updated = _instant(raw['updated']) if raw.get('updated') else None
    except ValueError:
        updated = None
    return event(raw['id'], calendar_id, title=raw.get('summary', ''), series_id=raw.get('recurringEventId'), exception=bool(raw.get('recurringEventId')) and _moved(raw),
                 cancelled=cancelled, place=raw.get('location', ''), conference_url=call, organizer={'name': organizer.get('displayName', ''), 'address': organizer.get('email', '')},
                 attendees=people, my_response=mine, visibility='busy' if busy_only else raw.get('visibility') if raw.get('visibility') in ('public', 'private') else 'default',
                 version=raw.get('etag'), description=raw.get('description', ''), provider_url=raw.get('htmlLink'), updated_epoch=updated, **when)


def _moved(raw) -> bool:
    """Is this instance of a series an exception: cancelled, or at another time than the series put it?"""
    if raw.get('status') == 'cancelled':
        return True
    original, start = raw.get('originalStartTime') or {}, raw.get('start') or {}
    return bool(original) and (original.get('dateTime') or original.get('date')) != (start.get('dateTime') or start.get('date'))


def to_calendar(raw) -> dict:
    return calendar(raw['id'], name=raw.get('summaryOverride') or raw.get('summary', ''), timezone=raw.get('timeZone'), access=ACCESS.get(raw.get('accessRole'), 'read'),
                    primary=bool(raw.get('primary')))


def _rfc3339(epoch) -> str:
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Pace:
    """At most `rate` starts a second, shared by every thread (and every adapter) that uses it."""
    def __init__(self, rate, *, clock=time.monotonic, sleep=time.sleep):
        self.gap, self.clock, self.sleep, self.next, self.lock = 1.0 / rate, clock, sleep, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = self.clock()
            at = max(now, self.next)
            self.next = at + self.gap
        if at > now:
            self.sleep(at - now)


_READS = Pace(READS_PER_SECOND)


# -- the adapter -------------------------------------------------------------------------------------------------------------------------------------------
class GoogleAdapter:
    def __init__(self, http=default_http, pace=None):
        self.http = http
        self.pace = pace if pace is not None else (_READS if http is default_http else None)      # the real network is paced; a test's fake is not

    def _get(self, credential, url, query=None):
        token = (credential or {}).get('access_token')
        if not token:
            raise ProviderError(401, 'authError')
        if query:
            url += '?' + urlencode([(k, v) for k, v in query if v is not None], doseq=True)
        status, headers, raw = self.http('GET', url, {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}, None)
        if status != 200:
            raise _failure(status, headers, raw)
        try:
            return json.loads(raw)
        except ValueError:
            raise ProviderError(0, 'bad_answer') from None

    @staticmethod
    def _scopes(credential) -> set:
        return set(str((credential or {}).get('scope') or '').split())

    def _label_names(self, credential) -> dict:
        return {str(l['id']): str(l.get('name') or l['id']) for l in self._get(credential, GMAIL + '/labels').get('labels', []) if l.get('type') == 'user'}

    # -- what can be chosen (the picker) -------------------------------------------------------------------------------------------------------------
    def resources(self, credential):
        """What the customer can let Lumina read: all mail or single labels, and each calendar. Only what the granted scopes cover is offered."""
        out, scopes = [], self._scopes(credential)
        if MAIL_SCOPE in scopes:
            out.append({'kind': 'mailbox', 'id': '*', 'name': 'All mail'})
            labels = self._get(credential, GMAIL + '/labels').get('labels', [])
            out += [{'kind': 'label', 'id': str(l['id']), 'name': LABEL_NAMES.get(l['id']) or str(l.get('name') or l['id'])} for l in labels
                    if l['id'] in LABEL_NAMES or l.get('type') == 'user']
        if CALENDAR_SCOPE in scopes:
            out += [{'kind': 'calendar', 'id': c['id'], 'name': c['name']} for c in self.calendars(credential)]
        return out

    # -- calendars -----------------------------------------------------------------------------------------------------------------------------------
    def calendars(self, credential):
        found, token = [], None
        for _ in range(10):
            page = self._get(credential, CALENDAR + '/users/me/calendarList', [('maxResults', 250), ('pageToken', token)])
            found += [to_calendar(c) for c in page.get('items', []) if c.get('id') and not c.get('deleted')]
            token = page.get('nextPageToken')
            if not token:
                break
        return found

    def event_changes(self, credential, calendar_id, cursor, start_epoch, end_epoch, limit):
        state = json.loads(cursor) if cursor else {}
        query = [('singleEvents', 'true'), ('showDeleted', 'true'), ('maxResults', min(int(limit or EVENT_PAGE), EVENT_PAGE))]
        if state.get('s'):
            query.append(('syncToken', state['s']))            # a sync token carries the window it was made for; no times may be sent with it
        else:
            query += [('timeMin', _rfc3339(start_epoch) if start_epoch else None), ('timeMax', _rfc3339(end_epoch))]      # no start: every past event
        if state.get('p'):
            query.append(('pageToken', state['p']))
        try:
            page = self._get(credential, f'{CALENDAR}/calendars/{quote(calendar_id, safe="")}/events', query)
        except ProviderError as error:
            if error.status == 410 or error.code in ('fullSyncRequired', 'updatedMinTooLongAgo'):
                raise ResyncRequired() from None
            raise
        items, removed = [], []
        for raw in page.get('items', []):
            if not raw.get('id'):
                continue
            converted = to_event(raw, calendar_id)
            if converted is None:
                removed.append(str(raw['id']))
            else:
                items.append(converted)
        if page.get('nextPageToken'):
            return Changes(items, removed, json.dumps({**({'s': state['s']} if state.get('s') else {}), 'p': page['nextPageToken']}), True)
        return Changes(items, removed, json.dumps({'s': page.get('nextSyncToken')}) if page.get('nextSyncToken') else None, False)

    # -- mail ----------------------------------------------------------------------------------------------------------------------------------------
    def _headers_of_all(self, credential, ids, names):
        """The headers of several messages, read a few at a time. -> (messages, the ids that are no longer there). The first real failure is raised."""
        def one(mid):
            if self.pace is not None:
                self.pace.wait()
            try:
                return mid, self._headers_of(credential, mid, names), None
            except ProviderError as error:
                return mid, None, error
        if not ids:
            return [], []
        with ThreadPoolExecutor(max_workers=min(PARALLEL, len(ids))) as pool:
            results = list(pool.map(one, ids))
        failure = next((e for _m, _h, e in results if e is not None and e.status != 404), None)
        if failure is not None:
            raise failure
        return [h for _m, h, e in results if h is not None], [m for m, _h, e in results if e is not None]      # a message deleted between the list and the read is simply not there

    def _headers_of(self, credential, message_id, names):
        return to_message(self._get(credential, f'{GMAIL}/messages/{quote(message_id, safe="")}',
                                    [('format', 'metadata'), ('metadataHeaders', ['From', 'To', 'Cc', 'Subject', 'Date'])]), names)

    def mail_changes(self, credential, cursor, since_epoch, labels, limit):
        """First fill: the window, one label at a time when only some labels were chosen (so mail outside what was chosen is never asked for), a page at a time. After that:
        Gmail's history from the id that was current when the fill began."""
        state = json.loads(cursor) if cursor else None
        names = self._label_names(credential)
        wanted = list(labels) if labels is not None else [None]
        if state is None:
            state = {'h': str(self._get(credential, GMAIL + '/profile').get('historyId') or ''), 'i': 0, 'p': None}
        if 'i' in state:
            if state['i'] >= len(wanted):
                return Changes([], [], json.dumps({'h': state['h']}), False)
            label = wanted[state['i']]
            page = self._get(credential, GMAIL + '/messages', [('maxResults', min(int(limit or MAIL_PAGE), MAIL_PAGE)), ('pageToken', state.get('p')),
                                                               ('q', '{after:%d is:starred}' % int(since_epoch) if since_epoch else None), ('labelIds', label), ('includeSpamTrash', 'true')])
            items, _gone = self._headers_of_all(credential, [ref['id'] for ref in page.get('messages', [])], names)      # Gmail lists newest first, so recent mail arrives first
            if page.get('nextPageToken'):
                following = {'h': state['h'], 'i': state['i'], 'p': page['nextPageToken']}
            elif state['i'] + 1 < len(wanted):
                following = {'h': state['h'], 'i': state['i'] + 1, 'p': None}
            else:
                return Changes(items, [], json.dumps({'h': state['h']}), False)
            return Changes(items, [], json.dumps(following), True)
        try:
            page = self._get(credential, GMAIL + '/history', [('startHistoryId', state['h']), ('maxResults', 100), ('pageToken', state.get('hp')),
                                                              ('historyTypes', ['messageAdded', 'messageDeleted', 'labelAdded', 'labelRemoved'])])
        except ProviderError as error:
            if error.status == 404:
                raise ResyncRequired() from None            # the history id is too old: Gmail keeps about a week
            raise
        changed, gone = [], set()
        for entry in page.get('history', []):
            for kind in ('messagesAdded', 'labelsAdded', 'labelsRemoved', 'messagesDeleted'):
                for item in entry.get(kind, []):
                    mid = str((item.get('message') or {}).get('id') or '')
                    if mid and mid not in changed:
                        changed.append(mid)
        items, missing = self._headers_of_all(credential, changed, names)
        gone |= set(missing)
        if labels is not None:                                # it may have left what was chosen
            gone |= {m['id'] for m in items if not any(p['id'] in labels for p in m['provider_labels'])}
            items = [m for m in items if m['id'] not in gone]
        if page.get('nextPageToken'):
            return Changes(items, sorted(gone), json.dumps({'h': state['h'], 'hp': page['nextPageToken']}), True)
        return Changes(items, sorted(gone), json.dumps({'h': str(page.get('historyId') or state['h'])}), False)

    def mail_body(self, credential, message_id):
        return to_body(self._get(credential, f'{GMAIL}/messages/{quote(message_id, safe="")}', [('format', 'full')]))

    def mail_search(self, credential, query, labels, position, limit):
        """Mail of any age, searched by Gmail. With only some labels chosen, the search is held to them."""
        scope = '' if labels is None else ' {' + ' '.join('label:' + _search_label(l, self._label_names(credential)) for l in labels) + '}'
        page = self._get(credential, GMAIL + '/messages', [('q', query + scope), ('maxResults', min(int(limit or 10), 10)), ('pageToken', position)])
        names = self._label_names(credential) if page.get('messages') else {}
        items = []
        for ref in page.get('messages', []):
            try:
                items.append(self._headers_of(credential, ref['id'], names))
            except ProviderError as error:
                if error.status != 404:
                    raise
        return Page(items, next=page.get('nextPageToken'), total=page.get('resultSizeEstimate'))


def _search_label(label_id, names) -> str:
    name = LABEL_NAMES.get(label_id) or names.get(label_id) or label_id
    return name.lower().replace(' ', '-').replace('"', '')


# -- signing in ---------------------------------------------------------------------------------------------------------------------------------------------
def authorize_url(client_id, redirect_uri, state, challenge, *, hint=None) -> str:
    """Where the customer is sent to give Lumina read access. `prompt=consent` with offline access, so a refresh token is always given and the customer always sees what is asked."""
    query = {'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code', 'scope': ' '.join((MAIL_SCOPE, CALENDAR_SCOPE, 'openid', 'email')), 'state': state,
             'code_challenge': challenge, 'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'false'}
    if hint:
        query['login_hint'] = hint
    return AUTHORIZE_URL + '?' + urlencode(query)


def _token_call(http, fields):
    status, headers, raw = http('POST', TOKEN_URL, {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}, urlencode(fields).encode())
    if status != 200:
        raise _failure(status, headers, raw)
    try:
        return json.loads(raw)
    except ValueError:
        raise ProviderError(0, 'bad_answer') from None


def exchanger(client_id, client_secret, http=default_http):
    """-> exchange(code, verifier, redirect_uri) for ConnectorService.finish_link: trades the code for tokens and reads which account it is from the ID token. The ID token
    came straight from Google's token endpoint over TLS, which is what makes its claims trustworthy here; it is used for nothing but the address."""
    from .connectors import Exchange

    def exchange(code, verifier, redirect_uri):
        data = _token_call(http, {'code': code, 'client_id': client_id, 'client_secret': client_secret, 'redirect_uri': redirect_uri, 'grant_type': 'authorization_code',
                                  'code_verifier': verifier})
        claims = {}
        try:
            claims = json.loads(_decode(str(data.get('id_token', '')).split('.')[1]))
        except (IndexError, ValueError):
            pass
        identity = str(claims.get('email') or '') if claims.get('email_verified') in (True, 'true') else ''
        granted = sorted(set(str(data.get('scope') or '').split()))
        tokens = {'access_token': data.get('access_token'), 'refresh_token': data.get('refresh_token'), 'scope': ' '.join(granted), 'expires_in': data.get('expires_in')}
        if not tokens['access_token'] or not tokens['refresh_token']:
            raise ProviderError(0, 'no_tokens')
        return Exchange(tokens=tokens, identity=identity, granted_scopes=granted)
    return exchange


def refresher(client_id, client_secret, http=default_http):
    """-> the function connector_refresh.ConnectorRefresher calls to renew an access token before it ends."""
    from .connector_refresh import RefreshFault

    def refresh(tokens):
        if not tokens.get('refresh_token'):
            raise RefreshFault('needs_customer')
        try:
            data = _token_call(http, {'client_id': client_id, 'client_secret': client_secret, 'refresh_token': tokens['refresh_token'], 'grant_type': 'refresh_token'})
        except ProviderError as error:
            if error.code == 'invalid_grant':                # the customer removed Lumina's access at Google, or the grant expired
                raise RefreshFault('revoked') from None
            raise RefreshFault('needs_customer' if error.status in (400, 401) else 'temporary') from None
        if not data.get('access_token'):
            raise RefreshFault('temporary')
        return {'tokens': {**tokens, 'access_token': data['access_token'], **({'scope': data['scope']} if data.get('scope') else {})}, 'expires_in': data.get('expires_in')}
    return refresh


def register(registry, http=default_http):
    registry.register(DECLARATION, lambda: GoogleAdapter(http))
    return registry
