import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Home from './Home';
import { resetWork, summary, work } from '../test/workMock';

// Home as Today (UI remodel phase 5): the prompt first, then tiles from live data, each opening its place and each degrading on its own.
vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
let features: Record<string, unknown> = {};
vi.mock('../state/data', () => ({ useData: () => ({ app: { user: { email: 'pat@example.com' }, features } }) }));
vi.mock('../components/Composer', () => ({ default: () => <textarea aria-label="Message Lumina" />, TEMPLATES: { Web: 'w', Code: 'c', Data: 'd', Automate: 'a' } }));
vi.mock('../components/Orb', () => ({ default: () => null }));

const NOW = Math.floor(Date.now() / 1000);
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const account = { id: 'a1', provider: 'p', provider_label: 'Mail', identity: 'me@x.test', state: 'working', needs_reason: null, capabilities: { mail: true, calendar: true }, granted: { mail: true, calendar: true }, mail: null, calendar: null };
let routes: Record<string, () => Promise<Response>> = {};
function server(over: Record<string, () => Promise<Response>> = {}) {
  routes = {
    '/v1/hub': () => reply({ accounts: [account], settings: { timezone: null, image_senders: [] }, counts: { unread: 7, by_account: {} }, calendars: [], labels: [], colours: [], read_only: true }),
    '/v1/hub/events': () => reply({ events: [{ connection_id: 'a1', calendar_id: 'c', id: 'e1', title: 'Design review', start_epoch: NOW + 3600, end_epoch: NOW + 7200, all_day: false, cancelled: false, busy_only: false, place: 'Room 2' },
      { connection_id: 'a1', calendar_id: 'c', id: 'e0', title: 'Over already', start_epoch: NOW - 7200, end_epoch: NOW - 3600, all_day: false, cancelled: false, busy_only: false, place: '' }], complete: true }),
    '/v1/hub/mail/threads': () => reply({ threads: [{ connection_id: 'a1', id: 't1', subject: 'Contract draft', snippet: '', people: [{ name: 'Ann', address: 'ann@x.test' }], last_epoch: NOW - 600, message_count: 1, unread: true, starred: false, has_attachments: false, labels: [], provider_labels: [] }], next: null, complete: true }),
    '/v1/catalogue': () => reply({ files: [{ kind: 'upload', id: 'u1', name: 'Budget.xlsx', original_name: 'Budget.xlsx', media_type: '', size_bytes: 2048, project_id: 'p', folder_id: null, source: 'uploaded', created_at: '2026-11-15T10:00:00Z', family: 'spreadsheet', copy_of: null }], folders: [], projects: [], total: 1, uploads: true }),
    '/v1/costs': () => reply({ reported_microusd: 140000, period_limit_microusd: 25000000, period_remaining_microusd: 24860000 }),
    ...over,
  };
  vi.stubGlobal('fetch', vi.fn((url: string) => { if (url === '/v1/csrf') return reply({ csrf_token: 't' }); const path = url.split('?')[0]; return routes[path] ? routes[path]() : reply({ error: 'not_found' }, 404); }));
}
const tile = (name: string) => within(screen.getByRole('region', { name }));
const show = () => render(<MemoryRouter><Home /></MemoryRouter>);
beforeEach(() => { resetWork(); features = { dashboard: true, files: true, usage: true }; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Today', () => {
  it('puts the prompt first, then the day from every source, each tile opening its place', async () => {
    server(); work.tasks = [summary({ id: 'w1', title: 'Approve the invoice run', attention: 'approval', phase: 'needs_you', label: 'Waiting for your permission' }), summary({ id: 'w2', title: 'Compare flights' })];
    show();
    const order = [...document.querySelectorAll('textarea, .tile-today')].map(e => e.tagName);
    expect(order[0]).toBe('TEXTAREA');
    expect(await tile('Next meetings').findByText('Design review')).toBeTruthy();
    expect(tile('Next meetings').queryByText('Over already')).toBeNull();                                         // nothing that has ended
    expect(tile('Next meetings').getByRole('link', { name: 'Next meetings' }).getAttribute('href')).toBe('/calendar');
    expect(await tile('Mail that needs you').findByText('Contract draft')).toBeTruthy();
    expect(tile('Mail that needs you').getByText('7 unread in your inbox, newest first.')).toBeTruthy();
    expect(tile('Work running and waiting on you').getByText('Approve the invoice run')).toBeTruthy();
    expect(tile('Work running and waiting on you').getByText('Approve the invoice run').closest('a')?.getAttribute('href')).toBe('/activity/w1');
    expect(await tile('Recent files').findByText('Budget.xlsx')).toBeTruthy();
    expect(await tile("This period's spending").findByText('$24.86 left this period.')).toBeTruthy();
  });

  it('degrades one tile at a time: a source that fails says so and offers to try again, the rest still show', async () => {
    server({ '/v1/catalogue': () => reply({ error: 'boom' }, 500) });
    show();
    expect(await tile('Recent files').findByText(/This could not be loaded just now/)).toBeTruthy();
    expect(tile('Recent files').getByRole('button', { name: 'Try again' })).toBeTruthy();
    expect(await tile('Next meetings').findByText('Design review')).toBeTruthy();
  });

  it('says in one line when a source is off or not connected, and "nothing today" when it is empty', async () => {
    features = { dashboard: false, files: false, usage: true };
    server(); show();
    expect(tile('Next meetings').getByText('Your calendars are not available on your account yet.')).toBeTruthy();
    expect(tile('Mail that needs you').getByText('Your mail is not available on your account yet.')).toBeTruthy();
    expect(tile('Recent files').getByText('Saved files are switched off for now.')).toBeTruthy();
    expect(tile('Work running and waiting on you').getByText('Nothing today.')).toBeTruthy();
    cleanup(); features = { dashboard: true, files: true, usage: true };
    server({ '/v1/hub': () => reply({ accounts: [], settings: { timezone: null, image_senders: [] }, counts: { unread: 0, by_account: {} }, calendars: [], labels: [], colours: [], read_only: true }) });
    show();
    expect(await tile('Next meetings').findByText(/No calendar is connected/)).toBeTruthy();
    expect(tile('Next meetings').getByRole('link', { name: 'Connect one' }).getAttribute('href')).toBe('/calendar');
  });
});
