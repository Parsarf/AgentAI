"""Calendar feeds by address (roadmap Phase 6, #D9): read only, fetched through the destination guard, the address kept in custody and never shown again, repeating
events expanded with their exceptions, and the copy replaced by each read (a feed has no change cursor)."""
import json
import unittest

from agentai_platform import ics_feed, ssrf
from agentai_platform.connectors import ConnectorService
from agentai_platform.connector_kit import ConnectorClient
from agentai_platform.hub import HubService
from agentai_platform.hub_sync import HubSync
from tests.hub_fixture import HubBase

FEED = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
X-WR-CALNAME:Riverside School\r
X-WR-TIMEZONE:America/New_York\r
BEGIN:VEVENT\r
UID:assembly@school\r
SUMMARY:Assembly\\, all years\r
LOCATION:Main hall\r
DTSTART;TZID=America/New_York:20330516T090000\r
DTEND;TZID=America/New_York:20330516T100000\r
RRULE:FREQ=WEEKLY;COUNT=4\r
EXDATE;TZID=America/New_York:20330523T090000\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:assembly@school\r
RECURRENCE-ID;TZID=America/New_York:20330530T090000\r
SUMMARY:Assembly (moved)\r
DTSTART;TZID=America/New_York:20330530T110000\r
DTEND;TZID=America/New_York:20330530T120000\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:holiday@school\r
SUMMARY:Holiday\r
DTSTART;VALUE=DATE:20330519\r
DTEND;VALUE=DATE:20330520\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:gone@school\r
SUMMARY:Cancelled trip\r
STATUS:CANCELLED\r
DTSTART:20330518T140000Z\r
DTEND:20330518T150000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:long@school\r
SUMMARY:Notes line one\r
DESCRIPTION:Bring a\r
  packed lunch\\nand water\r
