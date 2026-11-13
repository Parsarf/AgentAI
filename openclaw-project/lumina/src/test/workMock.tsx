/** Test stand-in for state/work.tsx: screens read task state from `work`, which a test fills in. Use it with
 *    vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
 *  The real client (transport, cursors, fallback) is tested on its own in lib/workClient.test.ts. */
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import type { Draft, Row, TaskSummary, TaskView } from '../lib/work';

export const work = {
  tasks: [] as TaskSummary[], details: {} as Record<string, { task: TaskView; rows: Row[]; cursor: number }>, drafts: {} as Record<string, Draft>,
  loaded: true, mode: 'poll' as 'poll' | 'stream' | 'connecting', rev: 'r', refresh: vi.fn(async () => {}), watched: [] as string[],
};
export function resetWork() { Object.assign(work, { tasks: [], details: {}, drafts: {}, loaded: true, mode: 'poll', refresh: vi.fn(async () => {}), watched: [] }); }

const CONTROLS = { stop: false, pause: false, resume: false, retry: false, goal_resume: false, goal_clear: false, steer: false };
export const summary = (over: Partial<TaskSummary> = {}): TaskSummary => ({
  id: 'r1', conversation_id: 'c1', title: 'Compare two laptops', follows: null, created_epoch: Math.floor(Date.now() / 1000) - 30, state: 'running', phase: 'working', label: 'Thinking', tone: 'live',
  activity: null, now: [], ahead: null, attention: null, attention_label: '', outcome: null, verification: null, note: '', goal: false, continuing: false, retry_of: null,
  needs: [], steps: 0, ...over, controls: { ...CONTROLS, ...(over.controls ?? {}) },
});
export const view = (over: Partial<TaskView> = {}): TaskView => ({
  ...summary(over), request: over.title ?? 'Compare two laptops', result: null, checklist: null, messages: 1, cancel_requested: false, browser: null, ended_epoch: null, rev: 'v',
  evidence: { steps: 0, failed_steps: 0, searches: 0, commands: 0, sites: [], files: [], saved: [], approvals: [], duration_s: null }, ...over, controls: { ...CONTROLS, ...(over.controls ?? {}) },
});
export const row = (over: Partial<Row> = {}): Row => ({ key: 'c1', kind: 'tool', category: 'search', label: 'Searched the web', detail: 'laptops', output: '', status: 'done', at: 1000, ended_at: 2000, first: 1, seq: 2, group: null, ...over });
/** Put one task in the list and give it a full record. */
export function hold(task: TaskView, rows: Row[] = []) { work.tasks = [task, ...work.tasks.filter(t => t.id !== task.id)]; work.details = { ...work.details, [task.id]: { task, rows, cursor: rows.length } }; }

export const mock = {
  WorkProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useWorkClient: () => ({ refresh: work.refresh, watch: () => () => {} }),
  useWork: () => ({ ...work, attention: work.tasks.filter(t => t.attention).length }),
  useTask: (id: string | null | undefined, watch = true) => {
    if (id && watch && !work.watched.includes(id)) work.watched.push(id);
    const held = id ? work.details[id] : undefined;
    return { task: held?.task ?? (id ? work.tasks.find(t => t.id === id) : undefined), full: held?.task, rows: held?.rows ?? [], draft: id ? work.drafts[id] : undefined };
  },
};
