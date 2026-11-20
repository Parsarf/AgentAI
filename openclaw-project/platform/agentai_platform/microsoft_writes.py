"""Changing Outlook mail and calendars through the action pipeline (roadmap Phase 6, #D8): the same kinds of change as Google, by the same names, so the screens, the
tools and the workflows do not change. Nothing here is called by a model; an approved action is executed by the action runner, once.

How Graph differs, and what Lumina does about it:
* Idempotency. A message or an event Lumina makes carries a private extended property holding the change's key (MARK), which Graph can search for: before a send or a
  create, and after a lost answer, the item is looked for by it, so nothing is ever made twice.
* Outlook always tells the people invited to an event; a change that asks it not to is refused before anything is sent (the preview always says who is told).
* A message is in one folder; Outlook has flags and categories rather than labels. Organizing a conversation changes each of its messages, and what each looked like
  before (folder, flag, read, categories) is recorded, so one undo puts every one back.
* A cancelled occurrence of a series cannot be brought back in Outlook: cancelling one is the one change here that cannot be undone, and its preview says so.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .connector_kit import ProviderError, WriteKind, record
from . import google_calendar_writes as neutral
from . import google_mail_writes as neutral_mail

MARK = 'String {6b1f0e3c-9a2d-4f5e-8c1b-1f2a3b4c5d6e} Name LuminaChange'
WEEK = 7 * 86400
WRITE_KINDS = (
    WriteKind('event.create', 'Create an event', policy_kind='invite', undo='event.delete', capability='event_write', undo_seconds=WEEK),
    WriteKind('event.delete', 'Cancel an event', policy_kind='delete', undo='event.recreate', capability='event_write', needs_version=True, undo_seconds=WEEK),
    WriteKind('event.recreate', 'Put a cancelled event back', policy_kind='invite', undo='event.delete', capability='event_write', undo_seconds=WEEK),
    WriteKind('event.respond', 'Answer an invitation', policy_kind='write', undo='event.respond', capability='respond', needs_version=True, undo_seconds=WEEK),
    WriteKind('event.update', 'Change an event', policy_kind='invite', undo='event.update', capability='event_change', needs_version=True, undo_seconds=WEEK),
    WriteKind('event.end_series', 'Cancel this and later occurrences', policy_kind='delete', undo='event.update', capability='event_series', needs_version=True, undo_seconds=WEEK),
    WriteKind('event.cancel_one', 'Cancel one occurrence', policy_kind='delete', capability='event_series', needs_version=True,
              irreversible_reason='Outlook cannot bring back a cancelled occurrence; it can be created again as a single event.'),
    WriteKind('mail.send', 'Send an email', policy_kind='send', capability='send', compensations=('mail.send',),
              irreversible_reason='A sent email cannot be taken back. A correction can be sent to the same people.'),
    WriteKind('mail.organize', 'Organize mail', policy_kind='write', undo='mail.organize', capability='organize', undo_seconds=WEEK),
    WriteKind('mail.mark', 'Mark mail read or unread', policy_kind='write', undo='mail.mark', capability='mark_read', undo_seconds=WEEK),
    WriteKind('mail.trash', 'Move mail to the bin', policy_kind='delete', undo='mail.untrash', capability='organize', undo_seconds=WEEK),
    WriteKind('mail.untrash', 'Take mail out of the bin', policy_kind='write', undo='mail.trash', capability='organize', undo_seconds=WEEK),
)
KINDS = {k.name for k in WRITE_KINDS}
DAYS = {'MO': 'monday', 'TU': 'tuesday', 'WE': 'wednesday', 'TH': 'thursday', 'FR': 'friday', 'SA': 'saturday', 'SU': 'sunday'}


# -- the neutral rules, with Outlook's differences ----------------------------------------------------------------------------------------------------
def check(kind, payload):
    if kind.startswith('mail.'):
        if kind in ('mail.organize', 'mail.mark', 'mail.trash', 'mail.untrash') and isinstance(payload, dict) and 'restore' in payload:
            restore = payload['restore']
            if not isinstance(restore, dict) or len(restore) > 2000 or any(not isinstance(v, dict) or set(v) - {'folder', 'flag', 'read', 'categories'} for v in restore.values()):
                raise ValueError('invalid request for this kind of change')
            rest = {k: v for k, v in payload.items() if k != 'restore'}
            if rest:
                neutral_mail.check(kind, rest)
            return
        return neutral_mail.check(kind, payload)
    if kind in ('event.create', 'event.recreate') and isinstance(payload, dict) and payload.get('attendees') and payload.get('notify') is False:
        raise ValueError('Outlook always tells the people invited to an event')
    if kind == 'event.update' and isinstance(payload, dict) and 'graph_recurrence' in payload:
        if set(payload) - {'event', 'graph_recurrence', 'notify'} or not isinstance(payload['graph_recurrence'], dict):
            raise ValueError('invalid request for this kind of change')
        neutral.split_id(payload['event'])
        return
    if kind in ('event.cancel_one', 'event.end_series'):
        allowed = {'event', 'notify'} | ({'series'} if kind == 'event.end_series' else set())
        if not isinstance(payload, dict) or set(payload) - allowed or not isinstance(payload.get('event'), str):
            raise ValueError('invalid request for this kind of change')
        ids = [payload['event']] + ([payload['series']] if kind == 'event.end_series' else [])
        if kind == 'event.end_series' and not isinstance(payload.get('series'), str):
            raise ValueError('invalid request for this kind of change')
        if len({neutral.split_id(i)[0] for i in ids}) != 1:
            raise ValueError('invalid request for this kind of change')
        return
    if kind == 'event.update' and isinstance(payload, dict) and 'occurrence' in payload:
        neutral.check(kind, {k: v for k, v in payload.items() if k != 'occurrence'})
        if not isinstance(payload['occurrence'], str) or neutral.split_id(payload['occurrence'])[0] != neutral.split_id(payload['event'])[0]:
            raise ValueError('invalid request for this kind of change')
        return
    return neutral.check(kind, payload)


def preview(kind, payload, before):
    if kind.startswith('mail.'):
        if kind == 'mail.send':
            return neutral_mail.preview(kind, payload, before)
        threads = ((before or {}).get('data') or {}).get('threads') or {}
        shown = neutral_mail.preview(kind, {k: v for k, v in payload.items() if k != 'restore'} if 'restore' not in payload or len(payload) > 1
                                     else {'threads': list(threads)} if kind in ('mail.trash', 'mail.untrash') else {'changes': [{'thread': t, 'add': ['inbox']} for t in threads]},
                                     before)
        if 'restore' in payload and len(payload) == 1:
            shown['summary'] = f'Put {len(payload["restore"])} {"message" if len(payload["restore"]) == 1 else "messages"} back as they were'
        return shown
    if kind == 'event.update' and 'graph_recurrence' in payload:
        data = (before or {}).get('data') or {}
        return {'destination': f'Calendar {neutral.split_id(payload["event"])[0]}', 'summary': f'Put the repeats of "{data.get("title") or "(no title)"}" back as they were',
                'affected': 1, 'changes': [{'field': 'repeats', 'before': None, 'after': 'As before'}]}
    if kind in ('event.create', 'event.recreate'):
        shown = neutral.preview(kind, payload, before)
        for c in shown['changes']:
            if c['field'] == 'invitations':
                c['after'] = f'{len(payload.get("attendees") or [])} {"person" if len(payload.get("attendees") or []) == 1 else "people"} will be invited by email'
        return shown
    if kind == 'event.cancel_one':
        data = (before or {}).get('data') or {}
        n = len([a for a in data.get('attendee_addresses') or [] if a and a != data.get('self_address')])
        return {'destination': f'Calendar {neutral.split_id(payload["event"])[0]}', 'summary': f'Cancel one occurrence of "{data.get("title") or "(no title)"}"', 'affected': 1,
                'changes': [{'field': 'event', 'before': data.get('title') or '(no title)', 'after': None}]
                + ([{'field': 'invitations', 'before': None, 'after': f'{n} {"person is" if n == 1 else "people are"} told it is cancelled'}] if n else [])
                + [{'field': 'series', 'before': None, 'after': 'Only this occurrence; Outlook cannot bring it back afterwards'}]}
    if kind == 'event.end_series':
        data = (before or {}).get('data') or {}
        return {'destination': f'Calendar {neutral.split_id(payload["event"])[0]}', 'summary': f'Cancel "{data.get("title") or "(no title)"}" from this occurrence on', 'affected': 1,
                'changes': [{'field': 'series', 'before': None, 'after': 'This and every later occurrence is cancelled; earlier ones stay'}]}
    return neutral.preview(kind, payload, before)


def undo_payload(kind, payload, before):
    data = (before or {}).get('data') or {}
    if kind in ('mail.organize', 'mail.mark', 'mail.trash', 'mail.untrash'):
        states = data.get('messages') or {}
        return {'restore': states} if states else None
    if kind == 'mail.send':
        return None
    if kind == 'event.end_series':
        return {'event': payload['series'], 'graph_recurrence': data['graph_recurrence'], 'notify': bool(payload.get('notify', True))} if data.get('graph_recurrence') else None
    if kind == 'event.update' and 'graph_recurrence' in payload:
        return {'event': payload['event'], 'graph_recurrence': data['graph_recurrence'], 'notify': True} if data.get('graph_recurrence') else None
    return neutral.undo_payload(kind, payload, before)


def undo_after(kind, undo, result):
    return neutral.undo_after(kind, undo, result) if kind.startswith('event.') else undo


def compensation_payload(kind, compensation, payload, result):
    return neutral_mail.compensation_payload(kind, compensation, payload, result) if kind == 'mail.send' else None


def verify(kind, payload, found):
    if kind == 'mail.send':
        return neutral_mail.verify(kind, payload, found)
    if kind.startswith('mail.'):
        if found is None:
            return False, 'it could not be read back'
        states = (found.get('data') or {}).get('messages') or {}
        ok = _mail_applied(kind, payload, states)
        return ok, 'every message shows the change' if ok else 'some messages do not show the change'
    if kind in ('event.delete', 'event.cancel_one'):
        gone = found is None or (found.get('data') or {}).get('cancelled')
        return bool(gone), 'the event is cancelled' if gone else 'the event is still there'
    if found is None:
        return False, 'the event is not there'
    data = found.get('data') or {}
    if kind == 'event.respond':
        same = data.get('my_response') == payload['response']
        return same, 'your answer is recorded' if same else 'your answer there is different'
    if kind == 'event.end_series':
        ended = ((data.get('graph_recurrence') or {}).get('range') or {}).get('type') == 'endDate'
        return ended, 'the series now ends there' if ended else 'the series does not end there'
    if kind == 'event.update' and 'graph_recurrence' in payload:
        same = data.get('graph_recurrence') == payload['graph_recurrence']
        return same, 'the repeats are as before' if same else 'the repeats differ'
    if kind == 'event.update':
        ok = (('title' not in payload or data.get('title') == payload['title']) and ('place' not in payload or (data.get('place') or '') == (payload['place'] or ''))
              and ('attendees' not in payload or sorted(a for a in data.get('attendee_addresses') or [] if a != data.get('self_address'))
                   == sorted(a.strip().lower() for a in payload['attendees'] if a.strip().lower() != data.get('self_address'))))
        return ok, 'what was sent is what is there' if ok else 'what is there differs from what was sent'
    ok = data.get('title') == payload.get('title') and sorted(data.get('attendee_addresses') or []) == sorted(a.strip().lower() for a in payload.get('attendees') or [])
    return ok, 'what was sent is what is there' if ok else 'what is there differs from what was sent'


def _mail_applied(kind, payload, states) -> bool:
    if 'restore' in payload:
        return all(states.get(m, {}).get('folder') == want.get('folder') for m, want in payload['restore'].items() if 'folder' in want)
    if kind == 'mail.trash':
        return all(s.get('well_known') == 'deleteditems' for s in states.values())
    if kind == 'mail.untrash':
        return all(s.get('well_known') != 'deleteditems' for s in states.values())
    for c in payload.get('changes') or []:
        mine = [s for s in states.values() if s.get('conversation') == c['thread']]
        for w in c.get('add', []):
            if w == 'unread' and any(s.get('read') for s in mine) or w == 'starred' and any(not s.get('flag') for s in mine) or w == 'inbox' and any(s.get('well_known') != 'inbox' for s in mine):
                return False
        for w in c.get('remove', []):
            if w == 'unread' and any(not s.get('read') for s in mine) or w == 'starred' and any(s.get('flag') for s in mine) or w == 'inbox' and any(s.get('well_known') == 'inbox' for s in mine):
                return False
    return True


# -- converting -------------------------------------------------------------------------------------------------------------------------------------------
def to_graph_recurrence(rule, start_day: str) -> dict:
    """One RRULE line (the subset the Calendar offers) as Graph's patternedRecurrence. Raises ValueError for what Outlook cannot say."""
    parts = dict(p.split('=', 1) for p in rule[len('RRULE:'):].split(';') if '=' in p)
    freq, interval = parts.get('FREQ'), int(parts.get('INTERVAL', '1'))
    days = [DAYS[d[-2:]] for d in parts.get('BYDAY', '').split(',') if d and d[-2:] in DAYS]
    start = datetime.strptime(start_day, '%Y-%m-%d')
    if freq == 'DAILY':
        pattern = {'type': 'daily', 'interval': interval}
    elif freq == 'WEEKLY':
        pattern = {'type': 'weekly', 'interval': interval, 'daysOfWeek': days or [start.strftime('%A').lower()], 'firstDayOfWeek': 'monday'}
    elif freq == 'MONTHLY':
        pattern = {'type': 'absoluteMonthly', 'interval': interval, 'dayOfMonth': int(parts.get('BYMONTHDAY', start.day))}
    elif freq == 'YEARLY':
        pattern = {'type': 'absoluteYearly', 'interval': interval, 'dayOfMonth': start.day, 'month': start.month}
    else:
        raise ValueError('Outlook cannot repeat an event that way')
    if 'COUNT' in parts:
        span = {'type': 'numbered', 'startDate': start_day, 'numberOfOccurrences': int(parts['COUNT'])}
    elif 'UNTIL' in parts:
        span = {'type': 'endDate', 'startDate': start_day, 'endDate': datetime.strptime(parts['UNTIL'][:8], '%Y%m%d').strftime('%Y-%m-%d')}
    else:
        span = {'type': 'noEnd', 'startDate': start_day}
    return {'pattern': pattern, 'range': span}


