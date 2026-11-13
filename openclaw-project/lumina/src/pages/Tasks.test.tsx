import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Tasks from './Tasks';
import { api, ApiError } from '../lib/api';
import { hold, resetWork, row, summary, view, work } from '../test/workMock';

vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn() }));
function Where() { return <div data-testid="where">{useLocation().pathname}</div>; }
const mount = (path = '/tasks') => render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/tasks/:id?" element={<Tasks />} /><Route path="*" element={<Where />} /></Routes></MemoryRouter>);
const posts = () => vi.mocked(api).mock.calls.filter(c => c[0] === 'POST').map(c => c[1]);
const ended = (id: string, over: object) => summary({ id, title: id, state: 'completed', phase: 'ended', tone: 'ok', label: 'Done', outcome: 'completed', verification: 'not_applicable', ...over });
beforeEach(() => { resetWork(); vi.mocked(api).mockResolvedValue({ request: { id: 'r2', conversation_id: null } } as any); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Activity', () => {
  it('puts what is waiting for you on top, then what is in progress, then finished work', () => {
    work.tasks = [
      summary({ id: 'ask', title: 'File the bug', phase: 'needs_you', label: 'Waiting for your permission', tone: 'attention', attention: 'approval', needs: [{ kind: 'approval', id: 'call1', tool: 'create_issue', service: 'Linear', arguments: {}, expires_epoch: 9e9 }] }),
      summary({ id: 'held', title: 'Weekly report', state: 'waiting', phase: 'paused', label: 'Paused', tone: 'attention', attention: 'paused', controls: { resume: true, stop: true } as any }),
      summary({ id: 'go', title: 'Find flights', label: 'Searching the web', activity: { key: 'k', category: 'search', label: 'Searching the web', detail: 'lisbon flights' } }),
      ended('fine', { steps: 4 }), ended('unsure', { label: 'Done · not confirmed', tone: 'unsure', verification: 'unverified' }),
    ];
    mount();
    const needs = screen.getByRole('region', { name: /Needs you/ }); const going = screen.getByRole('region', { name: 'In progress' }); const done = screen.getByRole('region', { name: 'Finished' });
    expect(within(needs).getByText('File the bug')).toBeTruthy(); expect(within(needs).getByText('Weekly report')).toBeTruthy();
    expect(within(needs).getByRole('group', { name: 'Permission to use Create issue' })).toBeTruthy();          // answered right here
    expect(within(needs).getByRole('button', { name: 'Resume' })).toBeTruthy();
    expect(within(going).getByText('Find flights')).toBeTruthy(); expect(within(going).getByText('lisbon flights')).toBeTruthy();
    expect(within(done).getByText('fine')).toBeTruthy(); expect(within(done).getByText('4 steps')).toBeTruthy();
    expect(within(going).queryByText('File the bug')).toBeNull();
    expect(within(done).getByText('fine').closest('a')?.getAttribute('href')).toBe('/tasks/fine');              // a line opens the task's record, not the chat
  });
  it('lets finished work be read by how it ended, with finished-but-unconfirmed apart from done', () => {
    work.tasks = [ended('fine', {}), ended('unsure', { label: 'Done · not confirmed', tone: 'unsure', verification: 'unverified' }), ended('broke', { state: 'failed', label: 'Failed', tone: 'bad', outcome: 'failed' })];
    mount();
    const done = screen.getByRole('region', { name: 'Finished' });
    fireEvent.click(within(done).getByRole('button', { name: /Not confirmed/ }));
    expect(within(done).getByText('unsure')).toBeTruthy(); expect(within(done).queryByText('fine')).toBeNull(); expect(within(done).queryByText('broke')).toBeNull();
    fireEvent.click(within(done).getByRole('button', { name: /^Done/ }));
    expect(within(done).getByText('fine')).toBeTruthy(); expect(within(done).queryByText('unsure')).toBeNull();
    fireEvent.click(within(done).getByRole('button', { name: /Stopped/ }));
    expect(within(done).getByText('No finished work ended that way.')).toBeTruthy();
  });
  it('is honest when there is nothing, and about how it is being kept current', () => {
    mount();
    expect(screen.getByText('Nothing is waiting for you.')).toBeTruthy(); expect(screen.getByText(/Nothing is running/)).toBeTruthy();
    expect(screen.getByText('Refreshing every few seconds')).toBeTruthy();
    cleanup(); work.mode = 'stream'; mount();
    expect(screen.getByText('Up to date as it happens')).toBeTruthy();
  });
});

