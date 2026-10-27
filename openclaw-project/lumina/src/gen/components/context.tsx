import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react';
import { Dispatcher, type ActionEnv, type AuditEntry, type PhaseState, type Result } from '../actions';
import type { Dataset } from '../schemas';
import type { ActivityItem } from '../../lib/activity';

export interface RequestInfo { id: string; state: string; result: string | null; message?: string; outcome?: string | null; outcome_note?: string | null; created_epoch: number }
export interface PlanInfo { id: string; title: string; phases: Array<{ id: string; title: string; description?: string }>; run: Record<string, { state: PhaseState; summary: string | null }>; run_status?: string }
/** Where agent-native blocks get their facts: Lumina's own records. A block never carries these values itself. */
export interface ExecutionProvider {
  request(id: string): RequestInfo | undefined;
  plan(id: string): PlanInfo | undefined;
  /** A hook: follows the request's real events. */
  useActivity(requestId: string, live: boolean): { rows: ActivityItem[]; err: string };
  /** Honest label for fixtures: shown on the block so nobody mistakes sample data for a real run. */
  label?: string;
}
export type Host = Omit<ActionEnv, 'local' | 'confirm' | 'audit' | 'now'> & { audit?(e: AuditEntry): void;
  /** Turns a `file:` reference into a URL the signed-in person may load, or null. The chat host has none yet (files are served by artifact id behind a ticket), so images show their alt text. */
  assetUrl?(ref: string): string | null };

interface Ctx { datasets: Record<string, Dataset>; exec: ExecutionProvider; act(raw: unknown, o?: { nonce?: string; destructiveStyle?: boolean }): Promise<Result>; local: Record<string, Record<string, unknown>>; setLocal(target: string, patch: Record<string, unknown>): void; scope: string; readOnly: boolean; assetUrl(ref: string): string | null }
const GenCtx = createContext<Ctx | null>(null);
export function useGen(): Ctx { const c = useContext(GenCtx); if (!c) throw new Error('GenProvider missing'); return c; }
/** Local, per-block UI state (sort, filter, page, tab, open items). Survives re-renders and streaming updates because the key is the block id. */
export function useLocal<T extends Record<string, unknown>>(id: string, initial: T): [T, (patch: Partial<T>) => void] {
  const g = useGen();
  const value = useMemo(() => ({ ...initial, ...(g.local[id] ?? {}) }) as T, [g.local, id]);   // eslint-disable-line react-hooks/exhaustive-deps
  return [value, (patch) => g.setLocal(id, patch as Record<string, unknown>)];
}

type Confirm = { title: string; detail: string; destructive: boolean; resolve(v: boolean): void } | null;
export function GenProvider({ datasets, blockIds, exec, host, scope, readOnly = false, children }: {
  datasets: Record<string, Dataset>; blockIds: string[]; exec: ExecutionProvider; host: Host; scope: string; readOnly?: boolean; children: ReactNode;
}) {
  const [local, patch] = useReducer((s: Record<string, Record<string, unknown>>, a: { id: string; patch: Record<string, unknown> }) => ({ ...s, [a.id]: { ...(s[a.id] ?? {}), ...a.patch } }), {});
  const [confirm, setConfirm] = useState<Confirm>(null);
  const ids = useRef(new Set(blockIds)); ids.current = new Set(blockIds);
  const hostRef = useRef(host); hostRef.current = host;
  const dispatcher = useMemo(() => {
    const env: ActionEnv = {
      local: a => {
        if (!ids.current.has(a.target)) return false;                       // a target must be a block in this very response
        if (a.kind === 'local.sort') patch({ id: a.target, patch: { sortColumn: a.column, sortDir: a.dir } });
        else if (a.kind === 'local.filter') patch({ id: a.target, patch: { query: a.query, page: 0 } });
        else if (a.kind === 'local.expand') patch({ id: a.target, patch: { expanded: a.expanded } });
        else if (a.kind === 'local.select') patch({ id: a.target, patch: { selected: a.value } });
        else patch({ id: a.target, patch: { [a.field]: a.value } });
        return true;
      },
      send: (m, k) => hostRef.current.send(m, k), phase: (b, p, v, k) => hostRef.current.phase(b, p, v, k), retryRequest: (r, k) => hostRef.current.retryRequest(r, k),
      navigate: p => hostRef.current.navigate(p), download: p => hostRef.current.download(p), phaseState: (b, p) => hostRef.current.phaseState(b, p),
      confirm: s => new Promise<boolean>(resolve => setConfirm({ ...s, resolve })),
      audit: e => { try { hostRef.current.audit?.(e); } catch { /* auditing never blocks an action */ } }, now: () => Date.now(),
    };
    return new Dispatcher(env, { scope });
  }, [scope]);
  const act = useCallback((raw: unknown, o?: { nonce?: string; destructiveStyle?: boolean }) => (readOnly ? Promise.resolve<Result>({ ok: false, reason: 'forbidden', message: 'Actions are off in this view.' }) : dispatcher.dispatch(raw, o)), [dispatcher, readOnly]);
  const value = useMemo<Ctx>(() => ({ datasets, exec, act, local, setLocal: (id, p) => patch({ id, patch: p }), scope, readOnly, assetUrl: r => hostRef.current.assetUrl?.(r) ?? null }), [datasets, exec, act, local, scope, readOnly]);
  return <GenCtx.Provider value={value}>{children}{confirm && <ConfirmDialog {...confirm} onDone={v => { confirm.resolve(v); setConfirm(null); }} />}</GenCtx.Provider>;
}

function ConfirmDialog({ title, detail, destructive, onDone }: { title: string; detail: string; destructive: boolean; onDone(v: boolean): void }) {
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => { first.current?.focus(); }, []);
  return <div className="gen-scrim" onKeyDown={e => { if (e.key === 'Escape') onDone(false); }}>
    <div className="gen-dialog" role="alertdialog" aria-modal="true" aria-labelledby="gen-confirm-t" aria-describedby="gen-confirm-d">
      <h3 id="gen-confirm-t">{title}</h3><p id="gen-confirm-d">{detail}</p>
      <div className="gen-row"><button ref={first} className="btn tertiary" onClick={() => onDone(false)}>Cancel</button>
        <button className={destructive ? 'btn danger' : 'btn primary'} onClick={() => onDone(true)}>Confirm</button></div></div></div>;
}
