import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Inbox from './Inbox';
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

describe('Inbox drafts and links', () => {
  const lumina = { id: 'd1', account: 'c1', thread: 't-1', to: ['ann@x.test'], cc: [], subject: 'Re: Quarterly numbers', body: 'Thanks, Ann.', origin: 'assistant', created_epoch: NOW, updated_epoch: NOW };
  it('shows the assistant\'s draft under its thread, and a reply goes to the last sender with Re: once and the message quoted', async () => {
    server(base({ '/v1/hub/drafts': { drafts: [lumina, { ...lumina, id: 'dx', thread: 'another', body: 'For another conversation.' }] },
      'POST /v1/hub/drafts': () => ({ draft: { ...lumina, id: 'd2', origin: 'customer', body: '' } }) }));
    show('/inbox?connection=c1&thread=t-1');
    const theirs = await screen.findByRole('region', { name: 'Draft by your assistant' });
    expect((within(theirs).getByLabelText('Message') as HTMLTextAreaElement).value).toBe('Thanks, Ann.');
    expect(screen.getAllByRole('region', { name: 'Draft by your assistant' })).toHaveLength(1);    // only this conversation's draft
    expect(asked('/v1/hub/drafts').every(q => q.get('thread') === null)).toBe(true);              // from the drafts already here: opening a conversation asks nothing more
    fireEvent.click(screen.getByRole('button', { name: 'Reply' }));
    const mine = screen.getByRole('region', { name: 'Your reply' });
    expect((within(mine).getByLabelText('To') as HTMLInputElement).value).toBe('ann@x.test');
    expect((within(mine).getByLabelText('Subject') as HTMLInputElement).value).toBe('Re: Quarterly numbers');
    const quoted = (within(mine).getByLabelText('Message') as HTMLTextAreaElement).value;
    expect(quoted).toMatch(/\n\nOn .*, Ann <ann@x\.test> wrote:\n> Here are the numbers$/);         // what is being answered travels with the answer
    expect(calls.some(c => c.method === 'POST' && /send|messages/.test(c.url))).toBe(false);       // writing sends nothing
  });
  it('lists what was written in Lumina under Drafts, across accounts, above the mailbox\'s own drafts', async () => {
    server(base({ '/v1/hub/drafts': { drafts: [lumina, { ...lumina, id: 'd3', account: 'c2', thread: null, subject: 'Hallo', to: ['bernd@y.test'], origin: 'customer' }] } }));
    show();
    expect(await screen.findByLabelText('2 written in Lumina')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /^Drafts/ }));
    const list = await screen.findByLabelText('Written in Lumina');
    expect(within(list).getAllByRole('button')).toHaveLength(2);
    fireEvent.click(within(list).getByText('Hallo'));
    expect(await screen.findByRole('region', { name: 'New message' })).toBeTruthy();
    expect((screen.getByLabelText('From') as HTMLSelectElement).value).toBe('c2');
  });
});