describe('a task’s record', () => {
  it('says how the run ended and, separately, whether the result was confirmed, with the evidence Lumina holds', () => {
    hold(view({ id: 'r1', title: 'Add wings to the cart', state: 'completed', phase: 'ended', label: 'Done · not confirmed', tone: 'unsure', outcome: 'completed', verification: 'unverified',
      note: 'Done, but I couldn’t confirm it from the page.', steps: 2, browser: { status: 'done', live: false, host: 'ubereats.com' },
      checklist: { mode: 'plan', steps: [{ id: 'a', title: 'Open the site', status: 'done' }, { id: 'b', title: 'Add to cart', status: 'unreported' }] },
      evidence: { steps: 2, failed_steps: 0, searches: 0, commands: 0, sites: ['ubereats.com'], files: [], saved: [{ id: 'f1', version: 1, name: 'order.pdf', size: 10 }], approvals: [], duration_s: 75 } }),
      [row({ key: 'b1', category: 'browse', label: 'Used the browser', detail: 'ubereats.com' }), row({ key: 'approval-x', kind: 'approval', category: 'approval', label: 'Asked for your permission to use place order on Uber', status: 'declined', first: 3, seq: 4 })]);
    mount('/tasks/r1');
    const verdict = screen.getByLabelText('How it ended');
    expect(within(verdict).getByText('The run finished')).toBeTruthy(); expect(within(verdict).getByText('Not confirmed')).toBeTruthy();
    expect(within(verdict).getByText('Done, but I couldn’t confirm it from the page.')).toBeTruthy();
    expect(screen.getByText('order.pdf')).toBeTruthy(); expect(screen.getAllByText('ubereats.com').length).toBeGreaterThan(0);
    expect(screen.getByText('Not reported as finished')).toBeTruthy();                                         // the assistant never said step b was done: neither do we
    expect(screen.getByText('you declined')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Continue in the chat' }).getAttribute('href')).toBe('/chat/c1');
    expect(screen.getByRole('link', { name: 'Open the workspace' }).getAttribute('href')).toBe('/live/r1');
  });
  it('offers what the server says can be done: pause and cancel while waiting, resume while held', async () => {
    hold(view({ id: 'r1', state: 'waiting', phase: 'queued', label: 'Queued', tone: 'pending', controls: { pause: true, stop: true } as any }));
    mount('/tasks/r1');
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(posts()).toContain('/v1/requests/r1/pause'));
    expect(work.refresh).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy(); expect(screen.queryByRole('button', { name: 'Resume' })).toBeNull();
  });
  it('retries a failed task and goes to the new one', async () => {
    hold(view({ id: 'r1', state: 'failed', phase: 'ended', label: 'Failed', tone: 'bad', outcome: 'failed', verification: 'unverified', controls: { retry: true } as any }));
    mount('/tasks/r1');
    expect(within(screen.getByLabelText('How it ended')).getByText('The run failed')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(posts()).toContain('/v1/requests/r1/retry'));
    await waitFor(() => expect(screen.queryByTestId('where') ?? screen.getByText(/not available|Loading/)).toBeTruthy());
  });
  it('explains a refused retry instead of failing silently', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError('budget_denied', 402));
    hold(view({ id: 'r1', state: 'failed', phase: 'ended', label: 'Failed', tone: 'bad', outcome: 'failed', controls: { retry: true } as any }));
    mount('/tasks/r1');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Your plan allowance or task budget cannot fund another run right now.')).toBeTruthy();
  });
  it('resumes or clears a goal that is on hold', async () => {
    hold(view({ id: 'r1', state: 'completed', phase: 'ended', label: 'Partly done', tone: 'attention', outcome: 'partial', verification: 'unverified', goal: true, attention: 'goal', controls: { goal_resume: true, goal_clear: true } as any }));
    mount('/tasks/r1');
    fireEvent.click(screen.getByRole('button', { name: 'Resume goal' }));
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(c => c[1] === '/v1/conversations/c1/goal' && (c[2] as any).action === 'resume')).toBe(true));
  });
  it('says so when the task is not this account’s or does not exist', () => { mount('/tasks/nope'); expect(screen.getByRole('alert').textContent).toMatch(/not available/); });
});
