import { ApiError } from '../lib/api';
import { interactionError } from './errors';

export type LocalState = Record<string, Record<string, unknown>>;
export interface RemoteState { version: number; state: LocalState }
export interface DraftHost {
  saveState?(state: LocalState): Promise<void>;
  loadState?(): Promise<RemoteState>;
  diagnostic?(kind: string, category: string): void;
}
type Snapshot = { state: LocalState; saving: boolean; error: string; conflict: boolean; dirty: boolean };
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
/** Three-way merge: disjoint edits combine, overlapping edits require an explicit decision. Arrays are atomic. */
export function mergeState(base: unknown, local: unknown, remote: unknown): { value: any; conflict: boolean } {
  if (equal(local, base)) return { value: remote, conflict: false };
  if (equal(remote, base) || equal(local, remote)) return { value: local, conflict: false };
  if (object(local) && object(remote) && (base === undefined || object(base))) {
    const result: Record<string, unknown> = {}; let conflict = false;
    for (const key of new Set([...Object.keys(base ?? {}), ...Object.keys(local), ...Object.keys(remote)])) {
      const item = mergeState((base as any)?.[key], local[key], remote[key]);
      if (item.value !== undefined) result[key] = item.value;
      conflict ||= item.conflict;
    }
    return { value: result, conflict };
  }
  return { value: local, conflict: true };
}

/** Memory only. Retains unsaved edits and event identities across route remounts, never on disk. */
export class ArtifactDraft {
  private snapshot: Snapshot;
  private baseline: LocalState;
  private remote?: LocalState;
  private listeners = new Set<() => void>();
  private work: Promise<void> | null = null;
  private cancelled = false;
  private paused = false;
  host: DraftHost = {};
  readonly events = new Map<string, string>();
  readonly inFlight = new Set<string>();
  constructor(readonly version: number, state: LocalState) {
    this.baseline = state;
    this.snapshot = { state, saving: false, error: '', conflict: false, dirty: false };
  }
  getSnapshot = () => this.snapshot;
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  private update(patch: Partial<Snapshot>) {
    if (this.cancelled) return;
    this.snapshot = { ...this.snapshot, ...patch };
    for (const fn of this.listeners) fn();
  }
  patch(id: string, patch: Record<string, unknown>) {
    this.update({ state: { ...this.snapshot.state, [id]: { ...this.snapshot.state[id], ...patch } }, dirty: true });
  }
  reopen(state: LocalState) {
    this.paused = false;
    const merged = mergeState(this.baseline, this.snapshot.state, state);
    if (merged.conflict) {
      this.remote = state;
      this.update({ conflict: true, error: 'The same answers were edited elsewhere. Choose which edits to keep. Your edits are still here.' });
    } else {
      this.baseline = state;
      this.update({ state: merged.value, dirty: !equal(merged.value, state), error: '', conflict: false });
    }
  }
  pause() { this.paused = true; }
  cancel() { this.update({ dirty: false, error: '', conflict: false }); this.cancelled = true; this.events.clear(); this.inFlight.clear(); this.listeners.clear(); }
  async resolve(keepMine: boolean) {
    if (!this.remote) return;
    const next = keepMine ? mergeState(this.baseline, this.snapshot.state, this.remote).value : this.remote;
    this.baseline = this.remote; this.remote = undefined;
    this.update({ state: next, conflict: false, error: '', dirty: !equal(next, this.baseline) });
    if (keepMine) await this.flush();
  }
  flush = (): Promise<void> => {
    if (this.cancelled || this.paused || !this.host.saveState) return Promise.resolve();
    if (this.work) return this.work;
    // Start on the microtask queue, so concurrent callers share the same claim.
    this.work = Promise.resolve().then(async () => {
      if (this.snapshot.conflict) throw new Error('unresolved conflict');
      this.update({ saving: true });
      try {
        let reconciled = false;
        while (!this.cancelled && !this.paused && !equal(this.snapshot.state, this.baseline)) {
          const next = this.snapshot.state;
          try { await this.host.saveState!(next); this.baseline = next; this.update({ error: '' }); }
          catch (error) {
            if (error instanceof ApiError && error.status === 409 && this.host.loadState && !reconciled) {
              const remote = await this.host.loadState();
              if (remote.version !== this.version) {
                this.update({ error: 'The assistant updated this answer. Your unsaved edits are kept here. Save a copy before opening the latest version.' });
                throw error;
              }
              const merge = mergeState(this.baseline, this.snapshot.state, remote.state);
              this.remote = remote.state;
              if (merge.conflict) {
                this.update({ conflict: true, error: 'The same answers were edited elsewhere. Choose which edits to keep. Your edits are still here.' });
                throw error;
              }
              this.baseline = remote.state; this.remote = undefined;
              this.update({ state: merge.value }); reconciled = true; continue;
            }
            this.update({ error: interactionError(error) }); throw error;
          }
        }
        this.update({ dirty: !equal(this.snapshot.state, this.baseline) });
      } catch (error) {
        if (!this.snapshot.error) this.update({ error: interactionError(error) });
        this.host.diagnostic?.('save_failed', error instanceof ApiError && error.status === 409 ? 'conflict' : 'network');
        throw error;
      } finally { this.update({ saving: false }); }
    }).finally(() => { this.work = null; });
    return this.work;
  };
}
const drafts = new Map<string, ArtifactDraft>();
export function artifactDraft(scope: string, version: number, state: LocalState): ArtifactDraft {
  const key = `${scope}:${version}`;
  let draft = drafts.get(key);
  if (!draft) {
    if (drafts.size >= 100) { const clean = [...drafts].find(([, d]) => !d.getSnapshot().dirty && !d.getSnapshot().saving && d.events.size === 0); if (clean) drafts.delete(clean[0]); }
    draft = new ArtifactDraft(version, state); drafts.set(key, draft); } else { draft.reopen(state); }
  return draft;
}
export function previousDrafts(scope: string, version: number): ArtifactDraft[] { return [...drafts].filter(([k, d]) => k.startsWith(`${scope}:`) && d.version !== version && d.getSnapshot().dirty).map(([, d]) => d); }
let account: string | null = null;
export function bindDraftAccount(identity: string) { if (account !== null && account !== identity) clearArtifactDrafts(); account = identity; }
export function pauseArtifactDrafts() { for (const d of drafts.values()) d.pause(); }
if (typeof window !== 'undefined') window.addEventListener('beforeunload', e => {
  if ([...drafts.values()].some(d => d.getSnapshot().dirty)) { e.preventDefault(); e.returnValue = ''; }
});
export function clearArtifactDrafts() { for (const d of drafts.values()) d.cancel(); drafts.clear(); account = null; }
export function downloadAnswers(state: LocalState) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = 'lumina-unsaved-answers.json'; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
