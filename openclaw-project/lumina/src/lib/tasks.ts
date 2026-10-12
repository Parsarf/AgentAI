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
export const isActive = (state: string) => ['queued', 'running'].includes(phase(state));

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
  const live = rows.filter(r => isActive(r.state));
  return live.length ? live.reduce((a, b) => (b.created_epoch > a.created_epoch ? b : a)) : null;
}

const NOISE = /transcript update/i;
export function visibleEvents<T extends { payload?: { summary?: string } }>(events: T[]): T[] {
  return events.filter(e => !NOISE.test(e.payload?.summary ?? ''));
}
