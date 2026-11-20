"""Calendar feeds by address (roadmap Phase 6, #D9): an ICS address the customer pastes (a school, a team, a booking system). Read only: its events show on the Calendar
with no controls, and nothing is ever sent to it except the request for the feed.

The address can carry a secret (many feeds are private links), so it is kept in custody like a token and never shown again in full: the connection is named by the
customer, or by the feed's own name, or by its host. It is fetched through the destination guard (https only, port 443, public addresses only, at most 5 redirects, each
checked again), at most 5 MB, on the sync timer. A feed has no "what changed" cursor: each read is the whole feed, and the copy is replaced by it (Changes.complete).

Repeating events are expanded here (python-dateutil's RRULE), with EXDATE and RECURRENCE-ID honoured, into the occurrences of the window the sync asks for.
"""
from __future__ import annotations
import hashlib
import json
import re
import socket
import ssl
import urllib.request
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .connector_kit import Caps, Declaration, ProviderError
from .hub_model import Changes, HubCaps, calendar, event
from . import ssrf

PROVIDER = 'ics'
MAX_BYTES = 5_000_000
MAX_INSTANCES = 5000
CALENDAR_ID = 'feed'
DECLARATION = Declaration(
    provider=PROVIDER, label='Calendar feed', auth='none', scopes=(), resource_kinds=('calendar',), record_kinds=(), read_operations=(), write_kinds=(),
    change_tokens=False, implementation='first_party', reason='An ICS feed is a plain address; there is no API to wrap.', hosts=(),
    freshness_seconds={'calendar': 3600}, caps=Caps(pages=1, items=MAX_INSTANCES, bytes=MAX_BYTES, seconds=25.0),
    disclosure='Reads the events of a calendar feed you added by its address. Nothing is ever sent to it.',
    hub=HubCaps(mail=False, calendar=True, mail_search=False, incremental=False, push=False, labels='none', subjects=True), several_accounts=True)


# A feed keeps its address (in custody) and a copy of its events: offered only once the privacy policy says so (the owner's approval), and in a live proof
# (hub_model.PROVING_IN_THIS_PROCESS holds 'feeds').
FEEDS_LIVE = False


def feeds_on() -> bool:
    from .hub_model import PROVING_IN_THIS_PROCESS
    return FEEDS_LIVE or 'feeds' in PROVING_IN_THIS_PROCESS


class FeedError(ValueError):
    """The address is not a calendar feed Lumina can read; the text is a sentence the customer reads."""


def fetch(url, *, resolver=ssrf.system_resolver, opener=None) -> bytes:
    """The feed's bytes, through the destination guard. Raises ProviderError (the sync's faults) or FeedError (when adding it)."""
    try:
        host = (urlsplit(url).hostname or '').lower()
        current = ssrf.check_url(url, [host], resolver=resolver)
    except ssrf.Blocked as blocked:
        raise FeedError('That address cannot be read: it must start with https:// and be on the public internet.') from blocked
    opener = opener or _open
    for _ in range(6):
        status, location, body = opener(current)
        if status in (301, 302, 303, 307, 308) and location:
            from urllib.parse import urljoin
            nxt = urljoin(current, location)
            try:
                current = ssrf.check_url(nxt, [(urlsplit(nxt).hostname or '').lower()], resolver=resolver)
            except ssrf.Blocked as blocked:
                raise FeedError('The feed sent Lumina somewhere it may not go.') from blocked
            continue
        if status in (401, 403):
            raise ProviderError(403, 'forbidden')
        if status in (404, 410):
            raise ProviderError(404, 'notFound')
        if status == 429 or status >= 500:
            raise ProviderError(503, 'unavailable')
        if status != 200:
            raise ProviderError(400, 'invalid')
        return body
    raise FeedError('The feed redirects too many times.')


def _open(url):
    request = urllib.request.Request(url, headers={'Accept': 'text/calendar, */*;q=0.5', 'User-Agent': 'Lumina-Calendar-Feed/1'})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    handler = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with handler.open(request, timeout=20) as answer:
            body = answer.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise FeedError('The feed is larger than 5 MB.')
            return answer.status, None, body
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get('Location'), b''
    except (urllib.error.URLError, socket.timeout, OSError):
        raise ProviderError(0, 'unreachable') from None


