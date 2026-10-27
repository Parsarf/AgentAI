import type { RequestRow } from './api';
import type { Ev } from './useActivity';
import { toActivity } from './activity';

export type StepStatus = 'pending' | 'running' | 'done' | 'blocked' | 'failed' | 'skipped' | 'stopped' | 'unreported';
export interface WorkStep { id: string; title: string; status: StepStatus; checkpoint?: string; result?: string }
export interface WorkProgress { mode: 'direct' | 'plan'; steps: WorkStep[] }
const statuses = ['pending', 'running', 'done', 'blocked', 'failed', 'skipped'];
/** Explicit checkpoint reports take precedence. Fallback tools use their matching result, never their position. */
export function taskProgress(events: Pick<Ev, 'kind' | 'payload'>[], task: RequestRow): WorkProgress {
  let progress: WorkProgress | undefined;
  for (const e of events) {
    const p = e.payload;
    if (e.kind !== 'task_steps' || !p || !['direct', 'plan'].includes(String(p.mode)) || !Array.isArray(p.steps) || !p.steps.length || p.steps.length > 24) continue;
    if (!p.steps.every(s => s && typeof s.id === 'string' && typeof s.title === 'string' && statuses.includes(s.status))) continue;
    progress = { mode: p.mode as 'direct' | 'plan', steps: p.steps.map(s => ({ id: s.id, title: s.title, status: s.status,
      checkpoint: typeof s.checkpoint === 'string' ? s.checkpoint : undefined, result: typeof s.result === 'string' ? s.result : undefined })) };
  }
  if (!progress) {
    const tools = toActivity(events).filter(r => r.status !== 'note' && r.category !== 'note');
    progress = { mode: 'direct', steps: tools.map(r => ({ id: r.key, title: r.detail ? `${r.label}: ${r.detail}` : r.label, status: r.status as StepStatus })) };
    // Parallel in-flight work stays current; finishing another call does not falsely complete it.
    progress.steps.sort((a, b) => Number(a.status === 'running') - Number(b.status === 'running'));
  }
  const terminal = ['completed', 'failed', 'cancelled'].includes(task.state);
  if (terminal) progress.steps = progress.steps.map(s => ['running', 'pending'].includes(s.status) ? { ...s, status: task.state === 'failed' ? 'failed' : task.state === 'cancelled' ? 'stopped' : 'unreported' } : s);
  return progress;
}
export const STEP_LABEL: Record<StepStatus, string> = { pending: 'Next', running: 'In progress', done: 'Done', blocked: 'Blocked', failed: 'Failed', skipped: 'Skipped', stopped: 'Stopped', unreported: 'Completion not reported' };
