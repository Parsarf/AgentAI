import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import Chat from './Chat';
const data = { app: { user: { email: 'test@example.com' }, limits: { max_message_chars: 16000 }, features: { execution: true } }, chats: [], refreshChats: vi.fn(async () => {}), refresh: vi.fn(async () => {}) };
vi.mock('../state/data', () => ({ useData: () => data }));
vi.mock('../components/Orb', () => ({ default: () => <span data-testid="thinking-orb" /> }));
vi.mock('../components/SceneBackground', () => ({ default: () => null }));   // the film has its own tests; these count fetches
const Switch = () => { const nav = useNavigate(); return <><button onClick={() => nav('/chat/a')}>Open A</button><button onClick={() => nav('/chat/b')}>Open B</button><Chat /></>; };
const msg = (id: number, content: string, provenance = 'agent') => ({ id, content, provenance, request_id: null, created_at: '' });
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
beforeEach(() => { sessionStorage.clear(); Element.prototype.scrollIntoView = vi.fn(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const mount = () => render(<MemoryRouter initialEntries={['/chat/a']}><Routes><Route path="/chat/:id" element={<Switch />} /></Routes></MemoryRouter>);
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

describe('pending assistant reply', () => {
  it('shows the orb on the assistant side and keeps Stop in the header', async () => {
    let cancelled = false;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/v1/csrf') return ok({ csrf_token: 't' });
      if (url.endsWith('/cancel')) { cancelled = true; return ok({}); }
      if (url.endsWith('/blocks')) return ok({ blocks: [] });
      if (url.includes('/events?')) return ok({ events: [{ sequence: 1, kind: 'activity', payload: { ref: 'tool', category: 'search', status: 'running' } }] });
      if (url.includes('/messages')) return ok({ messages: url.includes('after=') ? [] : [{ ...msg(1, 'hey', 'customer'), request_id: 'r' }], tasks: [{ id: 'r', state: cancelled ? 'cancelled' : 'running', created_epoch: 0 }] });
      return ok({ conversation: { id: 'a', title: 'Saved' } });
    }));
    const { container } = mount();
    await screen.findByText('Searching…');
    expect(container.querySelector('.agent-thinking')).toBeTruthy();
    expect(container.querySelector('.taskstrip')).toBeNull();
    const stop = screen.getByRole('button', { name: /^Stop$/ });
    expect(stop.closest('.thread-head')).toBeTruthy();
    fireEvent.click(stop);
    await screen.findByText('Stopped.');
    expect(screen.queryByTestId('thinking-orb')).toBeNull();
  });
});

describe('a card arriving while you watch', () => {
  it('is shown once at every stage: from the reply while it streams, then the stored card with pictures, then the final text', async () => {
    const ID = 'ab'.repeat(16);
    const spec = (withPicture: boolean) => ({ schemaVersion: '1.0', type: 'places', title: 'Spicy places', items: [{ name: 'Haidilao', link: 'https://haidilao.example/', tags: [], ...(withPicture ? { image: { id: ID, source: 'haidilao.example' } } : {}) }] });
    const live = 'Here you go.\n\n```lumina\n' + JSON.stringify(spec(false)) + '\n```';
    let messageCalls = 0; let stored = false; let finished = false;
    const task = () => ({ id: 'r1', state: finished ? 'completed' : 'running', created_epoch: 1 });
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/v1/conversations/a') return ok({ conversation: { id: 'a', title: 'Spicy' } });
      if (url.endsWith('/blocks')) return ok({ blocks: stored ? [{ id: 'b1', conversation_id: 'a', anchor_message_id: 2, kind: 'places', schema_version: '1.0', spec: spec(true), state: {}, version: 1, status: 'final', launched_request_id: null, created_epoch: 1, updated_epoch: 1 }] : [] });
      if (url.includes('/messages')) {
        messageCalls += 1;
        const after = Number(new URL(url, 'http://x').searchParams.get('after') ?? 0);
        const now = finished                                                                                 // what the server holds: the cleaned reply and a closing line once it finished
          ? [{ ...msg(1, 'spicy food near me', 'customer'), request_id: 'r1' }, { ...msg(2, 'Here you go.'), request_id: 'r1' }, { ...msg(3, 'Checked: the places are real.'), request_id: 'r1' }]
          : [{ ...msg(1, 'spicy food near me', 'customer'), request_id: 'r1' }, { ...msg(2, live), request_id: 'r1' }];
        return ok({ messages: now.filter(m => m.id > after), tasks: [task()] });
      }
      return ok({});
    }));
    mount();
    await screen.findByRole('heading', { name: 'Spicy places' });
    expect(screen.getAllByRole('heading', { name: 'Spicy places' }).length).toBe(1);                       // streaming: drawn from the reply's own text
    stored = true;                                                                                           // the server stored the card (with its picture) but the task is still running
    await waitFor(() => expect(screen.getByAltText('Haidilao')).toBeTruthy(), { timeout: 6000 });
    expect(screen.getAllByRole('heading', { name: 'Spicy places' }).length).toBe(1);                       // the stored card replaced it: never both
    finished = true;
    await screen.findByText('Checked: the places are real.', {}, { timeout: 6000 });
    expect(screen.getAllByRole('heading', { name: 'Spicy places' }).length).toBe(1);
    expect(screen.getByAltText('Haidilao')).toBeTruthy();
    expect(messageCalls).toBeGreaterThanOrEqual(3);
  }, 15000);
});
