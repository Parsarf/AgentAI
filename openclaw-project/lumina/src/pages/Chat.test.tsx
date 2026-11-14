import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import Chat from './Chat';
import { hold, resetWork, row, summary, view, work } from '../test/workMock';
vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
const data = { app: { user: { email: 'test@example.com' }, limits: { max_message_chars: 16000 }, features: { execution: true } }, chats: [], refreshChats: vi.fn(async () => {}), refresh: vi.fn(async () => {}) };
vi.mock('../state/data', () => ({ useData: () => data }));
vi.mock('../components/Orb', () => ({ default: () => <span data-testid="thinking-orb" /> }));
const Switch = () => { const nav = useNavigate(); return <><button onClick={() => nav('/chat/a')}>Open A</button><button onClick={() => nav('/chat/b')}>Open B</button><Chat /></>; };
const msg = (id: number, content: string, provenance = 'agent') => ({ id, content, provenance, request_id: null, created_at: '' });
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
beforeEach(() => { resetWork(); sessionStorage.clear(); Element.prototype.scrollIntoView = vi.fn(); window.scrollTo = vi.fn() as any; Element.prototype.scrollTo = vi.fn(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const mount = () => render(<MemoryRouter initialEntries={['/chat/a']}><Routes><Route path="/chat/:id" element={<Switch />} /></Routes></MemoryRouter>);
describe('messages typed in the side chat', () => {
  it('say where they were sent from, and ordinary messages do not', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/blocks')) return ok({ blocks: [] });
      if (url.includes('/messages')) return ok({ messages: [{ ...msg(1, 'only the red ones', 'customer'), surface: 'panel' }, msg(2, 'From the web', 'customer'), msg(3, 'Looking now')], tasks: [] });
      return ok({ conversation: { id: 'a', title: 'Saved chat' } });
    }));
    mount(); await screen.findByText('only the red ones');
    expect(screen.getAllByText('Sent from the side chat in your browser')).toHaveLength(1);
    expect(screen.getByText('only the red ones').parentElement?.textContent).toContain('Sent from the side chat in your browser');
    expect(screen.getByText('From the web').parentElement?.textContent).not.toContain('Sent from the side chat');
  });
});
describe('resuming conversations', () => {
  it('loads more than 100 messages and sends follow-ups into the same chat', async () => {
    const calls: string[] = []; let sent = false;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: any = {}) => {
      calls.push(url);
      if (url === '/v1/csrf') return ok({ csrf_token: 't' });
      if (url.endsWith('/blocks')) return ok({ blocks: [] });
      if (url.endsWith('/send')) { sent = true; return ok({ request: { id: 'r', message: 'follow up' } }); }
      if (url === '/v1/conversations/a') return ok({ conversation: { id: 'a', title: 'Saved chat' } });
      if (url.endsWith('/messages')) return ok({ messages: Array.from({ length: 100 }, (_, i) => msg(i + 1, `Message ${i + 1}`)), tasks: [], has_more: true, next_after: 100 });
      if (url.includes('after=100')) return ok({ messages: [msg(101, 'Last saved message')], tasks: [], has_more: false });
      if (url.includes('after=101')) return ok({ messages: sent ? [msg(102, 'follow up', 'customer'), msg(103, 'Continued answer')] : [], tasks: [] });
      return ok({});
    }));
    mount(); await screen.findByText('Last saved message');
    expect(screen.getByText('Message 1')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Message Lumina'), { target: { value: 'follow up' } }); fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByText('Continued answer'); expect(calls).toContain('/v1/conversations/a/send'); expect(calls).not.toContain('/v1/conversations');
  });
  it('restores separate drafts and hides the old transcript when switching chats', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/blocks')) return ok({ blocks: [] });
      if (url.includes('/messages')) return ok({ messages: [msg(url.includes('/a/') ? 1 : 2, url.includes('/a/') ? 'Answer A' : 'Answer B')], tasks: [] });
      return ok({ conversation: { id: url.endsWith('/a') ? 'a' : 'b', title: 'Saved chat' } });
    }));
    mount(); await screen.findByText('Answer A');
    fireEvent.change(screen.getByLabelText('Message Lumina'), { target: { value: 'Draft A' } });
    fireEvent.click(screen.getByRole('button', { name: 'Open B' })); await screen.findByText('Answer B');
    expect(screen.queryByText('Answer A')).toBeNull(); expect((screen.getByLabelText('Message Lumina') as HTMLTextAreaElement).value).toBe('');
    fireEvent.click(screen.getByRole('button', { name: 'Open A' })); await screen.findByText('Answer A');
    expect((screen.getByLabelText('Message Lumina') as HTMLTextAreaElement).value).toBe('Draft A');
  });
  it('ignores a late response from the conversation that was left', async () => {
    let release!: (value: unknown) => void; const old = new Promise(resolve => { release = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/a/messages')) return old;
      if (url.endsWith('/blocks')) return ok({ blocks: [] });
      if (url.endsWith('/b/messages')) return ok({ messages: [msg(2, 'Current answer B')], tasks: [] });
      return ok({ conversation: { id: 'b', title: 'Saved' } });
    }));
    mount(); await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(c => String(c[0]).endsWith('/a/messages'))).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: 'Open B' })); await screen.findByText('Current answer B');
    release(ok({ messages: [msg(1, 'Stale answer A')], tasks: [] }));
    await waitFor(() => expect(screen.queryByText('Stale answer A')).toBeNull());
  });
});

