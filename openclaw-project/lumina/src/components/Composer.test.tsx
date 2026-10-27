import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Composer from './Composer';
import { DataProvider } from '../state/data';

const app = { api_version: 't', user: { email: 'a@b.co', role: 'customer' }, assistant: { state: 'ready' },
  features: { chat: true, execution: true, files: false, uploads: false, telegram: false, connectors: false, billing_mode: 'open', requests: true, usage: true }, limits: { max_message_chars: 100 } };

function mockFetch(sendStatus = 202, sendBody: any = { request: {} }) {
  const calls: { url: string; method: string; body?: any; csrf?: string }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: any = {}) => {
    const method = init.method || 'GET';
    calls.push({ url, method, body: init.body ? JSON.parse(init.body) : undefined, csrf: init.headers?.['X-CSRFToken'] });
    const ok = (b: any, status = 200) => ({ ok: status < 400, status, json: async () => b });
    if (url === '/v1/csrf') return ok({ csrf_token: 'tok' });
    if (url === '/v1/app') return ok(app);
    if (url === '/v1/requests') return ok({ requests: [] });
    if (url === '/readyz') return ok({});
    if (url === '/v1/conversations' && method === 'POST') return ok({ conversation: { id: 'c1' } }, 201);
    if (url.endsWith('/send')) return ok(sendBody, sendStatus);
    return ok({}, 404);
  }));
  return calls;
}
const setup = (props: any = {}) => render(<DataProvider><Composer {...props} /></DataProvider>);
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); });

describe('Composer', () => {
  it('starts a new chat for the first message, sends with a CSRF token and a unique key, reports the chat id, then clears', async () => {
    const calls = mockFetch(); const sent = vi.fn(); setup({ onSent: sent });
    const box = await screen.findByLabelText(/message lumina/i);
    fireEvent.change(box, { target: { value: 'What is 17 times 3?' } });
    fireEvent.click(screen.getByRole('button', { name: /send message/i }));
    await waitFor(() => expect(calls.some(c => c.url === '/v1/conversations/c1/send')).toBe(true));
    const send = calls.find(c => c.url.endsWith('/send'))!;
    expect(send.method).toBe('POST'); expect(send.csrf).toBe('tok'); expect(send.body.message).toBe('What is 17 times 3?'); expect(send.body.key).toMatch(/^[0-9a-f]{32}$/);
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe(''));
    expect(calls.findIndex(c => c.url === '/v1/conversations' && c.body !== undefined)).toBeLessThan(calls.findIndex(c => c.url.endsWith('/send')));   // chat created first
    expect(sent.mock.calls[0][0].conversation_id).toBe('c1');
  });
  it('reuses the created chat and idempotency key when retrying a failed send', async () => {
    const calls = mockFetch(500, { error: 'temporary' }); setup();
    const box = await screen.findByLabelText(/message lumina/i);
    fireEvent.change(box, { target: { value: 'Retry this' } });
    fireEvent.click(screen.getByRole('button', { name: /send message/i })); await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: /send message/i }));
    await waitFor(() => expect(calls.filter(c => c.url.endsWith('/send')).length).toBe(2));
    expect(calls.filter(c => c.url === '/v1/conversations' && c.method === 'POST')).toHaveLength(1);
    const sends = calls.filter(c => c.url.endsWith('/send'));
    expect(sends[0].body.key).toBe(sends[1].body.key);
  });
  it('keeps working until complete only when the customer switches it on, and says so to the server once', async () => {
    const calls = mockFetch(); setup({ conversationId: 'c9' });
    const box = await screen.findByLabelText(/message lumina/i);
    fireEvent.change(box, { target: { value: 'normal question' } });
    fireEvent.click(screen.getByRole('button', { name: /send message/i }));
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/send'))).toBe(true));
    expect(calls.find(c => c.url.endsWith('/send'))!.body.goal).toBeUndefined();                                // off by default
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe(''));
    const toggle = screen.getByRole('button', { name: /keep working until complete/i });
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(toggle); expect(toggle.getAttribute('aria-pressed')).toBe('true');
    fireEvent.change(box, { target: { value: 'finish the report' } });
    fireEvent.click(screen.getByRole('button', { name: /send message/i }));
    await waitFor(() => expect(calls.filter(c => c.url.endsWith('/send')).length).toBe(2));
    expect(calls.filter(c => c.url.endsWith('/send'))[1].body.goal).toBe('true');
    await waitFor(() => expect(screen.getByRole('button', { name: /keep working until complete/i }).getAttribute('aria-pressed')).toBe('false'));   // one goal per switch-on, not a mode that sticks
  });
  it('follows up inside an existing chat without creating a new one', async () => {
    const calls = mockFetch(); setup({ conversationId: 'c9' });
    const box = await screen.findByLabelText(/message lumina/i); expect((box as HTMLTextAreaElement).placeholder).toMatch(/follow-up/i);
    fireEvent.change(box, { target: { value: 'and what about 18?' } });
    fireEvent.click(screen.getByRole('button', { name: /send message/i }));
    await waitFor(() => expect(calls.some(c => c.url === '/v1/conversations/c9/send')).toBe(true));
    expect(calls.some(c => c.url === '/v1/conversations' && c.body !== undefined)).toBe(false);   // no chat was created (listing chats is fine)
  });
  it('turns a budget refusal into a plain sentence and keeps the text', async () => {
    mockFetch(402, { error: 'budget_denied' }); setup();
    const box = await screen.findByLabelText(/message lumina/i) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'expensive' } });
    fireEvent.click(screen.getByRole('button', { name: /send message/i }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/allowance cannot fund/i);
    expect(box.value).toBe('expensive');
  });
  it('does not send empty input and prefills a template from a chip', async () => {
    const calls = mockFetch(); setup();
    const box = await screen.findByLabelText(/message lumina/i) as HTMLTextAreaElement;
    expect((screen.getByRole('button', { name: /send message/i }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Tools' })); fireEvent.click(screen.getByRole('menuitemradio', { name: /web search/i }));
    expect(box.value).toMatch(/^Search the web/);
    expect(calls.filter(c => c.url.endsWith('/send'))).toHaveLength(0);
  });
  it('explains that attachments are not enabled instead of silently dropping them', async () => {
    mockFetch(); setup();
    const box = await screen.findByLabelText(/message lumina/i);
    fireEvent.paste(box, { clipboardData: { files: [new File(['x'], 'a.png')], getData: () => '' } });
    expect((await screen.findByRole('alert')).textContent).toMatch(/not enabled yet/i);
    expect((screen.getByRole('button', { name: /use files/i }) as HTMLButtonElement).disabled).toBe(true);
  });
});
