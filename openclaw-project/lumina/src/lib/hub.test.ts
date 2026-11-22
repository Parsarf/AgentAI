import { describe, expect, it } from 'vitest';
import { addDays, addMonths, ago, dayKey, dayTitle, eventDays, eventTime, layoutDay, listTime, mergeNewest, minuteOfDay, people, rangeTitle, startOfWeek, zonedEpoch, type HubEvent, type Thread } from './hub';

const event = (over: Partial<HubEvent>): HubEvent => ({ connection_id: 'c', calendar_id: 'k', id: 'e', series_id: null, title: 'T', busy_only: false, start_epoch: 0, end_epoch: 0, all_day: false,
  start_date: null, end_date: null, timezone: null, place: '', conference_url: null, my_response: null, exception: false, cancelled: false, visibility: 'default', colour: 'blue', ...over });
const at = (iso: string) => Date.parse(iso) / 1000;

describe('time in a timezone', () => {
  it('finds the day and the minute an instant falls on, wherever the customer is', () => {
    const t = at('2026-03-08T04:30:00Z');
    expect([dayKey(t, 'UTC'), dayKey(t, 'America/Los_Angeles'), dayKey(t, 'Asia/Tokyo')]).toEqual(['2026-03-08', '2026-03-07', '2026-03-08']);
    expect([minuteOfDay(t, 'UTC'), minuteOfDay(t, 'America/Los_Angeles')]).toEqual([270, 20 * 60 + 30]);
  });
  it('turns a wall-clock time into an instant across a clock change', () => {
    expect(zonedEpoch('2026-03-08', 0, 'America/New_York')).toBe(at('2026-03-08T05:00:00Z'));
    expect(zonedEpoch('2026-03-09', 0, 'America/New_York')).toBe(at('2026-03-09T04:00:00Z'));          // that day had 23 hours
    expect(zonedEpoch('2026-11-01', 9 * 60, 'America/New_York')).toBe(at('2026-11-01T14:00:00Z'));
    expect(zonedEpoch('2026-06-01', 90, 'Asia/Kolkata')).toBe(at('2026-05-31T20:00:00Z'));
  });
  it('does date arithmetic on days, not on seconds', () => {
    expect([addDays('2026-02-27', 3), addDays('2026-01-01', -1), addMonths('2026-01-31', 1), addMonths('2026-12-05', 1)]).toEqual(['2026-03-02', '2025-12-31', '2026-02-01', '2027-01-01']);
    expect([startOfWeek('2026-11-18'), startOfWeek('2026-11-16'), startOfWeek('2026-11-18', 0)]).toEqual(['2026-11-16', '2026-11-16', '2026-11-15']);
  });
  it('words a day and a run of days', () => {
    expect([dayTitle('2026-05-20'), dayTitle('2026-05-20', 'short'), dayTitle('2026-05-20', 'weekday'), dayTitle('2026-05-20', 'month')]).toEqual(['Wednesday, May 20, 2026', 'Wed 20', 'Wed', 'May 2026']);
    expect([rangeTitle('2026-05-18', '2026-05-24'), rangeTitle('2026-04-27', '2026-05-03'), rangeTitle('2025-12-29', '2026-01-04')])
      .toEqual(['May 18 to 24, 2026', 'April 27 to May 3, 2026', 'December 29, 2025 to January 4, 2026']);
  });
  it('words a list time and a sync age plainly', () => {
    const now = at('2026-11-18T15:00:00Z');
    expect(listTime(at('2026-11-18T09:05:00Z'), 'UTC', now)).toBe('9:05 AM');
    expect(listTime(at('2026-11-16T09:05:00Z'), 'UTC', now)).toBe('Mon');
    expect(listTime(at('2026-10-02T09:05:00Z'), 'UTC', now)).toBe('Oct 2');
    expect(listTime(at('2025-10-02T09:05:00Z'), 'UTC', now)).toBe('Oct 2, 2025');
    expect([ago(null, now), ago(now - 30, now), ago(now - 600, now), ago(now - 7200, now), ago(now - 86400 * 5, now)]).toEqual(['not yet', 'just now', '10 min ago', '2 h ago', '5 days ago']);
  });
});

