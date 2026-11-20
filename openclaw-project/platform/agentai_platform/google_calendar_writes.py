"""Changing Google calendars through the action pipeline (roadmap Phase 6, #61 and #63): the write kinds, their checks and previews, how each is undone, and the adapter
methods that send them. Nothing here is called by a model: an approved action (the customer's own press, or their approval of what the assistant prepared) is executed by
the action runner (actions.py), once.

Idempotency: an event created by Lumina gets an id derived from the action's idempotency key (`<request id>-<step>`, made by Lumina). Google accepts a client-chosen event id
and refuses a second insert of the same id (409), so a retried create can never make a second event, and an unknown outcome is settled by reading that id.

Concurrent edits (#25): a change to an existing event carries its version (the ETag) as `If-Match`; Google answers 412 when the event changed meanwhile: `conflict`.

Record ids: an event is `<calendar id>|<event id>` (a calendar id never holds "|", an event id is base32hex or a series instance id).

Repeating events (#62, #63, #64): the customer always chooses how much of a series a change touches, and each choice is its own kind of change, so that each has its own
way back. One occurrence: `event.update`, `event.cancel_one` (back: `event.restore`). The whole series: `event.update` or `event.delete` on the series itself. This and
every later occurrence: `event.update_rest` splits the series in two (the original ends just before this occurrence, a new series carries the change from it on; back:
`event.unsplit`), `event.end_series` ends the series before this occurrence (back: `event.update` restoring its repeat rule). Google names an occurrence after its series and
the moment it was first scheduled (`<series id>_<UTC start>`), which is how a change finds where in the series it is.
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
CHANGE_FIELDS = {'title', 'start', 'end', 'timezone', 'all_day', 'attendees', 'place', 'description', 'recurrence'}
RULE_LINE = re.compile(r'(RRULE|EXRULE|RDATE|EXDATE)[:;][^\r\n]{1,500}')
INSTANCE = re.compile(r'(?P<series>.+)_(?P<day>\d{8})(T(?P<time>\d{6})Z)?')
WEEK = 7 * 86400

WRITE_KINDS = (
    WriteKind('event.create', 'Create an event', policy_kind='invite', undo='event.delete', capability='event_write', undo_seconds=7 * 86400),
    WriteKind('event.delete', 'Cancel an event', policy_kind='delete', undo='event.recreate', capability='event_write', needs_version=True, undo_seconds=7 * 86400),
    WriteKind('event.recreate', 'Put a cancelled event back', policy_kind='invite', undo='event.delete', capability='event_write', undo_seconds=7 * 86400),
    WriteKind('event.respond', 'Answer an invitation', policy_kind='write', undo='event.respond', capability='respond', needs_version=True, undo_seconds=7 * 86400),
    # Changing (#62) and the parts of a series (#62, #63). Each is proven on the real provider before the customer can use it (HubCaps.proving).
    WriteKind('event.update', 'Change an event', policy_kind='invite', undo='event.update', capability='event_change', needs_version=True, undo_seconds=WEEK),
    WriteKind('event.update_rest', 'Change this and later occurrences', policy_kind='invite', undo='event.unsplit', capability='event_series', needs_version=True,
              undo_seconds=WEEK),
    WriteKind('event.unsplit', 'Put a split series back together', policy_kind='invite', capability='event_series', needs_version=True,
              irreversible_reason='It is itself the undo of a change to a series; to change it again, change the series.'),
    WriteKind('event.cancel_one', 'Cancel one occurrence', policy_kind='delete', undo='event.restore', capability='event_series', needs_version=True, undo_seconds=WEEK),
    WriteKind('event.restore', 'Put a cancelled occurrence back', policy_kind='invite', undo='event.cancel_one', capability='event_series', needs_version=True,
              undo_seconds=WEEK),
    WriteKind('event.end_series', 'Cancel this and later occurrences', policy_kind='delete', undo='event.update', capability='event_series', needs_version=True,
              undo_seconds=WEEK),
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


def original_start(event_id):
    """When this occurrence of a series was first scheduled: an aware UTC datetime, or a date for an all-day series. None when the id is not an occurrence's."""
    found = INSTANCE.fullmatch(str(event_id or ''))
    if not found:
        return None
    try:
        if found['time']:
            return datetime.strptime(found['day'] + found['time'], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        return datetime.strptime(found['day'], '%Y%m%d').date()
    except ValueError:
        return None


def series_of(event_id):
    found = INSTANCE.fullmatch(str(event_id or ''))
    return found['series'] if found else None


def truncated(lines, split) -> list:
    """The series' rules with its repeat ending just before `split` (the first occurrence that is no longer part of it)."""
    until = (split - timedelta(seconds=1)).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ') if isinstance(split, datetime) else (split - timedelta(days=1)).strftime('%Y%m%d')
    out = []
    for line in lines or []:
        if line.startswith('RRULE:'):
            parts = [p for p in line[6:].split(';') if p and not p.startswith(('COUNT=', 'UNTIL='))]
            line = 'RRULE:' + ';'.join(parts + ['UNTIL=' + until])
        out.append(line)
    return out


def counted(lines):
    for line in lines or []:
        if line.startswith('RRULE:'):
            for part in line[6:].split(';'):
                if part.startswith('COUNT=') and part[6:].isdigit():
                    return int(part[6:])
    return None


def with_count(lines, count) -> list:
    return [('RRULE:' + ';'.join(('COUNT=%d' % count) if p.startswith('COUNT=') else p for p in line[6:].split(';'))) if line.startswith('RRULE:') else line
            for line in lines or []]


def _same_calendar(*ids):
    calendars = {split_id(i)[0] for i in ids}
    if len(calendars) != 1:
        raise ValueError('invalid request for this kind of change')


def _occurrence_of(event, series):
    """Is `event` an occurrence of `series` (both record ids)? Raises ValueError otherwise."""
    _same_calendar(event, series)
    if series_of(split_id(event)[1]) != split_id(series)[1] or original_start(split_id(event)[1]) is None:
        raise ValueError('that is not an occurrence of this series')


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
    if kind in ('event.update', 'event.update_rest'):
        allowed = {'event', 'notify'} | CHANGE_FIELDS | ({'occurrence'} if kind == 'event.update' else {'series'})
        if set(payload) - allowed or not text('event', 1400) or not isinstance(payload.get('notify', True), bool):
            raise ValueError('invalid request for this kind of change')
        split_id(payload['event'])
        if kind == 'event.update_rest':
            if not text('series', 1400):
                raise ValueError('invalid request for this kind of change')
            _occurrence_of(payload['event'], payload['series'])
            if 'recurrence' in payload:
                raise ValueError('the repeat rule of a series is changed on the whole series')
        if 'occurrence' in payload:
            if not text('occurrence', 1400) or original_start(split_id(payload['occurrence'])[1]) is None:
                raise ValueError('invalid request for this kind of change')
            _occurrence_of(payload['occurrence'], payload['event'])
        if not set(payload) & CHANGE_FIELDS:
            raise ValueError('nothing to change')
        if ('title' in payload and not text('title', 500)) or ('place' in payload and not text('place', 500, 0)) \
                or ('description' in payload and not text('description', 8000, 0)) or not isinstance(payload.get('all_day', False), bool):
            raise ValueError('invalid request for this kind of change')
        if 'start' in payload or 'end' in payload or 'timezone' in payload or 'all_day' in payload:
            pattern = DAY if payload.get('all_day') else LOCAL
            if not (text('start', 16) and text('end', 16) and pattern.fullmatch(payload['start']) and pattern.fullmatch(payload['end'])):
                raise ValueError('a start and an end are needed, as YYYY-MM-DDTHH:MM (or YYYY-MM-DD for a whole day)')
            if not payload.get('all_day') and not text('timezone', 64):
                raise ValueError('a timed event needs its timezone')
            start, end = _when(payload)
            if not end > start or (end - start) > timedelta(days=366):
                raise ValueError('the end must be after the start, within a year')
        if 'attendees' in payload:
            people = payload['attendees']
            if not isinstance(people, list) or len(people) > MAX_ATTENDEES or any(not isinstance(a, str) or not ADDRESS.fullmatch(a.strip()) for a in people) \
                    or len({a.strip().lower() for a in people}) != len(people):
                raise ValueError(f'attendees are up to {MAX_ATTENDEES} different email addresses')
        if 'recurrence' in payload:
            rules = payload['recurrence']
            if not isinstance(rules, list) or not 1 <= len(rules) <= 20 or any(not isinstance(r, str) or not RULE_LINE.fullmatch(r) for r in rules):
                raise ValueError('invalid repeat rule')
        return
    if kind == 'event.unsplit':
        if set(payload) - {'remove', 'series', 'recurrence', 'notify'} or not text('remove', 1400) or not text('series', 1400) \
                or not isinstance(payload.get('notify', True), bool):
            raise ValueError('invalid request for this kind of change')
        _same_calendar(payload['remove'], payload['series'])
        rules = payload.get('recurrence')
        if not isinstance(rules, list) or not 1 <= len(rules) <= 20 or any(not isinstance(r, str) or not RULE_LINE.fullmatch(r) for r in rules):
            raise ValueError('invalid repeat rule')
        return
    if kind in ('event.cancel_one', 'event.restore'):
        if set(payload) - {'event', 'notify'} or not text('event', 1400) or not isinstance(payload.get('notify', True), bool) \
                or original_start(split_id(payload['event'])[1]) is None:
            raise ValueError('that is not an occurrence of a series')
        return
    if kind == 'event.end_series':
        if set(payload) - {'event', 'series', 'notify'} or not text('event', 1400) or not text('series', 1400) or not isinstance(payload.get('notify', True), bool):
            raise ValueError('invalid request for this kind of change')
        _occurrence_of(payload['event'], payload['series'])
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
    if kind in ('event.update', 'event.update_rest'):
        return _change_preview(kind, payload, data)
    title = data.get('title') or '(no title)'
    calendar = split_id(payload.get('event') or payload.get('remove'))[0]
    def told(verb):
        n = len([a for a in data.get('attendee_addresses') or [] if a and a != data.get('self_address')])
        if not n:
            return []
        return [{'field': 'invitations', 'before': None, 'after': (f'{n} {"person is" if n == 1 else "people are"} {verb}' if payload.get('notify', True) else 'Nobody is told')}]
    if kind == 'event.cancel_one':
        return {'destination': f'Calendar {calendar}', 'summary': f'Cancel one occurrence of "{title}"', 'affected': 1,
                'changes': [{'field': 'event', 'before': f'{title}, {_when_words(data)}', 'after': None}] + told('told it is cancelled')
                + [{'field': 'series', 'before': None, 'after': 'Only this occurrence is cancelled; the rest of the series stays'}]}
    if kind == 'event.restore':
        return {'destination': f'Calendar {calendar}', 'summary': f'Put back one occurrence of "{title}"', 'affected': 1,
                'changes': [{'field': 'event', 'before': None, 'after': f'{title}, {_when_words(data)}'}] + told('told it is back on')}
    if kind == 'event.end_series':
        when = original_start(split_id(payload['event'])[1])
        day = when.strftime('%a %d %b %Y') if when else 'this occurrence'
        return {'destination': f'Calendar {calendar}', 'summary': f'Cancel "{title}" from {day} on', 'affected': 1,
                'changes': [{'field': 'series', 'before': None, 'after': f'This and every later occurrence is cancelled, from {day}; earlier ones stay'}] + told('told')}
    if kind == 'event.unsplit':
        return {'destination': f'Calendar {calendar}', 'summary': f'Put the series "{title}" back as it was', 'affected': 1,
                'changes': [{'field': 'series', 'before': 'Split in two', 'after': 'One series again, as before the change'}] + told('told')}
    people = [a for a in data.get('attendee_addresses') or [] if a and a != data.get('self_address')]
    told = payload.get('notify', True) and people
    changes = [{'field': 'event', 'before': data.get('title') or '(no title)', 'after': None}]
    if people:
        changes.append({'field': 'invitations', 'before': None, 'after': f'{len(people)} {"person is" if len(people) == 1 else "people are"} told it is cancelled' if told
                        else 'Nobody is told'})
    if data.get('series_id'):
        changes.append({'field': 'series', 'before': None, 'after': 'Only this occurrence is cancelled; the rest of the series stays'})
    elif data.get('recurring'):
        count = counted(data.get('recurrence_lines'))
        changes.append({'field': 'series', 'before': None, 'after': f'All {count} occurrences of the series are cancelled' if count else 'Every occurrence of the series is cancelled'})
    return {'destination': f'Calendar {split_id(payload["event"])[0]}', 'summary': f'Cancel the event "{data.get("title") or "(no title)"}"', 'affected': 1, 'changes': changes}


def _when_words(data) -> str:
    local = data.get('local')
    try:
        return _human(dict(local)) if local else 'at its time'
    except (ValueError, KeyError, TypeError):
        return 'at its time'


def _change_preview(kind, payload, data) -> dict:
    """A change to an event: each field before and after, who is told and how much of a series it touches, built from the payload and the event as it is now."""
    title = data.get('title') or '(no title)'
    changes = []
    if 'title' in payload:
        changes.append({'field': 'title', 'before': title, 'after': payload['title']})
    if 'start' in payload:
        after = _human(payload)
        if payload.get('occurrence'):
            after += '; every other occurrence moves the same way'
        changes.append({'field': 'when', 'before': _when_words(data), 'after': after})
    for field in ('place', 'description'):
        if field in payload:
            changes.append({'field': field, 'before': data.get(field) or None, 'after': payload[field] or None})
    me = data.get('self_address')
    before_people = [a for a in data.get('attendee_addresses') or [] if a and a != me]
    after_people = [a.strip().lower() for a in payload['attendees'] if a.strip().lower() != me] if 'attendees' in payload else before_people
    if 'attendees' in payload:
        added, removed = [a for a in after_people if a not in before_people], [a for a in before_people if a not in after_people]
        changes.append({'field': 'people', 'before': ', '.join(before_people) or None, 'after': ', '.join(after_people) or None})
        if added:
            changes.append({'field': 'invited', 'before': None, 'after': ', '.join(added)})
        if removed:
            changes.append({'field': 'removed', 'before': ', '.join(removed), 'after': None})
    if 'recurrence' in payload:
        changes.append({'field': 'repeats', 'before': '; '.join(data.get('recurrence_lines') or []) or None, 'after': '; '.join(payload['recurrence'])})
    told = sorted(set(before_people) | set(after_people))
    if told:
        changes.append({'field': 'invitations', 'before': None, 'after': (f'{len(told)} {"person is" if len(told) == 1 else "people are"} told about the change'
                                                                          if payload.get('notify', True) else 'Nobody is told')})
    if kind == 'event.update_rest':
        changes.append({'field': 'series', 'before': None, 'after': 'This and every later occurrence; earlier ones stay as they are'})
    elif data.get('series_id'):
        changes.append({'field': 'series', 'before': None, 'after': 'Only this occurrence'})
    elif data.get('recurring'):
        changes.append({'field': 'series', 'before': None, 'after': 'Every occurrence of the series'})
    return {'destination': f'Calendar {split_id(payload["event"])[0]}', 'summary': f'Change "{title}"', 'affected': 1, 'changes': changes}


def _changed_fields_match(payload, data) -> bool:
    """Do the fields this change set hold what was sent? Times are compared only where they were set directly (a whole series moved from one occurrence is checked by
    its other fields; its occurrences are Google's to compute)."""
    if 'title' in payload and data.get('title') != payload['title']:
        return False
    for field in ('place', 'description'):
        if field in payload and (data.get(field) or '') != (payload[field] or ''):
            return False
    if 'attendees' in payload:
        me = data.get('self_address')
        there = sorted(a for a in data.get('attendee_addresses') or [] if a != me)     # the account itself stays on its own event whether or not the list names it
        if there != sorted(a.strip().lower() for a in payload['attendees'] if a.strip().lower() != me):
            return False
    if 'recurrence' in payload and list(data.get('recurrence_lines') or []) != list(payload['recurrence']):
        return False
    if 'start' in payload and not payload.get('occurrence') and 'event' in payload and payload.get('series') is None:
        sent = to_google({'title': '-', **{k: payload[k] for k in ('start', 'end', 'timezone', 'all_day') if k in payload}}, None)
        if data.get('start_raw') != sent['start'] or data.get('end_raw') != sent['end']:
            return False
    return True


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
    data = (before or {}).get('data') or {}
    notify = bool(payload.get('notify', True))
    if kind == 'event.update':
        # The values as they were, for exactly the fields this change touches. Times go back as the event's own (a whole series: its own first occurrence).
        out = {'event': payload['event'], 'notify': notify}
        if 'title' in payload:
            out['title'] = data.get('title') or '(no title)'
        for field in ('place', 'description'):
            if field in payload:
                out[field] = data.get(field) or ''
        if 'attendees' in payload:
            out['attendees'] = [a for a in data.get('attendee_addresses') or [] if a and a != data.get('self_address')][:MAX_ATTENDEES]
        if 'recurrence' in payload:
            if not data.get('recurrence_lines'):
                return None
            out['recurrence'] = list(data['recurrence_lines'])
        if 'start' in payload:
            local = data.get('local')
            if not local:
                return None
            out.update({k: v for k, v in local.items() if k in ('start', 'end', 'timezone', 'all_day')})
        return out
    if kind == 'event.update_rest':
        return {'series': payload['series'], 'recurrence': list(data.get('recurrence_lines') or []), 'notify': notify} if data.get('recurrence_lines') else None
    if kind in ('event.cancel_one', 'event.restore'):
        return {'event': payload['event'], 'notify': notify}
    if kind == 'event.end_series':
        return {'event': payload['series'], 'recurrence': list(data.get('recurrence_lines') or []), 'notify': notify} if data.get('recurrence_lines') else None
    return None


def undo_after(kind, undo, result):
    if kind in ('event.create', 'event.recreate') and isinstance(undo, dict):
        return {'event': result['record']['id'], 'notify': undo.get('notify', False)}
    if kind == 'event.update_rest' and isinstance(undo, dict):
        return {**undo, 'remove': result['record']['id']}             # the new series this change made is what its undo removes
    return undo


def compensation_payload(kind, compensation, payload, result):
    return None


def verify(kind, payload, found):
    """After a write: does what Google holds now match what was sent? -> (matches, a short fixed note)."""
    if kind in ('event.delete', 'event.cancel_one', 'event.unsplit'):
        gone = found is None or (found.get('data') or {}).get('cancelled')
        return bool(gone), 'the event is cancelled' if gone else 'the event is still there'
    if found is None:
        return False, 'the event is not there'
    data = found.get('data') or {}
    if kind == 'event.restore':
        back = not data.get('cancelled')
        return back, 'the occurrence is back' if back else 'the occurrence is still cancelled'
    if kind == 'event.end_series':
        ended = any(line.startswith('RRULE:') and 'UNTIL=' in line for line in data.get('recurrence_lines') or [])
        return ended, 'the series now ends before that occurrence' if ended else 'the series does not end there'
    if kind in ('event.update', 'event.update_rest'):
        same = _changed_fields_match(payload, data)
        return same, 'what was sent is what is there' if same else 'what is there differs from what was sent'

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


def _local_when(raw):
    """An event's start and end as the customer would type them (local wall time and its timezone, or days): what an undo writes back. None when unreadable."""
    start, end = raw.get('start') or {}, raw.get('end') or {}
    try:
        if 'date' in start:
            return {'start': start['date'], 'end': end['date'], 'all_day': True}
        zone = start.get('timeZone') or 'UTC'
        local = lambda part: datetime.fromisoformat(str(part['dateTime']).replace('Z', '+00:00')).astimezone(_zone(part.get('timeZone') or zone)).strftime('%Y-%m-%dT%H:%M')
        return {'start': local(start), 'end': local(end), 'timezone': zone, 'all_day': False}
    except (KeyError, ValueError, TypeError):
        return None


def _moment(part):
    """A start or end from the API as an aware datetime, or a date for an all-day event."""
    if 'date' in (part or {}):
        return datetime.strptime(part['date'], '%Y-%m-%d').date()
    moment = datetime.fromisoformat(str(part['dateTime']).replace('Z', '+00:00'))
    return moment.astimezone(_zone(part['timeZone'])) if part.get('timeZone') else moment


def _as_part(moment, zone_name):
    return {'date': moment.isoformat()} if not isinstance(moment, datetime) else {'dateTime': moment.isoformat(), 'timeZone': zone_name}


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
            'series_id': raw.get('recurringEventId'), 'organizer_is_me': bool((raw.get('organizer') or {}).get('self')), 'recreate': again,
            'local': _local_when(raw), 'place': raw.get('location', '') or '', 'description': raw.get('description', '') or '',
            'recurrence_lines': [str(r) for r in raw.get('recurrence') or []][:20],
            'self_address': next((str(a.get('email') or '').lower() for a in raw.get('attendees') or [] if isinstance(a, dict) and a.get('self')), None)}
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
        if kind in KINDS:
            return ('calendar', split_id(payload.get('event') or payload.get('remove'))[0])
        return None

    @staticmethod
    def target_of(kind, payload):
        """The record whose version a change is based on: the event itself, or the series it changes (this and later occurrences), or the series a split made (its undo)."""
        if kind in ('event.update_rest', 'event.end_series'):
            return ('event', str(payload['series']))
        if kind == 'event.unsplit':
            return ('event', str(payload['remove']))
        return ('event', str(payload['event'])) if kind in KINDS - {'event.create', 'event.recreate'} else None

    def _patch(self, credential, calendar_id, event_id, body, *, precondition, notify):
        headers = {'If-Match': str(precondition)} if precondition else {}
        status, answer_headers, raw = self._send(credential, 'PATCH', self._event_url(calendar_id, event_id) + '?sendUpdates=' + ('all' if notify else 'none'), body, headers=headers)
        if status == 412:
            raise ProviderError(412, 'conditionNotMet')
        if status != 200:
            from .google_hub import _failure
            raise _failure(status, answer_headers, raw)
        return json.loads(raw or b'{}')

    def _count_before(self, credential, calendar_id, series_id, split):
        """How many occurrences of a series come before `split` (cancelled ones too: a repeat count counts them)."""
        low = split.isoformat() if isinstance(split, datetime) else datetime.combine(split, datetime.min.time(), timezone.utc).isoformat()
        total, token = 0, None
        for _ in range(20):
            url = self._event_url(calendar_id, series_id) + '/instances?showDeleted=true&maxResults=2500&timeMax=' + quote(low, safe='')
            page = self._get(credential, url + ('&pageToken=' + quote(token, safe='') if token else ''))
            total += sum(1 for e in page.get('items') or [] if isinstance(e, dict))
            token = page.get('nextPageToken')
            if not token:
                return total
        raise ProviderError(400, 'invalid')                        # more than 50,000 earlier occurrences: not something to split

    @staticmethod
    def _body_for(payload, raw, *, shift_from=None):
        """The PATCH body for the fields a change sets. People who stay keep their entry (and their answer); new ones are added; removed ones are dropped.
        `shift_from`: this change names one occurrence (first scheduled then) and moves the whole series by the same amount."""
        body = {}
        if 'title' in payload:
            body['summary'] = payload['title']
        if 'place' in payload:
            body['location'] = payload['place']
        if 'description' in payload:
            body['description'] = payload['description']
        if 'recurrence' in payload:
            body['recurrence'] = list(payload['recurrence'])
        if 'attendees' in payload:
            kept = {str(a.get('email') or '').lower(): a for a in raw.get('attendees') or [] if isinstance(a, dict)}
            body['attendees'] = [dict(kept.get(a.strip().lower()) or {'email': a.strip()}) for a in payload['attendees']]
            body['attendees'] += [dict(a) for a in raw.get('attendees') or [] if isinstance(a, dict) and (a.get('self') or a.get('resource'))
                                  and str(a.get('email') or '').lower() not in {x.strip().lower() for x in payload['attendees']}]
        if 'start' in payload:
            start, end = _when(payload)
            zone_name = payload.get('timezone') or (raw.get('start') or {}).get('timeZone') or 'UTC'
            if shift_from is not None:
                own = _moment(raw.get('start'))
                if isinstance(own, datetime) != isinstance(start, datetime) or isinstance(shift_from, datetime) != isinstance(start, datetime):
                    raise ProviderError(400, 'invalid')            # a whole day cannot become a time (or back) for a whole series from one occurrence
                moved = own + (start - (shift_from.astimezone(start.tzinfo) if isinstance(start, datetime) else shift_from))
                start, end = moved, moved + (end - start)
            body['start'], body['end'] = _as_part(start, zone_name), _as_part(end, zone_name)
        return body

    def _split_body(self, payload, master, occurrence, lines):
        """The new series that carries a change from one occurrence on: the original's details, the change, and the rest of its repeat rule."""
        body = {k: master[k] for k in ('summary', 'description', 'location', 'attendees', 'visibility', 'transparency', 'reminders', 'colorId') if k in master}
        own_start, own_end = _moment(master.get('start')), _moment(master.get('end'))
        zone_name = (master.get('start') or {}).get('timeZone') or 'UTC'
        first = occurrence.astimezone(own_start.tzinfo) if isinstance(occurrence, datetime) else occurrence
        body['start'], body['end'] = _as_part(first, zone_name), _as_part(first + (own_end - own_start), zone_name)
        body.update(self._body_for(payload, {**master, 'start': body['start']}))
        body['recurrence'] = lines
        return body

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
        notify = bool(payload.get('notify', True))
        if kind == 'event.update':
            calendar_id, event_id = split_id(payload['event'])
            raw = self._read_event(credential, calendar_id, event_id)
            if raw is None or raw.get('status') == 'cancelled':
                raise ProviderError(404, 'notFound')
            shift = original_start(split_id(payload['occurrence'])[1]) if payload.get('occurrence') else None
            changed = self._patch(credential, calendar_id, event_id, self._body_for(payload, raw, shift_from=shift), precondition=precondition, notify=notify)
            return {'receipt': f'google-event-{event_id}-changed', 'record': to_record(calendar_id, changed)}
        if kind == 'event.update_rest':
            # Split: a new series (its id from this change's key, so a retry finds it) carries the change from this occurrence on; then the original ends before it.
            if not idempotency_key:
                raise ProviderError(400, 'invalid')
            calendar_id, master_id = split_id(payload['series'])
            occurrence = original_start(split_id(payload['event'])[1])
            master = self._read_event(credential, calendar_id, master_id)
            if master is None or master.get('status') == 'cancelled' or not master.get('recurrence'):
                raise ProviderError(404, 'notFound')
            lines, cut = list(master['recurrence']), None
            new_id = event_id_for(idempotency_key)
            made = self._read_event(credential, calendar_id, new_id)
            if made is None:
                if precondition and str(master.get('etag')) != str(precondition):
                    raise ProviderError(412, 'conditionNotMet')
                rest = lines
                total = counted(lines)
                if total is not None:
                    before = self._count_before(credential, calendar_id, master_id, occurrence)
                    if before >= total:
                        raise ProviderError(400, 'invalid')
                    rest = with_count(lines, total - before)
                status, headers, answer = self._send(credential, 'POST', self._event_url(calendar_id) + '?sendUpdates=' + ('all' if notify else 'none'),
                                                     {**self._split_body(payload, master, occurrence, rest), 'id': new_id})
                if status == 409:
                    made = self._read_event(credential, calendar_id, new_id)
                elif status in (200, 201):
                    made = json.loads(answer or b'{}')
                else:
                    from .google_hub import _failure
                    raise _failure(status, headers, answer)
            cut = truncated(lines, occurrence)
            if lines != cut:                                   # already ended there (a retry after the original was ended): nothing more to send
                try:
                    self._patch(credential, calendar_id, master_id, {'recurrence': cut}, precondition=master.get('etag'), notify=notify)
                except ProviderError as error:
                    if error.status == 412:
                        # Changed by someone meanwhile: the original cannot be ended safely, so the new series is taken back and nothing is left half done.
                        self._send(credential, 'DELETE', self._event_url(calendar_id, new_id) + '?sendUpdates=none')
                    raise
            return {'receipt': f'google-event-{new_id}-split', 'record': to_record(calendar_id, made)}
        if kind == 'event.unsplit':
            calendar_id, remove_id = split_id(payload['remove'])
            headers = {'If-Match': str(precondition)} if precondition else {}
            status, answer_headers, raw = self._send(credential, 'DELETE', self._event_url(calendar_id, remove_id) + '?sendUpdates=' + ('all' if notify else 'none'), headers=headers)
            if status == 412:
                raise ProviderError(412, 'conditionNotMet')
            if status not in (200, 204, 410):
                from .google_hub import _failure
                raise _failure(status, answer_headers, raw)
            master_id = split_id(payload['series'])[1]
            master = self._read_event(credential, calendar_id, master_id)
            if master is None:
                raise ProviderError(404, 'notFound')
            if list(master.get('recurrence') or []) != list(payload['recurrence']):
                self._patch(credential, calendar_id, master_id, {'recurrence': list(payload['recurrence'])}, precondition=master.get('etag'), notify=notify)
            return {'receipt': f'google-event-{remove_id}-unsplit', 'record': record('event', payload['remove'], container=('calendar', calendar_id), data={'cancelled': True})}
        if kind == 'event.cancel_one':
            calendar_id, event_id = split_id(payload['event'])
            headers = {'If-Match': str(precondition)} if precondition else {}
            status, answer_headers, raw = self._send(credential, 'DELETE', self._event_url(calendar_id, event_id) + '?sendUpdates=' + ('all' if notify else 'none'), headers=headers)
            if status == 412:
                raise ProviderError(412, 'conditionNotMet')
            if status not in (200, 204, 410):
                from .google_hub import _failure
                raise _failure(status, answer_headers, raw)
            after = self._read_event(credential, calendar_id, event_id)            # the cancelled occurrence keeps an id and a version: what putting it back is based on
            found = to_record(calendar_id, after) if after else record('event', payload['event'], container=('calendar', calendar_id), data={'cancelled': True})
            return {'receipt': f'google-event-{event_id}-cancelled', 'record': found}
        if kind == 'event.restore':
            calendar_id, event_id = split_id(payload['event'])
            changed = self._patch(credential, calendar_id, event_id, {'status': 'confirmed'}, precondition=precondition, notify=notify)
            return {'receipt': f'google-event-{event_id}-restored', 'record': to_record(calendar_id, changed)}
        if kind == 'event.end_series':
            calendar_id, master_id = split_id(payload['series'])
            master = self._read_event(credential, calendar_id, master_id)
            if master is None or master.get('status') == 'cancelled' or not master.get('recurrence'):
                raise ProviderError(404, 'notFound')
            cut = truncated(master['recurrence'], original_start(split_id(payload['event'])[1]))
            if list(master['recurrence']) != cut:
                master = self._patch(credential, calendar_id, master_id, {'recurrence': cut}, precondition=precondition, notify=notify)
            return {'receipt': f'google-event-{master_id}-ended', 'record': to_record(calendar_id, master)}
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
        if kind == 'event.update':
            calendar_id, event_id = split_id(payload['event'])
            found = self._read_event(credential, calendar_id, event_id)
            now = to_record(calendar_id, found) if found else None
            return {'receipt': f'google-event-{event_id}-changed', 'record': now} if now and _changed_fields_match(payload, now['data']) else None
        if kind == 'event.update_rest':
            calendar_id, master_id = split_id(payload['series'])
            made = self._read_event(credential, calendar_id, event_id_for(idempotency_key))
            master = self._read_event(credential, calendar_id, master_id)
            if not made or made.get('status') == 'cancelled' or not master:
                return None
            ended = list(master.get('recurrence') or []) == truncated(master.get('recurrence') or [], original_start(split_id(payload['event'])[1]))
            return {'receipt': f'google-event-{made["id"]}-split', 'record': to_record(calendar_id, made)} if ended else None
        if kind in ('event.unsplit', 'event.cancel_one'):
            calendar_id, event_id = split_id(payload.get('remove') or payload['event'])
            found = self._read_event(credential, calendar_id, event_id)
            if found is not None and found.get('status') != 'cancelled':
                return None
            if kind == 'event.unsplit':
                master = self._read_event(credential, calendar_id, split_id(payload['series'])[1])
                if not master or list(master.get('recurrence') or []) != list(payload['recurrence']):
                    return None
            return {'receipt': f'google-event-{event_id}-{"unsplit" if kind == "event.unsplit" else "cancelled"}',
                    'record': to_record(calendar_id, found) if found else record('event', payload.get('remove') or payload['event'], container=('calendar', calendar_id), data={'cancelled': True})}
        if kind == 'event.restore':
            calendar_id, event_id = split_id(payload['event'])
            found = self._read_event(credential, calendar_id, event_id)
            return {'receipt': f'google-event-{event_id}-restored', 'record': to_record(calendar_id, found)} if found and found.get('status') != 'cancelled' else None
        if kind == 'event.end_series':
            calendar_id, master_id = split_id(payload['series'])
            master = self._read_event(credential, calendar_id, master_id)
            if not master:
                return None
            ended = list(master.get('recurrence') or []) == truncated(master.get('recurrence') or [], original_start(split_id(payload['event'])[1]))
            return {'receipt': f'google-event-{master_id}-ended', 'record': to_record(calendar_id, master)} if ended else None
        return None

    check = staticmethod(check)
    preview = staticmethod(preview)
    undo_payload = staticmethod(undo_payload)
    undo_after = staticmethod(undo_after)
    compensation_payload = staticmethod(compensation_payload)
    verify = staticmethod(verify)
