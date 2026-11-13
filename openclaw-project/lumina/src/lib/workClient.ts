/** One connection that keeps every screen's picture of the customer's tasks current. It replaces five separate timers (the chat, the thinking indicator, the activity list,
 *  the task drawer, the global list), each of which asked a different endpoint and could disagree with the others.
 *
 *  Preferred transport: the push gateway (text/event-stream), which sends state the moment it changes. The gateway needs a ticket from the signed-in session, lives for a short
 *  window, and is resumed with cursors (`rev` of the list, `rev` and `after` of the focused task), so a dropped connection loses nothing.
 *  Fallback: the same state from GET /v1/work and /v1/work/<id>, asked at a calm pace. Used automatically when the server runs no gateway (ticket 404), when the stream keeps
 *  failing, or when no greeting arrives (a proxy that buffers). The fallback returns after a while to try the stream again.
 *  A hidden tab asks for nothing either way.
 *
 *  Everything outside (network, timers, the stream constructor, visibility) is injected, so the whole lifecycle is tested without a browser. */
import { applyDraft, isMoving, isOpen, mergeRows, type Detail, type Draft, type Listing, type Row, type TaskSummary, type TaskView } from './work';

export interface Held { task: TaskView; rows: Row[]; cursor: number }
export interface WorkState {
  loaded: boolean; mode: 'connecting' | 'stream' | 'poll';
  tasks: TaskSummary[]; attention: number; rev: string;
  details: Record<string, Held>; drafts: Record<string, Draft>;
}
export interface Source { addEventListener(type: string, fn: (e: { data: string }) => void): void; close(): void; onerror: ((e: unknown) => void) | null }
export interface Deps {
  get<T>(path: string): Promise<T>;
  post<T>(path: string): Promise<T>;
  open?: (url: string) => Source;
  hidden?: () => boolean;
  onVisibility?: (fn: () => void) => () => void;
  now?: () => number;
  setTimeout?: (fn: () => void, ms: number) => unknown;
  clearTimeout?: (handle: unknown) => void;
}

const EMPTY: WorkState = { loaded: false, mode: 'connecting', tasks: [], attention: 0, rev: '', details: {}, drafts: {} };
export const HELLO_MS = 6000;                  // no greeting by then: something between us and the gateway is holding the stream back
export const STREAM_RETRY_MS = 5 * 60_000;     // how long the fallback runs before the stream is tried again
export const FAILS_BEFORE_POLL = 3;
export const pollEvery = (tasks: TaskSummary[]) => (tasks.some(isMoving) ? 1500 : tasks.some(isOpen) ? 4000 : 15000);
export const backoff = (fails: number) => Math.min(15000, 500 * 2 ** Math.max(0, fails - 1));

export class WorkClient {
  state: WorkState = EMPTY;
  private listeners = new Set<() => void>();
  private watching = new Map<string, number>();
  private focus = '';
  private source: Source | null = null;
  private ticket: { value: string; path: string; until: number } | null = null;
  private fails = 0; private pollUntil = 0; private running = false; private generation = 0;
  private timers = new Set<unknown>(); private draftBase: Record<string, number> = {};
  private unlisten: (() => void) | null = null;
  private d: Required<Deps>; private canStream: boolean;

  constructor(deps: Deps) {
    this.canStream = !!deps.open || typeof EventSource !== 'undefined';
    this.d = {
      open: deps.open ?? ((url: string) => new EventSource(url) as unknown as Source),      // only called when `canStream`
      hidden: deps.hidden ?? (() => typeof document !== 'undefined' && document.hidden),
      onVisibility: deps.onVisibility ?? (fn => { document.addEventListener('visibilitychange', fn); return () => document.removeEventListener('visibilitychange', fn); }),
      now: deps.now ?? (() => Date.now()),
      setTimeout: deps.setTimeout ?? ((fn, ms) => setTimeout(fn, ms)),
      clearTimeout: deps.clearTimeout ?? (h => clearTimeout(h as ReturnType<typeof setTimeout>)),
      get: deps.get, post: deps.post,
    };
  }

  // -- for React ------------------------------------------------------------------------------------------------------------------------------
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  snapshot = () => this.state;
  private set(patch: Partial<WorkState>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(fn => fn()); }
  private later(fn: () => void, ms: number) { const h = this.d.setTimeout(() => { this.timers.delete(h); fn(); }, ms); this.timers.add(h); return h; }