def _local(part):
    """A Graph dateTime (asked in UTC) as aware datetime."""
    return datetime.fromisoformat(str(part['dateTime'])[:26].rstrip('Z')).replace(tzinfo=timezone.utc)


def to_record(calendar_id, raw, me='') -> dict:
    people = [str(((a.get('emailAddress') or {}).get('address')) or '').lower() for a in raw.get('attendees') or [] if a.get('type') != 'resource']
    from .microsoft_hub import RESPONSES
    mine = RESPONSES.get(((raw.get('responseStatus') or {}).get('response')) or 'none')
    local = None
    try:
        zone = (raw.get('originalStartTimeZone') or 'UTC')
        if raw.get('isAllDay'):
            local = {'start': _local(raw['start']).strftime('%Y-%m-%d'), 'end': _local(raw['end']).strftime('%Y-%m-%d'), 'all_day': True}
        else:
            local = {'start': _local(raw['start']).strftime('%Y-%m-%dT%H:%M'), 'end': _local(raw['end']).strftime('%Y-%m-%dT%H:%M'), 'timezone': 'UTC', 'all_day': False}
    except (KeyError, ValueError, TypeError):
        local = None
    again = None
    if local and raw.get('type') in (None, 'singleInstance', 'seriesMaster') and not raw.get('isCancelled'):
        again = {'calendar': calendar_id, 'title': raw.get('subject') or '(no title)', **{k: v for k, v in local.items()}, 'attendees': [p for p in people if p and p != me][:50],
                 **({'place': raw['location']['displayName'][:500]} if (raw.get('location') or {}).get('displayName') else {}), 'notify': True}
    data = {'title': raw.get('subject') or '', 'attendee_addresses': people, 'cancelled': bool(raw.get('isCancelled')), 'my_response': None if raw.get('isOrganizer') else mine,
            'recurring': raw.get('type') == 'seriesMaster', 'series_id': raw.get('seriesMasterId'), 'organizer_is_me': bool(raw.get('isOrganizer')), 'recreate': again,
            'local': local, 'place': str(((raw.get('location') or {}).get('displayName')) or ''), 'description': str(raw.get('bodyPreview') or ''),
            'graph_recurrence': raw.get('recurrence'), 'recurrence_lines': [], 'self_address': me or None, 'original_start': raw.get('originalStart')}
    return record('event', f'{calendar_id}|{raw["id"]}', container=('calendar', calendar_id), version=raw.get('@odata.etag') or raw.get('changeKey'),
                  title=raw.get('subject') or '', data=data)


