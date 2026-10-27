// The response document protocol: parse and migrate documents, the streaming event reducer, and the text-first envelope scanner.
//
// Wire format inside a reply: prose first (streams at once), then optionally one ```lumina-doc fence. The fence body is either a single JSON document
// or JSON Lines: an optional header {"version":"1.0","responseId":"..."}, {"dataset":"id",...} lines, and one block per line. A line is parsed only when it is
// complete, so no incomplete JSON is ever parsed and every finished block can mount while later ones are still arriving.
import { REGISTRY } from './registry';
import { documentSchema, treeShape, children, parseBlock, datasetSchema, LIMITS, SCHEMA_VERSION, presentationPlanSchema, type Block, type Dataset, type PresentationPlan, type BlockIssue } from './schemas';

export type Slot =
  | { status: 'ready'; id: string; block: Block; fallback: string }
  | { status: 'pending'; id: string; type: string }
  | { status: 'invalid'; id: string; type: string; reason: string; fallback: string };
export interface GenDocument { version: typeof SCHEMA_VERSION; responseId: string; slots: Slot[]; datasets: Record<string, Dataset>; presentationPlan?: PresentationPlan; issues: BlockIssue[] }

/** Plain text a failed or unsupported block degrades to: its own fallback, else the title and obvious text props. Never empty. */
export function fallbackText(raw: unknown): string {
  const rec = (raw && typeof raw === 'object' ? raw : {}) as Record<string, any>;
  if (typeof rec.fallback === 'string' && rec.fallback) return rec.fallback;
  const p = rec.props && typeof rec.props === 'object' ? rec.props : {};
  const bits = [p.title, p.label, p.text, p.content, p.description].filter((x): x is string => typeof x === 'string' && !!x);
  if (p.value !== undefined && typeof p.value !== 'object') bits.push(String(p.value));
  return (bits.join(' — ') || 'This part of the answer could not be shown.').slice(0, 600);
}

export const slotFor = (raw: unknown): Slot => {
  const r = parseBlock(raw);
  if (r.ok) { const problem = actionIssue(r.block.props, REGISTRY[r.block.type].supportedActions); if (problem) return { status: 'invalid', id: r.block.id, type: r.block.type, reason: problem, fallback: fallbackText(raw) }; return { status: 'ready', id: r.block.id, block: r.block, fallback: fallbackText(r.block) }; }
  return { status: 'invalid', id: r.issue.id, type: r.issue.type, reason: r.issue.reason, fallback: fallbackText(raw) };
};

function actionIssue(value: unknown, allowed: readonly string[]): string | null {
  if (!value || typeof value !== 'object') return null;
  if (Array.isArray(value)) { for (const v of value) { const issue = actionIssue(v, allowed); if (issue) return issue; } return null; }
  const v = value as Record<string, unknown>;
  if ('type' in v && 'props' in v) return null; // child nodes have their own capabilities
  if (typeof v.kind === 'string' && !allowed.includes(v.kind)) return `action ${v.kind} is not supported by this component`;
  for (const item of Object.values(v)) { const issue = actionIssue(item, allowed); if (issue) return issue; }
  return null;
}

/** Document-wide checks the per-block schema cannot see: every dataRef must resolve to a dataset in this document. */
function resolveRefs(slots: Slot[], datasets: Record<string, Dataset>): Slot[] {
  return slots.map(s => {
    if (s.status !== 'ready' || !s.block.dataRef || Object.hasOwn(datasets, s.block.dataRef)) return s;
    return { status: 'invalid', id: s.id, type: s.block.type, reason: `dataRef "${s.block.dataRef}" does not exist in this response`, fallback: s.fallback };
  });
}

export function emptyDocument(responseId = 'local'): GenDocument { return { version: SCHEMA_VERSION, responseId, slots: [], datasets: {}, issues: [] }; }

/** Plain-text messages (everything written before documents existed) become a one-block document. */
export function fromPlainText(content: string, responseId = 'legacy'): GenDocument {
  const doc = emptyDocument(responseId);
  doc.slots = [slotFor({ id: 'text', type: 'text', props: { content: content.slice(0, 8000) || ' ', format: 'markdown' } })];
  return doc;
}

/** Older shapes are lifted to 1.0; a major version this build does not know is refused (the caller shows the prose). */
export function migrate(raw: unknown): { ok: true; value: unknown } | { ok: false; reason: string } {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, reason: 'not an object' };
  const rec = { ...(raw as Record<string, unknown>) };
  if (rec.type === 'document') delete rec.type; // persisted envelope, not a second document field
  if (rec.version === undefined && Array.isArray(rec.blocks)) rec.version = SCHEMA_VERSION;       // 0.x: documents written before the version field
  if (typeof rec.version !== 'string' || rec.version.split('.')[0] !== SCHEMA_VERSION.split('.')[0]) return { ok: false, reason: `unsupported version ${String(rec.version)}` };
  rec.version = SCHEMA_VERSION;                                                                     // 1.x minor differences are ignored fields-wise by the strict schema, so only 1.0 is accepted below
  if (typeof rec.responseId !== 'string') rec.responseId = 'migrated';
  return { ok: true, value: rec };
}