  // -- lifecycle ------------------------------------------------------------------------------------------------------------------------------
  start() {
    if (this.running) return;
    this.running = true; this.generation++;
    this.unlisten = this.d.onVisibility(() => { if (!this.running) return; if (this.d.hidden()) this.drop(); else this.go(); });
    this.go();
  }
  stop() {
    this.running = false; this.generation++; this.drop(); this.unlisten?.(); this.unlisten = null;
    this.state = EMPTY; this.ticket = null; this.fails = 0; this.pollUntil = 0; this.draftBase = {};
    this.listeners.forEach(fn => fn());
  }
  private drop() {
    this.source?.close(); this.source = null;
    this.timers.forEach(h => this.d.clearTimeout(h)); this.timers.clear();
  }
  /** (Re)establish whichever transport applies now. Safe to call at any time: it starts from scratch. */
  private go() {
    this.drop();
    if (!this.running || this.d.hidden()) return;
    this.generation++;
    if (this.d.now() < this.pollUntil || !this.canStream) void this.poll(this.generation);
    else void this.connect(this.generation);
  }

  /** A screen is showing this task in full: keep its detail current. The task most recently asked for that is still open gets the stream's attention. */
  watch(id: string) {
    this.watching.set(id, (this.watching.get(id) ?? 0) + 1);
    if (!this.state.details[id]) void this.fetchDetail(id);
    this.refocus();
    return () => {
      const n = (this.watching.get(id) ?? 1) - 1;
      if (n > 0) this.watching.set(id, n); else this.watching.delete(id);
      this.refocus();
    };
  }
  private refocus() {
    const ids = [...this.watching.keys()].reverse();
    const open = (id: string) => { const t = this.state.details[id]?.task ?? this.state.tasks.find(x => x.id === id); return !t || isOpen(t); };
    const next = ids.find(open) ?? ids[0] ?? '';
    if (next === this.focus) return;
    this.focus = next;
    if (this.running && this.state.mode === 'stream') this.later(() => this.go(), 30);          // several screens mounting at once settle on one focus before reconnecting
  }
  /** After the customer did something (sent, stopped, approved): do not wait for the next tick. */
  async refresh() { await Promise.all([this.fetchList(), ...[...this.watching.keys()].map(id => this.fetchDetail(id))]); }

  // -- applying what arrives ------------------------------------------------------------------------------------------------------------------
  private applyList(listing: Listing) {
    const before = new Map(this.state.tasks.map(t => [t.id, JSON.stringify(t)]));
    this.set({ tasks: listing.tasks, attention: listing.attention, rev: listing.rev, loaded: true });
    for (const id of this.watching.keys()) {                                                      // a watched task that is not the stream's focus is refreshed when its line changed
      if (id === this.focus && this.state.mode === 'stream') continue;
      const t = listing.tasks.find(x => x.id === id);
      if (t && before.get(id) !== JSON.stringify(t)) void this.fetchDetail(id);
    }
    this.refocus();
  }
  private applyDetail(detail: Detail) {
    const id = detail.task.id; const held = this.state.details[id];
    const rows = held && detail.cursor >= held.cursor ? mergeRows(held.rows, detail.rows) : detail.rows;
    // One update: the task's new state and the end of its draft are never shown apart (a finished task with its reply still "being written" for a frame).
    this.set({ details: { ...this.state.details, [id]: { task: detail.task, rows, cursor: detail.cursor } }, drafts: this.settled(id, detail.task) });
  }
  private applyDraftFrame(frame: { task: string; item: string; at: number; add: string; done: boolean }) {
    const held = this.state.drafts[frame.task];
    const next = applyDraft(held, frame, this.d.now());
    if (!next || next === held) return;
    if (!held || held.item !== next.item) this.draftBase[frame.task] = this.state.details[frame.task]?.task.messages ?? 0;
    this.set({ drafts: this.settled(frame.task, this.state.details[frame.task]?.task, { ...this.state.drafts, [frame.task]: next }) });
  }
  /** A finished draft goes away once its saved message has arrived (the chat then shows the message), or when the task is over. -> the drafts to keep. */
  private settled(id: string, task: TaskView | undefined, drafts = this.state.drafts) {
    const draft = drafts[id];
    if (!draft || !task || !((draft.done && task.messages > (this.draftBase[id] ?? 0)) || task.phase === 'ended')) return drafts;
    const { [id]: _gone, ...rest } = drafts;
    return rest;
  }

