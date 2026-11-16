import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Dock, { type Looking } from './Dock';

vi.mock('../../state/data', () => ({ useData: () => ({ app: { features: {} } }) }));
beforeEach(() => { window.localStorage.clear(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const calls: { method: string; url: string; body?: any }[] = [];
let messages: any[] = []; let tasks: any[] = []; let overlap = false;
function server(over: Record<string, () => Promise<Response>> = {}) {
  calls.length = 0; messages = []; tasks = []; overlap = false;
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url === '/v1/csrf') return reply({ csrf_token: 't' });
    const method = init?.method ?? 'GET'; const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    if (over[`${method} ${url}`]) return over[`${method} ${url}`]();
    if (method === 'POST' && url === '/v1/conversations') return reply({ conversation: { id: 'chat1' } }, 201);
    if (method === 'POST' && url === '/v1/hub/ask') {
      messages = [...messages, { id: messages.length + 1, request_id: 'r1', provenance: 'customer', content: body.message, created_at: '' }]; tasks = [{ id: 'r1', state: 'running', created_epoch: 1 }];
      return reply({ request: { id: 'r1' }, looking_at: body.looking_at ?? null }, 202);
    }
    const match = url.match(/^\/v1\/conversations\/(\w+)\/messages(?:\?after=(\d+))?$/);
    if (match) return match[1] === 'gone' ? reply({ error: 'not_found' }, 404) : reply({ messages: overlap ? messages : messages.filter(m => m.id > Number(match[2] ?? 0)), tasks });
    return reply({}, 404);
  }));
}
const thread: Looking = { kind: 'thread', connection: 'c1', thread: 't:1/a' };
const show = (looking: Looking | null = thread) => render(<MemoryRouter><Dock looking={looking} lookingWords="the thread “Quarterly numbers”" suggestions={[{ label: 'Summarize', message: 'Summarize this thread.' }]} /></MemoryRouter>);

describe('the assistant dock', () => {
  it('sends a message with what is open as ids, in an ordinary chat that opens in Chat', async () => {
    server(); show();
    expect(screen.getByText('Looking at: the thread “Quarterly numbers”')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Message to your assistant'), { target: { value: 'what is this about?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('what is this about?')).toBeTruthy();
    const asked = calls.find(c => c.url === '/v1/hub/ask')!;
    expect(asked.body).toMatchObject({ conversation_id: 'chat1', message: 'what is this about?', looking_at: { kind: 'thread', connection: 'c1', thread: 't:1/a' } });
    expect(asked.body.key).toMatch(/^[a-f0-9]{32}$/);
    expect(Object.keys(asked.body.looking_at).sort()).toEqual(['connection', 'kind', 'thread']);          // ids only: never the subject or the text of what is open
    expect(calls.findIndex(c => c.url === '/v1/conversations' && c.method === 'POST')).toBeLessThan(calls.findIndex(c => c.url === '/v1/hub/ask'));
    expect(screen.getByRole('status').textContent).toBe('Working…');
    expect(screen.getByRole('link', { name: 'Open in Chat' }).getAttribute('href')).toBe('/chat/chat1');
    expect(window.localStorage.getItem('lumina.hub.chat')).toBe('chat1');
  });

  it('shows the answer when it arrives, and one tap sends a suggestion', async () => {
    server(); show();
    fireEvent.click(screen.getByRole('button', { name: 'Summarize' }));
    await screen.findByText('Summarize this thread.');
    messages = [...messages, { id: 2, request_id: 'r1', provenance: 'agent', content: 'It is about the **Q3 numbers**.', created_at: '' }]; tasks = [{ id: 'r1', state: 'completed', created_epoch: 1 }];
    expect(await screen.findByText('Q3 numbers', {}, { timeout: 4000 })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull(), { timeout: 4000 });
    expect(calls.filter(c => c.url === '/v1/conversations' && c.method === 'POST').length).toBe(1);
  });

  it('shows each message once, even when two loads overlap', async () => {
    server(); overlap = true; show();                                                              // every read answers with the whole chat, as overlapping reads would
    fireEvent.click(screen.getByRole('button', { name: 'Summarize' }));
    await screen.findByText('Summarize this thread.');
    messages = [...messages, { id: 2, request_id: 'r1', provenance: 'agent', content: 'One answer.', created_at: '' }];
    await screen.findByText('One answer.', {}, { timeout: 4000 });
    await new Promise(r => setTimeout(r, 2700));                                                  // another poll comes round
    expect(screen.getAllByText('Summarize this thread.').length).toBe(1); expect(screen.getAllByText('One answer.').length).toBe(1);
  }, 12000);

  it('carries on the same chat on a later visit, and starts a new one when asked or when that chat is gone', async () => {
    window.localStorage.setItem('lumina.hub.chat', 'chat7'); server();
    messages = [{ id: 1, request_id: 'r0', provenance: 'customer', content: 'earlier question', created_at: '' }, { id: 2, request_id: 'r0', provenance: 'agent', content: 'earlier answer', created_at: '' }];
    show();
    expect(await screen.findByText('earlier answer')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    await waitFor(() => expect(screen.queryByText('earlier answer')).toBeNull());
    expect(window.localStorage.getItem('lumina.hub.chat')).toBeNull();
    cleanup();
    window.localStorage.setItem('lumina.hub.chat', 'gone'); server(); show();
    await waitFor(() => expect(window.localStorage.getItem('lumina.hub.chat')).toBeNull());
    expect(screen.getByText(/Ask about your mail and calendar/)).toBeTruthy();
  });

  it('says plainly when the assistant cannot take the message, and keeps what was typed', async () => {
    server({ 'POST /v1/hub/ask': () => reply({ error: 'budget_denied' }, 402) }); show();
    fireEvent.change(screen.getByLabelText('Message to your assistant'), { target: { value: 'hello' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText(/Your allowance does not cover this right now/)).toBeTruthy();
    expect((screen.getByLabelText('Message to your assistant') as HTMLTextAreaElement).value).toBe('hello');
  });

  it('can be closed to a small tab and remembers that', async () => {
    server(); show();
    fireEvent.click(screen.getByRole('button', { name: 'Close the assistant' }));
    expect(screen.queryByLabelText('Message to your assistant')).toBeNull();
    expect(window.localStorage.getItem('lumina.hub.dock')).toBe('closed');
    cleanup(); show();
    fireEvent.click(screen.getByRole('button', { name: 'Open the assistant' }));
    expect(screen.getByLabelText('Message to your assistant')).toBeTruthy();
    expect(calls.length).toBe(0);                                                                // a closed or idle dock asks the server nothing
  });
});
