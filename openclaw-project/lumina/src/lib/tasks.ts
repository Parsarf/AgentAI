import type { RequestRow } from './api';

export type Phase = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

/** Backend request states -> the few states a person needs. `uncertain` is the system reconciling: still in flight. */
export function phase(state: string): Phase {
  switch (state) {
    case 'waiting': return 'queued';
    case 'starting': case 'running': case 'uncertain': return 'running';
    case 'completed': return 'completed';
    case 'failed': return 'failed';
    case 'cancelled': return 'cancelled';
    default: return 'queued';
  }
}
type Row = Pick<RequestRow, 'state'> & Partial<Pick<RequestRow, 'paused' | 'ahead' | 'retry_of'>>;

/** What a person reads under a task. A paused task is held in the queue, so it is still "queued" for filters but never starts until resumed. */
export function statusLabel(r: Row): string {
  const p = phase(r.state);
  if (p === 'queued') return r.paused ? 'Paused' : 'Queued';
  return p === 'running' ? 'Working' : p === 'completed' ? 'Completed' : p === 'failed' ? 'Failed' : 'Cancelled';
}
/** The colour class for the status dot. */
export const dotClass = (r: Row) => (phase(r.state) === 'queued' && r.paused ? 'paused' : phase(r.state));

/** Where a waiting task stands in the line, in words. Empty when it is not waiting its turn. */
export function queueLine(r: Row): string {
  if (phase(r.state) !== 'queued') return '';
  if (r.paused) return 'Paused. It keeps its place and its budget, and will not start until you resume it.';
  if (r.ahead === 0) return 'Next in line.';
  if (typeof r.ahead === 'number') return `${r.ahead} ${r.ahead === 1 ? 'task is' : 'tasks are'} ahead of this one.`;
  return '';
}

/** What can be done to a task now. A task that is running cannot be paused: the assistant has no safe place to stop mid-run (cancel it instead). */
export function controls(r: Row) {
  const p = phase(r.state);
  const waiting = r.state === 'waiting';
  return { pause: waiting && !r.paused, resume: waiting && !!r.paused, cancel: p === 'queued' || p === 'running', retry: r.state === 'failed' || r.state === 'cancelled' };
}

/** Is Lumina working on it (or about to)? A held task is queued but nothing is happening, so it does not count: no thinking orb, no live badge. */
export const isActive = (x: string | Row) => { const r = typeof x === 'string' ? { state: x } : x; return ['queued', 'running'].includes(phase(r.state)) && !(r as Row).paused; };

export function counts(rows: RequestRow[]) {
  const c = { running: 0, queued: 0, completed: 0, failed: 0 };
  for (const r of rows) {
    const p = phase(r.state);
    if (p === 'running') c.running++; else if (p === 'queued') c.queued++; else if (p === 'completed') c.completed++; else if (p === 'failed') c.failed++;
  }
  return c;
}

/** Most recently created in-flight request: what the Active Task panel shows. */
export function activeTask(rows: RequestRow[]): RequestRow | null {
  const live = rows.filter(r => isActive(r));
  return live.length ? live.reduce((a, b) => (b.created_epoch > a.created_epoch ? b : a)) : null;
}

const NOISE = /transcript update/i;
export function visibleEvents<T extends { payload?: { summary?: string } }>(events: T[]): T[] {
  return events.filter(e => !NOISE.test(e.payload?.summary ?? ''));
}
