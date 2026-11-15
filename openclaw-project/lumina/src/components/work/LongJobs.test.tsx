import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import LongJobs, { spent, stateWord, type LongJob } from './LongJobs';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const job = (over: Partial<LongJob> = {}): LongJob => ({
  id: 'j1', conversation_id: 'c1', state: 'paused', cancelled: false, pause_reason: 'This job reached its limit of 20 turns. Raise the limit or resume to carry on.', resume_policy: 'ask', turns: 20, max_turns: 20,
  elapsed_seconds: 5400, max_seconds: null, over_budget: 'This job reached its limit of 20 turns.', auto_resumes: 0, created_epoch: 1000, updated_epoch: 2000,
  checkpoints: [{ sequence: 1, step: 'Turn 1: completed', receipt_id: 'r1', created_epoch: 1500 }, { sequence: 2, step: 'Turn 2: partial', receipt_id: 'r2', created_epoch: 1800 }], ...over,
});
const view = () => render(<MemoryRouter><LongJobs /></MemoryRouter>);

describe('LongJobs', () => {
  it('words the state, the time and the budget', () => {
    expect(stateWord(job())).toBe('Paused'); expect(stateWord(job({ state: 'active' }))).toBe('Working'); expect(stateWord(job({ cancelled: true }))).toBe('Cancelled');
    expect([spent(30), spent(600), spent(7200)]).toEqual(['30 s', '10 min', '2 h']);
  });

  it('shows nothing when there are no jobs, and nothing when the server does not have the feature', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply({ objectives: [] })));
    const first = view(); await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(first.container.innerHTML).toBe('');
    cleanup(); vi.stubGlobal('fetch', vi.fn(() => reply({ error: 'not_found' }, 404)));
    const again = view(); await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(again.container.innerHTML).toBe('');
  });

  it('lists a paused job with its reason, what it has done and its budget', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply({ objectives: [job()] })));
    view();
    expect(await screen.findByText('Paused')).toBeTruthy();
    expect(screen.getByText(/20 of 20 turns/)).toBeTruthy();
    expect(screen.getByRole('status').textContent).toMatch(/reached its limit of 20 turns/);
    expect(screen.getByText('Turn 1: completed')).toBeTruthy(); expect(screen.getByText('Turn 2: partial')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open the chat' }).getAttribute('href')).toBe('/chat/c1');
  });

  it('raises the turn budget by ten and shows what the server stored; it never resumes the job itself', async () => {
    const calls: { url: string; body?: string; method?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body as string | undefined, method: init?.method });
      if (url === '/v1/csrf') return reply({ csrf_token: 't' });
      if (init?.method === 'POST') return reply(job({ max_turns: 30, over_budget: null }));
      return reply({ objectives: [job()] });
    }));
    view();
    fireEvent.click(await screen.findByRole('button', { name: 'Allow 10 more turns' }));
    await screen.findByText(/20 of 30 turns/);
    const post = calls.find(c => c.method === 'POST')!;
    expect(post.url).toBe('/v1/objectives/j1'); expect(JSON.parse(post.body!)).toEqual({ max_turns: '30' });
    expect(calls.some(c => c.url.includes('resume'))).toBe(false);
  });

  it('chooses what happens after an interruption', async () => {
    const posted: string[] = [];
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url === '/v1/csrf') return reply({ csrf_token: 't' });
      if (init?.method === 'POST') { posted.push(init.body as string); return reply(job({ resume_policy: 'auto' })); }
      return reply({ objectives: [job()] });
    }));
    view();
    fireEvent.change(await screen.findByLabelText('After an interruption'), { target: { value: 'auto' } });
    await waitFor(() => expect(posted).toEqual([JSON.stringify({ resume_policy: 'auto' })]));
  });

  it('says so when a job cannot be stopped', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url === '/v1/csrf') return reply({ csrf_token: 't' });
      if (init?.method === 'POST') return reply({ error: 'x' }, 500);
      return reply({ objectives: [job()] });
    }));
    view();
    fireEvent.click(await screen.findByRole('button', { name: 'Stop for good' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Could not stop that job/);
  });

  it('offers no controls on a job that is over', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply({ objectives: [job({ state: 'cancelled', cancelled: true, pause_reason: null })] })));
    view();
    expect(await screen.findByText('Cancelled')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Stop for good' })).toBeNull();
  });
});
