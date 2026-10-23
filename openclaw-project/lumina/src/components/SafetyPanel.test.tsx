import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SafetyButton from './SafetyPanel';

const feature = (key: string, on = true) => ({ key, group: 'platform', title: key === 'budget_caps' ? 'Spending caps' : 'Rate limits', plain: 'x', wired: true, on, expires_epoch: null });
const state = (off = false) => ({ groups: [{ key: 'platform', title: 'Lumina platform' }], features: [feature('budget_caps', !off), feature('rate_limits')], off_count: off ? 1 : 0 });
const calls: { url: string; body?: string }[] = [];

beforeEach(() => { calls.length = 0; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const stub = (get: () => { ok: boolean; status: number; json: () => Promise<unknown> }) => vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
  calls.push({ url, body: init?.body as string | undefined });
  if (url === '/v1/csrf') return { ok: true, status: 200, json: async () => ({ csrf_token: 't' }) };
  if (init?.method === 'POST') return { ok: true, status: 200, json: async () => state(true) };
  return get();
}));

describe('SafetyButton', () => {
  it('is hidden when the server says 404 or answers without a feature list', async () => {
    stub(() => ({ ok: false, status: 404, json: async () => ({ error: 'unavailable' }) }));
    const { container } = render(<SafetyButton />);
    await waitFor(() => expect(calls.some(c => c.url === '/v1/safety')).toBe(true));
    expect(container.querySelector('.safety-btn')).toBeNull();
  });

  it('opens a popup with a switch per feature and sends only the changed ones with the password', async () => {
    stub(() => ({ ok: true, status: 200, json: async () => state() }));
    render(<SafetyButton />);
    fireEvent.click(await screen.findByText('Safety'));
    const caps = screen.getByRole('switch', { name: 'Spending caps' }) as HTMLInputElement;
    expect(caps.checked).toBe(true);
    const apply = screen.getByRole('button', { name: /Apply/ }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.click(caps);
    fireEvent.change(screen.getByLabelText('Your password'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: /Apply 1 change/ }));
    await waitFor(() => expect(calls.find(c => c.url === '/v1/safety/change')).toBeTruthy());
    expect(JSON.parse(calls.find(c => c.url === '/v1/safety/change')!.body!)).toEqual({ password: 'pw', changes: { budget_caps: false } });
  });
});
