import { describe, it, expect } from 'vitest';
import { taskProgress } from './taskProgress';
import type { RequestRow } from './api';
const task: RequestRow = { id: 't', state: 'running', message: 'Task', result: null, created_epoch: 1, cancel_requested: 0 };
describe('active task progress', () => {
  it('keeps failed tools failed and matches completions by ref, with current work last', () => {
    const steps = taskProgress([
      { kind: 'activity', payload: { ref: 'a', label: 'Read source', status: 'running' } },
      { kind: 'activity', payload: { ref: 'b', label: 'Run check', status: 'running' } },
      { kind: 'activity', payload: { ref: 'a', label: 'Read source', status: 'failed' } },
    ], task).steps;
    expect(steps.map(s => [s.title, s.status])).toEqual([['Read source', 'failed'], ['Run check', 'running']]);
  });
  it('uses the latest explicit plan with checkpoints and keeps pending phases', () => {
    const p = taskProgress([
      { kind: 'task_steps', payload: { mode: 'plan', steps: [{ id: 'a', title: 'Inspect', status: 'running', checkpoint: 'Find cause' }] } },
      { kind: 'task_steps', payload: { mode: 'plan', steps: [{ id: 'a', title: 'Inspect', status: 'done', checkpoint: 'Find cause', result: 'Cause found' }, { id: 'b', title: 'Fix', status: 'running', checkpoint: 'Tests pass' }, { id: 'c', title: 'Verify', status: 'pending', checkpoint: 'Review output' }] } },
    ], task);
    expect(p.mode).toBe('plan'); expect(p.steps.map(s => s.status)).toEqual(['done', 'running', 'pending']);
    expect(p.steps[0].result).toBe('Cause found');
  });
  it('does not invent success when a run ends without a checkpoint update', () => {
    const events = [{ kind: 'task_steps', payload: { mode: 'direct', steps: [{ id: 'a', title: 'Inspect', status: 'done' }, { id: 'b', title: 'Verify', status: 'running' }] } }];
    expect(taskProgress(events, { ...task, state: 'completed' }).steps.map(s => s.status)).toEqual(['done', 'unreported']);
    expect(taskProgress(events, { ...task, state: 'cancelled' }).steps[1].status).toBe('stopped');
  });
  it('ignores malformed progress and generic orchestration notes', () => {
    expect(taskProgress([{ kind: 'task_steps', payload: { mode: 'plan', steps: [null] } }, { kind: 'progress', payload: { summary: 'Runtime accepted the request.' } }], task).steps).toEqual([]);
  });
});
