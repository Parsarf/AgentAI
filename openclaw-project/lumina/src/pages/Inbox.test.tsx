import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Inbox from './Inbox';
import { frameDocument } from '../components/hub/MessageBody';
import type { HubAccount, HubCaps, Message, Overview, Thread } from '../lib/hub';

let features: Record<string, boolean> = { dashboard: true };
vi.mock('../state/data', () => ({ useData: () => ({ app: { features } }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); features = { dashboard: true }; });

const NOW = Math.floor(Date.now() / 1000);
const caps = (over: Partial<HubCaps> = {}): HubCaps => ({ mail: true, calendar: true, mail_search: true, incremental: true, push: false, labels: 'labels', subjects: true, send: false, organize: false,
  mark_read: false, event_write: false, respond: false, ...over });
const account = (over: Partial<HubAccount> = {}): HubAccount => ({ id: 'c1', provider: 'first', provider_label: 'First Mail', identity: 'me@first.test', state: 'working', needs_reason: null,
  capabilities: caps(), granted: { mail: true, calendar: true }, mail: { synced_epoch: NOW - 120, filled: true, items: 3, error: null, paused: false }, calendar: null, ...over });
// The second account is a different provider in everything a provider can differ in: its ids, its folders, and what it can do. Nothing in the page may care.
const second = account({ id: 'c2', provider: 'second', provider_label: 'Zweite Post', identity: 'ich@second.test', capabilities: caps({ labels: 'folders', mail_search: false }) });
const thread = (over: Partial<Thread> = {}): Thread => ({ connection_id: 'c1', id: 't-1', subject: 'Quarterly numbers', snippet: 'Here are the numbers', people: [{ name: 'Ann', address: 'ann@x.test' }, { name: 'Me', address: 'me@first.test' }],
  last_epoch: NOW - 600, message_count: 2, unread: true, starred: false, has_attachments: true, labels: ['inbox', 'unread'], provider_labels: [{ id: 'L1', name: 'Finance' }], ...over });
const other = thread({ connection_id: 'c2', id: 'conv:9@x/1', subject: 'Termin morgen', snippet: 'Passt 10 Uhr?', people: [{ name: 'Bernd', address: 'bernd@y.test' }], unread: false, has_attachments: false,
  message_count: 1, last_epoch: NOW - 7200, provider_labels: [{ id: 'folder/Posteingang', name: 'Posteingang' }] });
const message = (over: Partial<Message> = {}): Message => ({ id: 'm-2', thread_id: 't-1', subject: 'Quarterly numbers', snippet: 'Here are the numbers', sender: { name: 'Ann', address: 'ann@x.test' },
  to: [{ name: 'Me', address: 'me@first.test' }], cc: [], sent_epoch: NOW - 600, labels: ['inbox'], provider_labels: [], unread: true, starred: false, has_attachments: true,
  body: { html: '<p>Here are the numbers</p>', text: 'Here are the numbers', blocked_images: 2, images_shown: false, attachments: [{ id: 'f1', name: 'q3.pdf', type: 'application/pdf', size: 20480 }], fetched_epoch: NOW }, ...over });
const overview = (over: Partial<Overview> = {}): Overview => ({ accounts: [account(), second], providers: [{ provider: 'p1', label: 'First Mail' }], settings: { timezone: 'UTC', image_senders: [] }, counts: { unread: 4, by_account: { c1: 3, c2: 1 } }, calendars: [],
  labels: [], colours: [], read_only: true, ...over });

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const calls: { method: string; url: string; body?: any }[] = [];
type Routes = Record<string, unknown | ((url: URL) => unknown)>;
function server(routes: Routes) {
  calls.length = 0;
  vi.stubGlobal('fetch', vi.fn((raw: string, init?: RequestInit) => {
    if (raw === '/v1/csrf') return reply({ csrf_token: 't' });
    const url = new URL(raw, 'https://app.test'); const method = init?.method ?? 'GET';
    calls.push({ method, url: raw, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const found = routes[`${method} ${url.pathname}`] ?? routes[url.pathname];
    if (found === undefined) return reply({ error: 'not_found' }, 404);
    const body = typeof found === 'function' ? (found as (u: URL) => unknown)(url) : found;
    return body instanceof Response ? Promise.resolve(body) : reply(body);
  }));
}
const base = (over: Routes = {}): Routes => ({ '/v1/hub': overview(), '/v1/hub/mail/labels': { labels: [{ connection_id: 'c1', labels: [{ id: 'L1', name: 'Finance', threads: 1 }] }, { connection_id: 'c2', labels: [{ id: 'folder/Posteingang', name: 'Posteingang', threads: 1 }] }] },
  '/v1/hub/mail/threads': { threads: [thread(), other], next: null, complete: true },
  '/v1/hub/mail/thread': { thread: thread(), messages: [message({ id: 'm-1', body: null, snippet: 'Earlier note', sent_epoch: NOW - 9000 }), message()], problem: null }, ...over });
const show = (at = '/inbox') => render(<MemoryRouter initialEntries={[at]}><Inbox /></MemoryRouter>);
const asked = (path: string) => calls.map(c => new URL(c.url, 'https://app.test')).filter(u => u.pathname === path).map(u => u.searchParams);

describe('Inbox', () => {
  it('shows the mail of two different providers as one list, each row saying which account it is from', async () => {
    server(base()); show();
    const rows = within(await screen.findByRole('list', { name: 'Threads' })).getAllByRole('button');
    expect(rows.map(r => within(r).getByText(/Quarterly|Termin/).textContent)).toEqual(['Quarterly numbers', 'Termin morgen']);
    expect(within(rows[0]).getByText('me@first.test')).toBeTruthy(); expect(within(rows[1]).getByText('ich@second.test')).toBeTruthy();
    expect(within(rows[0]).getByText('Ann')).toBeTruthy();                                       // who it is with, without the account's own address
    expect(within(rows[0]).getByLabelText('Unread')).toBeTruthy(); expect(within(rows[1]).queryByLabelText('Unread')).toBeNull();
    expect(screen.getByText(/Read only for now/)).toBeTruthy();
    expect(screen.getByLabelText('4 unread')).toBeTruthy();
    expect(screen.getByText(/First Mail · Updated 2 min ago/)).toBeTruthy(); expect(screen.getByText(/Zweite Post · Updated/)).toBeTruthy();
    expect(screen.getByText('Labels in me@first.test')).toBeTruthy(); expect(screen.getByText('Folders in ich@second.test')).toBeTruthy();      // from the capability, not the provider's name
  });

  it('asks the server for what the filters say', async () => {
    server(base()); show();
    await screen.findByText('Quarterly numbers');
    expect(asked('/v1/hub/mail/threads')[0].get('label')).toBe('inbox');
    // Every account until the customer narrows them: no accounts named, so the first page does not wait for the accounts overview (UI remodel, measured on production).
    expect(asked('/v1/hub/mail/threads')[0].get('accounts')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Sent' }));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('label')).toBe('sent'));
    fireEvent.click(screen.getByLabelText('Unread only'));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('unread')).toBe('1'));
    fireEvent.click(screen.getByRole('checkbox', { name: /ich@second.test/ }));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('accounts')).toBe('c1'));
    fireEvent.change(screen.getByLabelText('Search mail'), { target: { value: ' budget ' } }); fireEvent.submit(screen.getByRole('search'));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('q')).toBe('budget'));
    expect(screen.queryByText('Folders in ich@second.test')).toBeNull();                          // an account that is not shown offers no folders
    fireEvent.click(screen.getByRole('checkbox', { name: /ich@second.test/ }));
    fireEvent.click(await screen.findByText('Folders in ich@second.test')); fireEvent.click(screen.getByRole('button', { name: /Posteingang/ }));
    await waitFor(() => { const last = asked('/v1/hub/mail/threads').at(-1)!; expect([last.get('provider_label'), last.get('accounts'), last.get('label')]).toEqual(['folder/Posteingang', 'c2', 'all']); });
  });

  it('opens a thread with its last message, in a frame that can run nothing, and sends an id with any character intact', async () => {
    server(base({ '/v1/hub/mail/thread': (url: URL) => ({ thread: url.searchParams.get('id') === 't-1' ? thread() : other, messages: [message({ id: 'm-1', body: null, snippet: 'Earlier note', sent_epoch: NOW - 9000 }), message()], problem: null }) }));
    show();
    fireEvent.click((await screen.findByText('Termin morgen')).closest('button')!);
    await screen.findByRole('heading', { name: 'Termin morgen' });
    expect([asked('/v1/hub/mail/thread')[0].get('connection'), asked('/v1/hub/mail/thread')[0].get('id')]).toEqual(['c2', 'conv:9@x/1']);
    const frames = document.querySelectorAll('iframe');
    expect(frames.length).toBe(1);                                                                // only the last message is open
    expect(frames[0].getAttribute('sandbox')).toBe('allow-same-origin allow-popups allow-popups-to-escape-sandbox');
    expect(frames[0].getAttribute('sandbox')).not.toContain('allow-scripts');
    expect(frames[0].getAttribute('srcdoc')).toContain('<p>Here are the numbers</p>');
    expect(frames[0].getAttribute('srcdoc')).toContain("default-src 'none'");
    expect(screen.getByText('q3.pdf')).toBeTruthy(); expect(screen.getByText('20 KB')).toBeTruthy();
    expect(screen.getByText('Earlier note')).toBeTruthy();                                        // the earlier message shows its header only
  });

  it('keeps remote pictures out until asked, for this message or for the sender', async () => {
    const withPictures = message({ body: { ...message().body!, html: '<p>x</p><img src="https://t.test/p.gif">', blocked_images: 0, images_shown: true } });
    server(base({ '/v1/hub/mail/message': { message: withPictures, problem: null }, 'POST /v1/hub/settings': { settings: { timezone: 'UTC', image_senders: ['ann@x.test'] } } }));
    show();
    fireEvent.click((await screen.findByText('Quarterly numbers')).closest('button')!);
    expect(await screen.findByText(/2 pictures are not shown, so the sender cannot tell that you opened this/)).toBeTruthy();
    expect(document.querySelector('iframe')!.getAttribute('srcdoc')).not.toContain('t.test');
    fireEvent.click(screen.getByRole('button', { name: 'Show pictures' }));
    await waitFor(() => expect(document.querySelector('iframe')!.getAttribute('srcdoc')).toContain('https://t.test/p.gif'));
    expect(asked('/v1/hub/mail/message')[0].get('images')).toBe('1');
    expect(screen.queryByText(/pictures are not shown/)).toBeNull();
    expect(calls.some(c => c.method === 'POST')).toBe(false);                                     // showing once remembers nothing
  });

  it('remembers a sender only when asked to', async () => {
    server(base({ '/v1/hub/mail/message': { message: message({ body: { ...message().body!, blocked_images: 0, images_shown: true } }), problem: null },
      'POST /v1/hub/settings': { settings: { timezone: 'UTC', image_senders: ['ann@x.test'] } } }));
    show();
    fireEvent.click((await screen.findByText('Quarterly numbers')).closest('button')!);
    fireEvent.click(await screen.findByRole('button', { name: 'Always show from ann@x.test' }));
    await waitFor(() => expect(calls.find(c => c.method === 'POST' && c.url === '/v1/hub/settings')?.body).toEqual({ allow_images_from: 'ann@x.test' }));
  });

  it('opens an earlier message when its header is pressed, and says plainly when it cannot be fetched', async () => {
    server(base({ '/v1/hub/mail/message': { message: message({ id: 'm-1', body: null, snippet: 'Earlier note' }), problem: 'retry_later' } }));
    show();
    fireEvent.click((await screen.findByText('Quarterly numbers')).closest('button')!);
    fireEvent.click((await screen.findByText('Earlier note')).closest('button')!);
    expect(await screen.findByText(/The mail service is busy right now/)).toBeTruthy();
    expect(asked('/v1/hub/mail/message')[0].get('id')).toBe('m-1');
  });

  it('keeps showing an account that needs its customer, with what was loaded before', async () => {
    server(base({ '/v1/hub': overview({ accounts: [account({ state: 'needs_you', needs_reason: 'reconnect' }), second] }) })); show();
    expect(await screen.findByText(/me@first.test needs you. What was loaded before is still shown/)).toBeTruthy();
    expect(screen.getByText(/It needs to be connected again/)).toBeTruthy();
    expect(await screen.findByText('Quarterly numbers')).toBeTruthy(); expect(screen.getByText('Termin morgen')).toBeTruthy();
  });

  it('says so when no account is connected, when an account is still loading, and when nothing matches', async () => {
    server(base({ '/v1/hub': overview({ accounts: [] }) })); show();
    expect(await screen.findByText('No mail account is connected')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Connect First Mail' }).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Lumina asks only to read/).length).toBeGreaterThan(0);
    cleanup();
    server(base({ '/v1/hub': overview({ accounts: [account({ mail: { synced_epoch: null, filled: false, items: 40, error: null, paused: false } })] }), '/v1/hub/mail/threads': { threads: [], next: null, complete: true } })); show();
    expect(await screen.findByText(/Loading all mail from me@first.test \(40 so far\)\. Newest first/)).toBeTruthy();
    expect(screen.getByText(/Loading… 40 so far/)).toBeTruthy();
  });

  it('offers a search of older mail only where the account can do it, and says when the result is partial', async () => {
    server(base({ '/v1/hub/mail/threads': { threads: [], next: null, complete: true },
      '/v1/hub/mail/search-older': (url: URL) => (url.searchParams.get('continuation')
        ? { messages: [{ ...message({ id: 'o3', subject: 'Old three' }), connection_id: 'c1' }], problem: null, page: { count: 1, complete: true, total_estimate: 3, continuation: null, stopped_by: null } }
        : { messages: [{ ...message({ id: 'o1', subject: 'Old one' }), connection_id: 'c1' }, { ...message({ id: 'o2', subject: 'Old two' }), connection_id: 'c1' }], problem: null,
            page: { count: 2, complete: false, total_estimate: 3, continuation: 'next', stopped_by: 'pages' } }) }));
    show();
    await screen.findByText('Nothing here.');
    fireEvent.change(screen.getByLabelText('Search mail'), { target: { value: 'invoice' } }); fireEvent.submit(screen.getByRole('search'));
    expect(await screen.findByText(/Nothing matches “invoice”/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Search older mail in me@first.test' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Search older mail in ich@second.test' })).toBeNull();          // that account's capability says it cannot
    fireEvent.click(screen.getByRole('button', { name: 'Search older mail in me@first.test' }));
    expect(await screen.findByText('The first 2 older messages are shown. There are more.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show more older mail' }));
    expect(await screen.findByText('3 older messages found. That is all of them.')).toBeTruthy();
    expect(screen.getByText('Old three')).toBeTruthy();
  });

  // UI remodel (phase 3): the list is virtualized and loads the next page by itself as the reader nears its end; the "Show more" button is gone.
  it('pages with the cursor the server gave, by itself near the end of the list', async () => {
    server(base({ '/v1/hub/mail/threads': (url: URL) => (url.searchParams.get('cursor') === 'c-2' ? { threads: [other], next: null, complete: true } : { threads: [thread()], next: 'c-2', complete: false }) }));
    show();
    expect(await screen.findByText('Termin morgen')).toBeTruthy(); expect(screen.getByText('Quarterly numbers')).toBeTruthy();
    expect(asked('/v1/hub/mail/threads').map(u => u.get('cursor'))).toEqual([null, 'c-2']);
  });

  it('moves through the list with the keyboard', async () => {
    server(base()); show();
    await screen.findByText('Quarterly numbers');
    // The list being on screen does not yet mean the page is listening for keys (that is attached just after it is drawn): press until the first thread opens.
    await waitFor(() => { if (!asked('/v1/hub/mail/thread').length) fireEvent.keyDown(window, { key: 'j' }); expect(asked('/v1/hub/mail/thread').at(-1)?.get('id')).toBe('t-1'); });
    await screen.findByRole('heading', { name: 'Quarterly numbers' });
    fireEvent.keyDown(window, { key: 'j' });
    await waitFor(() => expect(asked('/v1/hub/mail/thread').at(-1)?.get('id')).toBe('conv:9@x/1'));
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Open thread' })).toBeNull());     // the open thread's zone appears only while a thread is open (UI remodel)
    fireEvent.keyDown(window, { key: '/' });
    expect(document.activeElement).toBe(screen.getByLabelText('Search mail'));
  });

  it('starts a sign-in by sending the customer to the address the server gave', async () => {
    const assign = vi.fn(); vi.stubGlobal('location', { ...window.location, assign });
    server(base({ 'POST /v1/hub/link': { authorize_url: 'https://signin.first.test/auth?state=s', expires_in: 600 } })); show();
    await screen.findByText('Quarterly numbers');
    fireEvent.click(screen.getByRole('button', { name: 'Connect First Mail' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://signin.first.test/auth?state=s'));
    expect(calls.find(c => c.url === '/v1/hub/link')?.body).toEqual({ provider: 'p1' });
  });

  it('after signing in, asks what may be read, with nothing chosen for the customer', async () => {
    const fresh = account({ id: 'c9', identity: 'new@first.test', granted: { mail: false, calendar: false }, mail: null });
    server(base({ '/v1/hub': overview({ accounts: [account(), fresh] }),
      '/v1/integrations/c9/resources': { resources: [{ kind: 'mailbox', id: '*', name: 'All mail' }, { kind: 'label', id: 'L1', name: 'Finance' }, { kind: 'label', id: 'L2', name: 'Team' },
        { kind: 'calendar', id: 'k1', name: 'Work' }, { kind: 'calendar', id: 'k2', name: 'Family' }] },
      'POST /v1/integrations/c9/grants': { connection: {} }, 'POST /v1/hub/refresh': { requested: 1 } }));
    show('/inbox?connected=c9');
    const dialog = within(await screen.findByRole('dialog', { name: 'Choose what Lumina may read in new@first.test' }));
    await dialog.findByLabelText('All mail');
    expect((dialog.getByLabelText('No mail') as HTMLInputElement).checked).toBe(true);                    // nothing is chosen for them
    expect(dialog.getAllByRole('checkbox').every(c => !(c as HTMLInputElement).checked)).toBe(true);
    expect((dialog.getByRole('button', { name: 'Let Lumina read these' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(dialog.getByLabelText('Only these labels')); fireEvent.click(dialog.getByLabelText('Finance')); fireEvent.click(dialog.getByLabelText('Family'));
    fireEvent.click(dialog.getByRole('button', { name: 'Let Lumina read these' }));
    await waitFor(() => expect(calls.find(c => c.url === '/v1/integrations/c9/grants')?.body).toEqual({ grants: [{ kind: 'label', id: 'L1', name: 'Finance' }, { kind: 'calendar', id: 'k2', name: 'Family' }] }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(calls.find(c => c.url === '/v1/hub/refresh')?.body).toEqual({ connection_id: 'c9' });
  });

  it('finishes a sign-in when the provider sends the browser back, and takes the values out of the address', async () => {
    const fresh = account({ id: 'c9', identity: 'new@first.test', granted: { mail: false, calendar: false }, mail: null });
    let connected = false;
    server(base({ '/v1/hub': () => overview({ accounts: connected ? [account(), fresh] : [account()] }),
      'POST /v1/hub/link/finish': () => { connected = true; return new Response(JSON.stringify({ connection_id: 'c9' }), { status: 201 }); },
      '/v1/integrations/c9/resources': { resources: [{ kind: 'mailbox', id: '*', name: 'All mail' }] } }));
    window.history.replaceState(null, '', '/inbox#link-state=s%2F1&link-code=4%2Fabc');
    show();
    expect(await screen.findByRole('dialog', { name: 'Choose what Lumina may read in new@first.test' })).toBeTruthy();
    expect(calls.find(c => c.url === '/v1/hub/link/finish')?.body).toEqual({ state: 's/1', code: '4/abc' });
    expect(calls.filter(c => c.url === '/v1/hub/link/finish').length).toBe(1);
    expect(window.location.hash).toBe('');                                                        // gone from the address at once, so it is not kept or shared
  });

  it('says plainly when the provider return could not be finished', async () => {
    server(base({ 'POST /v1/hub/link/finish': () => new Response(JSON.stringify({ error: 'link_failed' }), { status: 409 }) }));
    window.history.replaceState(null, '', '/inbox#link-state=s1&link-code=c1');
    show();
    expect(await screen.findByText('The account could not be connected. Nothing was connected. Please try again.')).toBeTruthy();
    expect(window.location.hash).toBe('');
  });

  it('says plainly when a sign-in did not connect anything, and offers the choice again for an account with nothing chosen', async () => {
    const fresh = account({ id: 'c9', identity: 'new@first.test', granted: { mail: false, calendar: false }, mail: null });
    server(base({ '/v1/hub': overview({ accounts: [account(), fresh] }), '/v1/integrations/c9/resources': { resources: [] } })); show('/inbox?connect=declined');
    expect(await screen.findByText('You did not give access, so nothing was connected.')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(await screen.findByRole('button', { name: 'Choose what Lumina may read' }));
    expect(await screen.findByText(/This account gave Lumina nothing it can read/)).toBeTruthy();
  });

  it('is live: when the server says something changed, the list is loaded again without being asked', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    let mark = 'm1'; let list = [thread()];
    server(base({ '/v1/hub/pulse': () => ({ mark, loading: false, items: 1 }), '/v1/hub/mail/threads': () => ({ threads: list, next: null, complete: true }) }));
    show();
    await screen.findByText('Quarterly numbers');
    await waitFor(() => expect(asked('/v1/hub/pulse').length).toBe(1));
    const loads = asked('/v1/hub/mail/threads').length;
    await vi.advanceTimersByTimeAsync(8000);
    await waitFor(() => expect(asked('/v1/hub/pulse').length).toBe(2));
    expect(asked('/v1/hub/mail/threads').length).toBe(loads);                                      // the same mark: nothing is loaded again
    mark = 'm2'; list = [other, thread()];
    await vi.advanceTimersByTimeAsync(8000);
    expect(await screen.findByText('Termin morgen')).toBeTruthy();                                // new mail appeared by itself
    vi.useRealTimers();
  });

  it('does not throw the customer back to the top when they have paged further: it offers the new mail instead', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    let mark = 'm1';
    server(base({ '/v1/hub/pulse': () => ({ mark, loading: false, items: 2 }),
      '/v1/hub/mail/threads': (url: URL) => (url.searchParams.get('cursor') ? { threads: [other], next: null, complete: true } : { threads: [thread()], next: 'c-2', complete: false }) }));
    show();
    await screen.findByText('Termin morgen');                                                     // the second page came by itself (the list reached its end)
    await waitFor(() => expect(asked('/v1/hub/pulse').length).toBeGreaterThan(0));
    mark = 'm2';
    await vi.advanceTimersByTimeAsync(8000);
    expect(await screen.findByText('There is new mail.')).toBeTruthy();
    expect(screen.getByText('Termin morgen')).toBeTruthy();                                       // what they were reading is still there
    vi.useRealTimers();
  });

  it('is a plain "not available" page while the feature is off, and asks the server nothing', async () => {
    features = {}; server(base()); show();
    expect(screen.getByText('Not available yet')).toBeTruthy();
    expect(calls.length).toBe(0);
  });
});

describe('the frame a message is shown in', () => {
  it('lets pictures load and nothing else, and opens links in a new tab', () => {
    const doc = frameDocument('<p>hi</p>', { '--text-primary': 'white' });
    expect(doc).toContain(`content="default-src 'none'; img-src http: https:; style-src 'unsafe-inline'"`);
    expect(doc).toContain('<base target="_blank">'); expect(doc).toContain('color:white'); expect(doc).toContain('<body><p>hi</p></body>');
  });
});

describe('no provider is named in the dashboard', () => {
  it('has no provider name in any page, component, helper or style of the dashboard', () => {
    const sources = import.meta.glob<string>(['/src/pages/Inbox.tsx', '/src/pages/CalendarPage.tsx', '/src/components/hub/*.tsx', '/src/lib/hub.ts', '/src/styles/hub.css'],
      { query: '?raw', import: 'default', eager: true });
    const names = /\b(google|gmail|microsoft|outlook|office365|yahoo|icloud|imap|exchange)\b/i;
    expect(Object.keys(sources).length).toBeGreaterThanOrEqual(6);
    for (const [file, text] of Object.entries(sources)) expect(text.split('\n').filter(line => names.test(line)), file).toEqual([]);
  });
});
