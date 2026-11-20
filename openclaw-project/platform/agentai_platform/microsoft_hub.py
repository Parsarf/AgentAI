"""Outlook mail and calendars through Microsoft Graph (roadmap Phase 6, #D8): the second provider of the dashboard, on the same neutral model as Google, with no change to
the screens, the tools or the workflows. Personal (outlook.com) and work or school accounts both sign in through Microsoft's common endpoint.

Reading (to the Phase 5 gate): the mailbox's folders map to the common set by their well-known names (inbox, sentitems, drafts, archive, junkemail, deleteditems); a
message is in one folder (`labels='folders'`), and Outlook's categories show as the customer's own labels. Mail is synced with Graph's delta links, one per folder (the
cursor holds them); calendars with calendarView delta, which gives occurrences already expanded. Changes are in `microsoft_writes.py`.

A work account whose organization does not let its members allow apps gets a plain sentence: an administrator must allow Lumina (Microsoft answers the sign-in with
`AADSTS65001`/`consent_required` or `admin_consent_required`).
"""
from __future__ import annotations
import base64
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from .connector_kit import Caps, Declaration, Page, ProviderError
from .hub_model import Changes, Grant, HubCaps, ResyncRequired, body, calendar, event, message
from . import microsoft_writes
from .microsoft_writes import WRITE_KINDS, MicrosoftWrites

PROVIDER = 'microsoft'
AUTHORIZE_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
TOKEN_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
GRAPH = 'https://graph.microsoft.com/v1.0'
HOSTS = ('graph.microsoft.com', 'login.microsoftonline.com')
IDENTITY_SCOPES = ('openid', 'email', 'offline_access', 'User.Read')
MAIL_SCOPE, CALENDAR_SCOPE = 'Mail.Read', 'Calendars.Read'
EVENTS_SCOPE, SEND_SCOPE, MODIFY_SCOPE = 'Calendars.ReadWrite', 'Mail.Send', 'Mail.ReadWrite'
GRANTS = (Grant('calendar_write', EVENTS_SCOPE, ('event_write', 'respond', 'event_change', 'event_series'),
                'Create, change, cancel and answer events in this account\'s calendars, only when you do it or approve it.'),
          Grant('send', SEND_SCOPE, ('send',), 'Send email from this account, only when you press Send or approve a message.'),
          Grant('organize', MODIFY_SCOPE, ('organize', 'mark_read'), 'Move, flag, categorize and mark mail in this account, only when you do it or approve it.'))
WRITE_SCOPES = tuple(g.scope for g in GRANTS)
WELL_KNOWN = {'inbox': 'inbox', 'sentitems': 'sent', 'drafts': 'drafts', 'archive': 'archive', 'junkemail': 'spam', 'deleteditems': 'trash'}
SYNCED = ('inbox', 'sentitems', 'archive')                     # with "all mail": these and the customer's own folders (not junk, the bin or drafts)
MESSAGE_FIELDS = 'id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,bodyPreview,isRead,flag,hasAttachments,parentFolderId,categories'
EVENT_FIELDS = ('id,subject,start,end,isAllDay,location,onlineMeeting,organizer,attendees,responseStatus,seriesMasterId,type,isCancelled,sensitivity,showAs,bodyPreview,'
                'webLink,changeKey,isOrganizer')
RESPONSES = {'accepted': 'accepted', 'declined': 'declined', 'tentativelyAccepted': 'tentative', 'notResponded': 'needs_action', 'none': None, 'organizer': 'accepted'}
MAX_ANSWER = 12_000_000

DECLARATION = Declaration(
    provider=PROVIDER, label='Microsoft', auth='oauth', scopes=(MAIL_SCOPE, CALENDAR_SCOPE) + IDENTITY_SCOPES + WRITE_SCOPES,
    resource_kinds=('mailbox', 'label', 'calendar'), record_kinds=('event', 'message', 'threads'), read_operations=(), write_kinds=WRITE_KINDS,
    change_tokens=True, version_token='etag', preconditions=True, idempotency_keys=True, paging='cursor',
    error_map={'TooManyRequests': 'retry_later', 'ApplicationThrottled': 'retry_later', 'MailboxConcurrency': 'retry_later', 'InvalidAuthenticationToken': 'needs_customer',
               'ErrorAccessDenied': 'refused', 'ErrorItemNotFound': 'not_found', 'ErrorIrresolvableConflict': 'conflict', 'PreconditionFailed': 'conflict', 412: 'conflict'},
    implementation='first_party', reason='The dashboard needs delta queries (mail per folder, calendarView), which only Microsoft Graph offers.',
    hosts=HOSTS, freshness_seconds={'mailbox': 900, 'calendar': 900}, caps=Caps(pages=4, items=100, bytes=2_000_000, seconds=25.0),
    disclosure='Reads your mail and calendars. It changes them only when you allow each kind of change and then do it yourself or approve what your assistant prepared.',
    hub=HubCaps(mail=True, calendar=True, mail_search=True, incremental=True, push=False, labels='folders', attachments=True, compose_link=False, free_busy=False,
                send=True, organize=True, mark_read=True, event_write=True, respond=True, event_change=True, event_series=True,
                # every change is proven on a real Microsoft account before a customer gets it (owner's Entra app and test accounts pending, 2026-11-20)
                proving=('send', 'organize', 'mark_read', 'event_write', 'respond', 'event_change', 'event_series'), grants=GRANTS),
    several_accounts=True)

