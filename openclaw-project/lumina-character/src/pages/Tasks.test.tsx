import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Tasks from './Tasks';
import { api, ApiError } from '../lib/api';

const fixture = vi.hoisted(() => ({ requests: [] as any[], refresh: vi.fn() }));
vi.mock('../state/data', () => ({ useData: () => ({ app: {}, requests: fixture.requests, refresh: fixture.refresh }) }));
vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn() }));

const row = (over: object) => ({ id: 'r1', message: 'Compare two laptops', state: 'waiting', cancel_requested: 0, result: null, created_epoch: 1000, conversation_id: null, paused: false, ahead: 2, retry_of: null, ...over });
function Where() { return <div data-testid="where">{useLocation().pathname}</div>; }
const mount = (id = 'r1') => render(<MemoryRouter initialEntries={[`/tasks/${id}`]}><Routes><Route path="/tasks/:id?" element={<><Tasks /><Where /></>} /></Routes></MemoryRouter>);
const posts = () => vi.mocked(api).mock.calls.filter(c => c[0] === 'POST').map(c => c[1]);

beforeEach(() => {
  fixture.requests = [row({})];
  fixture.refresh = vi.fn(async () => {});
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'GET' && String(path).includes('/events')) return { events: [] } as any;
    if (method === 'GET') return { task: { conversation_id: null } } as any;
    return { request: { id: 'r2' } } as any;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('task control drawer', () => {
  it('shows the place in the line and offers Pause and Cancel for a waiting task', async () => {
    mount();
    expect(await screen.findByText('2 tasks are ahead of this one.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Pause' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel task' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Resume' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
  });

  it('pauses, then shows a held task with Resume', async () => {
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(posts()).toContain('/v1/requests/r1/pause'));
    expect(fixture.refresh).toHaveBeenCalled();
    cleanup(); fixture.requests = [row({ paused: true, ahead: null })]; mount();
    expect(await screen.findByText(/will not start until you resume it/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    await waitFor(() => expect(posts()).toContain('/v1/requests/r1/resume'));
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull();
  });

  it('says plainly that a running task cannot be paused', async () => {
    fixture.requests = [row({ state: 'running', ahead: null })]; mount();
    expect(await screen.findByText(/cannot be paused/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Cancel task' })).toBeTruthy();
  });

  it('retries a failed task and opens the new one', async () => {
    fixture.requests = [row({ state: 'failed', ahead: null })]; mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(posts()).toContain('/v1/requests/r1/retry'));
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/tasks/r2'));
    expect(screen.queryByRole('button', { name: 'Cancel task' })).toBeNull();
  });

  it('explains a refused retry and a refused pause instead of failing silently', async () => {
    fixture.requests = [row({ state: 'cancelled', ahead: null })]; mount();
    vi.mocked(api).mockImplementation(async (method, path) => {
      if (method === 'GET') return (String(path).includes('/events') ? { events: [] } : { task: { conversation_id: null } }) as any;
      throw new ApiError('budget_denied', 402);
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Your plan allowance or task budget cannot fund another run right now.');
    cleanup(); fixture.requests = [row({})]; mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Pause' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Could not pause this task/);
  });

  it('marks a held task in the list without removing it from Queued', async () => {
    fixture.requests = [row({ paused: true, ahead: null }), row({ id: 'r3', message: 'Another', ahead: 1 })];
    render(<MemoryRouter initialEntries={['/tasks']}><Routes><Route path="/tasks/:id?" element={<Tasks />} /></Routes></MemoryRouter>);
    expect(await screen.findByText(/Paused ·/)).toBeTruthy();
    expect(screen.getByText(/Queued \(1 ahead\) ·/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Queued' }));
    expect(screen.getByText(/Paused ·/)).toBeTruthy();
  });
});
