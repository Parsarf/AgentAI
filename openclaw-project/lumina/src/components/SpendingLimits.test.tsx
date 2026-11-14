import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SpendingLimits, { validAmount } from './SpendingLimits';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const none = { limits: { task_microusd: null, daily_microusd: null, period_microusd: null }, chosen: false };

describe('SpendingLimits', () => {
  it('accepts an empty field or a dollar amount and nothing else', () => {
    for (const ok of ['', ' ', '5', '2.50', '$10', '0.5']) expect(validAmount(ok)).toBe(true);
    for (const bad of ['0', '-1', 'abc', '1.234', '1e3', '5 dollars']) expect(validAmount(bad)).toBe(false);
  });

  it('shows no limit by default and says Lumina sets none', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply(none)));
    render(<SpendingLimits />);
    expect(await screen.findByText('No limit')).toBeTruthy();
    expect(screen.getByText(/Lumina does not limit what you spend/)).toBeTruthy();
    for (const input of screen.getAllByPlaceholderText('No limit')) expect((input as HTMLInputElement).value).toBe('');
  });

  it('saves the amounts the customer typed, as text, and shows what the server stored', async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url === '/v1/csrf') return reply({ csrf_token: 't' });
      if (init?.method === 'POST') return reply({ limits: { task_microusd: 2_500_000, daily_microusd: null, period_microusd: 40_000_000 }, chosen: true });
      return reply(none);
    }));
    render(<SpendingLimits />);
    const [task, , period] = await screen.findAllByPlaceholderText('No limit');
    fireEvent.change(task, { target: { value: '2.5' } }); fireEvent.change(period, { target: { value: '40' } });
    fireEvent.click(screen.getByText('Save limits'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Saved'));
    const post = calls.find(c => c.init?.method === 'POST')!;
    expect(post.url).toBe('/v1/spending-limits');
    expect(JSON.parse(String(post.init!.body))).toEqual({ task: '2.5', daily: '', period: '40' });
    expect((task as HTMLInputElement).value).toBe('2.50'); expect((period as HTMLInputElement).value).toBe('40');
    expect(screen.getByText('Your limits')).toBeTruthy();
  });

  it('does not send an amount that is not a dollar figure', async () => {
    const fetchMock = vi.fn(() => reply(none));
    vi.stubGlobal('fetch', fetchMock);
    render(<SpendingLimits />);
    const [task] = await screen.findAllByPlaceholderText('No limit');
    fireEvent.change(task, { target: { value: 'lots' } });
    expect(screen.getByRole('alert').textContent).toContain('dollar amounts');
    expect((screen.getByText('Save limits') as HTMLButtonElement).disabled).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('stays hidden when the server does not offer limits', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply({ error: 'unavailable' }, 404)));
    const { container } = render(<SpendingLimits />);
    await waitFor(() => expect(container.textContent).toBe(''));
  });
});