describe('Inbox', () => {
  it('shows the mail of two different providers as one list, each row saying which account it is from', async () => {
    server(base()); show();
    const list = within(await screen.findByRole('list', { name: 'Conversations' }));
    const rows = list.getAllByRole('listitem');
    expect(rows.map(r => within(r).getByText(/Quarterly|Termin/).textContent)).toEqual(['Quarterly numbers', 'Termin morgen']);
    expect(within(rows[0]).getByTitle('In me@first.test').textContent).toBe('first.test'); expect(within(rows[1]).getByTitle('In ich@second.test').textContent).toBe('second.test');   // the shortest name that tells them apart, never an address cut short
    expect(within(rows[0]).getByText('Ann')).toBeTruthy();                                       // who it is with, without the account's own address
    expect(within(rows[0]).getByLabelText('Unread')).toBeTruthy(); expect(within(rows[1]).queryByLabelText('Unread')).toBeNull();
    expect(within(rows[0]).getByLabelText('Has an attachment')).toBeTruthy();
    expect(screen.queryByText(/Read only for now/)).toBeNull();                                  // no notice that is always there: what cannot be done is simply not drawn
    expect(within(rows[0]).queryByRole('button', { name: 'Archive' })).toBeNull();
    expect(screen.getByLabelText('4 unread')).toBeTruthy();
    expect(screen.getByText('First Mail')).toBeTruthy(); expect(screen.getByText('Zweite Post')).toBeTruthy();      // an account that simply works says nothing more
    expect(screen.getByText('Labels · first.test')).toBeTruthy(); expect(screen.getByText('Folders · second.test')).toBeTruthy();      // from the capability, not the provider's name
  });

  it('asks the server for what the filters say', async () => {
    server(base()); show();
    await screen.findByText('Quarterly numbers');
    expect(asked('/v1/hub/mail/threads')[0].get('label')).toBe('inbox');
    // Every account until the customer narrows them: no accounts named, so the first page does not wait for the accounts overview (UI remodel, measured on production).
    expect(asked('/v1/hub/mail/threads')[0].get('accounts')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Sent' }));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('label')).toBe('sent'));
    fireEvent.click(screen.getByRole('button', { name: 'Unread' }));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('unread')).toBe('1'));
    fireEvent.click(screen.getByRole('button', { name: 'Attachments' }));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('attachments')).toBe('1'));
    fireEvent.click(screen.getByRole('button', { name: /me@first\.test/, pressed: false }));      // one account only
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('accounts')).toBe('c1'));
    expect(screen.queryByText('Folders · second.test')).toBeNull();                           // an account that is not shown offers no folders
    fireEvent.change(screen.getByLabelText('Search mail'), { target: { value: ' budget ' } }); fireEvent.submit(screen.getByRole('search'));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('q')).toBe('budget'));
    fireEvent.click(screen.getByRole('button', { name: 'All accounts' }));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('accounts')).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: /Posteingang/ }));
    await waitFor(() => { const last = asked('/v1/hub/mail/threads').at(-1)!; expect([last.get('provider_label'), last.get('accounts'), last.get('label')]).toEqual(['folder/Posteingang', 'c2', 'all']); });
  });

  it('opens a thread with its last message in a page of its own that can run nothing, and sends an id with any character intact', async () => {
    server(base({ '/v1/hub/mail/thread': (url: URL) => ({ thread: url.searchParams.get('id') === 't-1' ? thread() : other, messages: [message({ id: 'm-1', body: null, snippet: 'Earlier note', sent_epoch: NOW - 9000 }), message()], problem: null }) }));
    show();
    fireEvent.click((await screen.findByText('Termin morgen')).closest('button')!);
    await screen.findByRole('heading', { name: 'Termin morgen' });
    expect([asked('/v1/hub/mail/thread')[0].get('connection'), asked('/v1/hub/mail/thread')[0].get('id')]).toEqual(['c2', 'conv:9@x/1']);
    const frames = document.querySelectorAll('iframe');
    expect(frames.length).toBe(1);                                                                // only the last message is open
    expect(frames[0].getAttribute('sandbox')).toBe('allow-same-origin allow-popups allow-popups-to-escape-sandbox');
    expect(frames[0].getAttribute('sandbox')).not.toContain('allow-scripts');
    // The message is a page fetched from the server with its own content policy, never markup written into the frame here (that would inherit the app's policy,
    // which refuses a message's styles and pictures: every message was shown unstyled).
    expect(frames[0].hasAttribute('srcdoc')).toBe(false);
    const at = new URL(frames[0].getAttribute('src')!, 'https://app.test');
    expect([at.pathname, at.searchParams.get('connection'), at.searchParams.get('id'), at.searchParams.get('images')]).toEqual(['/v1/hub/mail/frame', 'c2', 'm-2', null]);
    expect(frames[0].getAttribute('referrerpolicy')).toBe('no-referrer');
    const file = screen.getByRole('link', { name: 'Download q3.pdf' });
    expect(new URL(file.getAttribute('href')!, 'https://app.test').searchParams.get('attachment')).toBe('f1'); expect(file.getAttribute('download')).toBe('q3.pdf');
    expect(screen.getByText(/PDF · 20 KB/)).toBeTruthy();
    expect(screen.getByText('Earlier note')).toBeTruthy();                                        // the earlier message shows its header only
  });

  it('shows a designed message on a light page of its own, and a picture among the files opens here', async () => {
    const designed = message({ body: { ...message().body!, designed: true, blocked_images: 0, attachments: [{ id: 'p1', name: 'chart.png', type: 'image/png', size: 2048 }, { id: 'v1', name: 'drawing.svg', type: 'image/svg+xml', size: 900 }] } });
    server(base({ '/v1/hub/mail/thread': { thread: thread(), messages: [designed], problem: null } }));
    show();
    fireEvent.click((await screen.findByText('Quarterly numbers')).closest('button')!);
    await screen.findByRole('heading', { name: 'Quarterly numbers' });
    expect(document.querySelector('iframe')!.className).toContain('designed');
    fireEvent.click(screen.getByTitle('Show chart.png'));
    const shown = within(await screen.findByRole('dialog', { name: 'chart.png' }));
    expect(new URL((shown.getByAltText('chart.png') as HTMLImageElement).src).searchParams.get('inline')).toBe('1');
    expect(screen.queryByTitle('Show drawing.svg')).toBeNull();                                   // a vector picture can hold a script: it is a download, never shown
    expect(screen.getByTitle('Download drawing.svg')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'chart.png' })).toBeNull());
    expect(screen.getByRole('heading', { name: 'Quarterly numbers' })).toBeTruthy();              // Escape closed the picture, not the conversation
  });

  it('keeps remote pictures out until asked, for this message or for the sender', async () => {
    const withPictures = message({ body: { ...message().body!, blocked_images: 0, images_shown: true } });
    server(base({ '/v1/hub/mail/message': { message: withPictures, problem: null }, 'POST /v1/hub/settings': { settings: { timezone: 'UTC', image_senders: ['ann@x.test'] } } }));
    show();
    fireEvent.click((await screen.findByText('Quarterly numbers')).closest('button')!);
    expect(await screen.findByText(/2 pictures are hidden, so the sender cannot tell that you opened this/)).toBeTruthy();
    expect(document.querySelector('iframe')!.getAttribute('src')).not.toContain('images=');
    fireEvent.click(screen.getByRole('button', { name: 'Show pictures' }));
    await waitFor(() => expect(document.querySelector('iframe')!.getAttribute('src')).toContain('images=1'));
    expect(asked('/v1/hub/mail/message')[0].get('images')).toBe('1');
    expect(screen.queryByText(/pictures are hidden/)).toBeNull();
    expect(calls.some(c => c.method === 'POST')).toBe(false);                                     // showing once remembers nothing
  });

  it('remembers a sender only when asked to', async () => {
    server(base({ '/v1/hub/mail/message': { message: message({ body: { ...message().body!, blocked_images: 0, images_shown: true } }), problem: null },
      'POST /v1/hub/settings': { settings: { timezone: 'UTC', image_senders: ['ann@x.test'] } } }));
    show();
    fireEvent.click((await screen.findByText('Quarterly numbers')).closest('button')!);
    fireEvent.click(await screen.findByRole('button', { name: 'Always from this sender' }));
    await waitFor(() => expect(calls.find(c => c.method === 'POST' && c.url === '/v1/hub/settings')?.body).toEqual({ allow_images_from: 'ann@x.test' }));
  });

  it('opens an earlier message when its header is pressed, and says plainly when it cannot be fetched', async () => {
    server(base({ '/v1/hub/mail/message': { message: message({ id: 'm-1', body: null, snippet: 'Earlier note' }), problem: 'retry_later' } }));
    show();
    fireEvent.click((await screen.findByText('Quarterly numbers')).closest('button')!);
    const earlier = (await screen.findByText('Earlier note')).closest('article')!;
    fireEvent.click(within(earlier).getByRole('button', { expanded: false }));
    expect(await screen.findByText(/The mail service is busy right now/)).toBeTruthy();
    expect(asked('/v1/hub/mail/message')[0].get('id')).toBe('m-1');
  });

  it('keeps showing an account whose access ended, says what that means, and connects it again in place', async () => {
    const assign = vi.fn(); vi.stubGlobal('location', { ...window.location, assign });
    server(base({ '/v1/hub': overview({ accounts: [account({ state: 'needs_you', needs_reason: 'reconnect' }), second] }), 'POST /v1/hub/link': { authorize_url: 'https://signin.first.test/again', expires_in: 600 } })); show();
    const banner = (await screen.findByText(/is no longer connected: its access ended at First Mail/)).closest('p')!;
    expect(banner.textContent).toContain('The mail already here is still shown');
    expect(await screen.findByText('Quarterly numbers')).toBeTruthy(); expect(screen.getByText('Termin morgen')).toBeTruthy();
    fireEvent.click(within(banner).getByRole('button', { name: 'Reconnect' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://signin.first.test/again'));
    expect(calls.find(c => c.url === '/v1/hub/link')?.body).toEqual({ provider: 'first', connection: 'c1' });       // the same connection: its mail and what it was allowed stay
  });

  it('says so when no account is connected, when an account is still loading, and when nothing matches', async () => {
    server(base({ '/v1/hub': overview({ accounts: [] }) })); show();
    expect(await screen.findByText('Bring your mail into Lumina')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Connect an account' }));
    expect(await screen.findByRole('menuitem', { name: 'First Mail' })).toBeTruthy();
    expect(screen.getByText(/Lumina asks only to read/)).toBeTruthy();                           // said where an account is added, not on every screen
    expect(screen.queryByRole('button', { name: 'Compose' })).toBeNull();
    cleanup();
    server(base({ '/v1/hub': overview({ accounts: [account({ mail: { synced_epoch: null, filled: false, items: 40, error: null, paused: false } })] }), '/v1/hub/mail/threads': { threads: [], next: null, complete: true } })); show();
    expect(await screen.findByText(/First Mail · Loading mail: 40 so far/)).toBeTruthy();
    expect(screen.getByText('Still loading older mail…')).toBeTruthy();
    expect(await screen.findByText('Nothing in Inbox.')).toBeTruthy();
  });

  it('offers a search of older mail only where the account can do it, and says when the result is partial', async () => {
    server(base({ '/v1/hub/mail/threads': { threads: [], next: null, complete: true },
      '/v1/hub/mail/search-older': (url: URL) => (url.searchParams.get('continuation')
        ? { messages: [{ ...message({ id: 'o3', subject: 'Old three' }), connection_id: 'c1' }], problem: null, page: { count: 1, complete: true, total_estimate: 3, continuation: null, stopped_by: null } }
        : { messages: [{ ...message({ id: 'o1', subject: 'Old one' }), connection_id: 'c1' }, { ...message({ id: 'o2', subject: 'Old two' }), connection_id: 'c1' }], problem: null,
            page: { count: 2, complete: false, total_estimate: 3, continuation: 'next', stopped_by: 'pages' } }) }));
    show();
    await screen.findByText('Nothing in Inbox.');
    fireEvent.change(screen.getByLabelText('Search mail'), { target: { value: 'invoice' } }); fireEvent.submit(screen.getByRole('search'));
    expect(await screen.findByText(/Nothing matches “invoice”/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Search me@first.test' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Search ich@second.test' })).toBeNull();          // that account's capability says it cannot
    fireEvent.click(screen.getByRole('button', { name: 'Search me@first.test' }));
    expect(await screen.findByText('The first 2 older messages are shown. There are more.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show more older mail' }));
    expect(await screen.findByText('3 older messages found. That is all of them.')).toBeTruthy();
    expect(screen.getByText('Old three')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Clear the search' }));
    await waitFor(() => expect(asked('/v1/hub/mail/threads').at(-1)!.get('q')).toBeNull());
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
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Termin morgen' })).toBeNull());   // the open conversation is gone; the place for it says how to open one
    expect(screen.getByText('Select a conversation to read it here.')).toBeTruthy();
    fireEvent.keyDown(window, { key: '/' });
    expect(document.activeElement).toBe(screen.getByLabelText('Search mail'));
    (document.activeElement as HTMLElement).blur();
    fireEvent.keyDown(window, { key: 'c' });
    expect(await screen.findByRole('region', { name: 'New message' })).toBeTruthy();
  });

  it('starts a sign-in by sending the customer to the address the server gave, for the kind of account they chose', async () => {
    const assign = vi.fn(); vi.stubGlobal('location', { ...window.location, assign });
    server(base({ '/v1/hub': overview({ providers: [{ provider: 'p1', label: 'First Mail' }, { provider: 'p2', label: 'Second Mail', kinds: [{ id: 'personal', label: 'Personal account' }, { id: 'work', label: 'Work or school' }] }] }),
      'POST /v1/hub/link': { authorize_url: 'https://signin.first.test/auth?state=s', expires_in: 600 } })); show();
    await screen.findByText('Quarterly numbers');
    fireEvent.click(screen.getByRole('button', { name: 'Add an account' }));
    expect(await screen.findByRole('menuitem', { name: 'First Mail' })).toBeTruthy();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Work or school' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://signin.first.test/auth?state=s'));
    expect(calls.find(c => c.url === '/v1/hub/link')?.body).toEqual({ provider: 'p2', kind: 'work' });
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

  it('says why a sign-in connected nothing, in words that say what to do, never one sentence for every cause', async () => {
    const finish = (body: unknown) => { cleanup(); server(base({ 'POST /v1/hub/link/finish': () => new Response(JSON.stringify(body), { status: 409 }) })); window.history.replaceState(null, '', '/inbox#link-state=s1&link-code=c1'); show(); };
    finish({ error: 'link_failed', reason: 'provider_setup', reference: 'AADSTS7000222' });
    const setup = await screen.findByRole('alert');
    expect(setup.textContent).toContain('The mail service refused Lumina itself, not your account.'); expect(setup.textContent).toContain('(Reference: AADSTS7000222.)');
    expect(window.location.hash).toBe('');
    finish({ error: 'link_failed', reason: 'admin_consent' });
    expect((await screen.findByRole('alert')).textContent).toContain('Ask your IT administrator to allow Lumina');
    finish({ error: 'link_failed', reason: 'no_access' });
    expect((await screen.findByRole('alert')).textContent).toContain('leave mail or calendars ticked');
    finish({ error: 'link_failed', reason: 'expired' });
    expect((await screen.findByRole('alert')).textContent).toContain('already used or took too long');
    finish({ error: 'different_account', reason: 'different_account' });
    expect((await screen.findByRole('alert')).textContent).toContain('Sign in with the same address');
    finish({ error: 'link_failed' });                                                              // an older server, or a cause without a name
    expect((await screen.findByRole('alert')).textContent).toContain('The account could not be connected. Nothing was connected. Try again.');
    fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByText(/could not be connected/)).toBeNull());
  });

  it('says plainly when the provider sent the customer back without connecting, and offers the choice again for an account with nothing chosen', async () => {
    const fresh = account({ id: 'c9', identity: 'new@first.test', granted: { mail: false, calendar: false }, mail: null });
    server(base({ '/v1/hub': overview({ accounts: [account(), fresh] }), '/v1/integrations/c9/resources': { resources: [] } })); show('/inbox?connect=declined');
    expect(await screen.findByText('You did not give access, so nothing was connected.')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(await screen.findByText(/First Mail · Nothing chosen to read yet/)).toBeTruthy();
    fireEvent.click(await screen.findByRole('button', { name: 'Choose what to read' }));
    expect(await screen.findByText(/This account gave Lumina nothing it can read/)).toBeTruthy();
    cleanup(); server(base()); show('/inbox?connect=admin_consent&ref=AADSTS65001');
    expect((await screen.findByRole('alert')).textContent).toMatch(/only an administrator allow apps like Lumina.*Reference: AADSTS65001/);
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

describe('no provider is named in the dashboard', () => {
  it('has no provider name in any page, component, helper or style of the dashboard', () => {
    const sources = import.meta.glob<string>(['/src/pages/Inbox.tsx', '/src/pages/CalendarPage.tsx', '/src/components/hub/*.tsx', '/src/lib/hub.ts', '/src/styles/hub.css', '/src/styles/mail.css'],
      { query: '?raw', import: 'default', eager: true });
    const names = /\b(google|gmail|microsoft|outlook|office365|yahoo|icloud|imap|exchange)\b/i;
    expect(Object.keys(sources).length).toBeGreaterThanOrEqual(8);
    for (const [file, text] of Object.entries(sources)) expect(text.split('\n').filter(line => names.test(line)), file).toEqual([]);
  });
});


describe('Managing mail from the Inbox (Phase 6, #66, #67, #D6)', () => {
  const able = account({ capabilities: caps({ send: true, organize: true, mark_read: true }) });
  const mail = { undo_send_seconds: 10, mark_read_on_open: false, limits: {}, allowed: { recipients: 50, per_hour: 30 }, platform: { recipients: 50, per_hour: 30 } };
  const action = (id: string, kind: string, state = 'done') => ({ action: { id, kind, state, preview: { title: '', summary: '', destination: '', changes: [], can_undo: kind !== 'mail.send' },
    verified: true, can_undo: kind !== 'mail.send', undo_until_epoch: null, direct: 'inbox', ended_words: '' } });
  const routes = (over: Routes = {}) => base({ '/v1/hub': overview({ accounts: [able, second], read_only: false, settings: { timezone: 'UTC', image_senders: [], mail } }), ...over });
  const organized = () => calls.filter(c => c.url === '/v1/hub/mail/organize').map(c => c.body);

  it('archives the chosen conversations at once, says so, and undoes it in one step', async () => {
    server(routes({ 'POST /v1/hub/mail/organize': action('a1', 'mail.organize'), 'POST /v1/hub/actions/a1/undo': action('a2', 'mail.organize') }));
    show();
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select the conversation with Ann' }));
    const bar = within(screen.getByRole('toolbar', { name: 'Selected conversations' }));
    expect(bar.getByText('1 selected')).toBeTruthy();
    fireEvent.click(bar.getByRole('button', { name: 'Archive' }));
    await screen.findByText('Archived.');
    expect(organized()).toEqual([{ connection: 'c1', threads: ['t-1'], op: 'archive' }]);
    expect(screen.queryByRole('checkbox', { name: 'Select the conversation with Ann' })).toBeNull();           // it left the inbox at once
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText('Undone.');
    expect(calls.filter(c => c.url === '/v1/hub/actions/a1/undo').map(c => c.body)).toEqual([{ screen: 'inbox' }]);
  });

  it('a change the mailbox refused goes back with a sentence, never silently', async () => {
    server(routes({ 'POST /v1/hub/mail/organize': { action: { ...action('a1', 'mail.organize', 'failed').action, ended_words: 'The connected service did not accept this request.' } } }));
    show();
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select the conversation with Ann' }));
    fireEvent.click(within(screen.getByRole('toolbar', { name: 'Selected conversations' })).getByRole('button', { name: 'Archive' }));
    expect((await screen.findByRole('alert')).textContent).toContain('The connected service did not accept this request.');
    expect(await screen.findByRole('checkbox', { name: 'Select the conversation with Ann' })).toBeTruthy();       // back in the list as it really is
  });

  it('reads the list again after a change for the mailbox shown then, not the one that was shown when the change was made', async () => {
    server(routes({ 'POST /v1/hub/mail/organize': action('a1', 'mail.organize'),
      '/v1/hub/mail/threads': (url: URL) => ({ threads: url.searchParams.get('label') === 'sent' ? [other] : [thread()], next: null, complete: true }) }));
    show();
    const mine = (await screen.findByText('Quarterly numbers')).closest('li')!;
    fireEvent.click(within(mine).getByRole('button', { name: 'Mark as read' }));
    await waitFor(() => expect(organized()).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: 'Sent' }));                                  // the customer moves on before the list is read again
    expect(await screen.findByText('Termin morgen')).toBeTruthy();
    const before = asked('/v1/hub/mail/threads').length;
    await waitFor(() => expect(asked('/v1/hub/mail/threads').length).toBeGreaterThan(before), { timeout: 6000 });     // the list is read again a moment after the change
    expect(asked('/v1/hub/mail/threads').at(-1)!.get('label')).toBe('sent');
    await new Promise(r => setTimeout(r, 50));
    expect(screen.getByText('Termin morgen')).toBeTruthy(); expect(screen.queryByText('Quarterly numbers')).toBeNull();
  });

  it('offers each row its quick actions only where the account may change mail, and the open conversation its own', async () => {
    server(routes({ 'POST /v1/hub/mail/organize': action('a1', 'mail.organize') }));
    show();
    const mine = (await screen.findByText('Quarterly numbers')).closest('li')!; const theirs = screen.getByText('Termin morgen').closest('li')!;
    expect(within(mine).getByRole('group', { name: /Quick actions/ })).toBeTruthy();
    expect(within(theirs).queryByRole('group', { name: /Quick actions/ })).toBeNull();           // the second account is read only here: nothing is drawn disabled, it is not drawn
    fireEvent.click(within(mine).getByRole('button', { name: 'Mark as read' }));
    await waitFor(() => expect(organized()).toEqual([{ connection: 'c1', threads: ['t-1'], op: 'read' }]));
    fireEvent.click(screen.getByText('Quarterly numbers').closest('button')!);
    const tools = within(await screen.findByRole('toolbar', { name: 'This conversation' }));
    fireEvent.click(tools.getByRole('button', { name: 'Star' }));
    await waitFor(() => expect(organized().at(-1)).toEqual({ connection: 'c1', threads: ['t-1'], op: 'star' }));
    expect(await tools.findByRole('button', { name: 'Remove the star' })).toBeTruthy();           // shown at once, before the mailbox has answered again
  });

  it('archives the open conversation with a key and moves on to the next one, as a mail program does', async () => {
    server(routes({ 'POST /v1/hub/mail/organize': action('a1', 'mail.organize'),
      '/v1/hub/mail/thread': (url: URL) => ({ thread: url.searchParams.get('id') === 't-1' ? thread() : other, messages: [message()], problem: null }) }));
    show();
    fireEvent.click((await screen.findByText('Quarterly numbers')).closest('button')!);
    await screen.findByRole('toolbar', { name: 'This conversation' });
    fireEvent.keyDown(window, { key: 'e' });
    await waitFor(() => expect(organized()).toEqual([{ connection: 'c1', threads: ['t-1'], op: 'archive' }]));
    expect(await screen.findByRole('heading', { name: 'Termin morgen' })).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: 'Select the conversation with Ann' })).toBeNull();
  });

  it('leaves "G then a letter" to the app: the letter after G is not a mail key', async () => {
    server(routes({ 'POST /v1/hub/mail/organize': action('a1', 'mail.organize'), '/v1/hub/drafts': { drafts: [] } }));
    show('/inbox?connection=c1&thread=t-1');
    await screen.findByRole('toolbar', { name: 'This conversation' });
    fireEvent.keyDown(window, { key: 'g' }); fireEvent.keyDown(window, { key: 's' });               // "G then S" is Settings, not "star"
    fireEvent.keyDown(window, { key: 'g' }); fireEvent.keyDown(window, { key: 'a' });               // "G then A" is Activity, not "reply to everyone"
    expect(organized()).toEqual([]); expect(screen.queryByRole('region', { name: 'Your reply' })).toBeNull();
    fireEvent.keyDown(window, { key: 's' });
    await waitFor(() => expect(organized()).toEqual([{ connection: 'c1', threads: ['t-1'], op: 'star' }]));
    fireEvent.keyDown(window, { key: 'r' });
    expect(await screen.findByRole('region', { name: 'Your reply' })).toBeTruthy();
  });

  it('sends a reply after showing who it goes to, with Undo send while it waits', async () => {
    const saved = { id: 'd9', account: 'c1', thread: 't-1', to: ['ann@x.test'], cc: [], subject: 'Re: Quarterly numbers', body: 'Thanks!', origin: 'customer', created_epoch: NOW, updated_epoch: NOW };
    server(routes({ '/v1/hub/drafts': { drafts: [] }, 'POST /v1/hub/drafts': { draft: saved }, '/v1/hub/mail/check': { notes: ['You have not written to ann@x.test before (in the mail Lumina can see).'] },
      'POST /v1/hub/mail/send': { ...action('s1', 'mail.send', 'approved'), undo_send_seconds: 10 }, 'POST /v1/hub/actions/s1/stop': action('s1', 'mail.send', 'declined') }));
    show('/inbox?connection=c1&thread=t-1');
    fireEvent.click(await screen.findByRole('button', { name: 'Reply' }));
    const mine = screen.getByRole('region', { name: 'Your reply' });
    fireEvent.change(within(mine).getByLabelText('Message'), { target: { value: 'Thanks!' } });
    fireEvent.click(within(mine).getByRole('button', { name: 'Send' }));
    const before = await within(mine).findByRole('alertdialog', { name: 'Before you send' });
    expect(before.textContent).toContain('You have not written to ann@x.test before');
    expect(calls.find(c => c.method === 'POST' && c.url === '/v1/hub/drafts')?.body).toMatchObject({ connection_id: 'c1', thread_id: 't-1', to: ['ann@x.test'], body: 'Thanks!' });
    expect(calls.some(c => c.url === '/v1/hub/mail/send')).toBe(false);                                       // nothing is sent before the customer has seen it
    fireEvent.click(within(before).getByRole('button', { name: 'Send anyway' }));
    await within(mine).findByText(/Sending from me@first.test in 10 s/);
    expect(calls.filter(c => c.url === '/v1/hub/mail/send').map(c => c.body)).toEqual([{ draft: 'd9' }]);
    fireEvent.click(within(mine).getByRole('button', { name: 'Undo send' }));
    await within(mine).findByText('Not sent. The draft is still here.');
    expect(calls.filter(c => c.url === '/v1/hub/actions/s1/stop')).toHaveLength(1);
  });

  it('forwards the last message quoted, to nobody yet, from the account that received it', async () => {
    server(routes({ '/v1/hub/drafts': { drafts: [] } }));
    show('/inbox?connection=c1&thread=t-1');
    fireEvent.click(await screen.findByRole('button', { name: 'Forward' }));
    const mine = await screen.findByRole('region', { name: 'Forward' });
    expect((within(mine).getByLabelText('To') as HTMLInputElement).value).toBe('');
    expect((within(mine).getByLabelText('From') as HTMLSelectElement).value).toBe('c1');
    expect((within(mine).getByLabelText('Subject') as HTMLInputElement).value).toBe('Fwd: Quarterly numbers');
    expect((within(mine).getByLabelText('Message') as HTMLTextAreaElement).value).toContain('---------- Forwarded message ----------');
    expect((within(mine).getByLabelText('Message') as HTMLTextAreaElement).value).toContain('Here are the numbers');
  });

  it('keeps the settings out of the way in a sheet, and saves each as it is changed', async () => {
    server(routes({ 'POST /v1/hub/settings': { settings: { timezone: 'UTC', image_senders: [], mail: { ...mail, mark_read_on_open: true } } } }));
    show();
    await screen.findByText('Quarterly numbers');
    expect(screen.queryByText('Undo send')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Mail settings' }));
    fireEvent.click(await screen.findByLabelText(/Opening a message marks it read in my mailbox/));
    await waitFor(() => expect(calls.find(c => c.method === 'POST' && c.url === '/v1/hub/settings')?.body).toEqual({ mail: { mark_read_on_open: true } }));
  });
});