DTSTART:20330520T130000Z\r
DURATION:PT90M\r
END:VEVENT\r
END:VCALENDAR\r
"""
START, END = 1999900000, 2010000000            # 2033-05-17 .. 2033-09-10


class Parsing(unittest.TestCase):
    def test_repeats_exceptions_moved_occurrences_cancelled_events_whole_days_and_folded_text(self):
        items = ics_feed.instances(ics_feed.parse(FEED), 1999500000, END)
        titles = [(i['title'], i['start_date'] or i['start_epoch']) for i in items]
        self.assertEqual([t for t, _ in titles], ['Assembly, all years', 'Holiday', 'Notes line one', 'Assembly (moved)', 'Assembly, all years'])
        assembly = [i for i in items if i['title'].startswith('Assembly')]
        self.assertEqual([i['start_epoch'] for i in assembly], [1999861200, 2001078000, 2001675600])          # 16th 09:00 (the 23rd is excepted), 30th moved to 11:00, 6 June 09:00
        self.assertEqual(len({i['series_id'] for i in assembly}), 1)
        holiday = next(i for i in items if i['title'] == 'Holiday')
        self.assertEqual((holiday['all_day'], holiday['start_date'], holiday['end_date']), (True, '2033-05-19', '2033-05-20'))
        notes = next(i for i in items if i['title'] == 'Notes line one')
        self.assertEqual((notes['description'], notes['end_epoch'] - notes['start_epoch']), ('Bring a packed lunch\nand water', 5400))
        self.assertNotIn('Cancelled trip', [i['title'] for i in items])

    def test_what_is_not_a_calendar_or_not_on_the_public_internet_is_refused(self):
        with self.assertRaises(ics_feed.FeedError):
            ics_feed.parse(b'<html>not a feed</html>')
        public, private = (lambda host: ['93.184.216.34']), (lambda host: ['10.0.0.7'])
        with self.assertRaises(ics_feed.FeedError):
            ics_feed.fetch('http://cal.school.test/a.ics', resolver=public)                    # https only
        with self.assertRaises(ics_feed.FeedError):
            ics_feed.fetch('https://cal.school.test/a.ics', resolver=private, opener=lambda u: (200, None, FEED))
        with self.assertRaises(ics_feed.FeedError):                                               # a redirect is checked again: to a private address, refused
            ics_feed.fetch('https://cal.school.test/a.ics', resolver=lambda host: ['10.0.0.7'] if host == 'inside.test' else ['93.184.216.34'],
                           opener=lambda u: (302, 'https://inside.test/x.ics', b''))
        self.assertEqual(ics_feed.fetch('https://cal.school.test/a.ics', resolver=public, opener=lambda u: (200, None, FEED)), FEED)


class Feeds(HubBase):
    def setUp(self):
        super().setUp()
        self.served = {'body': FEED}
        ics_feed.register(self.registry, fetcher=lambda url: self.served['body'])
        clock = lambda: self.now
        self.connectors = ConnectorService(self.store, custody=self.custody, registry=self.registry, clock=clock)
        self.client = ConnectorClient(self.store, self.connectors, self.registry, clock=clock, sleep=lambda s: None)
        self.sync = HubSync(self.store, self.connectors, self.client, clock=clock, page=50, pages_per_run=20, interval=300)
        self.hub = HubService(self.store, self.connectors, self.client, self.sync, clock=clock)

    def add(self, **over):
        connection = self.connectors.add_feed(self.a, 'webcal://cal.school.test/private/s3cr3t-token/basic.ics', **over, fetch=lambda url: self.served['body'])
        self.sync.ensure('a', connection)
        for _ in range(3):
            self.sync.tick(limit=10)
        return connection

    def test_a_feed_is_read_only_named_without_its_address_and_replaced_by_each_read(self):
        connection = self.add()
        account = next(x for x in self.hub.accounts(self.a) if x['id'] == connection)
        self.assertEqual(account['identity'], 'Riverside School')                                  # the feed's own name, never its address
        self.assertNotIn('s3cr3t', json.dumps(self.hub.accounts(self.a)))
        self.assertFalse(any(account['capabilities'].get(k) for k in ('event_write', 'respond', 'event_change', 'send', 'organize')))
        cal = next(c for c in self.hub.calendars(self.a) if c['connection_id'] == connection) if hasattr(self.hub, 'calendars') else None
        stored = self.custody.get('a', self.rows('SELECT secret_ref FROM connector_connections WHERE id=?', (connection,))[0]['secret_ref'])
        self.assertEqual(json.loads(stored)['url'], 'https://cal.school.test/private/s3cr3t-token/basic.ics')      # in custody only, webcal:// read as https://
        titles = sorted({r['title'] for r in self.rows('SELECT title FROM hub_events WHERE account_id=? AND connection_id=?', ('a', connection))})
        self.assertEqual(titles, ['Assembly (moved)', 'Assembly, all years', 'Holiday', 'Notes line one'])
        self.served['body'] = FEED.replace(b'SUMMARY:Holiday', b'SUMMARY:Holiday').replace(b'BEGIN:VEVENT\r\nUID:holiday@school', b'BEGIN:VEVENT\r\nUID:holiday@school\r\nSTATUS:CANCELLED')
        self.now += 4000
        self.sync.request('a', connection)
        for _ in range(3):
            self.sync.tick(limit=10)
        titles = sorted({r['title'] for r in self.rows('SELECT title FROM hub_events WHERE account_id=? AND connection_id=?', ('a', connection))})
        self.assertNotIn('Holiday', titles)                                                         # gone from the feed: gone from the copy
        self.assertEqual(self.rows('SELECT count(*) AS n FROM hub_events WHERE account_id=? AND connection_id=?', ('b', connection))[0]['n'], 0)

    def test_the_customers_own_name_is_used_and_a_page_that_is_not_a_feed_adds_nothing(self):
        named = self.add(name='Kids school')
        self.assertEqual(next(x for x in self.hub.accounts(self.a) if x['id'] == named)['identity'], 'Kids school')
        self.served['body'] = b'<html>login</html>'
        before = len(self.rows('SELECT 1 FROM connector_connections'))
        with self.assertRaises(ics_feed.FeedError):
            self.connectors.add_feed(self.a, 'https://cal.school.test/x.ics', fetch=lambda url: self.served['body'])
        self.assertEqual(len(self.rows('SELECT 1 FROM connector_connections')), before)
