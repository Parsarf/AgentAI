import { createContext, useCallback, useContext, useEffect, useMemo, useId, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { Dispatcher, type ActionEnv, type AuditEntry, type PhaseState, type Result } from '../actions';
import type { Action, Block, Dataset } from '../schemas';
import type { Ev } from '../../lib/useActivity';
import type { ActivityItem } from '../../lib/activity';
import { ArtifactDraft, artifactDraft, downloadAnswers, previousDrafts, type LocalState, type RemoteState } from '../drafts';
import { ApiError } from '../../lib/api';
import { interactionError, failureCategory } from '../errors';

export interface RequestInfo { id: string; state: string; result: string | null; message?: string; outcome?: string | null; outcome_note?: string | null; created_epoch: number }
export interface PlanInfo { id: string; title: string; phases: Array<{ id: string; title: string; description?: string; dependsOn?: string[] }>; run: Record<string, { state: PhaseState; summary: string | null }>; run_status?: string }
/** Where agent-native blocks get their facts: Lumina's own records. A block never carries these values itself. */
export interface ExecutionProvider {
  request(id: string): RequestInfo | undefined;
  plan(id: string): PlanInfo | undefined;
  /** A hook: follows the request's real events. */
  useActivity(requestId: string, live: boolean): { rows: ActivityItem[]; err: string; events?: Ev[] };
  useSnapshot?(id: string, live: boolean): { usage?: { tokens: number | null; cost_microusd: number | null; estimated: boolean }; error?: string };
  /** Honest label for fixtures: shown on the block so nobody mistakes sample data for a real run. */
  label?: string;
  planEditor?(id: string): ReactNode;
}
export type { LocalState } from '../drafts';
export type Host = Omit<ActionEnv, 'local' | 'confirm' | 'audit' | 'now'> & { audit?(e: AuditEntry): void;
  /** Resolves a stored document's authorized project-file reference, or returns null. */
  assetUrl?(ref: string): string | null;
  artifactVersion?: number; initialState?: LocalState; saveState?(state: LocalState): Promise<void>;
  loadState?(): Promise<RemoteState>; diagnostic?(kind: string, category: string): void;
  submit?(nodeId: string, actionId: string, values: Record<string, unknown>, eventId: string): Promise<void>;
};

interface Ctx { datasets: Record<string, Dataset>; exec: ExecutionProvider; act(raw: unknown, o?: { nonce?: string; destructiveStyle?: boolean }): Promise<Result>; local: Record<string, Record<string, unknown>>; setLocal(target: string, patch: Record<string, unknown>): void; scope: string; readOnly: boolean; confirm?(detail: string): Promise<boolean>; submit?(actionId: string, values: Record<string, unknown>): Promise<Result>; assetUrl(ref: string): string | null }
const GenCtx = createContext<Ctx | null>(null);
const NodeCtx = createContext<Block | null>(null);
export const NodeProvider = NodeCtx.Provider;
/** The id of the block being rendered (its own local state key), or undefined outside a document. */
export function useNodeId(): string | undefined { return useContext(NodeCtx)?.id; }
export function useGen(): Ctx {
  const c = useContext(GenCtx); const node = useContext(NodeCtx);
  if (!c) throw new Error('GenProvider missing');
  const submit = c.submit && node ? (id: string, values: Record<string, unknown>) => c.submit!(`${node.id}:${id}`, values) : undefined;
  return { ...c, submit, act: (raw: unknown, options) => {
    const a = raw as Action;
    if (a?.kind.startsWith('agent.') && submit && node) {
      const p = node.props as any;
      const candidates: Array<[string, any]> = [
        ...(p.action ? [['confirm', p.action]] as Array<[string, any]> : []),
        ...(p.items ?? []).filter((i: any) => i.action).map((i: any) => [i.id, i.action]),
        ...(p.cards ?? []).flatMap((card: any, i: number) => (card.actions ?? []).map((v: any, j: number) => [`card-${i}-action-${j}`, v.action])),
        ...(p.buttons ?? []).map((b: any) => [b.id, b.action]),
        ...(p.actions ?? []).map((b: any, i: number) => [`action-${i}`, b.action]),
        ...(p.suggestions ?? []).map((message: string, i: number) => [`suggestion-${i}`, { kind: 'agent.request', message }]),
      ];
      if (node.type === 'approval_request') candidates.push(['approve', { kind: 'agent.approve', planBlockId: p.planBlockId, phaseId: p.phaseId }], ['deny', { kind: 'agent.deny', planBlockId: p.planBlockId, phaseId: p.phaseId }]);
      if (node.type === 'error_retry') candidates.push(['retry', { kind: 'agent.retry', ...Object.fromEntries(['planBlockId', 'phaseId', 'requestId'].filter(k => p[k]).map(k => [k, p[k]])) }]);
      const binding = candidates.find(([id, action]) => (!options?.nonce || id === options.nonce) && Object.keys(action).length === Object.keys(a).length && Object.keys(action).every(k => action[k] === (a as any)[k]));
      if (!binding) return Promise.resolve({ ok: false, reason: 'invalid', message: 'That action is not defined on this artifact node.' });
      return (async () => {
        if ((a.kind !== 'agent.request' || options?.destructiveStyle) && !(await c.confirm?.(a.kind === 'agent.request' ? a.message : `${a.kind.slice(6)} this task step?`))) return { ok: false, reason: 'declined', message: 'Cancelled.' } as Result;
        return submit(binding[0], {});
      })();
    }
    return c.act(raw, options);
  } };
}
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
  const hostRef = useRef(host); hostRef.current = host;
  const [draft] = useState(() => host.artifactVersion === undefined ? new ArtifactDraft(1, host.initialState ?? {}) : artifactDraft(scope, host.artifactVersion, host.initialState ?? {}));
  draft.host = {
    saveState: host.saveState ? state => hostRef.current.saveState!(state) : undefined,
    loadState: host.loadState ? () => hostRef.current.loadState!() : undefined,
    diagnostic: (kind, category) => hostRef.current.diagnostic?.(kind, category),
  };
  const snapshot = useSyncExternalStore(draft.subscribe, draft.getSnapshot);
  const local = snapshot.state;
  const patch = ({ id, patch }: { id: string; patch: Record<string, unknown> }) => draft.patch(id, patch);
  const [older, setOlder] = useState(() => host.artifactVersion === undefined ? [] : previousDrafts(scope, host.artifactVersion));
  useEffect(() => {
    if (!snapshot.dirty || !host.saveState || readOnly || snapshot.error) return;
    const timer = window.setTimeout(() => { void draft.flush().catch(() => {}); }, 350);
    return () => window.clearTimeout(timer);
  }, [local, snapshot.dirty, snapshot.error, readOnly, draft, !!host.saveState]);
  useEffect(() => {
    const flush = () => { if (!readOnly) void draft.flush().catch(() => {}); };
    const leaving = (e: BeforeUnloadEvent) => {
      if (draft.getSnapshot().dirty || older.some(d => d.getSnapshot().dirty)) { e.preventDefault(); e.returnValue = ''; flush(); }
    };
    const hidden = () => { if (document.visibilityState === 'hidden') flush(); };
    window.addEventListener('beforeunload', leaving); window.addEventListener('online', flush); document.addEventListener('visibilitychange', hidden);
    return () => { window.removeEventListener('beforeunload', leaving); window.removeEventListener('online', flush); document.removeEventListener('visibilitychange', hidden); flush(); };
  }, [draft, readOnly, older]);
  const eventIds = draft.events;
  const inFlight = draft.inFlight;
  const submit = host.submit ? async (binding: string, values: Record<string, unknown>): Promise<Result> => {
    if (readOnly) return { ok: false, reason: 'forbidden', message: 'Actions are off in this view.' };
    const [node, action] = binding.split(':');
    const fingerprint = `${hostRef.current.artifactVersion ?? 1}:${binding}:${JSON.stringify(values)}`;
    if (inFlight.has(fingerprint)) return { ok: false, reason: 'duplicate', message: 'Submission is pending.' };
    const eventId = eventIds.get(fingerprint) ?? crypto.randomUUID().replaceAll('-', ''); eventIds.set(fingerprint, eventId); inFlight.add(fingerprint);
    try { await draft.flush(); await hostRef.current.submit!(node, action, values, eventId); return { ok: true }; }
    catch (error) { hostRef.current.diagnostic?.('submit_failed', failureCategory(error)); return { ok: false, reason: 'failed', message: draft.getSnapshot().conflict ? 'Resolve the conflicting edits below before sending.' : interactionError(error), fieldErrors: error instanceof ApiError ? error.fieldErrors : undefined }; } finally { inFlight.delete(fingerprint); }
  } : undefined;
  const [confirm, setConfirm] = useState<Confirm>(null);
  const ids = useRef(new Set(blockIds)); ids.current = new Set(blockIds);
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
  const value = useMemo<Ctx>(() => ({ datasets, exec, act, submit, confirm: detail => new Promise<boolean>(resolve => setConfirm({ title: 'Confirm action', detail, destructive: true, resolve })), local, setLocal: (id, p) => patch({ id, patch: p }), scope, readOnly, assetUrl: r => hostRef.current.assetUrl?.(r) ?? null }), [datasets, exec, act, local, scope, readOnly, host.submit, host.artifactVersion]);
  return <GenCtx.Provider value={value}>{children}
    {host.saveState && <div className="gen-save" aria-live="polite" role="status">{snapshot.saving ? 'Saving changes…' : snapshot.dirty ? 'Unsaved changes' : 'Changes saved'}</div>}
    {snapshot.error && <div className="notice" role="alert"><p>{snapshot.error}</p><div className="gen-row">
      {snapshot.conflict ? <><button className="btn" onClick={() => { void draft.resolve(true).catch(() => {}); }}>Keep my edits</button><button className="btn" onClick={() => { void draft.resolve(false); }}>Use saved edits</button></> : <button className="btn" disabled={snapshot.saving} onClick={() => { void draft.flush().catch(() => {}); }}>Retry saving</button>}
      <button className="btn tertiary" onClick={() => downloadAnswers(local)}>Download my answers</button>
    </div></div>}
    {older.length > 0 && <div className="notice" role="alert"><p>This answer was updated while you had unsaved edits. Your earlier answers are kept in this tab.</p><div className="gen-row"><button className="btn" onClick={() => downloadAnswers(older[older.length - 1].getSnapshot().state)}>Download earlier answers</button><button className="btn tertiary" onClick={() => { if (window.confirm('Discard the unsaved answers from the earlier version?')) { older.forEach(d => d.cancel()); setOlder([]); } }}>Discard earlier edits</button></div></div>}
    {confirm && <ConfirmDialog {...confirm} onDone={v => { confirm.resolve(v); setConfirm(null); }} />}</GenCtx.Provider>;
}

function ConfirmDialog({ title, detail, destructive, onDone }: { title: string; detail: string; destructive: boolean; onDone(v: boolean): void }) {
  const dialog = useRef<HTMLDialogElement>(null); const uid = useId();
  useEffect(() => { const d = dialog.current; d?.showModal?.(); return () => d?.close?.(); }, []);
  return <dialog ref={dialog} open={typeof HTMLDialogElement.prototype.showModal !== 'function' || undefined} className="gen-dialog" role="alertdialog" aria-modal="true" aria-labelledby={`${uid}-t`} aria-describedby={`${uid}-d`} onCancel={e => { e.preventDefault(); onDone(false); }}>
    <h3 id={`${uid}-t`}>{title}</h3><p id={`${uid}-d`}>{detail}</p>
    <div className="gen-row"><button autoFocus className="btn tertiary" onClick={() => onDone(false)}>Cancel</button>
      <button className={destructive ? 'btn danger' : 'btn primary'} onClick={() => onDone(true)}>Confirm</button></div></dialog>;
}
