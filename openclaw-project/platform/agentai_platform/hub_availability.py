"""Free time and scheduling conflicts across every calendar a customer let Lumina read (roadmap Phase 6, #59 and #60). Pure functions; `HubService.free` and
`HubService.conflicts` feed them the provider's live free/busy answer and the synced, expanded event instances.

Times are epoch seconds in and out; the customer's timezone decides working hours, days and how a repeating proposal falls on the clock (the same wall time every time,
across a daylight-saving change). A time that does not exist on a day (inside a spring-forward gap) moves to the next valid time; one that exists twice (fall back) is the
first of the two.
"""
from __future__ import annotations
import re
from datetime import date, datetime, time as clock_time, timedelta, timezone
from zoneinfo import ZoneInfo

DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
DEFAULTS = {'hours': {d: (['09:00', '17:00'] if d not in ('sat', 'sun') else None) for d in DAYS}, 'notice_minutes': 60, 'buffer_minutes': 0, 'busy_calendars': None,
            'tentative_busy': True, 'all_day_busy': True}
HHMM = re.compile(r'([01]\d|2[0-3]):[0-5]\d')
MAX_OCCURRENCES = 200


def clean_settings(raw) -> dict:
    """Validated availability settings, the defaults filled in. Raises ValueError with a fixed word."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    raw = raw if isinstance(raw, dict) else {}
    if set(raw) - set(DEFAULTS):
        raise ValueError('unknown setting')
    if 'hours' in raw:
        hours = raw['hours']
        if not isinstance(hours, dict) or set(hours) - set(DAYS):
            raise ValueError('invalid working hours')
        for day, span in hours.items():
            if span is not None and not (isinstance(span, list) and len(span) == 2 and all(isinstance(x, str) and HHMM.fullmatch(x) for x in span) and span[0] < span[1]):
                raise ValueError('invalid working hours')
            out['hours'][day] = span
    for key, high in (('notice_minutes', 7 * 24 * 60), ('buffer_minutes', 240)):
        if key in raw:
            if type(raw[key]) is not int or not 0 <= raw[key] <= high:
                raise ValueError('invalid ' + key)
            out[key] = raw[key]
    for key in ('tentative_busy', 'all_day_busy'):
        if key in raw:
            if not isinstance(raw[key], bool):
                raise ValueError('invalid ' + key)
            out[key] = raw[key]
    if 'busy_calendars' in raw:
        value = raw['busy_calendars']
        if value is not None and not (isinstance(value, list) and len(value) <= 100 and all(isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) and 0 < len(x) <= 300 for x in p)
                                                                                         for p in value)):
            raise ValueError('invalid busy_calendars')
        out['busy_calendars'] = value
    return out


def local_epoch(day: date, hhmm: str, zone: ZoneInfo) -> int:
    """`hhmm` on `day` in `zone`, as epoch seconds; a time in a spring-forward gap becomes the first valid moment after it."""
    hour, minute = map(int, hhmm.split(':'))
    naive = datetime.combine(day, clock_time(hour, minute))
    for _ in range(16):                                         # a gap is at most a few hours: step on in wall time until the time exists
        aware = naive.replace(tzinfo=zone, fold=0)
        if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive:
            return int(aware.timestamp())
        naive = (naive + timedelta(minutes=15)).replace(minute=(naive.minute + 15) // 15 * 15 % 60) if naive.minute % 15 else naive + timedelta(minutes=15)
    return int(naive.replace(tzinfo=zone).timestamp())


def merge(intervals) -> list:
    out = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [tuple(i) for i in out]


def working_windows(start: int, end: int, settings: dict, zone: ZoneInfo) -> list:
    """The customer's working hours between start and end, as epoch intervals."""
    out, day = [], datetime.fromtimestamp(start, zone).date()
    last = datetime.fromtimestamp(end, zone).date()
    while day <= last:
        span = settings['hours'].get(DAYS[day.weekday()])
        if span:
            low, high = local_epoch(day, span[0], zone), local_epoch(day, span[1], zone)
            if high > low:
                out.append((max(low, start), min(high, end)))
        day += timedelta(days=1)
    return [w for w in out if w[1] > w[0]]


def free_intervals(start: int, end: int, busy: list, settings: dict, zone: ZoneInfo, *, now: int, minutes: int = 30) -> list:
    """Free time of at least `minutes` inside working hours, not before `now` plus the notice, with the buffer kept around every busy block."""
    start = max(start, now + 60 * settings['notice_minutes'])
    if end <= start:
        return []
    pad = 60 * settings['buffer_minutes']
    blocked = merge((b[0] - pad, b[1] + pad) for b in busy)
    out = []
    for low, high in working_windows(start, end, settings, zone):
        cursor = low
        for b_start, b_end in blocked:
            if b_end <= cursor or b_start >= high:
                continue
            if b_start > cursor:
                out.append((cursor, min(b_start, high)))
            cursor = max(cursor, b_end)
        if cursor < high:
            out.append((cursor, high))
    return [i for i in out if i[1] - i[0] >= 60 * minutes]


def all_day_busy(events, zone: ZoneInfo) -> list:
    """All-day events (and out-of-office days) as busy intervals in the customer's timezone, when they count (settings `all_day_busy`)."""
    out = []
    for e in events:
        if e.get('all_day') and not e.get('cancelled') and e.get('my_response') != 'declined' and e.get('start_date'):
            first = datetime.strptime(e['start_date'], '%Y-%m-%d').date()
            last = datetime.strptime(e.get('end_date') or e['start_date'], '%Y-%m-%d').date()
            out.append((local_epoch(first, '00:00', zone), local_epoch(last if last > first else first + timedelta(days=1), '00:00', zone)))
    return out


