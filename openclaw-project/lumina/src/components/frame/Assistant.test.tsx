import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FrameProvider, useFrame } from './FrameProvider';
import { AssistantProvider, AssistantZone, useSelection, type Selection } from './Assistant';
import Workspace from './Workspace';
import { resetWork, summary, work } from '../../test/workMock';

// The shared assistant panel (UI remodel phase 2). It replaces the old mail and calendar dock (components/hub/Dock.tsx); these cover what that dock's tests covered,
// and what is new: any page, any selection, one-step changes to a draft, background work, stop.
vi.mock('../../state/work', async () => (await import('../../test/workMock')).mock);
vi.mock('../../state/data', () => ({ useData: () => ({ app: { features: {} } }) }));

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const calls: { method: string; url: string; body?: any }[] = [];
let messages: any[] = []; let tasks: any[] = []; let refuse = 0; let answer = false;
function server() {
  calls.length = 0; messages = []; tasks = []; refuse = 0; answer = false;
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url === '/v1/csrf') return reply({ csrf_token: 't' });
    const method = init?.method ?? 'GET'; const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    if (method === 'POST' && url === '/v1/conversations') return reply({ conversation: { id: 'chat1' } }, 201);
    if (method === 'POST' && url === '/v1/assistant/ask') {
      if (refuse) return reply({ error: 'request_conflict' }, refuse);
      const id = `r${asked().length}`;
      messages = [...messages, { id: messages.length + 1, request_id: id, provenance: 'customer', content: body.message, created_at: '' }]; tasks = [{ id, state: answer ? 'completed' : 'running', created_epoch: 1 }];
      if (answer) messages = [...messages, { id: messages.length + 1, request_id: id, provenance: 'agent', content: `Answer to: ${body.message}`, created_at: '' }];
      return reply({ request: { id }, looking_at: body.looking_at ?? null }, 202);
    }
    if (method === 'POST' && url.endsWith('/cancel')) return reply({}, 202);
    const match = url.match(/^\/v1\/conversations\/(\w+)\/messages(?:\?after=(\d+))?$/);
    if (match) return match[1] === 'gone' ? reply({ error: 'not_found' }, 404) : reply({ messages: messages.filter(m => m.id > Number(match[2] ?? 0)), tasks });
    return reply({}, 404);
  }));
}
const asked = () => calls.filter(c => c.url === '/v1/assistant/ask');

function Page({ selection }: { selection: Selection | null }) { useSelection(selection); return <Workspace title="Files"><p>page</p></Workspace>; }
function Opener() { const f = useFrame()!; return <button onClick={() => f.reveal('assistant')}>Open assistant</button>; }
const file: Selection = { looking: { kind: 'file', source: 'upload', id: 'u1' }, words: 'the file “Budget.xlsx”', actions: [{ label: 'Summarize', message: 'Summarize this file.' }, { label: 'Draft a note', message: 'Draft a note about it.', draft: true }] };
const mount = (selection: Selection | null = file) => render(<MemoryRouter><FrameProvider person="a@example.com"><AssistantProvider><Opener /><Page selection={selection} /><AssistantZone /></AssistantProvider></FrameProvider></MemoryRouter>);
const panel = () => within(screen.getByRole('complementary', { name: 'Assistant' }));

