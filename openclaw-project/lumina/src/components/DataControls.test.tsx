import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DataControls, { size } from './DataControls';

let features: Record<string, unknown> = { self_service: true };
vi.mock('../state/data', () => ({ useData: () => ({ app: { features } }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); features = { self_service: true }; });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const rules = [{ key: 'events', title: 'The step-by-step activity timeline of a task', kept: '30 days, from when each step happened.', you_can: '', note: '' },
  { key: 'messages', title: 'Chats, tasks, plans and the results shown in them', kept: 'Until you delete the chat or your account.', you_can: 'Delete a chat, or your account, in Settings.', note: '' }];
const calls: string[] = [];
const server = (state: { exports?: unknown[]; offboarding?: unknown }) => { calls.length = 0; vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
  if (url === '/v1/csrf') return reply({ csrf_token: 't' });
  if (init?.method === 'POST') { calls.push(url); return reply({ offboarding: state.offboarding ?? null, export: {} }); }
  if (url === '/v1/retention') return reply({ rules });
  if (url === '/v1/exports') return reply({ exports: state.exports ?? [] });
  return reply({ offboarding: state.offboarding ?? null, cooling_off_seconds: 7 * 86400 }); })); };
const job = (over: Record<string, unknown> = {}) => ({ id: 'j1', state: 'waiting', has_archive: false, archive_bytes: null, waiting_for: 'export_choice', not_before_epoch: null, created_epoch: 1794000000, steps: [],
  remains_by_design: [], cooling_off_seconds: 604800, ...over });

describe('DataControls', () => {
  it('shows how long things are kept from the server table, and nothing else when self-service is off', async () => {
    features = {};
    server({});
    render(<DataControls />);
    expect(await screen.findByText('30 days, from when each step happened.')).toBeTruthy();
    expect(screen.getByText('Delete a chat, or your account, in Settings.')).toBeTruthy();
    expect(screen.queryByText('Export my data')).toBeNull(); expect(screen.queryByText('Close my account…')).toBeNull();
  });

  it('asks for an export and offers the finished archive', async () => {
    server({ exports: [{ ...job({ state: 'completed', has_archive: true, archive_bytes: 2_400_000, waiting_for: null }) }] });
    render(<DataControls />);
    expect(await screen.findByText(/ready \(2\.4 MB\)/)).toBeTruthy();
    fireEvent.click(screen.getByText('Export my data'));
    await waitFor(() => expect(calls).toContain('/v1/exports'));
    expect(size(900)).toBe('1 KB'); expect(size(null)).toBe('');
  });

  it('closing asks twice, says what remains, and nothing starts on the first click', async () => {
    server({});
    render(<DataControls />);
    fireEvent.click(await screen.findByText('Close my account…'));
    expect(screen.getByText(/after 7 days in which you can change your mind/)).toBeTruthy();
    expect(screen.getByText(/What remains afterwards/)).toBeTruthy();
    expect(calls).toEqual([]);
    fireEvent.click(screen.getByText('Yes, start closing it'));
    await waitFor(() => expect(calls).toEqual(['/v1/account/offboarding']));
  });

  it('waits for the export choice, and can still be cancelled', async () => {
    server({ offboarding: job() });
    render(<DataControls />);
    expect(await screen.findByText(/Do you want an archive of your data first/)).toBeTruthy();
    fireEvent.click(screen.getByText('No export'));
    await waitFor(() => expect(calls).toEqual(['/v1/account/offboarding/skip']));
    fireEvent.click(screen.getByText('Keep my account'));
    await waitFor(() => expect(calls).toContain('/v1/account/offboarding/cancel'));
  });

  it('says when everything will be deleted, and that a started deletion cannot be stopped', async () => {
    server({ offboarding: job({ waiting_for: 'cooling_off', not_before_epoch: 1794600000 }) });
    render(<DataControls />);
    expect(await screen.findByText(/Until then you can change your mind/)).toBeTruthy();
    expect(screen.getByText('Keep my account after all')).toBeTruthy();
    cleanup();
    server({ offboarding: job({ waiting_for: 'deletion', steps: [{ step: 'deletion_started', state: 'done' }] }) });
    render(<DataControls />);
    expect(await screen.findByText(/This can no longer be stopped/)).toBeTruthy();
    expect(screen.queryByText('Keep my account after all')).toBeNull();
  });
});
