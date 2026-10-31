import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ActiveTask, TaskSteps } from './Rail';
const data = vi.hoisted(() => ({ requests: [] as any[] }));
const activity = vi.hoisted(() => ({ events: [] as any[], err: '' }));
vi.mock('../state/data', () => ({ useData: () => data }));
vi.mock('../lib/useActivity', () => ({ useActivity: () => activity }));
vi.mock('./Orb', () => ({ default: () => <span>Activity orb</span> }));
afterEach(() => { cleanup(); data.requests = []; activity.events = []; });
const row = (id: string, state: string, created_epoch: number) => ({ id, state, created_epoch, message: id, cancel_requested: 0, result: null });
describe('Active Task widget', () => {
  it('shows compact plan bullets with explicit status and checkpoints', () => {
    render(<TaskSteps progress={{ mode: 'plan', steps: [{ id: 'a', title: 'Inspect', status: 'done', checkpoint: 'Cause identified', result: 'Found the cause' }, { id: 'b', title: 'Fix', status: 'running', checkpoint: 'Checks pass' }, { id: 'c', title: 'Verify', status: 'pending' }] }} />);
    expect(screen.getByRole('list', { name: 'Phase plan' })).toBeTruthy();
    for (const text of ['Done', 'In progress', 'Next', 'Checkpoint: Checks pass', 'Found the cause']) expect(screen.getByText(text)).toBeTruthy();
  });
  it('shows running work ahead of queued work and retains the finished checklist', () => {
    data.requests = [row('queued', 'waiting', 2), row('executing', 'running', 1)];
    activity.events = [{ kind: 'task_steps', payload: { mode: 'direct', steps: [{ id: 'a', title: 'Read source', status: 'done' }, { id: 'b', title: 'Run checks', status: 'running' }] } }];
    const view = render(<MemoryRouter><ActiveTask /></MemoryRouter>);
    expect(screen.getByRole('link').textContent).toBe('executing');
    expect(screen.getByText('Read source')).toBeTruthy();
    data.requests = [row('executing', 'completed', 1)];
    activity.events = [{ kind: 'task_steps', payload: { mode: 'direct', steps: [{ id: 'a', title: 'Read source', status: 'done' }, { id: 'b', title: 'Run checks', status: 'done' }] } }];
    view.rerender(<MemoryRouter><ActiveTask /></MemoryRouter>);
    expect(screen.getByText('Completed')).toBeTruthy(); expect(screen.getAllByText('Done')).toHaveLength(2);
    expect(screen.queryByText('Activity orb')).toBeNull();
  });
});