# -- parsing ----------------------------------------------------------------------------------------------------------------------------------------------
def _lines(text):
    out = []
    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if raw[:1] in (' ', '\t') and out:
            out[-1] += raw[1:]
        elif raw:
            out.append(raw)
    return out


def _prop(line):
    head, _, value = line.partition(':')
    name, *params = head.split(';')
    return name.upper(), {k.upper(): v.strip('"') for k, _, v in (p.partition('=') for p in params)}, value


def _text(value) -> str:
    return re.sub(r'\\([nN,;\\])', lambda m: '\n' if m.group(1) in 'nN' else m.group(1), value)


def parse(raw: bytes) -> dict:
    """{'name', 'timezone', 'events': [{'uid', 'summary', ..., 'start', 'end', 'rrule', 'exdates', 'recurrence_id', 'status'}]}. Raises FeedError when it is not a calendar."""
    text = raw.decode('utf-8', errors='replace')
    if 'BEGIN:VCALENDAR' not in text[:2000].upper():
        raise FeedError('That address does not give a calendar (an .ics feed).')
    feed, events, current = {'name': '', 'timezone': None}, [], None
    for line in _lines(text):
        name, params, value = _prop(line)
        if name == 'BEGIN' and value.upper() == 'VEVENT':
            current = {'exdates': [], 'params': {}}
        elif name == 'END' and value.upper() == 'VEVENT':
            if current and current.get('DTSTART'):
                events.append(current)
            current = None
        elif current is not None:
            if name == 'EXDATE':
                current['exdates'] += [(v, params) for v in value.split(',') if v]
            elif name in ('UID', 'SUMMARY', 'LOCATION', 'DESCRIPTION', 'DTSTART', 'DTEND', 'DURATION', 'RRULE', 'RECURRENCE-ID', 'STATUS', 'URL', 'TRANSP'):
                current[name] = value
                current['params'][name] = params
        elif name == 'X-WR-CALNAME':
            feed['name'] = _text(value)[:200]
        elif name == 'X-WR-TIMEZONE':
            feed['timezone'] = value.strip()[:64]
    feed['events'] = events
    return feed


def _zone(name, fallback):
    for candidate in (name, fallback, 'UTC'):
        if candidate:
            try:
                return ZoneInfo(candidate)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return timezone.utc


