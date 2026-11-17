import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Knowledge, { type Commitment, type Source } from './Knowledge';

let features: Record<string, boolean> = { knowledge: true, commitments: true };
vi.mock('../state/data', () => ({ useData: () => ({ app: { features } }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); features = { knowledge: true, commitments: true }; });

const source = (over: Partial<Source> = {}): Source => ({ id: 's1', kind: 'upload', name: 'contract.pdf', media_type: 'application/pdf', size_bytes: 2048, state: 'ready', step: null, error: null,
  pages: 4, passages: 12, tables: 1, charts: 0, read_by_model: 0, low_confidence: false, unread_pages: 0, parser: 'p', scope: 'account', origin: null, added_epoch: 1, updated_epoch: 1,
  indexed_epoch: 1, own: true, ...over });
const item = (over: Partial<Commitment> = {}): Commitment => ({ id: 'c1', kind: 'commitment', what: 'Send the signed copy', owner: 'Ana', due_epoch: null, due_zone: 'UTC', due_has_time: false,
  source_kind: 'mail', origin: 'outside', state: 'open', suggested: false, source: null, ...over });
const reply = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
const calls: { method: string; url: string; body?: unknown }[] = [];
function server(sources: Source[], items: Commitment[]) {
  calls.length = 0;
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url === '/v1/csrf') return reply({ csrf_token: 't' });
    const method = init?.method ?? 'GET'; calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url === '/v1/knowledge') return reply({ available: true, sources, shared_with_me: [], groups: [] });
    if (url === '/v1/commitments' && method === 'GET') return reply({ available: true, items, counts: {} });
    return reply({});
  }));
}
const show = () => render(<MemoryRouter><Knowledge /></MemoryRouter>);

describe('Knowledge', () => {
  it('lists each source with its state and removes one only after asking', async () => {
    server([source(), source({ id: 's2', name: 'scan.pdf', low_confidence: true, state: 'failed', error: 'password protected' })], []); show();
    expect(await screen.findByText('contract.pdf')).toBeTruthy();
    expect(screen.getByText(/12 passages on 4 pages/)).toBeTruthy();
    expect(screen.getByText(/Could not be read: password protected/)).toBeTruthy();
    expect(screen.getByText(/read from a scan and may contain errors/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0]);
    expect(calls.some(c => c.url.endsWith('/remove'))).toBe(false);
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url === '/v1/knowledge/sources/s1/remove')).toBe(true));
  });

  it('shows a suggested commitment as only a suggestion until it is confirmed', async () => {
    server([], [item({ id: 'c2', suggested: true, state: 'proposed', what: 'Pay the deposit' })]); show();
    expect(await screen.findByText('Pay the deposit')).toBeTruthy();
    expect(screen.getByText(/counts only once you confirm/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(calls.find(c => c.url === '/v1/commitments/c2')?.body).toEqual({ state: 'open' }));
  });

  it('adds a commitment the customer typed', async () => {
    server([], []); show();
    fireEvent.change(await screen.findByLabelText('What was decided or promised'), { target: { value: 'Call the bank' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(calls.find(c => c.method === 'POST' && c.url === '/v1/commitments')?.body).toEqual({ what: 'Call the bank' }));
  });

  it('says so when both features are off', () => {
    features = {}; server([], []); show();
    expect(screen.getByText('Not available yet')).toBeTruthy();
  });
});