def _event_body(payload, *, mark=None) -> dict:
    out = {}
    if 'title' in payload:
        out['subject'] = payload['title']
    if 'start' in payload:
        if payload.get('all_day'):
            out.update({'isAllDay': True, 'start': {'dateTime': payload['start'] + 'T00:00:00', 'timeZone': 'UTC'}, 'end': {'dateTime': payload['end'] + 'T00:00:00', 'timeZone': 'UTC'}})
        else:
            out.update({'isAllDay': False, 'start': {'dateTime': payload['start'] + ':00', 'timeZone': payload.get('timezone') or 'UTC'},
                        'end': {'dateTime': payload['end'] + ':00', 'timeZone': payload.get('timezone') or 'UTC'}})
    if 'place' in payload:
        out['location'] = {'displayName': payload['place'] or ''}
    if 'description' in payload:
        out['body'] = {'contentType': 'text', 'content': payload['description'] or ''}
    if 'attendees' in payload:
        out['attendees'] = [{'emailAddress': {'address': a.strip()}, 'type': 'required'} for a in payload['attendees']]
    if payload.get('recurrence'):
        out['recurrence'] = to_graph_recurrence(payload['recurrence'][0], payload['start'][:10])
    if payload.get('visibility') in ('private', 'public'):
        out['sensitivity'] = 'private' if payload['visibility'] == 'private' else 'normal'
    if mark:
        out['singleValueExtendedProperties'] = [{'id': MARK, 'value': mark}]
    return out