export function parseDocument(raw: unknown): GenDocument | { error: string } {
  const m = migrate(raw);
  if (!m.ok) return { error: m.reason };
  const env = documentSchema.safeParse(m.value);
  if (!env.success) return { error: env.error.issues[0]?.message ?? 'invalid document' };
  const shape = treeShape(env.data.blocks);
  if (shape.count > LIMITS.nested || shape.depth > LIMITS.depth) return { error: 'document nesting limit exceeded' };
  const datasets: Record<string, Dataset> = {};
  for (const [k, v] of Object.entries(env.data.datasets ?? {})) { const d = datasetSchema.safeParse(v); if (d.success) datasets[k] = d.data; }
  const seen = new Set<string>();
  const slots = resolveRefs(env.data.blocks.map(slotFor).filter(s => (seen.has(s.id) ? false : (seen.add(s.id), true))), datasets);
  const nodeIds = new Set<string>();
  const checked = slots.map(s => {
    if (s.status !== 'ready') return s;
    const stack: any[] = [s.block]; let duplicate = false;
    while (stack.length) { const node = stack.pop(); if (nodeIds.has(node.id)) duplicate = true; nodeIds.add(node.id); stack.push(...children(node)); }
    if (duplicate) return { status: 'invalid' as const, id: s.id, type: s.block.type, reason: 'duplicate node id', fallback: s.fallback };
    const hint = env.data.presentationPlan?.blocks.find(h => h.blockId === s.id);
    if (hint?.layout && !s.block.layout) {
      const layout = hint.layout === 'grid' ? { columns: 2 } : hint.layout === 'horizontal' ? { direction: 'row' as const } : { direction: 'column' as const };
      return { ...s, block: { ...s.block, layout } };
    }
    return s;
  });
  return { version: SCHEMA_VERSION, responseId: env.data.responseId, slots: checked, datasets, presentationPlan: env.data.presentationPlan, issues: checked.filter(s => s.status === 'invalid').map(s => ({ id: s.id, type: (s as any).type, reason: (s as any).reason })) };
}

// ---- reply splitting -------------------------------------------------------------------------------------------------------------------------
const OPEN = /```lumina-doc[ \t]*\n/;
export interface Reply { prose: string; fence: string | null; open: boolean }
/** Separates the prose from the first lumina-doc fence. An unfinished fence is `open` and its text is never shown. */
export function splitReply(content: string): Reply {
  const m = OPEN.exec(content);
  if (!m) return { prose: content, fence: null, open: false };
  const after = content.slice(m.index + m[0].length); const end = after.indexOf('```');
  const rest = end < 0 ? '' : after.slice(end + 3);
  return { prose: (content.slice(0, m.index) + rest.replace(/```lumina-doc[ \t]*\n[\s\S]*?(```|$)/g, '')).replace(/\n{3,}/g, '\n\n').trim(), fence: end < 0 ? after : after.slice(0, end), open: end < 0 };
}

/** Fence body -> document. JSON document first; otherwise JSON Lines. Lines that fail are kept as invalid slots, never thrown. */
export function parseFence(body: string): GenDocument | { error: string } {
  const trimmed = body.trim();
  if (!trimmed) return { error: 'empty' };
  if (trimmed.length > LIMITS.bytes) return { error: 'document too large' };
  try { const whole = JSON.parse(trimmed); if (whole && typeof whole === 'object' && 'blocks' in whole) return parseDocument(whole); } catch { /* maybe JSON Lines */ }
  const acc = new LineAccumulator();
  for (const line of trimmed.split('\n')) acc.line(line);
  return acc.document();
}

