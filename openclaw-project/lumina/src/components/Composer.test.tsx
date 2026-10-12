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
    if (url === '/v1/conversations' && method === 'GET') return ok({ conversations: [{ id: 'c1' }] });
    if (url.endsWith('/send')) return ok(sendBody, sendStatus);
    return ok({}, 404);
  }));
  return calls;
}
const setup = () => render(<DataProvider><Composer /></DataProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Composer', () => {
  it('sends the message to the latest conversation with a CSRF token and a unique key, then clears', async () => {
    const calls = mockFetch(); setup();
    const box = await screen.findByLabelText(/ask anything/i);
    fireEvent.change(box, { target: { value: 'What is 17 times 3?' } });
    fireEvent.click(screen.getByRole('button', { name: /send task/i }));
    await waitFor(() => expect(calls.some(c => c.url === '/v1/conversations/c1/send')).toBe(true));
    const send = calls.find(c => c.url.endsWith('/send'))!;
    expect(send.method).toBe('POST'); expect(send.csrf).toBe('tok'); expect(send.body.message).toBe('What is 17 times 3?'); expect(send.body.key).toMatch(/^[0-9a-f]{32}$/);
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe(''));
  });
  it('turns a budget refusal into a plain sentence and keeps the text', async () => {
    mockFetch(402, { error: 'budget_denied' }); setup();
    const box = await screen.findByLabelText(/ask anything/i) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'expensive' } });
    fireEvent.click(screen.getByRole('button', { name: /send task/i }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/allowance cannot fund/i);
    expect(box.value).toBe('expensive');
  });
  it('does not send empty input and prefills a template from a chip', async () => {
    const calls = mockFetch(); setup();
    const box = await screen.findByLabelText(/ask anything/i) as HTMLTextAreaElement;
    expect((screen.getByRole('button', { name: /send task/i }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Web' }));
    expect(box.value).toMatch(/^Search the web/);
    expect(calls.filter(c => c.url.endsWith('/send'))).toHaveLength(0);
  });
  it('explains that attachments are not enabled instead of silently dropping them', async () => {
    mockFetch(); setup();
    const box = await screen.findByLabelText(/ask anything/i);
    fireEvent.paste(box, { clipboardData: { files: [new File(['x'], 'a.png')], getData: () => '' } });
    expect((await screen.findByRole('alert')).textContent).toMatch(/not enabled yet/i);
    expect((screen.getByRole('button', { name: /use files/i }) as HTMLButtonElement).disabled).toBe(true);
  });
});
