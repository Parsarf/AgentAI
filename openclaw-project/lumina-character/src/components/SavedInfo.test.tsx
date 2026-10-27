import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SavedInfo from './SavedInfo';

const calls: [string, string, unknown][] = [];
let vault: unknown;
vi.mock('../lib/api', () => ({
  ApiError: class extends Error { status = 0; },
  api: vi.fn(async (method: string, path: string, body?: unknown) => {
    calls.push([method, path, body]);
    if (path === '/v1/vault' && method === 'GET') return vault;
    if (path === '/v1/saved') return { saved: [{ field: 'size', value: 'M' }] };
    return { ok: true };
  }),
}));

beforeEach(() => { calls.length = 0; vault = { enabled: true, items: [{ id: 'i1', kind: 'card', label: 'Visa ending 4242', site: '', hint: 'Visa ending 4242' }] }; });

describe('saved info', () => {
  it('lists what is kept and lets each item be removed', async () => {
    render(<SavedInfo />);
    expect(await screen.findByText('Visa ending 4242')).toBeTruthy(); expect(screen.getByText('size: M')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Delete Visa ending 4242'));
    await waitFor(() => expect(calls.some(c => c[1] === '/v1/vault/i1/delete')).toBe(true));
    fireEvent.click(screen.getByLabelText('Forget size'));
    await waitFor(() => expect(calls.some(c => c[1] === '/v1/saved/size/forget')).toBe(true));
  });

  it('shows the notice and saves nothing until it is ticked, and never asks for the security code', async () => {
    render(<SavedInfo />);
    fireEvent.click(await screen.findByText('Add a card'));
    expect(screen.queryByLabelText(/security code|cvv/i)).toBeNull();
    fireEvent.change(screen.getByLabelText('Card number'), { target: { value: '4242 4242 4242 4242' } });
    fireEvent.change(screen.getByLabelText('Expiry month'), { target: { value: '12' } }); fireEvent.change(screen.getByLabelText('Expiry year'), { target: { value: '2030' } });
    fireEvent.click(screen.getByText('Continue'));
    expect(screen.getByRole('dialog')).toBeTruthy(); expect(screen.getByText(/never saved/)).toBeTruthy();
    const save = screen.getByText('Save') as HTMLButtonElement; expect(save.disabled).toBe(true);
    expect(calls.some(c => c[1] === '/v1/vault/add')).toBe(false);
    fireEvent.click(screen.getByLabelText(/I understand/)); fireEvent.click(save);
    await waitFor(() => expect(calls.some(c => c[1] === '/v1/vault/add')).toBe(true));
    const body = calls.find(c => c[1] === '/v1/vault/add')![2] as { accepted: boolean; secret: { number: string } };
    expect(body.accepted).toBe(true); expect(body.secret.number).toBe('4242424242424242');
  });

  it('says so when saving is not switched on', async () => {
    vault = { enabled: false, items: [] };
    render(<SavedInfo />);
    expect(await screen.findByText(/not switched on yet/)).toBeTruthy(); expect(screen.queryByText('Add a card')).toBeNull();
  });
});
