import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import Chat from './Chat';
const data = { app: { user: { email: 'test@example.com' }, limits: { max_message_chars: 16000 }, features: { execution: true } }, chats: [], refreshChats: vi.fn(async () => {}), refresh: vi.fn(async () => {}) };
vi.mock('../state/data', () => ({ useData: () => data }));
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