beforeEach(() => { localStorage.clear(); resetWork(); server(); Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1600 }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('the assistant panel', () => {
  it('asks the server nothing while it is closed', async () => {
    localStorage.setItem('lumina.hub.chat', 'chat1');
    mount();
    await act(async () => { await new Promise(r => setTimeout(r, 20)); });
    expect(calls).toEqual([]);
    expect(screen.queryByRole('complementary', { name: 'Assistant' })).toBeNull();
  });

  it('says in words what is selected, and its first message carries the selection as ids, in an ordinary chat that opens in Chat', async () => {
    mount(); fireEvent.click(screen.getByRole('button', { name: 'Open assistant' }));
    expect(panel().getByText('Looking at: the file “Budget.xlsx”')).toBeTruthy();
    fireEvent.change(panel().getByLabelText('Message to your assistant'), { target: { value: 'What is in it?' } });
    fireEvent.click(panel().getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(asked()).toHaveLength(1));
    expect(asked()[0].body).toMatchObject({ conversation_id: 'chat1', message: 'What is in it?', looking_at: { kind: 'file', source: 'upload', id: 'u1' } });
    expect(await panel().findByText('What is in it?')).toBeTruthy();
    expect(panel().getByRole('link', { name: 'Open in Chat' }).getAttribute('href')).toBe('/chat/chat1');
  });

  it('offers the page\'s one-tap actions, and after a draft, one-step changes to it that each go as a single message', async () => {
    answer = true;                                                   // this server answers at once, and the task is over
    work.tasks = ['r1', 'r2'].map(id => summary({ id, conversation_id: 'chat1', phase: 'ended', state: 'completed' }));
    mount(); fireEvent.click(screen.getByRole('button', { name: 'Open assistant' }));
    expect(panel().getByRole('group', { name: 'Suggested for what is selected' })).toBeTruthy();
    fireEvent.click(panel().getByRole('button', { name: 'Draft a note' }));
    expect(await panel().findByText('Answer to: Draft a note about it.')).toBeTruthy();
    const changes = within(await panel().findByRole('group', { name: 'Change the draft' }));
    expect(changes.getAllByRole('button').map(b => b.textContent)).toEqual(['Shorter', 'Longer', 'More formal', 'Simpler']);
    fireEvent.click(changes.getByRole('button', { name: 'Shorter' }));
    await waitFor(() => expect(asked()).toHaveLength(2));
    expect(asked()[1].body.message).toBe('Make that draft shorter. Keep what matters.');
    expect(await panel().findByRole('group', { name: 'Change the draft' })).toBeTruthy();       // still a draft: the changes stay on offer
  });

  it('offers no draft changes after an ordinary answer', async () => {
    answer = true; work.tasks = [summary({ id: 'r1', conversation_id: 'chat1', phase: 'ended', state: 'completed' })];
    mount(); fireEvent.click(screen.getByRole('button', { name: 'Open assistant' }));
    fireEvent.click(panel().getByRole('button', { name: 'Summarize' }));
    expect(await panel().findByText('Answer to: Summarize this file.')).toBeTruthy();
    expect(panel().queryByRole('group', { name: 'Change the draft' })).toBeNull();
  });

  it('puts Stop where Send is while its task runs, and offers the background for a long one', async () => {
    localStorage.setItem('lumina.hub.chat', 'chat1');
    messages = [{ id: 1, request_id: 'r9', provenance: 'customer', content: 'Compare the files', created_at: '' }]; tasks = [{ id: 'r9', state: 'running', created_epoch: 1 }];
    work.tasks = [summary({ id: 'r9', conversation_id: 'chat1', created_epoch: Math.floor(Date.now() / 1000) - 90, controls: { stop: true } as any })];
    mount(); fireEvent.click(screen.getByRole('button', { name: 'Open assistant' }));
    fireEvent.click(await panel().findByRole('button', { name: 'Stop' }));
    await waitFor(() => expect(calls.some(c => c.url === '/v1/requests/r9/cancel')).toBe(true));
    fireEvent.click(panel().getByRole('button', { name: 'Keep it going in the background' }));
    expect(screen.queryByRole('complementary', { name: 'Assistant' })).toBeNull();
  });

  it('says plainly when the message could not be taken, and keeps what was typed', async () => {
    mount(); fireEvent.click(screen.getByRole('button', { name: 'Open assistant' }));
    refuse = 409;
    fireEvent.change(panel().getByLabelText('Message to your assistant'), { target: { value: 'Hello' } });
    fireEvent.click(panel().getByRole('button', { name: 'Send' }));
    expect(await panel().findByText('Your assistant is still busy with something else. Try again in a moment.')).toBeTruthy();
    expect((panel().getByLabelText('Message to your assistant') as HTMLTextAreaElement).value).toBe('Hello');
  });

  it('starts a new chat when asked, and when its chat is gone', async () => {
    localStorage.setItem('lumina.hub.chat', 'gone');
    mount(); fireEvent.click(screen.getByRole('button', { name: 'Open assistant' }));
    await waitFor(() => expect(localStorage.getItem('lumina.hub.chat')).toBeNull());
    expect(panel().queryByRole('link', { name: 'Open in Chat' })).toBeNull();
  });

  it('opens as a sheet where it has no room, and says when nothing is selected', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
    mount(null); fireEvent.click(screen.getByRole('button', { name: 'Open assistant' }));
    const sheet = within(screen.getByRole('dialog', { name: 'Assistant' }));
    expect(sheet.getByText('Nothing selected on this page.')).toBeTruthy();
  });
});