ADMIN_WORDS = 'Your organization lets only an administrator allow apps like Lumina. Ask your IT administrator to allow Lumina, then connect again.'


def default_http(method, url, headers, data=None, timeout=20):
    from .google_hub import default_http as http
    return http(method, url, headers, data, timeout)


def _failure(status, headers, raw) -> ProviderError:
    code = ''
    try:
        code = str((json.loads(raw or b'{}').get('error') or {}).get('code') or '')
    except (ValueError, AttributeError):
        code = ''
    retry = None
    try:
        retry = int((headers or {}).get('Retry-After') or (headers or {}).get('retry-after') or 0) or None
    except (TypeError, ValueError):
        retry = None
    return ProviderError(status, code, retry)


def _when(part, zone='UTC') -> int:
    """A Graph dateTimeTimeZone (we ask for UTC) as epoch seconds."""
    text = str((part or {}).get('dateTime') or '')
    if not text:
        return 0
    moment = datetime.fromisoformat(text[:26].rstrip('Z'))
    return int(moment.replace(tzinfo=timezone.utc).timestamp())


def _person(addr) -> dict:
    a = (addr or {}).get('emailAddress') or {}
    return {'name': str(a.get('name') or ''), 'address': str(a.get('address') or '').lower()}


def to_calendar(raw, me='') -> dict:
    owner = str(((raw.get('owner') or {}).get('address')) or '').lower()
    access = ('owner' if not owner or owner == me else 'write') if raw.get('canEdit') else 'read'
    return calendar(raw['id'], name=raw.get('name', ''), timezone=None, access=access, primary=bool(raw.get('isDefaultCalendar')))


def to_message(raw, folders) -> dict:
    """A Graph message as the neutral message. `folders`: {folder id: {'well_known': .., 'name': ..}}."""
    folder = folders.get(raw.get('parentFolderId') or '', {})
    marks = [WELL_KNOWN[folder['well_known']]] if folder.get('well_known') in WELL_KNOWN else ['archive']
    if not raw.get('isRead'):
        marks.append('unread')
    if ((raw.get('flag') or {}).get('flagStatus')) == 'flagged':
        marks.append('starred')
    own = ([{'id': raw['parentFolderId'], 'name': folder.get('name') or 'Folder'}] if raw.get('parentFolderId') and not folder.get('well_known') else [])
    own += [{'id': 'category:' + c, 'name': c} for c in raw.get('categories') or [] if isinstance(c, str)]
    try:
        sent = int(datetime.fromisoformat(str(raw.get('receivedDateTime', '')).replace('Z', '+00:00')).timestamp())
    except ValueError:
        sent = 0
    return message(raw['id'], raw.get('conversationId') or raw['id'], subject=raw.get('subject') or '', sender=_person(raw.get('from')),
                   to=[_person(p) for p in raw.get('toRecipients') or []], cc=[_person(p) for p in raw.get('ccRecipients') or []], sent_epoch=sent,
                   snippet=str(raw.get('bodyPreview') or '')[:300], labels=marks, provider_labels=own, has_attachments=bool(raw.get('hasAttachments')))


