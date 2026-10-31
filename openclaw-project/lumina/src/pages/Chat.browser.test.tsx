import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Chat from './Chat';

const data = { app: { user: { email: 'test@example.com' }, limits: { max_message_chars: 16000 }, features: { execution: true } }, chats: [], refreshChats: vi.fn(async () => {}), refresh: vi.fn(async () => {}) };
vi.mock('../state/data', () => ({ useData: () => data }));
vi.mock('../components/Orb', () => ({ default: () => <span data-testid="thinking-orb" /> }));
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
beforeEach(() => {
  sessionStorage.clear(); Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/v1/csrf') return ok({ csrf_token: 't' });
    if (url === '/v1/devices') return ok({ available: true, use: false, connected: false, devices: [] });
    if (url.endsWith('/blocks')) return ok({ blocks: [] });
    if (url.includes('/messages')) return ok({ messages: [{ id: 1, content: 'Hello there', provenance: 'agent', request_id: null, created_at: '' }], tasks: [] });
    return ok({ conversation: { id: 'a', title: 'Saved chat' } });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const at = (path: string) => render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/chat/:id?" element={<Chat />} /></Routes></MemoryRouter>);

describe('the browser icon is on every chat page', () => {
  it('sits in the header of a conversation, before Activity and the chat menu', async () => {
    const { container } = at('/chat/a');
    const icon = await screen.findByRole('button', { name: /^Use my own browser/ });
    const header = container.querySelector('.thread-head')!;
    expect(header.contains(icon)).toBe(true);
    expect(header.querySelector('h1')!.compareDocumentPosition(icon) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelectorAll('.own-browser').length).toBe(1);
  });

  it('sits at the top of a new chat too, which has no header', async () => {
    const { container } = at('/chat');
    const icon = await screen.findByRole('button', { name: /^Use my own browser/ });
    expect(container.querySelector('.thread-head')).toBeNull();
    expect(container.querySelector('.thread-tools')!.contains(icon)).toBe(true);
    expect(container.querySelectorAll('.own-browser').length).toBe(1);
  });
});