class LineAccumulator {
  responseId = 'local'; blocks: unknown[] = []; datasets: Record<string, unknown> = {}; plan: unknown; bad = 0;
  line(line: string): { block?: unknown; dataset?: string } {
    const s = line.trim(); if (!s) return {};
    let v: any; try { v = JSON.parse(s); } catch { this.bad++; return {}; }
    if (!v || typeof v !== 'object') return {};
    if (typeof v.dataset === 'string') { const { dataset, ...rest } = v; this.datasets[dataset] = rest; return { dataset }; }
    if (typeof v.presentationPlan === 'object') { this.plan = v.presentationPlan; return {}; }
    if (typeof v.type !== 'string') { if (typeof v.responseId === 'string') this.responseId = v.responseId.slice(0, 64); return {}; }
    const i = this.blocks.findIndex((b: any) => b?.id === v.id);
    if (i >= 0) this.blocks[i] = v; else this.blocks.push(v);
    return { block: v };
  }
  document() {
    return parseDocument({ version: SCHEMA_VERSION, responseId: this.responseId, blocks: this.blocks.slice(0, LIMITS.blocks), datasets: this.datasets, ...(presentationPlanSchema.safeParse(this.plan).success ? { presentationPlan: this.plan } : {}) });
  }
}

// ---- streaming events ------------------------------------------------------------------------------------------------------------------------
export type StreamEvent =
  | { type: 'response.started'; seq: number; responseId: string }
  | { type: 'block.started'; seq: number; responseId: string; id: string; blockType: string }
  | { type: 'block.delta'; seq: number; responseId: string; id: string; text: string }
  | { type: 'block.completed'; seq: number; responseId: string; id: string; block: unknown }
  | { type: 'block.updated'; seq: number; responseId: string; id: string; block: unknown }
  | { type: 'dataset.completed'; seq: number; responseId: string; id: string; dataset: unknown }
  | { type: 'response.completed'; seq: number; responseId: string }
  | { type: 'response.error'; seq: number; responseId: string; message: string; retriable: boolean };

export interface StreamState {
  responseId: string | null; status: 'idle' | 'streaming' | 'complete' | 'error'; slots: Slot[]; datasets: Record<string, Dataset>; lastSeq: number;
  held: Record<number, StreamEvent>; partial: Record<string, string>; error?: { message: string; retriable: boolean };
}
export const initialStream = (): StreamState => ({ responseId: null, status: 'idle', slots: [], datasets: {}, lastSeq: 0, held: {}, partial: {} });
const MAX_HELD = 64;

function setSlot(slots: Slot[], slot: Slot): Slot[] {
  const i = slots.findIndex(s => s.id === slot.id);
  if (i < 0) return slots.length >= LIMITS.blocks ? slots : [...slots, slot];
  const next = slots.slice(); next[i] = slot; return next;                       // same id, same position: the key never changes, so local state survives
}

function apply(s: StreamState, e: StreamEvent): StreamState {
  switch (e.type) {
    case 'response.started': return { ...initialStream(), responseId: e.responseId, status: 'streaming', lastSeq: e.seq };
    case 'block.started': return { ...s, slots: setSlot(s.slots, { status: 'pending', id: e.id, type: e.blockType }) };
    case 'block.delta': {
      const text = ((s.partial[e.id] ?? '') + e.text).slice(0, 8000);
      const cur = s.slots.find(x => x.id === e.id);
      // Prose streams as a text block whose content grows; every other kind waits for block.completed.
      if (cur && ((cur.status === 'pending' && cur.type === 'text') || (cur.status === 'ready' && cur.block.type === 'text' && e.id in s.partial))) return { ...s, partial: { ...s.partial, [e.id]: text }, slots: setSlot(s.slots, slotFor({ id: e.id, type: 'text', props: { content: text || ' ', format: 'markdown' } })) };
      return { ...s, partial: { ...s.partial, [e.id]: text } };
    }
    case 'block.completed': case 'block.updated': {
      const { [e.id]: _drop, ...partial } = s.partial;
      return { ...s, partial, slots: resolveRefs(setSlot(s.slots, slotFor(e.block)), s.datasets) };
    }
    case 'dataset.completed': { const d = datasetSchema.safeParse(e.dataset); return d.success ? { ...s, datasets: { ...s.datasets, [e.id]: d.data }, slots: resolveRefs(s.slots, { ...s.datasets, [e.id]: d.data }) } : s; }
    case 'response.completed': return { ...s, status: 'complete', slots: s.slots.map(x => (x.status === 'pending' && x.type !== 'text' ? { status: 'invalid', id: x.id, type: x.type, reason: 'the block never finished', fallback: 'This part of the answer did not finish loading.' } as Slot : x)) };
    case 'response.error': return { ...s, status: 'error', error: { message: e.message, retriable: e.retriable } };
  }
}