def to_event(raw, calendar_id) -> dict:
    all_day = bool(raw.get('isAllDay'))
    start, end = _when(raw.get('start')), _when(raw.get('end'))
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%d')
    mine = RESPONSES.get(((raw.get('responseStatus') or {}).get('response')) or 'none')
    if raw.get('isOrganizer'):
        mine = None
    people = [{**_person(a), 'response': RESPONSES.get(((a.get('status') or {}).get('response')) or 'none') or 'needs_action', 'self': False,
               'optional': a.get('type') == 'optional'} for a in raw.get('attendees') or [] if a.get('type') != 'resource']
    return event(raw['id'], calendar_id, title=raw.get('subject') or '', start_epoch=start, end_epoch=end, all_day=all_day,
                 start_date=day(start) if all_day else None, end_date=day(end) if all_day else None, timezone=None if all_day else 'UTC',
                 series_id=raw.get('seriesMasterId'), place=str(((raw.get('location') or {}).get('displayName')) or ''),
                 conference_url=((raw.get('onlineMeeting') or {}).get('joinUrl')) or None, organizer=_person(raw.get('organizer')), attendees=people,
                 my_response=mine, exception=raw.get('type') == 'exception', cancelled=bool(raw.get('isCancelled')),
                 visibility='private' if raw.get('sensitivity') in ('private', 'confidential') else 'default', version=raw.get('changeKey'),
                 description=str(raw.get('bodyPreview') or ''), provider_url=raw.get('webLink') if str(raw.get('webLink', '')).startswith('https://') else None)