  // -- the fallback: ask ----------------------------------------------------------------------------------------------------------------------
  private async fetchList() {
    try {
      const r = await this.d.get<Listing & { unchanged?: boolean }>(`/v1/work${this.state.rev ? `?rev=${this.state.rev}` : ''}`);
      if (!r.unchanged) this.applyList(r); else if (!this.state.loaded) this.set({ loaded: true });
    } catch { /* keep the last picture; the next tick asks again */ }
  }
  private async fetchDetail(id: string) {
    const held = this.state.details[id];
    try {
      const r = await this.d.get<Detail & { unchanged?: boolean }>(`/v1/work/${id}?after=${held?.cursor ?? 0}${held ? `&rev=${held.task.rev}` : ''}`);
      if (!r.unchanged) this.applyDetail(r);
    } catch { /* not found or a blip: the screen shows what it has */ }
  }
  private async poll(generation: number) {
    if (this.state.mode !== 'poll') this.set({ mode: 'poll' });
    // A finished task's record changes only when its line in the list does (applyList asks again then), so only unfinished watched tasks are asked about every tick.
    const open = [...this.watching.keys()].filter(id => { const t = this.state.details[id]?.task; return !t || isOpen(t); });
    await Promise.all([this.fetchList(), ...open.map(id => this.fetchDetail(id))]);
    if (generation !== this.generation || !this.running) return;
    if (this.d.now() >= this.pollUntil && this.canStream) { this.go(); return; }
    this.later(() => { if (generation === this.generation) void this.poll(generation); }, pollEvery(this.state.tasks));
  }

  // -- the stream -----------------------------------------------------------------------------------------------------------------------------
  private fallBack(ms: number) { this.pollUntil = this.d.now() + ms; this.fails = 0; this.go(); }
  private async connect(generation: number) {
    if (!this.state.loaded) void this.fetchList();                                                // never make the first paint wait for a ticket
    if (!this.ticket || this.d.now() > this.ticket.until) {
      try {
        const t = await this.d.post<{ ticket: string; path: string; expires_in: number }>('/v1/work/ticket');
        this.ticket = { value: t.ticket, path: t.path, until: this.d.now() + Math.max(10, t.expires_in - 25) * 1000 };
      } catch (e) {
        if (generation !== this.generation) return;
        const status = (e as { status?: number }).status;
        if (status === 401) return;                                                               // signed out: the app is about to stop this client
        this.fallBack(status === 404 || status === 403 ? STREAM_RETRY_MS : 20_000);               // no gateway here, or the app is having a moment
        return;
      }
    }
    if (generation !== this.generation || !this.running) return;
    const held = this.focus ? this.state.details[this.focus] : undefined;
    const q = new URLSearchParams({ t: this.ticket.value, focus: this.focus, after: String(held?.cursor ?? 0), rev: this.state.rev, frev: held?.task.rev ?? '' });
    let greeted = false;
    const source = this.d.open(`${this.ticket.path}?${q}`);
    this.source = source;
    const mine = () => generation === this.generation && this.source === source;
    const failed = () => {
      if (!mine()) return;
      source.close(); this.source = null; this.fails += 1;
      if (!greeted) this.ticket = null;                                                           // refused before a greeting: the ticket may be the reason
      if (this.fails >= FAILS_BEFORE_POLL) this.fallBack(60_000);
      else { this.set({ mode: 'connecting' }); this.later(() => { if (generation === this.generation) this.go(); }, backoff(this.fails)); }
    };
    const hello = this.later(() => { if (!greeted) failed(); }, HELLO_MS);
    const on = (type: string, fn: (data: any) => void) => source.addEventListener(type, e => { if (!mine()) return; let data: unknown; try { data = JSON.parse(e.data); } catch { return; } fn(data); });
    on('hello', () => { greeted = true; this.fails = 0; this.d.clearTimeout(hello); this.timers.delete(hello); this.set({ mode: 'stream' }); });
    on('list', (listing: Listing) => this.applyList(listing));
    on('task', (detail: Detail) => this.applyDetail(detail));
    on('draft', frame => this.applyDraftFrame(frame));
    on('reopen', () => { if (mine()) this.go(); });
    on('bye', () => { if (mine()) { source.close(); this.source = null; this.fallBack(STREAM_RETRY_MS); } });
    source.onerror = failed;
  }
}