/** Applies one event. Duplicates and replays are ignored; early events wait until the gap fills; events from another response are ignored. */
export function reduce(state: StreamState, e: StreamEvent): StreamState {
  if (e.type === 'response.started') return state.responseId === e.responseId && state.lastSeq >= e.seq ? state : apply(state, e);
  if (state.responseId === null || e.responseId !== state.responseId) return state;
  if (e.seq <= state.lastSeq) return state;
  if (state.status === 'complete' || state.status === 'error') return state;
  if (e.seq !== state.lastSeq + 1) return Object.keys(state.held).length >= MAX_HELD ? state : { ...state, held: { ...state.held, [e.seq]: e } };
  let next = { ...apply(state, e), lastSeq: e.seq };
  while (next.held[next.lastSeq + 1]) { const h = next.held[next.lastSeq + 1]; const { [next.lastSeq + 1]: _x, ...held } = next.held; next = { ...apply({ ...next, held }, h), lastSeq: h.seq, held }; }
  return next;
}

/** Text-first envelope scanner: feed it the growing reply, get events. Prose is emitted as soon as it arrives; fence lines as soon as each completes. */
export class EnvelopeStream {
  private seq = 0; private buf = ''; private inFence = false; private proseId = 'prose-0'; private proseN = 0; private started = false; private acc = new LineAccumulator(); private tail = '';
  constructor(readonly responseId: string) {}
  private ev<T extends StreamEvent>(e: Omit<T, 'seq' | 'responseId'>): StreamEvent { return { ...e, seq: ++this.seq, responseId: this.responseId } as StreamEvent; }
  start(): StreamEvent[] { this.started = true; return [{ type: 'response.started', seq: ++this.seq, responseId: this.responseId }]; }
  feed(chunk: string): StreamEvent[] {
    const out: StreamEvent[] = this.started ? [] : this.start();
    this.buf += chunk;
    for (;;) {
      if (!this.inFence) {
        const m = OPEN.exec(this.buf);
        if (!m) {
          // Hold back a possible partial fence marker at the end (the longest suffix that could still become "```lumina-doc"); everything before it is prose.
          const marker = '```lumina-doc\n'; let hold = this.buf.length;
          const tailSpaces = /```lumina-doc[ \t]*$/.exec(this.buf);
          if (tailSpaces) hold = tailSpaces.index;
          else for (let k = Math.min(this.buf.length, marker.length - 1); k >= 1; k--) if (marker.startsWith(this.buf.slice(-k))) { hold = this.buf.length - k; break; }
          this.prose(this.buf.slice(0, hold), out); this.buf = this.buf.slice(hold); return out;
        }
        this.prose(this.buf.slice(0, m.index), out); this.buf = this.buf.slice(m.index + m[0].length); this.inFence = true;
      }
      const close = this.buf.indexOf('```');
      const keep = close < 0 ? Math.min(2, (/`+$/.exec(this.buf)?.[0].length ?? 0)) : 0;        // a closing fence may arrive split across chunks
      const body = close < 0 ? this.buf.slice(0, this.buf.length - keep) : this.buf.slice(0, close);
      this.tail += body; this.buf = close < 0 ? this.buf.slice(this.buf.length - keep) : this.buf.slice(close + 3);
      const nl = this.tail.lastIndexOf('\n'); const lines = nl < 0 ? [] : this.tail.slice(0, nl).split('\n'); this.tail = nl < 0 ? this.tail : this.tail.slice(nl + 1);
      if (close >= 0 && this.tail.trim()) { lines.push(this.tail); this.tail = ''; }
      for (const l of lines) this.line(l, out);
      if (close < 0) return out;
      this.inFence = false; this.proseN++; this.proseId = `prose-${this.proseN}`; this.proseStarted = false; this.afterFence = true;
    }
  }
  private afterFence = false;
  private prose(text: string, out: StreamEvent[]) {
    if (this.afterFence && text) { text = text.replace(/^\n/, ''); if (text) this.afterFence = false; }       // the newline that ends the fence line is not prose
    if (!text) return;
    if (!text.trim() && !this.proseStarted) return;
    if (!this.proseStarted) { out.push(this.ev({ type: 'block.started', id: this.proseId, blockType: 'text' } as any)); this.proseStarted = true; }
    out.push(this.ev({ type: 'block.delta', id: this.proseId, text } as any));
  }
  private proseStarted = false;
  private line(l: string, out: StreamEvent[]) {
    const r = this.acc.line(l);
    if (r.dataset) out.push(this.ev({ type: 'dataset.completed', id: r.dataset, dataset: this.acc.datasets[r.dataset] } as any));
    if (r.block) { const id = String((r.block as any).id ?? ''); out.push(this.ev({ type: 'block.started', id, blockType: String((r.block as any).type) } as any), this.ev({ type: 'block.completed', id, block: r.block } as any)); }
  }
  /** Closes the prose block (so the next prose segment gets a fresh id) and completes the response. */
  finish(): StreamEvent[] { return [this.ev({ type: 'response.completed' } as any)]; }
  fail(message: string, retriable = true): StreamEvent[] { return [this.ev({ type: 'response.error', message, retriable } as any)]; }
}