class MicrosoftAdapter(MicrosoftWrites):
    def __init__(self, http=default_http):
        self.http = http

    check = staticmethod(microsoft_writes.check)
    preview = staticmethod(microsoft_writes.preview)
    undo_payload = staticmethod(microsoft_writes.undo_payload)
    undo_after = staticmethod(microsoft_writes.undo_after)
    compensation_payload = staticmethod(microsoft_writes.compensation_payload)
    verify = staticmethod(microsoft_writes.verify)

    # -- the wire ----------------------------------------------------------------------------------------------------------------------------------
    def _send(self, credential, method, url, body=None, headers=None):
        token = (credential or {}).get('access_token')
        if not token:
            raise ProviderError(401, 'InvalidAuthenticationToken')
        sent = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'Prefer': 'outlook.timezone="UTC", odata.maxpagesize=50', **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            sent['Content-Type'] = 'application/json'
        try:
            return self.http(method, url if url.startswith('https://') else GRAPH + url, sent, data)
        except ProviderError as error:
            if error.status == 0 and error.code == 'unreachable':
                from .connector_kit import Unanswered
                raise Unanswered() from None
            raise

    def _get(self, credential, url, query=None):
        full = url + (('&' if '?' in url else '?') + urlencode(query) if query else '')
        status, headers, raw = self._send(credential, 'GET', full)
        if status == 410:
            raise ResyncRequired()
        if status != 200:
            raise _failure(status, headers, raw)
        if len(raw or b'') > MAX_ANSWER:
            raise ProviderError(413, 'tooLarge')
        return json.loads(raw or b'{}')

    def _me(self, credential) -> str:
        me = self._get(credential, '/me', [('$select', 'mail,userPrincipalName')])
        return str(me.get('mail') or me.get('userPrincipalName') or '').lower()

    def _folders(self, credential) -> dict:
        """{id: {'well_known', 'name'}} for the mailbox's folders, one level of children included."""
        out = {}
        for wk in WELL_KNOWN:
            try:
                raw = self._get(credential, f'/me/mailFolders/{wk}', [('$select', 'id,displayName')])
                out[raw['id']] = {'well_known': wk, 'name': raw.get('displayName') or wk}
            except ProviderError:
                continue
        top = self._get(credential, '/me/mailFolders', [('$top', '100'), ('$select', 'id,displayName,childFolderCount')]).get('value') or []
        for f in top:
            out.setdefault(f['id'], {'well_known': None, 'name': f.get('displayName') or ''})
            if f.get('childFolderCount'):
                for c in self._get(credential, f'/me/mailFolders/{f["id"]}/childFolders', [('$top', '100'), ('$select', 'id,displayName')]).get('value') or []:
                    out.setdefault(c['id'], {'well_known': None, 'name': f'{f.get("displayName")}/{c.get("displayName")}'})
        return out

    # -- the hub interface -------------------------------------------------------------------------------------------------------------------------
    def resources(self, credential):
        folders = self._folders(credential)
        labels = [{'kind': 'label', 'id': fid, 'name': f['name']} for fid, f in folders.items() if f['well_known'] not in ('junkemail', 'deleteditems', 'drafts')]
        cals = [{'kind': 'calendar', 'id': c['id'], 'name': c['name']} for c in self.calendars(credential)]
        return [{'kind': 'mailbox', 'id': '*', 'name': 'All mail'}] + labels + cals

    def calendars(self, credential):
        me = self._me(credential)
        return [to_calendar(c, me) for c in self._get(credential, '/me/calendars', [('$top', '100'), ('$select', 'id,name,canEdit,isDefaultCalendar,owner')]).get('value') or []]

    def mail_changes(self, credential, cursor, since_epoch, labels, limit):
        """One page of changes across the folders that count (all mail but junk, the bin and drafts; or the folders granted). The cursor holds each folder's next or
        delta link; a link Graph no longer knows (410) makes the sync start over."""
        state = json.loads(cursor) if cursor else {}
        folders = self._folders(credential)
        wanted = [fid for fid, f in folders.items() if (f['well_known'] in SYNCED or not f['well_known'])] if labels is None else [l for l in labels if l in folders]
        since = datetime.fromtimestamp(int(since_epoch or 0), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        items, removed, more = [], [], False
        for fid in wanted:
            link = state.get(fid)
            if link and link.startswith('done:'):
                link = link[5:]
            url = link or (f'/me/mailFolders/{quote(fid, safe="")}/messages/delta?$select={MESSAGE_FIELDS}&$filter=' + quote(f'receivedDateTime ge {since}', safe=' ').replace(' ', '%20'))
            page = self._get(credential, url)
            for raw in page.get('value') or []:
                if '@removed' in raw:
                    removed.append(raw['id'])
                elif raw.get('id'):
                    items.append(to_message(raw, folders))
            if page.get('@odata.nextLink'):
                state[fid] = page['@odata.nextLink']
                more = True
            else:
                state[fid] = 'done:' + str(page.get('@odata.deltaLink') or link or '')
            if len(items) >= limit:
                more = more or any(not str(state.get(f, '')).startswith('done:') for f in wanted)
                break
        cursor = json.dumps(state)
        if len(cursor) > 4000:                                              # too many folders to remember: the sync starts again from the window
            raise ResyncRequired()
        return Changes(items, removed, cursor, more)

    def mail_body(self, credential, message_id):
        raw = self._get(credential, f'/me/messages/{quote(message_id, safe="")}', [('$select', 'body,hasAttachments')])
        content = (raw.get('body') or {})
        html = content.get('content', '') if content.get('contentType') == 'html' else ''
        text = content.get('content', '') if content.get('contentType') != 'html' else ''
        files = []
        if raw.get('hasAttachments'):
            for a in self._get(credential, f'/me/messages/{quote(message_id, safe="")}/attachments', [('$select', 'id,name,contentType,size,isInline')]).get('value') or []:
                if not a.get('isInline'):
                    files.append({'id': a['id'], 'name': a.get('name') or 'attachment', 'type': a.get('contentType') or 'application/octet-stream', 'size': int(a.get('size') or 0)})
        return body(text, html, files)

    def mail_attachment(self, credential, message_id, attachment_id) -> bytes:
        raw = self._get(credential, f'/me/messages/{quote(message_id, safe="")}/attachments/{quote(attachment_id, safe="")}')
        return base64.b64decode(raw.get('contentBytes') or b'')

    def mail_search(self, credential, query, labels, position, limit):
        """Older mail, live: Graph's search over the whole mailbox. `position` is Graph's next link."""
        folders = self._folders(credential)
        url = position or f'/me/messages?$search=' + quote('"' + str(query).replace('"', ' ')[:200] + '"') + f'&$top={min(int(limit), 25)}&$select={MESSAGE_FIELDS}'
        page = self._get(credential, url, None)
        found = [to_message(m, folders) for m in page.get('value') or [] if labels is None or m.get('parentFolderId') in labels]
        return Page(found, next=page.get('@odata.nextLink'), total=None)

    def event_changes(self, credential, calendar_id, cursor, start_epoch, end_epoch, limit):
        iso = lambda t: datetime.fromtimestamp(int(t), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        url = cursor or (f'/me/calendars/{quote(calendar_id, safe="")}/calendarView/delta?startDateTime={iso(start_epoch)}&endDateTime={iso(end_epoch)}')
        page = self._get(credential, url)
        items, removed = [], []
        for raw in page.get('value') or []:
            if '@removed' in raw:
                removed.append(raw['id'])
            elif raw.get('type') != 'seriesMaster' and raw.get('id'):
                if 'start' not in raw:                                      # a delta page names a change; read the occurrence itself
                    raw = self._get(credential, f'/me/events/{quote(raw["id"], safe="")}', [('$select', EVENT_FIELDS)])
                items.append(to_event(raw, calendar_id))
        nxt = page.get('@odata.nextLink')
        return Changes(items, removed, nxt or page.get('@odata.deltaLink') or cursor, bool(nxt))


# -- signing in ---------------------------------------------------------------------------------------------------------------------------------------
def authorize_url(client_id, redirect_uri, state, challenge, *, hint=None, add=()) -> str:
    """Microsoft's sign-in (v2, common: personal and work accounts). Only reading is asked for; `add` names grants (GRANTS) asked on top for an account already connected."""
    if set(add or ()) - {g.name for g in GRANTS}:
        raise ValueError('unknown permission')
    scopes = [MAIL_SCOPE, CALENDAR_SCOPE, *IDENTITY_SCOPES] + [g.scope for g in GRANTS if g.name in set(add or ())]
    query = {'client_id': client_id, 'response_type': 'code', 'redirect_uri': redirect_uri, 'response_mode': 'query', 'scope': ' '.join(scopes), 'state': state,
             'code_challenge': challenge, 'code_challenge_method': 'S256', 'prompt': 'select_account'}
    if hint:
        query['login_hint'] = hint
    return AUTHORIZE_URL + '?' + urlencode(query)


def _short(scope) -> str:
    return scope.rsplit('/', 1)[-1] if scope.startswith('https://graph.microsoft.com/') else scope


def _token_call(http, form):
    status, headers, raw = http('POST', TOKEN_URL, {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}, urlencode(form).encode())
    data = json.loads(raw or b'{}') if raw else {}
    if status != 200:
        code = str(data.get('error') or '')
        described = str(data.get('error_description') or '')
        if 'AADSTS65001' in described or code in ('consent_required', 'admin_consent_required') or 'AADSTS90094' in described:
            raise ProviderError(403, 'admin_consent_required')
        raise ProviderError(status, code or 'token_error')
    return data


def _decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))