class MicrosoftWrites:
    """Mixed into MicrosoftAdapter: `self._get`, `self._send` are the adapter's."""

    def _ok(self, status, headers, raw, allowed=(200, 201, 202, 204)):
        if status == 412:
            raise ProviderError(412, 'PreconditionFailed')
        if status not in allowed:
            from .microsoft_hub import _failure
            raise _failure(status, headers, raw)
        return json.loads(raw or b'{}') if raw else {}

    def _marked(self, credential, where, mark):
        flt = f"singleValueExtendedProperties/Any(ep: ep/id eq '{MARK}' and ep/value eq '{mark}')"
        page = self._get(credential, where, [('$filter', flt), ('$select', 'id,parentFolderId,conversationId'), ('$top', '5')])
        return (page.get('value') or [None])[0]

    def _event(self, credential, event_id):
        from .microsoft_hub import EVENT_FIELDS
        try:
            return self._get(credential, f'/me/events/{quote(event_id, safe="")}', [('$select', EVENT_FIELDS + ',recurrence,originalStart')])
        except ProviderError as error:
            if error.status in (404, 410):
                return None
            raise

    def _conversation(self, credential, thread):
        flt = f"conversationId eq '{thread}'"
        return self._get(credential, '/me/messages', [('$filter', flt), ('$select', 'id,parentFolderId,flag,isRead,categories,conversationId'), ('$top', '100')]).get('value') or []

    # -- the contract's methods for changes ---------------------------------------------------------------------------------------------------------
    @staticmethod
    def target_of(kind, payload):
        if kind == 'mail.send':
            return None
        if kind.startswith('mail.'):
            ids = (list(payload.get('restore') or {}) and ['messages:' + ','.join(sorted(payload['restore']))]) or \
                  (payload.get('threads') if kind in ('mail.trash', 'mail.untrash') else [c.get('thread') for c in payload.get('changes') or []])
            return ('threads', ','.join(sorted(str(t) for t in ids)))
        if kind == 'event.end_series':
            return ('event', str(payload['series']))
        return ('event', str(payload['event'])) if kind not in ('event.create', 'event.recreate') else None

    def container_of(self, credential, kind, payload):
        if kind.startswith('mail.'):
            return ('mail', 'all')
        if kind in ('event.create', 'event.recreate'):
            return ('calendar', str(payload.get('calendar', '')))
        return ('calendar', neutral.split_id(payload['event'])[0])

    def read(self, credential, record_kind, record_id):
        if record_kind == 'event':
            calendar_id, event_id = neutral.split_id(record_id)
            raw = self._event(credential, event_id)
            return to_record(calendar_id, raw, self._me(credential)) if raw else None
        if record_kind == 'message':
            raw = self._get(credential, f'/me/messages/{quote(record_id, safe="")}', [('$select', 'id,toRecipients,ccRecipients,parentFolderId,conversationId')])
            people = [str(((p.get('emailAddress') or {}).get('address')) or '').lower() for p in (raw.get('toRecipients') or []) + (raw.get('ccRecipients') or [])]
            folders = self._folders(credential)
            sent = folders.get(raw.get('parentFolderId'), {}).get('well_known') == 'sentitems'
            return record('message', raw['id'], container=('mail', 'all'), data={'labels': ['SENT'] if sent else [], 'recipients': people, 'thread': raw.get('conversationId')})
        if record_kind == 'threads':
            folders = self._folders(credential)
            if record_id.startswith('messages:'):
                messages = []
                for mid in record_id[len('messages:'):].split(','):
                    try:
                        messages.append(self._get(credential, f'/me/messages/{quote(mid, safe="")}', [('$select', 'id,parentFolderId,flag,isRead,categories,conversationId')]))
                    except ProviderError:
                        continue
            else:
                messages = [m for t in record_id.split(',') if t for m in self._conversation(credential, t)]
            states = {m['id']: {'folder': m.get('parentFolderId'), 'well_known': folders.get(m.get('parentFolderId'), {}).get('well_known'), 'flag': ((m.get('flag') or {}).get('flagStatus')) == 'flagged',
                                'read': bool(m.get('isRead')), 'categories': list(m.get('categories') or []), 'conversation': m.get('conversationId')} for m in messages}
            subjects = {m.get('conversationId'): '' for m in messages}
            return record('threads', record_id, container=('mail', 'all'), data={'messages': states, 'threads': {t: {'subject': s, 'labels': []} for t, s in subjects.items()}})
        return None

    def write(self, credential, kind, payload, *, idempotency_key=None, precondition=None):
        if kind == 'mail.send':
            return self._mail_send(credential, payload)
        if kind.startswith('mail.'):
            return self._mail_change(credential, kind, payload)
        return self._event_write(credential, kind, payload, idempotency_key, precondition)

    def find_effect(self, credential, kind, payload, idempotency_key):
        if kind == 'mail.send':
            found = self._marked(credential, '/me/mailFolders/sentitems/messages', neutral_mail.marker(payload['draft']))
            return {'receipt': f'outlook-message-{found["id"]}', 'record': self.read(credential, 'message', found['id'])} if found else None
        if kind.startswith('mail.'):
            target = self.target_of(kind, payload)
            now = self.read(credential, *target)
            return {'receipt': f'outlook-{kind}', 'record': now} if now and _mail_applied(kind, payload, now['data']['messages']) else None
        if kind in ('event.create', 'event.recreate'):
            found = self._marked(credential, f'/me/calendars/{quote(payload["calendar"], safe="")}/events', idempotency_key)
            return {'receipt': f'outlook-event-{found["id"]}', 'record': self.read(credential, 'event', f'{payload["calendar"]}|{found["id"]}')} if found else None
        target = self.target_of(kind, payload)
        now = self.read(credential, *target) if target else None
        if kind in ('event.delete', 'event.cancel_one'):
            return {'receipt': f'outlook-event-cancelled', 'record': now or record('event', payload['event'], data={'cancelled': True})} if not now or now['data'].get('cancelled') else None
        ok, _ = verify(kind, payload, now)
        return {'receipt': f'outlook-{kind}', 'record': now} if ok else None

    # -- mail -----------------------------------------------------------------------------------------------------------------------------------
    def _mail_send(self, credential, payload):
        mark = neutral_mail.marker(payload['draft'])
        already = self._marked(credential, '/me/mailFolders/sentitems/messages', mark)       # sent before (a retry, or a second change for the same draft): never again
        if already:
            return {'receipt': f'outlook-message-{already["id"]}', 'record': self.read(credential, 'message', already['id'])}
        draft = self._marked(credential, '/me/mailFolders/drafts/messages', mark)            # made but not sent (the answer was lost between the two steps)
        people = lambda xs: [{'emailAddress': {'address': a.strip()}} for a in xs or []]
        content = {'subject': payload.get('subject') or '', 'body': {'contentType': 'text', 'content': payload.get('body') or ''}, 'toRecipients': people(payload.get('to')),
                   'ccRecipients': people(payload.get('cc')), 'singleValueExtendedProperties': [{'id': MARK, 'value': mark}]}
        if draft is None:
            if payload.get('reply_to'):
                made = self._ok(*self._send(credential, 'POST', f'/me/messages/{quote(payload["reply_to"], safe="")}/createReply', {}))
                self._ok(*self._send(credential, 'PATCH', f'/me/messages/{quote(made["id"], safe="")}', content))
            else:
                made = self._ok(*self._send(credential, 'POST', '/me/messages', content))
            draft = made
        self._ok(*self._send(credential, 'POST', f'/me/messages/{quote(draft["id"], safe="")}/send', {}), allowed=(202, 204, 200))
        sent = None
        for _ in range(3):
            sent = self._marked(credential, '/me/mailFolders/sentitems/messages', mark)
            if sent:
                break
        return {'receipt': f'outlook-message-{(sent or draft)["id"]}', 'record': self.read(credential, 'message', sent['id']) if sent else
                record('message', draft['id'], container=('mail', 'all'), data={'labels': ['SENT'], 'recipients': [a.strip().lower() for a in (payload.get('to') or []) + (payload.get('cc') or [])]})}

    def _mail_change(self, credential, kind, payload):
        folders = self._folders(credential)
        by_name = {f['well_known']: fid for fid, f in folders.items() if f.get('well_known')}
        def patch(mid, body):
            self._ok(*self._send(credential, 'PATCH', f'/me/messages/{quote(mid, safe="")}', body))
        def move(mid, folder):
            self._ok(*self._send(credential, 'POST', f'/me/messages/{quote(mid, safe="")}/move', {'destinationId': folder}))
        if 'restore' in payload:                                                            # undo: each message back as it was
            for mid, want in payload['restore'].items():
                now = self._get(credential, f'/me/messages/{quote(mid, safe="")}', [('$select', 'id,parentFolderId,flag,isRead,categories')])
                if 'folder' in want and now.get('parentFolderId') != want['folder']:
                    move(mid, want['folder'])
                change = {}
                if 'flag' in want and (((now.get('flag') or {}).get('flagStatus')) == 'flagged') != want['flag']:
                    change['flag'] = {'flagStatus': 'flagged' if want['flag'] else 'notFlagged'}
                if 'read' in want and bool(now.get('isRead')) != want['read']:
                    change['isRead'] = want['read']
                if 'categories' in want and list(now.get('categories') or []) != want['categories']:
                    change['categories'] = want['categories']
                if change:
                    patch(mid, change)
            return {'receipt': f'outlook-restored-{len(payload["restore"])}', 'record': record('threads', 'messages:' + ','.join(sorted(payload['restore'])), container=('mail', 'all'))}
        threads = payload['threads'] if kind in ('mail.trash', 'mail.untrash') else [c['thread'] for c in payload['changes']]
        changes = {c['thread']: c for c in payload.get('changes') or []}
        for t in threads:
            for m in self._conversation(credential, t):
                if kind == 'mail.trash':
                    move(m['id'], by_name['deleteditems'])
                elif kind == 'mail.untrash':
                    if folders.get(m.get('parentFolderId'), {}).get('well_known') == 'deleteditems':
                        move(m['id'], by_name['inbox'])
                else:
                    c = changes[t]
                    body = {}
                    for w in c.get('add', []):
                        if w == 'unread':
                            body['isRead'] = False
                        elif w == 'starred':
                            body['flag'] = {'flagStatus': 'flagged'}
                        elif w == 'inbox' and m.get('parentFolderId') != by_name.get('inbox'):
                            move(m['id'], by_name['inbox'])
                        elif w.startswith('label:category:'):
                            body['categories'] = sorted(set(m.get('categories') or []) | {w[len('label:category:'):]})
                        elif w.startswith('label:'):
                            move(m['id'], w[len('label:'):])
                    for w in c.get('remove', []):
                        if w == 'unread':
                            body['isRead'] = True
                        elif w == 'starred':
                            body['flag'] = {'flagStatus': 'notFlagged'}
                        elif w == 'inbox' and m.get('parentFolderId') == by_name.get('inbox') and not any(x.startswith('label:') and not x.startswith('label:category:') for x in c.get('add', [])):
                            move(m['id'], by_name['archive'])
                        elif w.startswith('label:category:'):
                            body['categories'] = sorted(set(m.get('categories') or []) - {w[len('label:category:'):]})
                    if body:
                        patch(m['id'], body)
        return {'receipt': f'outlook-{kind}-{len(threads)}', 'record': record('threads', ','.join(sorted(threads)), container=('mail', 'all'))}

    # -- calendars ----------------------------------------------------------------------------------------------------------------------------------
    def _event_write(self, credential, kind, payload, key, precondition):
        headers = {'If-Match': str(precondition)} if precondition else {}
        me = self._me(credential)
        if kind in ('event.create', 'event.recreate'):
            if not key:
                raise ProviderError(400, 'invalid')
            cal = payload['calendar']
            found = self._marked(credential, f'/me/calendars/{quote(cal, safe="")}/events', key)
            made = found and self._event(credential, found['id'])
            if not made:
                made = self._ok(*self._send(credential, 'POST', f'/me/calendars/{quote(cal, safe="")}/events', {**_event_body(payload, mark=key), 'transactionId': key[:200]}))
            return {'receipt': f'outlook-event-{made["id"]}', 'record': to_record(cal, made, me)}
        cal, event_id = neutral.split_id(payload['event'])
        if kind == 'event.delete':
            raw = self._event(credential, event_id)
            if raw is None or raw.get('isCancelled'):
                return {'receipt': f'outlook-event-{event_id}-cancelled', 'record': record('event', payload['event'], container=('calendar', cal), data={'cancelled': True})}
            if raw.get('isOrganizer') and raw.get('attendees') and payload.get('notify', True):
                self._ok(*self._send(credential, 'POST', f'/me/events/{quote(event_id, safe="")}/cancel', {'comment': ''}, headers=headers), allowed=(202, 204, 200))
            else:
                self._ok(*self._send(credential, 'DELETE', f'/me/events/{quote(event_id, safe="")}', headers=headers), allowed=(204, 200, 404))
            return {'receipt': f'outlook-event-{event_id}-cancelled', 'record': record('event', payload['event'], container=('calendar', cal), data={'cancelled': True})}
        if kind == 'event.cancel_one':
            self._ok(*self._send(credential, 'DELETE', f'/me/events/{quote(event_id, safe="")}', headers=headers), allowed=(204, 200, 404))
            return {'receipt': f'outlook-event-{event_id}-cancelled', 'record': record('event', payload['event'], container=('calendar', cal), data={'cancelled': True})}
        if kind == 'event.respond':
            verb = {'accepted': 'accept', 'declined': 'decline', 'tentative': 'tentativelyAccept'}.get(payload['response'])
            if verb is None:
                raise ProviderError(400, 'invalid')                                         # Outlook cannot take an answer back to "not answered"
            self._ok(*self._send(credential, 'POST', f'/me/events/{quote(event_id, safe="")}/{verb}', {'comment': payload.get('note') or '', 'sendResponse': bool(payload.get('notify', True))}),
                     allowed=(202, 204, 200))
            return {'receipt': f'outlook-event-{event_id}-{payload["response"]}', 'record': to_record(cal, self._event(credential, event_id), me)}
        if kind == 'event.end_series':
            master_id = neutral.split_id(payload['series'])[1]
            master, occurrence = self._event(credential, master_id), self._event(credential, event_id)
            if not master or not master.get('recurrence') or not occurrence:
                raise ProviderError(404, 'ErrorItemNotFound')
            last = (_local(occurrence.get('originalStart') and {'dateTime': occurrence['originalStart']} or occurrence['start']) - timedelta(days=1)).strftime('%Y-%m-%d')
            rec = {**master['recurrence'], 'range': {'type': 'endDate', 'startDate': master['recurrence']['range']['startDate'], 'endDate': last}}
            changed = self._ok(*self._send(credential, 'PATCH', f'/me/events/{quote(master_id, safe="")}', {'recurrence': rec}, headers=headers))
            return {'receipt': f'outlook-event-{master_id}-ended', 'record': to_record(cal, changed, me)}
        if kind == 'event.update' and 'graph_recurrence' in payload:
            changed = self._ok(*self._send(credential, 'PATCH', f'/me/events/{quote(event_id, safe="")}', {'recurrence': payload['graph_recurrence']}, headers=headers))
            return {'receipt': f'outlook-event-{event_id}-repeats', 'record': to_record(cal, changed, me)}
        if kind == 'event.update':
            body = _event_body({k: v for k, v in payload.items() if k not in ('event', 'occurrence', 'notify')})
            if payload.get('occurrence') and 'start' in payload:
                occ = self._event(credential, neutral.split_id(payload['occurrence'])[1])
                master = self._event(credential, event_id)
                if not occ or not master:
                    raise ProviderError(404, 'ErrorItemNotFound')
                shift = datetime.fromisoformat(payload['start']).replace(tzinfo=timezone.utc) - _local({'dateTime': occ.get('originalStart') or occ['start']['dateTime']})
                start, end = _local(master['start']) + shift, _local(master['end']) + shift
                body['start'] = {'dateTime': start.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'UTC'}
                body['end'] = {'dateTime': end.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'UTC'}
            changed = self._ok(*self._send(credential, 'PATCH', f'/me/events/{quote(event_id, safe="")}', body, headers=headers))
            return {'receipt': f'outlook-event-{event_id}-changed', 'record': to_record(cal, changed, me)}
        raise ProviderError(400, 'invalid')
