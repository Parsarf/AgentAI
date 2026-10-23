export interface ActivityItem { key: string; category: string; label: string; detail: string; output: string; status: 'running' | 'done' | 'failed' | 'note'; at: string }
interface Ev { sequence?: number; kind: string; created_at?: string; payload?: Record<string, unknown> }

const str = (v: unknown, max = 1500) => (typeof v === 'string' ? v.slice(0, max) : '');
const NOISE = /transcript update/i;      // the stage lines (received, waking, ready, working) are shown: they are what the person is waiting for

/** Raw task events -> one row per tool call (a later 'done' replaces the earlier 'running') plus plain progress notes, in order. */
export function toActivity(events: Ev[]): ActivityItem[] {
  const rows: ActivityItem[] = []; const byRef = new Map<string, number>();
  for (const e of events) {
    const p = e.payload ?? {}; const at = e.created_at ?? '';
    if (e.kind === 'activity') {
      const ref = str(p.ref, 128); if (!ref) continue;
      const status = p.status === 'done' || p.status === 'failed' ? p.status : 'running';
      const item: ActivityItem = { key: ref, category: str(p.category, 20) || 'other', label: str(p.label, 80) || 'Used a tool', detail: str(p.detail, 400), output: str(p.output), status, at };
      const at0 = byRef.get(ref);
      if (at0 === undefined) { byRef.set(ref, rows.length); rows.push(item); } else rows[at0] = { ...item, at: rows[at0].at };
    } else if (e.kind === 'plan') {
      const steps = Array.isArray(p.steps) ? p.steps.filter((x): x is string => typeof x === 'string').slice(0, 12) : [];
      const summary = str(p.summary, 200); if (!summary && !steps.length) continue;
      rows.push({ key: `n${e.sequence ?? rows.length}`, category: 'note', label: summary ? `Plan: ${summary}` : 'Plan', detail: steps.map((t, i) => `${i + 1}. ${t.slice(0, 120)}`).join('  ').slice(0, 400), output: '', status: 'note', at });
    } else if (['progress', 'error', 'result', 'task_queued', 'task_started'].includes(e.kind)) {
      const text = str(p.summary, 300); if (!text || NOISE.test(text)) continue;
      rows.push({ key: `n${e.sequence ?? rows.length}`, category: e.kind === 'error' ? 'error' : 'note', label: text, detail: '', output: '', status: e.kind === 'error' ? 'failed' : 'note', at });
    }
  }
  return rows;
}

export const ICON: Record<string, string> = { search: '⌕', read: '↗', command: '›_', file: '▤', browse: '◰', other: '•', note: '·', error: '!' };