def exchanger(client_id, client_secret, http=default_http):
    """-> exchange(code, verifier, redirect_uri): the tokens, and which account it is (the ID token's address, checked against Graph's own /me)."""
    from .connectors import Exchange

    def exchange(code, verifier, redirect_uri):
        data = _token_call(http, {'client_id': client_id, 'client_secret': client_secret, 'code': code, 'redirect_uri': redirect_uri, 'grant_type': 'authorization_code',
                                  'code_verifier': verifier})
        granted = sorted({_short(s) for s in str(data.get('scope') or '').split()})
        tokens = {'access_token': data.get('access_token'), 'refresh_token': data.get('refresh_token'), 'scope': ' '.join(granted), 'expires_in': data.get('expires_in')}
        if not tokens['access_token'] or not tokens['refresh_token']:
            raise ProviderError(0, 'no_tokens')
        claims = {}
        try:
            claims = json.loads(_decode(str(data.get('id_token', '')).split('.')[1]))
        except (IndexError, ValueError):
            claims = {}
        identity = ''
        try:
            identity = MicrosoftAdapter(http)._me(tokens)                   # Graph's own answer for the signed-in mailbox
        except ProviderError:
            identity = ''
        if not identity:
            identity = str(claims.get('email') or claims.get('preferred_username') or '').lower()
        return Exchange(tokens=tokens, identity=identity, granted_scopes=granted)
    return exchange


def refresher(client_id, client_secret, http=default_http):
    from .connector_refresh import RefreshFault

    def refresh(tokens):
        if not tokens.get('refresh_token'):
            raise RefreshFault('needs_customer')
        try:
            data = _token_call(http, {'client_id': client_id, 'client_secret': client_secret, 'refresh_token': tokens['refresh_token'], 'grant_type': 'refresh_token',
                                      'scope': ' '.join(tokens.get('scope', '').split() or [MAIL_SCOPE, CALENDAR_SCOPE, *IDENTITY_SCOPES])})
        except ProviderError as error:
            if error.code in ('invalid_grant', 'interaction_required'):
                raise RefreshFault('revoked') from None
            raise RefreshFault('needs_customer' if error.status in (400, 401, 403) else 'temporary') from None
        if not data.get('access_token'):
            raise RefreshFault('temporary')
        return {'tokens': {**tokens, 'access_token': data['access_token'], 'refresh_token': data.get('refresh_token') or tokens['refresh_token'],
                           **({'scope': ' '.join(sorted({_short(s) for s in data['scope'].split()}))} if data.get('scope') else {})}, 'expires_in': data.get('expires_in')}
    return refresh


def register(registry, http=default_http):
    registry.register(DECLARATION, lambda: MicrosoftAdapter(http))
    return registry
