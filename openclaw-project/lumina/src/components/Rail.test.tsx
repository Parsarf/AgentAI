import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ActiveTask, SystemStatus } from './Rail';
import { hold, resetWork, summary, view, work } from '../test/workMock';
vi.mock('../state/data', () => ({ useData: () => ({ health: 'ok' }) }));
vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
vi.mock('./Orb', () => ({ default: () => <span>Activity orb</span> }));
beforeEach(resetWork); afterEach(cleanup);
const mount = () => render(<MemoryRouter><ActiveTask /></MemoryRouter>);

describe('the rail’s task card', () => {
  it('shows the task that is working ahead of a newer queued one, in the same words every screen uses', () => {
    work.tasks = [summary({ id: 'q', title: 'queued one', phase: 'queued', label: 'Queued', tone: 'pending' })];
    hold(view({ id: 'w', title: 'working one', label: 'Running a command', activity: { key: 'k', category: 'command', label: 'Running a command', detail: 'npm test' },
      checklist: { mode: 'plan', steps: [{ id: 'a', title: 'Inspect', status: 'done', result: 'Found the cause' }, { id: 'b', title: 'Fix', status: 'running', checkpoint: 'Checks pass' }] } }));
    work.tasks = [work.tasks.find(t => t.id === 'q')!, work.tasks.find(t => t.id === 'w')!];
    mount();
    expect(screen.getByRole('link', { name: 'working one' })).toBeTruthy();
    expect(screen.getByText('Running a command')).toBeTruthy(); expect(screen.getByText('Activity orb')).toBeTruthy();
    expect(screen.getByText('as reported by the assistant')).toBeTruthy();               // the checklist is the assistant's report, and says so
    for (const text of ['Done', 'In progress', 'Found the cause', 'Done when: Checks pass']) expect(screen.getByText(text)).toBeTruthy();
  });
  it('points at what a task needs instead of showing it as working, and keeps the last result when nothing runs', () => {
    work.tasks = [summary({ id: 'n', phase: 'needs_you', label: 'Waiting for your permission', tone: 'attention', attention: 'approval' })];
    const first = mount();
    expect(screen.getByText('Waiting for your permission')).toBeTruthy(); expect(screen.queryByText('Activity orb')).toBeNull();
    expect(screen.getByRole('link', { name: 'See what it needs' }).getAttribute('href')).toBe('/tasks/n');
    first.unmount();
    work.tasks = [summary({ id: 'd', state: 'completed', phase: 'ended', label: 'Done · confirmed', tone: 'ok', outcome: 'completed', verification: 'verified' })];
    mount();
    expect(screen.getByText('Latest')).toBeTruthy(); expect(screen.getByText('Done · confirmed')).toBeTruthy(); expect(screen.queryByText('Activity orb')).toBeNull();
  });
  it('says so when there is nothing', () => { mount(); expect(screen.getByText(/Nothing is running/)).toBeTruthy(); });
  it('counts from the same task state', () => {
    work.tasks = [summary({ id: 'a' }), summary({ id: 'b', phase: 'queued' }), summary({ id: 'c', phase: 'ended', outcome: 'completed' })];
    render(<SystemStatus />);
    for (const name of ['1 Running', '1 Queued', '1 Completed']) expect(screen.getByRole('img', { name })).toBeTruthy();
  });
});
