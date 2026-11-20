import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CalendarPage from './CalendarPage';
import type { HubAccount, HubCalendar, HubCaps, HubEvent, Overview } from '../lib/hub';

let features: Record<string, boolean> = { dashboard: true };
vi.mock('../state/data', () => ({ useData: () => ({ app: { features } }) }));
// A fixed "now": Wednesday 20 May 2026, 10:00 in New York (14:00 UTC).
const NOW = Date.parse('2026-05-20T14:00:00Z');
beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'], now: NOW }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); features = { dashboard: true }; });

const at = (iso: string) => Date.parse(iso) / 1000;
const caps = (over: Partial<HubCaps> = {}): HubCaps => ({ mail: true, calendar: true, mail_search: true, incremental: true, push: false, labels: 'labels', subjects: true, send: false, organize: false,
  mark_read: false, event_write: false, respond: false, ...over });
const part = { synced_epoch: NOW / 1000 - 300, filled: true, items: 3, error: null, paused: false };
const account = (over: Partial<HubAccount> = {}): HubAccount => ({ id: 'c1', provider: 'first', provider_label: 'First Calendar', identity: 'me@first.test', state: 'working', needs_reason: null,
  capabilities: caps(), granted: { mail: true, calendar: true }, mail: null, calendar: part, ...over });
const second = account({ id: 'c2', provider: 'second', provider_label: 'Zweiter Kalender', identity: 'ich@second.test', capabilities: caps({ incremental: false }) });
const calendar = (over: Partial<HubCalendar> = {}): HubCalendar => ({ connection_id: 'c1', id: 'work', name: 'Work', colour: 'blue', timezone: 'America/New_York', access: 'owner', primary: true, selected: true,
  synced_epoch: NOW / 1000 - 300, filled: true, error: null, paused: false, ...over });
const event = (over: Partial<HubEvent> = {}): HubEvent => ({ connection_id: 'c1', calendar_id: 'work', id: 'e1', series_id: null, title: 'Standup', busy_only: false, start_epoch: at('2026-05-20T13:00:00Z'),
  end_epoch: at('2026-05-20T13:30:00Z'), all_day: false, start_date: null, end_date: null, timezone: 'America/New_York', place: 'Room 4', conference_url: null, my_response: 'accepted', exception: false,
  cancelled: false, visibility: 'default', colour: 'blue', ...over });
const EVENTS = [event(),
  event({ connection_id: 'c2', calendar_id: 'main', id: 'k:1/a', title: 'Zahnarzt', colour: 'green', start_epoch: at('2026-05-20T13:15:00Z'), end_epoch: at('2026-05-20T14:15:00Z'), timezone: 'Europe/Berlin', place: '', my_response: null }),
  event({ id: 'e3', title: 'Offsite', all_day: true, start_date: '2026-05-21', end_date: '2026-05-23', start_epoch: at('2026-05-21T00:00:00Z'), end_epoch: at('2026-05-23T00:00:00Z'), place: '' }),
  event({ id: 'b1', title: '', busy_only: true, visibility: 'busy', start_epoch: at('2026-05-22T18:00:00Z'), end_epoch: at('2026-05-22T19:00:00Z'), place: '', my_response: null })];
const overview = (over: Partial<Overview> = {}): Overview => ({ accounts: [account(), second], settings: { timezone: 'America/New_York', image_senders: [] }, counts: { unread: 0, by_account: {} },
  calendars: [calendar(), calendar({ connection_id: 'c2', id: 'main', name: 'Kalender', colour: 'green', timezone: null })], labels: [], colours: ['blue', 'green', 'amber', 'red', 'violet', 'teal', 'pink', 'grey'], read_only: true, ...over });

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const calls: { method: string; url: URL; body?: any }[] = [];
type Routes = Record<string, unknown | ((url: URL, body?: any) => unknown)>;
function server(routes: Routes) {
  calls.length = 0;
  vi.stubGlobal('fetch', vi.fn((raw: string, init?: RequestInit) => {
    if (raw === '/v1/csrf') return reply({ csrf_token: 't' });
    const url = new URL(raw, 'https://app.test'); const method = init?.method ?? 'GET'; const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    const found = routes[`${method} ${url.pathname}`] ?? routes[url.pathname];
    return found === undefined ? reply({ error: 'not_found' }, 404) : reply(typeof found === 'function' ? (found as (u: URL, b?: any) => unknown)(url, body) : found);
  }));
}
const base = (over: Routes = {}): Routes => ({ '/v1/hub': overview(), '/v1/hub/events': { events: EVENTS, complete: true },
  '/v1/hub/event': (url: URL) => ({ event: { ...EVENTS.find(e => e.id === url.searchParams.get('id'))!, description: 'Daily sync', organizer: { name: 'Ann', address: 'ann@x.test' },
    attendees: [{ name: 'Me', address: 'me@first.test', response: 'accepted', self: true, optional: false }, { name: 'Ann', address: 'ann@x.test', response: 'tentative', self: false, optional: true }],
    provider_url: 'https://calendar.first.test/e1', synced_epoch: NOW / 1000 - 300 } }), ...over });
