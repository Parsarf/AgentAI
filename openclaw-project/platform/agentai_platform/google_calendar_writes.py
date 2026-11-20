"""Changing Google calendars through the action pipeline (roadmap Phase 6, #61 and #63): the write kinds, their checks and previews, how each is undone, and the adapter
methods that send them. Nothing here is called by a model: an approved action (the customer's own press, or their approval of what the assistant prepared) is executed by
the action runner (actions.py), once.

Idempotency: an event created by Lumina gets an id derived from the action's idempotency key (`<request id>-<step>`, made by Lumina). Google accepts a client-chosen event id
and refuses a second insert of the same id (409), so a retried create can never make a second event, and an unknown outcome is settled by reading that id.

Concurrent edits (#25): a change to an existing event carries its version (the ETag) as `If-Match`; Google answers 412 when the event changed meanwhile: `conflict`.

Record ids: an event is `<calendar id>|<event id>` (a calendar id never holds "|", an event id is base32hex or a series instance id).
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .connector_kit import ProviderError, Unanswered, WriteKind, record

CALENDAR = 'https://www.googleapis.com/calendar/v3'
MAX_ATTENDEES = 50
LOCAL = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}')
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
RRULE = re.compile(r'RRULE:FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)(;(INTERVAL=\d{1,3}|COUNT=\d{1,3}|UNTIL=\d{8}(T\d{6}Z)?|BYDAY=([+-]?\d?(MO|TU|WE|TH|FR|SA|SU),?){1,7}|BYMONTHDAY=-?\d{1,2}))*')
ADDRESS = re.compile(r'[^@\s<>"]{1,64}@[^@\s<>"]{1,255}')
FIELDS = {'calendar', 'title', 'start', 'end', 'timezone', 'all_day', 'attendees', 'place', 'description', 'recurrence', 'visibility', 'notify'}

WRITE_KINDS = (
    WriteKind('event.create', 'Create an event', policy_kind='invite', undo='event.delete', capability='event_write', undo_seconds=7 * 86400),
    WriteKind('event.delete', 'Cancel an event', policy_kind='delete', undo='event.recreate', capability='event_write', needs_version=True, undo_seconds=7 * 86400),
    WriteKind('event.recreate', 'Put a cancelled event back', policy_kind='invite', undo='event.delete', capability='event_write', undo_seconds=7 * 86400),
    WriteKind('event.respond', 'Answer an invitation', policy_kind='write', undo='event.respond', capability='respond', needs_version=True, undo_seconds=7 * 86400),
)
RESPONSES = {'accepted': 'accepted', 'declined': 'declined', 'tentative': 'tentative', 'needs_action': 'needsAction'}
RESPONSE_WORDS = {'accepted': 'Going', 'declined': 'Not going', 'tentative': 'Maybe', 'needs_action': 'Not answered'}
KINDS = {k.name for k in WRITE_KINDS}


def event_id_for(key: str) -> str:
    """The id an event created under this idempotency key gets: base32hex, which is what Google allows (a to v and 0 to 9, 5 to 1024 characters)."""
    return 'lm' + base64.b32hexencode(hashlib.sha256(str(key).encode()).digest()).decode().rstrip('=').lower()


def split_id(record_id):
    calendar_id, _, event_id = str(record_id or '').rpartition('|')
    if not calendar_id or not event_id:
        raise ValueError('invalid event')
    return calendar_id, event_id


def _zone(name):
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('invalid timezone') from None


def _when(payload) -> tuple:
    """(start, end) as aware datetimes for a timed event, or as dates for an all-day one. Raises ValueError for a time that does not exist (inside a clock change)."""
    if payload.get('all_day'):
        start, end = datetime.strptime(payload['start'], '%Y-%m-%d').date(), datetime.strptime(payload['end'], '%Y-%m-%d').date()
        return start, end
    zone = _zone(payload['timezone'])
    out = []
    for key in ('start', 'end'):
        local = datetime.strptime(payload[key], '%Y-%m-%dT%H:%M')
        aware = local.replace(tzinfo=zone)
        if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
            raise ValueError('that time does not exist on that day (the clocks change)')
        out.append(aware)
    return tuple(out)


def check(kind, payload):
    """Is this a well-formed change of this kind? Raises ValueError with a fixed sentence. Called when the change is proposed, long before anything is sent."""
    if not isinstance(payload, dict):
        raise ValueError('invalid request for this kind of change')
    text = lambda key, most, least=1: isinstance(payload.get(key), str) and least <= len(payload[key]) <= most
    if kind in ('event.create', 'event.recreate'):
        if set(payload) - FIELDS or not text('calendar', 300) or '|' in payload['calendar'] or not text('title', 500) or not isinstance(payload.get('all_day', False), bool):
            raise ValueError('invalid request for this kind of change')
        pattern = DAY if payload.get('all_day') else LOCAL
        if not (text('start', 16) and text('end', 16) and pattern.fullmatch(payload['start']) and pattern.fullmatch(payload['end'])):
            raise ValueError('a start and an end are needed, as YYYY-MM-DDTHH:MM (or YYYY-MM-DD for a whole day)')
        if not payload.get('all_day') and not text('timezone', 64):
            raise ValueError('a timed event needs its timezone')
        start, end = _when(payload)
        if not end > start or (end - start) > timedelta(days=366):
            raise ValueError('the end must be after the start, within a year')
        people = payload.get('attendees', [])
        if not isinstance(people, list) or len(people) > MAX_ATTENDEES or any(not isinstance(a, str) or not ADDRESS.fullmatch(a.strip()) for a in people) \
                or len({a.strip().lower() for a in people}) != len(people):
            raise ValueError(f'attendees are up to {MAX_ATTENDEES} different email addresses')
        if ('place' in payload and not text('place', 500, 0)) or ('description' in payload and not text('description', 8000, 0)):
            raise ValueError('invalid request for this kind of change')
        rules = payload.get('recurrence', [])
        if not isinstance(rules, list) or len(rules) > 2 or any(not isinstance(r, str) or not RRULE.fullmatch(r) for r in rules):
            raise ValueError('a repeat rule is one RRULE line such as RRULE:FREQ=WEEKLY;COUNT=10')
        if payload.get('visibility', 'default') not in ('default', 'private', 'public') or not isinstance(payload.get('notify', bool(people)), bool):
            raise ValueError('invalid request for this kind of change')
        return
    if kind == 'event.delete':
        if set(payload) - {'event', 'notify'} or not text('event', 1400) or not isinstance(payload.get('notify', True), bool):
            raise ValueError('invalid request for this kind of change')
        split_id(payload['event'])
        return
    if kind == 'event.respond':
        if set(payload) - {'event', 'response', 'note', 'notify'} or not text('event', 1400) or payload.get('response') not in RESPONSES \
                or ('note' in payload and not text('note', 500, 0)) or not isinstance(payload.get('notify', True), bool):
            raise ValueError('an answer is accepted, tentative, declined (or needs_action to undo one), with an optional short note')
        split_id(payload['event'])
        return
    raise ValueError('invalid request for this kind of change')


def _human(payload) -> str:
    if payload.get('all_day'):
        start, end = _when(payload)
        last = end - timedelta(days=1)
        return start.strftime('%a %d %b %Y') + ('' if last == start else ' to ' + last.strftime('%a %d %b %Y')) + ', all day'
    start, end = _when(payload)
    same = start.date() == end.date()
    return f"{start.strftime('%a %d %b %Y, %H:%M')} to {end.strftime('%H:%M') if same else end.strftime('%a %d %b, %H:%M')} ({payload['timezone']})"


def preview(kind, payload, before):
    """What the customer is shown: built only from the payload that will be sent and the event as it is now, never from anything the assistant wrote about it."""
    if kind in ('event.create', 'event.recreate'):
        people = payload.get('attendees') or []
        notify = payload.get('notify', bool(people))
        changes = [{'field': 'title', 'before': None, 'after': payload['title']}, {'field': 'when', 'before': None, 'after': _human(payload)}]
        changes += [{'field': f, 'before': None, 'after': payload[f]} for f in ('place', 'description') if payload.get(f)]
        if people:
            changes.append({'field': 'people', 'before': None, 'after': ', '.join(people)})
            changes.append({'field': 'invitations', 'before': None,
                            'after': f'{len(people)} {"person" if len(people) == 1 else "people"} will be invited by email' if notify else 'No invitation is sent'})
        if payload.get('recurrence'):
            changes.append({'field': 'repeats', 'before': None, 'after': '; '.join(payload['recurrence'])})
        if payload.get('visibility', 'default') != 'default':
            changes.append({'field': 'visibility', 'before': None, 'after': payload['visibility']})
        verb = 'Put back' if kind == 'event.recreate' else 'Create'
        return {'destination': f'Calendar {payload["calendar"]}', 'summary': f'{verb} the event "{payload["title"]}" on {_human(payload)}', 'affected': 1, 'changes': changes}
    data = (before or {}).get('data') or {}
    if kind == 'event.respond':
        was, now = data.get('my_response'), payload['response']
        changes = [{'field': 'your answer', 'before': RESPONSE_WORDS.get(was, was), 'after': RESPONSE_WORDS[now]}]
        if payload.get('note'):
            changes.append({'field': 'note to the organizer', 'before': None, 'after': payload['note']})
        changes.append({'field': 'organizer', 'before': None, 'after': 'The organizer is told' if payload.get('notify', True) else 'The organizer is not told by email'})
        if data.get('series_id') is None and data.get('recurring'):
            changes.append({'field': 'series', 'before': None, 'after': 'Every occurrence of the series'})
        elif data.get('series_id'):
            changes.append({'field': 'series', 'before': None, 'after': 'Only this occurrence'})
        return {'destination': f'Calendar {split_id(payload["event"])[0]}', 'summary': f'Answer "{RESPONSE_WORDS[now]}" to "{data.get("title") or "(no title)"}"', 'affected': 1,
                'changes': changes}
    people = [a for a in data.get('attendee_addresses') or [] if a]
    told = payload.get('notify', True) and people
    changes = [{'field': 'event', 'before': data.get('title') or '(no title)', 'after': None}]
    if people:
        changes.append({'field': 'invitations', 'before': None, 'after': f'{len(people)} {"person is" if len(people) == 1 else "people are"} told it is cancelled' if told
                        else 'Nobody is told'})
    if data.get('series_id'):
        changes.append({'field': 'series', 'before': None, 'after': 'Only this occurrence is cancelled; the rest of the series stays'})
    return {'destination': f'Calendar {split_id(payload["event"])[0]}', 'summary': f'Cancel the event "{data.get("title") or "(no title)"}"', 'affected': 1, 'changes': changes}


def undo_payload(kind, payload, before):
    """What the inverse needs, taken BEFORE the forward write: a creation is undone by deleting what it made (its id is known after, `undo_after`); a cancellation by
    creating the same event again from the event as it was."""
    if kind in ('event.create', 'event.recreate'):
        return {'notify': bool(payload.get('notify', bool(payload.get('attendees'))))}
    if kind == 'event.delete':
        data = (before or {}).get('data') or {}
        again = data.get('recreate')
        return dict(again) if isinstance(again, dict) else None
    if kind == 'event.respond':
        was = ((before or {}).get('data') or {}).get('my_response')
        return {'event': payload['event'], 'response': was if was in RESPONSES else 'needs_action', 'notify': bool(payload.get('notify', True))}
    return None


def undo_after(kind, undo, result):
    if kind in ('event.create', 'event.recreate') and isinstance(undo, dict):
        return {'event': result['record']['id'], 'notify': undo.get('notify', False)}
    return undo


def compensation_payload(kind, compensation, payload, result):
    return None


def verify(kind, payload, found):
    """After a write: does what Google holds now match what was sent? -> (matches, a short fixed note)."""
    if kind == 'event.delete':
        gone = found is None or (found.get('data') or {}).get('cancelled')
        return bool(gone), 'the event is cancelled' if gone else 'the event is still there'
    if found is None:
        return False, 'the event is not there'
    data = found.get('data') or {}
    if kind == 'event.respond':
        same = data.get('my_response') == payload['response']
        return same, 'your answer is recorded' if same else 'your answer there is different'
    sent = to_google(payload, None)
    same = (data.get('title') == payload['title'] and data.get('start_raw') == sent['start'] and data.get('end_raw') == sent['end']
            and sorted(data.get('attendee_addresses') or []) == sorted(a.strip().lower() for a in payload.get('attendees') or []))
    return same, 'what was sent is what is there' if same else 'what is there differs from what was sent'


def to_google(payload, event_id):
    """The Calendar API body for a create."""
    if payload.get('all_day'):
        when = {'start': {'date': payload['start']}, 'end': {'date': payload['end']}}
    else:
        start, end = _when(payload)
        when = {'start': {'dateTime': start.isoformat(), 'timeZone': payload['timezone']}, 'end': {'dateTime': end.isoformat(), 'timeZone': payload['timezone']}}
    body = {'summary': payload['title'], **when}
    if event_id:
        body['id'] = event_id
    if payload.get('place'):
        body['location'] = payload['place']
    if payload.get('description'):
        body['description'] = payload['description']
    if payload.get('attendees'):
        body['attendees'] = [{'email': a.strip()} for a in payload['attendees']]
    if payload.get('recurrence'):
        body['recurrence'] = list(payload['recurrence'])
    if payload.get('visibility', 'default') != 'default':
        body['visibility'] = payload['visibility']
    return body


def _raw_when(part):
    """A start or end of an event as the API gives it, in the shape `to_google` writes (for comparing what was sent with what is there)."""
    part = part or {}
    if 'date' in part:
        return {'date': part['date']}
    text = str(part.get('dateTime') or '')
    try:
        moment = datetime.fromisoformat(text[:-1] + '+00:00' if text.endswith('Z') else text)
        zone = _zone(part['timeZone']) if part.get('timeZone') else moment.tzinfo
        return {'dateTime': moment.astimezone(zone).isoformat(), 'timeZone': part.get('timeZone')}
    except (ValueError, TypeError):
        return {'dateTime': text, 'timeZone': part.get('timeZone')}


def to_record(calendar_id, raw) -> dict:
    """An event as the pipeline's record: the version, what verification compares, and what is needed to put it back if it is cancelled."""
    people = [str(a.get('email') or '').lower() for a in raw.get('attendees') or [] if isinstance(a, dict) and not a.get('resource')]
    start, end = raw.get('start') or {}, raw.get('end') or {}
    again = None
    if raw.get('status') != 'cancelled' and start:
        all_day = 'date' in start
        def local(part):
            if all_day:
                return part.get('date')
            moment = datetime.fromisoformat(str(part['dateTime']).replace('Z', '+00:00'))
            return moment.astimezone(_zone(part.get('timeZone') or start.get('timeZone') or 'UTC')).strftime('%Y-%m-%dT%H:%M')
        try:
            again = {'calendar': calendar_id, 'title': raw.get('summary') or '(no title)', 'start': local(start), 'end': local(end), 'all_day': all_day,
                     **({} if all_day else {'timezone': start.get('timeZone') or 'UTC'}), 'attendees': [p for p in people if p][:MAX_ATTENDEES],
                     **({'place': raw['location'][:500]} if raw.get('location') else {}), **({'description': raw['description'][:8000]} if raw.get('description') else {}),
                     **({'recurrence': list(raw['recurrence'])[:2]} if raw.get('recurrence') else {}), 'notify': bool(people)}
            if not raw.get('recurringEventId'):
                check('event.create', again)
            else:
                again = None                                   # one occurrence of a series is put back through the series itself (#62), not as a new single event
        except (ValueError, KeyError, TypeError):
            again = None
    mine = next((a.get('responseStatus') for a in raw.get('attendees') or [] if isinstance(a, dict) and a.get('self')), None)
    data = {'title': raw.get('summary', ''), 'start_raw': _raw_when(start), 'end_raw': _raw_when(end), 'attendee_addresses': people, 'cancelled': raw.get('status') == 'cancelled',
            'my_response': {v: k for k, v in RESPONSES.items()}.get(mine), 'recurring': bool(raw.get('recurrence')),
            'series_id': raw.get('recurringEventId'), 'organizer_is_me': bool((raw.get('organizer') or {}).get('self')), 'recreate': again}
    return record('event', f'{calendar_id}|{raw["id"]}', container=('calendar', calendar_id), version=raw.get('etag'), title=raw.get('summary', ''), data=data)


