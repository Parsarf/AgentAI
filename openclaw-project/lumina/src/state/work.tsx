import { createContext, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { api } from '../lib/api';
import { WorkClient, type WorkState } from '../lib/workClient';
import type { Draft, Row, TaskSummary, TaskView } from '../lib/work';
import { useData } from './data';

const Ctx = createContext<WorkClient | null>(null);

/** One WorkClient for the signed-in session. Every screen reads task state from it; none of them asks the server about tasks by itself. */
export function WorkProvider({ children, client }: { children: ReactNode; client?: WorkClient }) {
  const { status } = useData();
  const own = useMemo(() => client ?? new WorkClient({ get: path => api('GET', path), post: path => api('POST', path, {}) }), [client]);
  useEffect(() => { if (status !== 'in') return; own.start(); return () => own.stop(); }, [status, own]);
  return <Ctx.Provider value={own}>{children}</Ctx.Provider>;
}

export function useWorkClient(): WorkClient {
  const client = useContext(Ctx);
  if (!client) throw new Error('WorkProvider is missing');
  return client;
}
/** The account's tasks, what needs the customer, and how the picture is being kept current. */
export function useWork(): WorkState & { refresh(): Promise<void> } {
  const client = useWorkClient();
  const state = useSyncExternalStore(client.subscribe, client.snapshot, client.snapshot);
  return useMemo(() => ({ ...state, refresh: () => client.refresh() }), [state, client]);
}
/** One task in full, kept current for as long as the calling screen is mounted. Until the full view arrives, `task` is the list's summary of it (or undefined). */
export function useTask(id: string | null | undefined, watch = true): { task: TaskView | TaskSummary | undefined; full: TaskView | undefined; rows: Row[]; draft: Draft | undefined } {
  const client = useWorkClient();
  const state = useSyncExternalStore(client.subscribe, client.snapshot, client.snapshot);
  useEffect(() => (id && watch ? client.watch(id) : undefined), [client, id, watch]);      // `watch` false: read what is already known (the list's line) without asking for the full record
  const held = id ? state.details[id] : undefined;
  const summary = id ? state.tasks.find(t => t.id === id) : undefined;
  return { task: held?.task ?? summary, full: held?.task, rows: held?.rows ?? NO_ROWS, draft: id ? state.drafts[id] : undefined };
}
const NO_ROWS: Row[] = [];