def _when(value, params, fallback_zone):
    """A DATE-TIME (aware) or a DATE."""
    value = value.strip()
    if params.get('VALUE', '').upper() == 'DATE' or re.fullmatch(r'\d{8}', value):
        return datetime.strptime(value[:8], '%Y%m%d').date()
    if value.endswith('Z'):
        return datetime.strptime(value[:15], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
    return datetime.strptime(value[:15], '%Y%m%dT%H%M%S').replace(tzinfo=_zone(params.get('TZID'), fallback_zone))


def _duration(value) -> timedelta:
    found = re.fullmatch(r'([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', value.strip())
    if not found:
        return timedelta(0)
    sign = -1 if found.group(1) == '-' else 1
    w, d, h, m, s = (int(x or 0) for x in found.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=m, seconds=s)


def _epoch(moment) -> int:
    return int(moment.timestamp()) if isinstance(moment, datetime) else int(datetime.combine(moment, datetime.min.time(), timezone.utc).timestamp())


def instances(feed, window_start, window_end) -> list:
    """The feed's events as the neutral occurrences in [window_start, window_end] (epochs). Repeats are expanded; a changed occurrence (RECURRENCE-ID) replaces the one it
    changes; a cancelled one is left out."""
    from dateutil.rrule import rrulestr
    fallback = feed.get('timezone')
    by_uid, overrides = {}, {}
    for e in feed['events']:
        uid = (e.get('UID') or hashlib.sha256((e.get('SUMMARY', '') + e['DTSTART']).encode()).hexdigest()[:16])[:200]
        if e.get('RECURRENCE-ID'):
            try:
                overrides[(uid, _epoch(_when(e['RECURRENCE-ID'], e['params'].get('RECURRENCE-ID', {}), fallback)))] = e
            except ValueError:
                continue
        else:
            by_uid[uid] = e
    out = []
    low, high = datetime.fromtimestamp(window_start, timezone.utc), datetime.fromtimestamp(window_end, timezone.utc)

    def occurrence(uid, e, start, series):
        try:
            p = e['params']
            first = _when(e['DTSTART'], p.get('DTSTART', {}), fallback)
            if e.get('DTEND'):
                length = _when(e['DTEND'], p.get('DTEND', {}), fallback) - first
            elif e.get('DURATION'):
                length = _duration(e['DURATION'])
            else:
                length = timedelta(days=1) if isinstance(first, date) and not isinstance(first, datetime) else timedelta(0)
        except ValueError:
            return None
        if (e.get('STATUS') or '').upper() == 'CANCELLED':
            return None
        if e.get('RECURRENCE-ID'):
            start = first                                                    # a changed occurrence is where it was moved to, not where the series puts it
        end = start + length
        all_day = not isinstance(start, datetime)
        eid = hashlib.sha256(f'{uid}|{_epoch(start)}'.encode()).hexdigest()[:24]
        zone = (p.get('DTSTART', {}) or {}).get('TZID') or fallback
        return event(eid, CALENDAR_ID, title=_text(e.get('SUMMARY', ''))[:500], start_epoch=_epoch(start), end_epoch=_epoch(end), all_day=all_day,
                     start_date=start.isoformat() if all_day else None, end_date=end.isoformat() if all_day else None, timezone=None if all_day else zone,
                     series_id=series, place=_text(e.get('LOCATION', ''))[:500], description=_text(e.get('DESCRIPTION', ''))[:8000],
                     provider_url=e.get('URL') if str(e.get('URL', '')).startswith('https://') else None)

    for uid, e in by_uid.items():
        try:
            first = _when(e['DTSTART'], e['params'].get('DTSTART', {}), fallback)
        except ValueError:
            continue
        if not e.get('RRULE'):
            item = occurrence(uid, overrides.pop((uid, _epoch(first)), e), first, None)
            if item and item['end_epoch'] >= window_start and item['start_epoch'] <= window_end:
                out.append(item)
            continue
        excluded = set()
        for value, params in e['exdates']:
            try:
                excluded.add(_epoch(_when(value, params, fallback)))
            except ValueError:
                continue
        try:
            start_for_rule = first if isinstance(first, datetime) else datetime.combine(first, datetime.min.time())
            rule = rrulestr(e['RRULE'], dtstart=start_for_rule, forceset=False)
            series_low = low - timedelta(days=366) if isinstance(first, datetime) else (low - timedelta(days=366)).replace(tzinfo=None)
            series_high = high if isinstance(first, datetime) else high.replace(tzinfo=None)
            moments = rule.between(series_low, series_high, inc=True)
        except (ValueError, TypeError, OverflowError):
            continue
        for moment in moments[:MAX_INSTANCES]:
            start = moment if isinstance(first, datetime) else moment.date()
            if _epoch(start) in excluded:
                continue
            item = occurrence(uid, overrides.pop((uid, _epoch(start)), e), start, uid)
            if item and item['end_epoch'] >= window_start and item['start_epoch'] <= window_end:
                out.append(item)
    for (uid, at), e in overrides.items():                                         # a changed occurrence whose series is not in the feed
        item = occurrence(uid, e, _when(e['DTSTART'], e['params'].get('DTSTART', {}), fallback), uid)
        if item and item['end_epoch'] >= window_start and item['start_epoch'] <= window_end:
            out.append(item)
    return sorted(out, key=lambda x: (x['start_epoch'], x['id']))[:MAX_INSTANCES]


class FeedAdapter:
    """The dashboard's adapter for one feed: one calendar, read whole on each sync."""
    def __init__(self, fetcher=fetch):
        self.fetcher = fetcher

    def calendars(self, credential):
        return [calendar(CALENDAR_ID, name=(credential or {}).get('name') or 'Calendar feed', access='read', primary=False)]

    def resources(self, credential):
        return self.calendars(credential)

    def event_changes(self, credential, calendar_id, cursor, start_epoch, end_epoch, limit):
        feed = parse(self.fetcher(credential['url']))
        items = instances(feed, int(start_epoch), int(end_epoch))
        digest = hashlib.sha256(json.dumps([(i['id'], i['title'], i['start_epoch'], i['end_epoch'], i['place']) for i in items]).encode()).hexdigest()[:32]
        return Changes(items=items, removed=[], cursor=digest, more=False, complete=True)


def register(registry, fetcher=fetch):
    registry.register(DECLARATION, lambda: FeedAdapter(fetcher))
    return registry