class CalendarWrites:
    """Mixed into GoogleAdapter: `self._get(credential, url)` and `self.http` are the adapter's."""

    def _send(self, credential, method, url, body=None, headers=None):
        token = (credential or {}).get('access_token')
        if not token:
            raise ProviderError(401, 'authError')
        sent = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json', **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            sent['Content-Type'] = 'application/json'
        try:
            status, answer_headers, raw = self.http(method, url, sent, data)
        except ProviderError as error:
            if error.status == 0 and error.code == 'unreachable':
                raise Unanswered() from None                   # it may have arrived: the outcome is read back, never sent again blindly
            raise
        return status, answer_headers, raw

    def _event_url(self, calendar_id, event_id=None):
        url = f'{CALENDAR}/calendars/{quote(calendar_id, safe="")}/events'
        return url + (f'/{quote(event_id, safe="")}' if event_id else '')

    def _read_event(self, credential, calendar_id, event_id):
        try:
            raw = self._get(credential, self._event_url(calendar_id, event_id))
        except ProviderError as error:
            if error.status in (404, 410):
                return None
            raise
        return raw if isinstance(raw, dict) and raw.get('id') else None

    # -- free/busy (#59): read with the calendar read permission --------------------------------------------------------------------------------
    def free_busy(self, credential, calendar_ids, start_epoch, end_epoch):
        """-> {calendar id: [(start, end), ...] or None when Google could not answer for that calendar}. Live, so it includes what changed since the last sync."""
        iso = lambda t: datetime.fromtimestamp(int(t), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        out = {}
        ids = list(calendar_ids)
        for at in range(0, len(ids), 50):                        # Google answers for at most 50 calendars a call
            status, headers, raw = self._send(credential, 'POST', f'{CALENDAR}/freeBusy', {'timeMin': iso(start_epoch), 'timeMax': iso(end_epoch),
                                                                                             'items': [{'id': i} for i in ids[at:at + 50]]})
            if status != 200:
                from .google_hub import _failure
                raise _failure(status, headers, raw)
            answer = (json.loads(raw or b'{}').get('calendars') or {})
            for cid in ids[at:at + 50]:
                part = answer.get(cid) or {}
                if part.get('errors'):
                    out[cid] = None
                    continue
                spans = []
                for b in part.get('busy') or []:
                    try:
                        spans.append((int(datetime.fromisoformat(str(b['start']).replace('Z', '+00:00')).timestamp()),
                                      int(datetime.fromisoformat(str(b['end']).replace('Z', '+00:00')).timestamp())))
                    except (KeyError, ValueError, TypeError):
                        continue
                out[cid] = spans
        return out

    # -- the contract's adapter methods for changes ----------------------------------------------------------------------------------------------
    def container_of(self, credential, kind, payload):
        if kind in ('event.create', 'event.recreate'):
            return ('calendar', str(payload.get('calendar', '')))
        if kind in ('event.delete', 'event.respond'):
            return ('calendar', split_id(payload['event'])[0])
        return None

    @staticmethod
    def target_of(kind, payload):
        return ('event', str(payload['event'])) if kind in ('event.delete', 'event.respond') else None

    def read(self, credential, record_kind, record_id):
        if record_kind != 'event':
            return None
        calendar_id, event_id = split_id(record_id)
        raw = self._read_event(credential, calendar_id, event_id)
        return to_record(calendar_id, raw) if raw is not None else None

    def write(self, credential, kind, payload, *, idempotency_key=None, precondition=None):
        if kind in ('event.create', 'event.recreate'):
            if not idempotency_key:
                raise ProviderError(400, 'invalid')                # never created without a key: a retry could make a second event
            calendar_id, event_id = payload['calendar'], event_id_for(idempotency_key)
            notify = 'all' if payload.get('notify', bool(payload.get('attendees'))) else 'none'
            status, headers, raw = self._send(credential, 'POST', self._event_url(calendar_id) + '?sendUpdates=' + notify, to_google(payload, event_id))
            if status == 409:                                   # this key was already used: the event exists, this is its answer
                found = self._read_event(credential, calendar_id, event_id)
                if found is None:
                    raise ProviderError(409, 'duplicate')
                return {'receipt': f'google-event-{event_id}', 'record': to_record(calendar_id, found)}
            if status not in (200, 201):
                from .google_hub import _failure
                raise _failure(status, headers, raw)
            made = json.loads(raw or b'{}')
            return {'receipt': f'google-event-{made.get("id", event_id)}', 'record': to_record(calendar_id, made)}
        if kind == 'event.delete':
            calendar_id, event_id = split_id(payload['event'])
            headers = {'If-Match': str(precondition)} if precondition else {}
            notify = 'all' if payload.get('notify', True) else 'none'
            status, answer_headers, raw = self._send(credential, 'DELETE', self._event_url(calendar_id, event_id) + '?sendUpdates=' + notify, headers=headers)
            if status == 412:
                raise ProviderError(412, 'conditionNotMet')
            if status not in (200, 204, 410):
                from .google_hub import _failure
                raise _failure(status, answer_headers, raw)
            return {'receipt': f'google-event-{event_id}-cancelled', 'record': record('event', payload['event'], container=('calendar', calendar_id), data={'cancelled': True})}
        if kind == 'event.respond':
            # Only the customer's own attendee entry changes; the list is sent whole (the API replaces it), read just now under the same version (If-Match).
            calendar_id, event_id = split_id(payload['event'])
            raw = self._read_event(credential, calendar_id, event_id)
            if raw is None:
                raise ProviderError(404, 'notFound')
            people = [dict(a) for a in raw.get('attendees') or [] if isinstance(a, dict)]
            mine = next((a for a in people if a.get('self')), None)
            if mine is None:
                raise ProviderError(400, 'invalid')                # not invited: there is nothing to answer
            mine['responseStatus'] = RESPONSES[payload['response']]
            if payload.get('note'):
                mine['comment'] = payload['note']
            headers = {'If-Match': str(precondition)} if precondition else {}
            notify = 'all' if payload.get('notify', True) else 'none'
            status, answer_headers, answer = self._send(credential, 'PATCH', self._event_url(calendar_id, event_id) + '?sendUpdates=' + notify, {'attendees': people}, headers=headers)
            if status == 412:
                raise ProviderError(412, 'conditionNotMet')
            if status != 200:
                from .google_hub import _failure
                raise _failure(status, answer_headers, answer)
            changed = json.loads(answer or b'{}')
            return {'receipt': f'google-event-{event_id}-{payload["response"]}', 'record': to_record(calendar_id, changed)}
        raise ProviderError(400, 'invalid')

    def find_effect(self, credential, kind, payload, idempotency_key):
        """A write whose answer never came: did it happen? A creation is found by the id its key gives it; a cancellation by the event being gone."""
        if kind in ('event.create', 'event.recreate'):
            found = self._read_event(credential, payload['calendar'], event_id_for(idempotency_key))
            return {'receipt': f'google-event-{found["id"]}', 'record': to_record(payload['calendar'], found)} if found and found.get('status') != 'cancelled' else None
        if kind == 'event.delete':
            calendar_id, event_id = split_id(payload['event'])
            found = self._read_event(credential, calendar_id, event_id)
            gone = found is None or found.get('status') == 'cancelled'
            return {'receipt': f'google-event-{event_id}-cancelled', 'record': record('event', payload['event'], container=('calendar', calendar_id), data={'cancelled': True})} if gone else None
        if kind == 'event.respond':
            calendar_id, event_id = split_id(payload['event'])
            found = self._read_event(credential, calendar_id, event_id)
            if found is None:
                return None
            now = to_record(calendar_id, found)
            return {'receipt': f'google-event-{event_id}-{payload["response"]}', 'record': now} if now['data']['my_response'] == payload['response'] else None
        return None

    check = staticmethod(check)
    preview = staticmethod(preview)
    undo_payload = staticmethod(undo_payload)
    undo_after = staticmethod(undo_after)
    compensation_payload = staticmethod(compensation_payload)
    verify = staticmethod(verify)