describe('answers given through a component', () => {
  it('are not shown as a message from the person, while the assistant working on them still shows', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/v1/csrf') return ok({ csrf_token: 't' });
      if (url.endsWith('/blocks')) return ok({ blocks: [] });
      if (url.includes('/events?')) return ok({ events: [] });
      if (url.includes('/messages')) return ok({ messages: url.includes('after=') ? [] : [msg(1, 'Which size?', 'agent'), { ...msg(2, '- Size: Large', 'customer'), request_id: 'r', ui_answer: 1 }], tasks: [{ id: 'r', state: 'running', created_epoch: 0 }] });
      return ok({ conversation: { id: 'a', title: 'Saved' } });
    }));
    work.tasks = [summary({ id: 'r', conversation_id: 'a' })];
    mount(); await screen.findByText('Which size?');
    expect(screen.queryByText('- Size: Large')).toBeNull(); expect(screen.queryByText(/Size: Large/)).toBeNull();      // no bubble for the answer
    expect(await screen.findByTestId('thinking-orb')).toBeTruthy();                                                   // but the assistant's work on it is still shown
  });
});

describe('pending assistant reply', () => {
  const thread = (extra: object[] = [], state = 'running') => vi.fn(async (url: string) => {
    if (url === '/v1/csrf') return ok({ csrf_token: 't' });
    if (url.endsWith('/cancel')) return ok({});
    if (url.endsWith('/blocks')) return ok({ blocks: [] });
    if (url.includes('/messages')) return ok({ messages: url.includes('after=') ? [] : [{ ...msg(1, 'hey', 'customer'), request_id: 'r' }, ...extra], tasks: [{ id: 'r', state, created_epoch: 0 }] });
    return ok({ conversation: { id: 'a', title: 'Saved' } });
  });

  it('shows the orb and what the task is doing in the server\'s words, with no card, and keeps Stop in the composer', async () => {
    const fetch = thread(); vi.stubGlobal('fetch', fetch);
    work.tasks = [summary({ id: 'r', conversation_id: 'a', label: 'Searching the web', activity: { key: 'c1', category: 'search', label: 'Searching the web', detail: 'flights to lisbon' }, now: [{ key: 'c1', category: 'search', label: 'Searching the web', detail: 'flights to lisbon' }], controls: { stop: true } as any })];
    const { container } = mount();
    await screen.findByText('Searching the web…');
    expect(screen.getByText('flights to lisbon')).toBeTruthy();
    expect(screen.getByTestId('thinking-orb')).toBeTruthy();
    expect(container.querySelector('.agent-thinking')).toBeTruthy();
    expect(container.querySelector('.taskstrip, .card .agent-thinking')).toBeNull();
    const stop = screen.getByRole('button', { name: 'Stop task' });
    expect(stop.closest('.composer')).toBeTruthy();
    fireEvent.click(stop);
    await waitFor(() => expect(fetch.mock.calls.some(c => String(c[0]).endsWith('/v1/requests/r/cancel'))).toBe(true));
    await waitFor(() => expect(work.refresh).toHaveBeenCalled());
  });

  it('lists everything that is happening at the same time', async () => {
    vi.stubGlobal('fetch', thread());
    const now = [{ key: 'c1', category: 'search', label: 'Searching the web', detail: 'flights' }, { key: 'c2', category: 'read', label: 'Reading a page', detail: 'tap.pt/fares' }];
    work.tasks = [summary({ id: 'r', conversation_id: 'a', label: 'Reading a page', activity: now[1], now })];
    mount();
    const list = await screen.findByRole('list', { name: 'Happening at the same time' });
    expect(list.textContent).toContain('Searching the web'); expect(list.textContent).toContain('tap.pt/fares');
  });

  it('shows a stopping task without a moving orb, and a stopped one in plain words', async () => {
    vi.stubGlobal('fetch', thread());
    work.tasks = [summary({ id: 'r', conversation_id: 'a', phase: 'stopping', label: 'Stopping', tone: 'pending' })];
    const { unmount } = mount();
    await screen.findByText('Stopping…');
    expect(screen.queryByTestId('thinking-orb')).toBeNull();
    expect(screen.getByRole('button', { name: 'Stopping task' })).toHaveProperty('disabled', true);
    unmount();
    work.tasks = [summary({ id: 'r', conversation_id: 'a', state: 'cancelled', phase: 'ended', label: 'Stopped', tone: 'muted', outcome: 'cancelled', verification: 'not_applicable' })];
    mount();
    await screen.findByText('Stopped');
    expect(screen.getByText('Stopped at your request. What was already done is kept.')).toBeTruthy();
    expect(screen.queryByTestId('thinking-orb')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Stop task' })).toBeNull();
  });

  it('says nothing under a plain answer that used no tools, and gives a finished task with tools a record that opens', async () => {
    vi.stubGlobal('fetch', thread([{ ...msg(2, 'Paris.'), request_id: 'r' }], 'completed'));
    work.tasks = [summary({ id: 'r', conversation_id: 'a', state: 'completed', phase: 'ended', label: 'Done', tone: 'ok', outcome: 'completed', verification: 'not_applicable' })];
    const { container, unmount } = mount();
    await screen.findByText('Paris.');
    expect(container.querySelector('.wk-strip')).toBeNull();
    unmount();
    hold(view({ id: 'r', conversation_id: 'a', state: 'completed', phase: 'ended', label: 'Done · not confirmed', tone: 'unsure', outcome: 'completed', verification: 'unverified', note: 'Done, but I couldn\'t confirm it from the page.', steps: 2,
      evidence: { steps: 2, failed_steps: 0, searches: 1, commands: 0, sites: ['tap.pt'], files: [], saved: [], approvals: [], duration_s: 102 } }), [row({ key: 'c1' }), row({ key: 'c2', category: 'read', label: 'Opened a page', detail: 'tap.pt/fares', first: 3, seq: 4 })]);
    mount();
    await screen.findByText('Done · not confirmed');
    expect(screen.getByText('Done, but I couldn\'t confirm it from the page.')).toBeTruthy();                 // finished and confirmed are two different facts
    expect(screen.getByText('2 steps')).toBeTruthy(); expect(screen.getByText('1 site')).toBeTruthy(); expect(screen.getByText('1m 42s')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Details' }));
    expect(await screen.findByText('tap.pt/fares')).toBeTruthy();
    expect(screen.getByText('from Lumina’s own record')).toBeTruthy();
  });

  it('asks for permission in the thread, decides on the approval route, and never sends a message in the customer\'s name', async () => {
    const fetch = thread(); vi.stubGlobal('fetch', fetch);
    fetch.mockImplementation(async (url: string, init: any = {}) => {
      if (url === '/v1/csrf') return ok({ csrf_token: 't' });
      if (url.endsWith('/blocks')) return ok({ blocks: [] });
      if (url.includes('/mcp-approvals/')) return ok({ decided: true, continued: true });
      if (url.includes('/messages')) return ok({ messages: url.includes('after=') ? [] : [{ ...msg(1, 'file the bug', 'customer'), request_id: 'r' }], tasks: [{ id: 'r', state: 'running', created_epoch: 0 }] });
      return ok({ conversation: { id: 'a', title: 'Saved' } });
    });
    const call = { kind: 'approval' as const, id: 'call1', tool: 'create_issue', service: 'Linear', arguments: { title: 'Bug' }, expires_epoch: 9e9 };
    work.tasks = [summary({ id: 'r', conversation_id: 'a', phase: 'needs_you', label: 'Waiting for your permission', tone: 'attention', attention: 'approval', needs: [call] })];
    mount();
    const prompt = await screen.findByRole('group', { name: 'Permission to use Create issue' });
    expect(prompt.textContent).toContain('Linear'); expect(prompt.textContent).toContain('title: Bug');
    expect(screen.queryByTestId('thinking-orb')).toBeNull();                                               // waiting on a person is not shown as working
    fireEvent.click(screen.getByRole('button', { name: 'Allow' }));
    await waitFor(() => expect(work.refresh).toHaveBeenCalled());
    const posts = (fetch.mock.calls as unknown as [string, { method?: string }?][]).filter(c => c[1]?.method === 'POST').map(c => String(c[0]));
    expect(posts).toEqual(['/v1/account/mcp-approvals/call1']);
    expect(posts.some(u => u.endsWith('/send'))).toBe(false);
  });

  it('shows a decision Lumina recorded as a record line, not as a bubble from either side, and a reply being written as a draft', async () => {
    vi.stubGlobal('fetch', thread([{ ...msg(2, 'You allowed create issue on Linear.', 'system'), request_id: 'r' }]));
    hold(view({ id: 'r', conversation_id: 'a' })); work.drafts = { r: { item: 'm:1', text: 'Filing the issue now', done: false, at: 1 } };
    const { container } = mount();
    const line = await screen.findByText('You allowed create issue on Linear.');
    expect(line.className).toBe('chat-record'); expect(line.closest('.bubble')).toBeNull();
    expect(screen.getByText('Filing the issue now').closest('.chat-draft')).toBeTruthy();
    expect(container.querySelectorAll('.wk-strip')).toHaveLength(1);                                       // the strip sits under the newest entry of that request, once
  });
});

describe('runnable app deliveries', () => {
  it('keeps an app visible when the assistant adds a later summary for the same completed request', async () => {
    const app = { version: 1, title: 'Saved calculator', runtime: 'html', code: '<button>Calculate</button>' };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/blocks')) return ok({ blocks: [] });
      if (url.includes('/messages')) return ok({ messages: [
        { ...msg(1, '```lumina-app\n' + JSON.stringify(app) + '\n```'), request_id: 'r' },
        { ...msg(2, 'Your app is ready. ' + 'Use the calculator controls to calculate an expression. '.repeat(5)), request_id: 'r' },
      ], tasks: [{ id: 'r', state: 'completed', created_epoch: 1 }] });
      return ok({ conversation: { id: 'a', title: 'Saved chat' } });
    }));
    mount();
    await screen.findByText(/Your app is ready/);
    expect(screen.getByRole('button', { name: 'Open app' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Show the steps/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Show as chart' })).toBeNull();
  });
});