# -- a proposed time, and its repeats ---------------------------------------------------------------------------------------------------------------------------
RULE = re.compile(r'RRULE:(.+)')
WEEKDAY = {'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6}


def occurrences(start_local: str, end_local: str, zone: ZoneInfo, rule: str | None = None) -> list:
    """The (start, end) epochs of a proposal: one time, or every occurrence of a repeat rule (DAILY, WEEKLY with BYDAY, MONTHLY, YEARLY; INTERVAL; COUNT or UNTIL), at
    the same wall time in the customer's timezone. At most MAX_OCCURRENCES."""
    first = datetime.strptime(start_local, '%Y-%m-%dT%H:%M')
    length = datetime.strptime(end_local, '%Y-%m-%dT%H:%M') - first
    if length <= timedelta(0):
        raise ValueError('the end must be after the start')
    def at(day):
        start = local_epoch(day, first.strftime('%H:%M'), zone)
        return start, start + int(length.total_seconds())
    if not rule:
        return [at(first.date())]
    match = RULE.fullmatch(rule)
    if not match:
        raise ValueError('invalid repeat rule')
    parts = dict(p.split('=', 1) for p in match.group(1).split(';') if '=' in p)
    freq, step = parts.get('FREQ'), int(parts.get('INTERVAL', '1'))
    count = int(parts['COUNT']) if 'COUNT' in parts else None
    until = datetime.strptime(parts['UNTIL'][:8], '%Y%m%d').date() if 'UNTIL' in parts else None
    if freq not in ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY') or not 1 <= step <= 999 or (count is None and until is None):
        raise ValueError('a repeat needs an end (COUNT or UNTIL)')
    days = [WEEKDAY[d[-2:]] for d in parts['BYDAY'].split(',')] if freq == 'WEEKLY' and 'BYDAY' in parts else [first.weekday()]
    out, n, cursor = [], 0, first.date()
    while len(out) < min(count or MAX_OCCURRENCES, MAX_OCCURRENCES) and n < 5000:
        n += 1
        if freq == 'DAILY':
            candidates = [cursor]
            cursor += timedelta(days=step)
        elif freq == 'WEEKLY':
            monday = cursor - timedelta(days=cursor.weekday())
            candidates = sorted(monday + timedelta(days=d) for d in days)
            cursor = monday + timedelta(weeks=step)
        elif freq == 'MONTHLY':
            candidates = [cursor]
            month = cursor.month - 1 + step
            year = cursor.year + month // 12
            try:
                cursor = cursor.replace(year=year, month=month % 12 + 1)
            except ValueError:                                  # the 31st in a shorter month: that month has no occurrence
                cursor = date(year, month % 12 + 1, 1) + timedelta(days=first.day - 1) if first.day <= 28 else date(year, month % 12 + 1, 28)
        else:
            candidates = [cursor]
            cursor = cursor.replace(year=cursor.year + step)
        for day in candidates:
            if day < first.date() or (until and day > until):
                continue
            out.append(at(day))
            if count and len(out) >= count:
                break
        if until and cursor > until:
            break
    return out


def conflicts(proposed: list, events: list, settings: dict, zone: ZoneInfo) -> list:
    """For each proposed (start, end): the events that overlap it, with the buffer. An event the customer may see in detail is named; one shared as busy only is "busy".
    A tentative one is said to be tentative; one the customer declined, a cancelled one and a transparent one (shown as free) do not count."""
    pad = 60 * settings['buffer_minutes']
    timed = [e for e in events if not e.get('all_day') and not e.get('cancelled') and e.get('my_response') != 'declined' and not e.get('transparent')]
    days = all_day_busy(events, zone) if settings['all_day_busy'] else []
    out = []
    for start, end in proposed:
        hits = []
        for e in timed:
            if e['start_epoch'] < end + pad and e['end_epoch'] > start - pad:
                tentative = e.get('my_response') == 'tentative'
                if tentative and not settings['tentative_busy']:
                    continue
                hits.append({'title': 'busy' if e.get('busy_only') else (e.get('title') or '(no title)'), 'start_epoch': e['start_epoch'], 'end_epoch': e['end_epoch'],
                             'tentative': tentative, 'buffer_only': not (e['start_epoch'] < end and e['end_epoch'] > start),
                             'account': e.get('connection_id'), 'calendar': e.get('calendar_id'), 'event': e.get('id') if not e.get('busy_only') else None})
        for (low, high), e in zip(days, [e for e in events if e.get('all_day') and not e.get('cancelled') and e.get('my_response') != 'declined' and e.get('start_date')]):
            if low < end and high > start:
                hits.append({'title': 'busy' if e.get('busy_only') else (e.get('title') or '(all day)'), 'start_epoch': low, 'end_epoch': high, 'tentative': False,
                             'buffer_only': False, 'all_day': True, 'account': e.get('connection_id'), 'calendar': e.get('calendar_id'), 'event': None if e.get('busy_only') else e.get('id')})
        out.append({'start_epoch': start, 'end_epoch': end, 'conflicts': sorted(hits, key=lambda h: h['start_epoch'])})
    return out