describe('events', () => {
  it('draws an all-day event on its own dates, whatever the timezone, and a timed one where the customer is', () => {
    const offsite = event({ all_day: true, start_date: '2026-05-20', end_date: '2026-05-22', start_epoch: at('2026-05-20T00:00:00Z'), end_epoch: at('2026-05-22T00:00:00Z') });
    expect(eventDays(offsite, 'America/Los_Angeles', '2026-05-18', '2026-05-24')).toEqual(['2026-05-20', '2026-05-21']);
    const late = event({ start_epoch: at('2026-05-20T23:00:00Z'), end_epoch: at('2026-05-21T01:00:00Z') });
    expect(eventDays(late, 'UTC', '2026-05-18', '2026-05-24')).toEqual(['2026-05-20', '2026-05-21']);
    expect(eventDays(late, 'America/Los_Angeles', '2026-05-18', '2026-05-24')).toEqual(['2026-05-20']);
    expect(eventDays(event({ start_epoch: at('2026-05-20T10:00:00Z'), end_epoch: at('2026-05-21T00:00:00Z') }), 'UTC', '2026-05-18', '2026-05-24')).toEqual(['2026-05-20']);      // ends at midnight: not on the next day
  });
  it('lays overlapping events side by side and never hides one', () => {
    const day = '2026-05-20';
    const a = event({ id: 'a', start_epoch: at('2026-05-20T09:00:00Z'), end_epoch: at('2026-05-20T10:00:00Z') });
    const b = event({ id: 'b', start_epoch: at('2026-05-20T09:30:00Z'), end_epoch: at('2026-05-20T10:30:00Z') });
    const c = event({ id: 'c', start_epoch: at('2026-05-20T10:00:00Z'), end_epoch: at('2026-05-20T11:00:00Z') });
    const d = event({ id: 'd', start_epoch: at('2026-05-20T13:00:00Z'), end_epoch: at('2026-05-20T13:05:00Z') });
    const placed = Object.fromEntries(layoutDay([d, c, b, a, event({ id: 'x', all_day: true })], day, 'UTC').map(p => [p.event.id, p]));
    expect(Object.keys(placed).sort()).toEqual(['a', 'b', 'c', 'd']);
    expect([placed.a.column, placed.b.column, placed.c.column]).toEqual([0, 1, 0]);                     // c takes a's place once a is over
    expect([placed.a.columns, placed.b.columns, placed.c.columns, placed.d.columns]).toEqual([2, 2, 2, 1]);
    expect([placed.a.top, placed.a.height, placed.d.height]).toEqual([540, 60, 20]);                    // a very short event is still tall enough to read
  });
  it('clips an event that crosses midnight to the day being drawn', () => {
    const night = event({ start_epoch: at('2026-05-20T22:00:00Z'), end_epoch: at('2026-05-21T02:00:00Z') });
    expect(layoutDay([night], '2026-05-20', 'UTC').map(p => [p.top, p.height])).toEqual([[1320, 120]]);
    expect(layoutDay([night], '2026-05-21', 'UTC').map(p => [p.top, p.height])).toEqual([[0, 120]]);
  });
  it('says when an event is, and adds its own timezone only when that differs', () => {
    const e = event({ start_epoch: at('2026-05-20T14:00:00Z'), end_epoch: at('2026-05-20T15:00:00Z'), timezone: 'America/New_York' });
    expect(eventTime(e, 'America/New_York')).toBe('Wednesday, May 20, 2026, 10:00 AM to 11:00 AM');
    expect(eventTime(e, 'Europe/Berlin')).toBe('Wednesday, May 20, 2026, 4:00 PM to 5:00 PM (10:00 AM in America/New York)');
    expect(eventTime(event({ all_day: true, start_date: '2026-05-20', end_date: '2026-05-21' }), 'Asia/Tokyo')).toBe('Wednesday, May 20, 2026, all day');
    expect(eventTime(event({ all_day: true, start_date: '2026-05-20', end_date: '2026-05-23' }), 'UTC')).toBe('Wednesday, May 20, 2026 to Friday, May 22, 2026');
  });
});

describe('people', () => {
  it('names who a thread is with, leaving out the account itself', () => {
    const list = [{ name: 'Ann', address: 'ann@x.test' }, { name: 'Me', address: 'me@a.test' }, { name: '', address: 'cy@z.test' }, { name: 'Dee', address: 'dee@z.test' }];
    expect(people(list, 'Me@a.test')).toBe('Ann, cy@z.test +1');
    expect(people(list.slice(0, 2), 'me@a.test')).toBe('Ann');
    expect(people([list[1]], 'me@a.test')).toBe('Me');
  });
});

describe('keeping a list current while the reader is further down it', () => {
  const t = (id: string, last_epoch: number, over: Partial<Thread> = {}): Thread => ({ connection_id: 'c', id, subject: id, snippet: '', people: [], last_epoch, message_count: 1, unread: false, starred: false,
    has_attachments: false, labels: ['inbox'], provider_labels: [], ...over });
  const ids = (list: Thread[]) => list.map(x => x.id);
  it('puts new mail on top, shows what changed as it is now, and keeps what was loaded below', () => {
    const loaded = [t('a', 90), t('b', 80), t('c', 70), t('d', 60), t('e', 50)];                  // two pages on screen: a b c | d e
    const merged = mergeNewest(loaded, [t('new', 100), t('a', 90, { unread: true }), t('b', 80)], false);
    expect(ids(merged)).toEqual(['new', 'a', 'b', 'c', 'd', 'e']);
    expect(merged[1].unread).toBe(true);
  });
  it('moves a conversation that got an answer to the top once, and drops one that left the mailbox', () => {
    const loaded = [t('a', 90), t('b', 80), t('c', 70), t('d', 60)];
    expect(ids(mergeNewest(loaded, [t('d', 95), t('a', 90), t('c', 70)], false))).toEqual(['d', 'a', 'c']);       // d answered; b archived elsewhere (it would be between a and c)
  });
  it('keeps a conversation as old as the newest page\'s last one (it may simply be next), and takes a whole mailbox as it is', () => {
    expect(ids(mergeNewest([t('a', 90), t('b', 80), t('x', 80), t('c', 70)], [t('a', 90), t('b', 80)], false))).toEqual(['a', 'b', 'x', 'c']);
    expect(ids(mergeNewest([t('a', 90), t('b', 80), t('c', 70)], [t('a', 90)], true))).toEqual(['a']);
    expect(mergeNewest([t('a', 90)], [], false)).toEqual([]);
  });
});