const show = () => render(<MemoryRouter><CalendarPage /></MemoryRouter>);
const asked = (path: string) => calls.filter(c => c.url.pathname === path);

describe('Calendar', () => {
  it('shows this week in the customer timezone with the events of two providers together, none hidden', async () => {
    server(base()); show();
    expect(await screen.findByRole('heading', { level: 1, name: 'May 18 to 24, 2026' })).toBeTruthy();
    await screen.findByRole('button', { name: 'Standup, 9:00 AM' });
    const wednesday = screen.getByLabelText('Wednesday, May 20, 2026', { selector: '.hub-day-col' });
    const chips = within(wednesday).getAllByRole('button');
    expect(chips.map(c => c.getAttribute('aria-label'))).toEqual(['Standup, 9:00 AM', 'Zahnarzt, 9:15 AM']);        // 13:00 and 13:15 UTC, shown in New York
    expect(chips[0].style.left).toContain('0%'); expect(chips[1].style.left).toContain('50%');                  // overlapping: side by side
    expect(chips[0].className).toContain('cal-blue'); expect(chips[1].className).toContain('cal-green');
    expect(within(wednesday).getByLabelText('Now')).toBeTruthy();
    for (const day of ['Thursday, May 21, 2026', 'Friday, May 22, 2026'])
      expect(within(screen.getByLabelText(`All day, ${day}`)).getByRole('button', { name: 'Offsite, all day' })).toBeTruthy();
    expect(within(screen.getByLabelText('All day, Saturday, May 23, 2026')).queryByRole('button')).toBeNull();          // the end date of an all-day event is exclusive
    expect(within(screen.getByLabelText('Friday, May 22, 2026', { selector: '.hub-day-col' })).getByRole('button', { name: 'Busy, 2:00 PM' })).toBeTruthy();
    const range = asked('/v1/hub/events')[0].url.searchParams;
    expect([Number(range.get('start')), Number(range.get('end')), range.get('accounts')]).toEqual([at('2026-05-17T04:00:00Z'), at('2026-05-26T04:00:00Z'), 'c1,c2']);
    expect(screen.getByText(/Times are shown in America\/New York\. Read only for now\./)).toBeTruthy();
  });

  it('opens an event in the inspector: its time here and in its own timezone, people, notes, the account it is from', async () => {
    server(base()); show();
    fireEvent.click(await screen.findByRole('button', { name: 'Zahnarzt, 9:15 AM' }));
    const panel = within(await screen.findByRole('complementary', { name: 'Event' }));
    expect(await panel.findByText('Daily sync')).toBeTruthy();
    expect(panel.getByText(/Wednesday, May 20, 2026, 9:15 AM to 10:15 AM \(3:15 PM in Europe\/Berlin\)/)).toBeTruthy();
    expect(panel.getByText('Kalender · ich@second.test')).toBeTruthy();
    expect(panel.getByText('Me (you)')).toBeTruthy(); expect(panel.getByText(/Maybe · optional/)).toBeTruthy();
    expect(panel.getByRole('link', { name: 'Open in Zweiter Kalender' }).getAttribute('href')).toBe('https://calendar.first.test/e1');
    const q = asked('/v1/hub/event')[0].url.searchParams;
    expect([q.get('connection'), q.get('calendar'), q.get('id')]).toEqual(['c2', 'main', 'k:1/a']);                // an id with any character travels intact
    fireEvent.click(panel.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('complementary', { name: 'Event' })).toBeNull();
  });

  it('shows nothing but "busy" for an event the calendar only shares as busy', async () => {
    server(base({ '/v1/hub/event': { event: EVENTS[3] } })); show();
    fireEvent.click(await screen.findByRole('button', { name: 'Busy, 2:00 PM' }));
    const panel = within(await screen.findByRole('complementary', { name: 'Event' }));
    expect(panel.getByRole('heading', { name: 'Busy' })).toBeTruthy();
    expect(panel.getByText(/only shares when you are busy/)).toBeTruthy();
    expect(panel.queryByText('Notes')).toBeNull();
  });

  it('switches between day, week, month and agenda and moves through time', async () => {
    server(base()); show();
    await screen.findByRole('button', { name: 'Standup, 9:00 AM' });
    fireEvent.click(screen.getByRole('button', { name: 'Month' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'May 2026' })).toBeTruthy();
    expect(within(screen.getByRole('grid')).getByRole('button', { name: 'Standup, 9:00 AM' })).toBeTruthy();
    await waitFor(() => expect(Number(asked('/v1/hub/events').at(-1)!.url.searchParams.get('start'))).toBe(at('2026-04-26T04:00:00Z')));          // the month grid starts on Monday 27 April
    fireEvent.click(screen.getByRole('button', { name: 'Later' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'June 2026' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Today' })); fireEvent.click(screen.getByRole('button', { name: 'Day' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Wednesday, May 20, 2026' })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Thursday, May 21, 2026' })).toBeTruthy();
    fireEvent.keyDown(window, { key: 't' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Wednesday, May 20, 2026' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Agenda' }));
    const todayList = within(await screen.findByRole('region', { name: 'Wednesday, May 20, 2026' }));
    expect(todayList.getByText('Today · Wednesday, May 20, 2026')).toBeTruthy();
    expect(todayList.getAllByRole('button').map(b => b.textContent)).toEqual(['9:00 AM to 9:30 AMStandup · Room 4 · me@first.test', '9:15 AM to 10:15 AMZahnarzt · ich@second.test']);
  });

  it('lets the customer hide a calendar, colour it and hide a whole account', async () => {
    const calendars = overview().calendars;
    server(base({ 'POST /v1/hub/calendars': (_u: URL, body: any) => ({ calendars: calendars.map(c => (c.id === body.calendar_id ? { ...c, ...('selected' in body ? { selected: body.selected } : {}), ...(body.colour ? { colour: body.colour } : {}) } : c)) }) }));
    show();
    await screen.findByRole('button', { name: 'Standup, 9:00 AM' });
    fireEvent.click(within(screen.getByRole('region', { name: 'Calendars of ich@second.test' })).getByRole('checkbox'));
    await waitFor(() => expect(asked('/v1/hub/calendars')[0].body).toEqual({ connection_id: 'c2', calendar_id: 'main', selected: false }));
    fireEvent.click(screen.getByRole('button', { name: 'Colour of Work' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Choose a colour for Work' })).getByRole('button', { name: 'pink' }));
    await waitFor(() => expect(asked('/v1/hub/calendars')[1].body).toEqual({ connection_id: 'c1', calendar_id: 'work', colour: 'pink' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /ich@second.test/ }));
    await waitFor(() => expect(asked('/v1/hub/events').at(-1)!.url.searchParams.get('accounts')).toBe('c1'));
    expect(screen.queryByRole('region', { name: 'Calendars of ich@second.test' })).toBeNull();
  });

  it('changes the timezone everything is shown in, and refuses one that does not exist', async () => {
    server(base({ 'POST /v1/hub/settings': (_u: URL, body: any) => ({ settings: { timezone: body.timezone, image_senders: [] } }) })); show();
    await screen.findByRole('button', { name: 'Standup, 9:00 AM' });
    fireEvent.click(screen.getByRole('button', { name: 'Change timezone' }));
    fireEvent.change(screen.getByLabelText('Timezone'), { target: { value: 'Mars/Olympus' } }); fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText(/That timezone is not known/)).toBeTruthy();
    expect(asked('/v1/hub/settings').length).toBe(0);
    fireEvent.change(screen.getByLabelText('Timezone'), { target: { value: 'Europe/Berlin' } }); fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('button', { name: 'Standup, 3:00 PM' })).toBeTruthy();
    expect(asked('/v1/hub/settings')[0].body).toEqual({ timezone: 'Europe/Berlin' });
  });

  it('searches events and lists what matched', async () => {
    server(base({ '/v1/hub/events/search': { events: [EVENTS[1]], complete: true } })); show();
    await screen.findByRole('button', { name: 'Standup, 9:00 AM' });
    fireEvent.change(screen.getByLabelText('Search events'), { target: { value: 'zahn' } }); fireEvent.submit(screen.getByRole('search'));
    expect(await screen.findByRole('heading', { level: 1, name: 'Events matching “zahn”' })).toBeTruthy();
    expect(screen.getByText('Zahnarzt')).toBeTruthy(); expect(screen.queryByRole('button', { name: 'Standup, 9:00 AM' })).toBeNull();
    expect(asked('/v1/hub/events/search')[0].url.searchParams.get('q')).toBe('zahn');
    fireEvent.click(screen.getByRole('button', { name: 'Week' }));
    expect(await screen.findByRole('button', { name: 'Standup, 9:00 AM' })).toBeTruthy();
  });

  it('says so when nothing is connected, when a calendar is loading and when an account needs its customer', async () => {
    server(base({ '/v1/hub': overview({ accounts: [], calendars: [] }) })); show();
    expect(await screen.findByText('No calendar is connected')).toBeTruthy();
    cleanup();
    server(base({ '/v1/hub': overview({ accounts: [account({ state: 'needs_you', needs_reason: 'reconnect' }), second], calendars: [calendar({ filled: false }), overview().calendars[1]] }) })); show();
    expect(await screen.findByText(/me@first.test needs you. What was loaded before is still shown/)).toBeTruthy();
    expect(screen.getByText('Loading Work for the first time.')).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Zahnarzt, 9:15 AM' })).toBeTruthy();
  });

  it('is a plain "not available" page while the feature is off, and asks the server nothing', () => {
    features = {}; server(base()); show();
    expect(screen.getByText('Not available yet')).toBeTruthy();
    expect(calls.length).toBe(0);
  });

  it('lets the customer cancel an event they organize, says who is told, and undoes it (Phase 6)', async () => {
    const writable = account({ capabilities: caps({ event_write: true }) });
    const done = (id: string, kind: string) => ({ action: { id, kind, state: 'done', preview: { title: '', summary: '', destination: '', changes: [], can_undo: true }, verified: true, can_undo: true,
      undo_until_epoch: null, direct: 'calendar', ended_words: '' } });
    server(base({ '/v1/hub': overview({ accounts: [writable, second], read_only: false }), 'POST /v1/hub/refresh': { requested: 1 },
      '/v1/hub/event': () => ({ event: { ...EVENTS[0], organizer: { name: 'Me', address: 'me@first.test' }, attendees: [{ name: 'Me', address: 'me@first.test', response: 'accepted', self: true, optional: false },
        { name: 'Ann', address: 'ann@x.test', response: 'tentative', self: false, optional: false }], synced_epoch: NOW / 1000 - 300 } }),
      'POST /v1/hub/events/cancel': done('a1', 'event.delete'), 'POST /v1/hub/actions/a1/undo': done('a2', 'event.recreate') }));
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Standup, 9:00 AM' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel event' }));
    expect(screen.getByRole('alertdialog', { name: 'Cancel this event?' }).textContent).toContain('1 person is told it is cancelled.');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel it' }));
    await screen.findByText('"Standup" was cancelled.');
    expect(asked('/v1/hub/events/cancel').map(c => c.body)).toEqual([{ connection: 'c1', calendar: 'work', event: 'e1', notify: true }]);
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText('Undone.');
    expect(asked('/v1/hub/actions/a1/undo').map(c => c.body)).toEqual([{ screen: 'calendar' }]);
  });

  it('shows no control that changes anything while changes are off, and asks for the permission where it is missing', async () => {
    server(base()); show();
    fireEvent.click(await screen.findByRole('button', { name: 'Standup, 9:00 AM' }));
    await screen.findByText('Daily sync');
    expect(screen.queryByRole('button', { name: 'Cancel event' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'New event' })).toBeNull();
    cleanup();
    const asking = account({ capabilities: caps({ missing: { event_write: 'calendar_write' } }), grants: [{ name: 'calendar_write', capabilities: ['event_write'], words: 'Create and change events when you approve.' }] });
    server(base({ '/v1/hub': overview({ accounts: [asking, second], read_only: false }) })); show();
    fireEvent.click(await screen.findByRole('button', { name: 'New event' }));
    expect(await screen.findByRole('button', { name: 'Allow changes for me@first.test' })).toBeTruthy();
    expect(screen.queryByRole('form', { name: 'New event' })).toBeNull();
  });
});
