/** The customer-facing picture of a task, as the server computes it (platform/agentai_platform/work.py). Nothing here re-derives status: these are the types, the cursor merge,
 *  and the few words the screen composes from fields the server already decided. */
import type { OrbState } from './orbs';

export type Phase = 'queued' | 'paused' | 'starting' | 'working' | 'needs_you' | 'stopping' | 'reconnecting' | 'ended';
export type Tone = 'pending' | 'attention' | 'live' | 'ok' | 'unsure' | 'bad' | 'muted';
export type Outcome = 'completed' | 'partial' | 'blocked' | 'failed' | 'cancelled';
export type Verification = 'verified' | 'unverified' | 'not_applicable';

export interface Doing { key: string; category: string; label: string; detail: string }
export interface Approval { kind: 'approval'; id: string; tool: string; service: string; arguments: Record<string, unknown>; expires_epoch: number }
/** What a prepared change will do, rendered by the server from the exact payload that would be sent (never from the assistant's words). */
export interface ChangePreview {
  title: string; destination: string; summary: string; changes: { field: string; before: unknown; after: unknown }[]; affected: number;
  irreversible: string | null; can_undo: boolean; undo_seconds: number | null; compensations: { kind: string; label: string }[];
}
/** A change in a connected service that waits for the customer's approval of exactly this payload. */
export interface ActionNeed { kind: 'action'; id: string; payload_hash: string; preview: ChangePreview; needs_admin: boolean; approved_by_you: boolean; expires_epoch: number }
/** Several changes approved together: one approval covers every step shown. */
export interface WorkflowNeed { kind: 'workflow'; id: string; title: string; steps_hash: string; steps: ChangePreview[]; expires_epoch: number }
/** One option of a question: what to pick, and what the assistant knows of it (as the page or the seller shows it). */
export interface AskOption { label: string; price?: string; details?: string }
/** A question the assistant asked. `questions` (one to three) is what the server sends today; `question` and `options` are the same first question, for older rows.
 *  `in_place`: the task is waiting for this answer right now, and carries on with it in the same run. */
export interface QuestionNeed { kind: 'question'; id: string; question: string; options: string[]; questions?: { question: string; options: AskOption[] }[]; in_place?: boolean; expires_epoch: number }
export type Need = Approval | ActionNeed | WorkflowNeed | QuestionNeed | { kind: 'browser_question' | 'browser_control' | 'browser_handoff'; before?: string } | { kind: 'location_permission' };
/** The needs that are answered right where the task is shown (a prompt with its own buttons), as opposed to the ones answered in the browser view. */
export const isPrompt = (n: Need): n is Approval | ActionNeed | WorkflowNeed | QuestionNeed => n.kind === 'approval' || n.kind === 'action' || n.kind === 'workflow' || n.kind === 'question';
export interface Controls { stop: boolean; pause: boolean; resume: boolean; retry: boolean; goal_resume: boolean; goal_clear: boolean; steer: boolean }

/** What every list shows. */
export interface TaskSummary {
  id: string; conversation_id: string | null; title: string; follows: string | null; created_epoch: number; state: string;
  phase: Phase; label: string; tone: Tone; activity: Doing | null; now: Doing[]; ahead: number | null; wait?: 'your_task' | 'assistant' | null;
  /** What the run is waiting for while no tool runs, as the server names it; when that began; and about how long such a wait takes (measured by the server, or absent). */
  waiting_for?: 'model' | 'provider' | 'workspace' | null; since_epoch?: number | null; expect_seconds?: number | null;
  attention: string | null; attention_label: string; outcome: Outcome | null; verification: Verification | null; note: string;
  goal: boolean; continuing: boolean; retry_of: string | null; controls: Controls; needs: Need[]; steps: number;
}
export interface Step { id: string; title: string; status: 'pending' | 'running' | 'done' | 'blocked' | 'failed' | 'skipped' | 'stopped' | 'unreported'; checkpoint?: string; result?: string }
export interface Evidence {
  steps: number; failed_steps: number; searches: number; commands: number; sites: string[]; files: string[];
  saved: { id: string; version: number; name: string; size: number }[]; approvals: { label: string; decision: string }[]; duration_s: number | null;
  /** Steps that did not work, each with the server's sentence for why, and whether a later step of the same kind worked. */
  failed?: { label: string; detail: string; why: string; recovered: boolean }[]; unrecovered?: number;
}
/** One task in full. */
export interface TaskView extends TaskSummary {
  request: string; result: string | null; checklist: { mode: 'direct' | 'plan'; steps: Step[] } | null; evidence: Evidence; messages: number; cancel_requested: boolean;
  browser: { status: string; live: boolean; host: string } | null; ended_epoch: number | null; rev: string;
  /** Set when the task is over and a step failed that nothing made up for. */
  trouble?: { steps: number; why: string };
}
/** One thing that happened. A tool call is one row from start to finish; rows that ran at the same time share `group`. */
export interface Row {
  key: string; kind: 'tool' | 'note' | 'error' | 'approval' | 'file'; category: string; label: string; detail: string; output: string;
  status: 'running' | 'done' | 'failed' | 'note' | 'waiting' | 'approved' | 'declined' | 'expired'; at: number; ended_at: number | null; first: number; seq: number; group: string | null;
  /** For a step that did not do what was asked: the server's registered reason code, and the one sentence it gives for it. Absent on rows that have none. */
  reason?: string; why?: string;
  /** The browser's own steps inside one browser call, in order, in the server's words. A call of exactly one step has none: its label is the step. */
  steps?: { label: string; status: 'done' | 'failed'; at: number }[];
}
/** Where a task's browser is shown: beside its conversation (the chat opens with the browser as a pane on the right), or on the task's own page when it has no chat. */
export const browserPath = (task: { id: string; conversation_id: string | null }) => (task.conversation_id ? `/chat/${task.conversation_id}?browser=${task.id}` : `/live/${task.id}`);
export interface Listing { tasks: TaskSummary[]; attention: number; rev: string }
export interface Detail { task: TaskView; rows: Row[]; cursor: number; trimmed?: number }
/** The reply being written right now. Never stored: the saved message replaces it. */
export interface Draft { item: string; text: string; done: boolean; at: number }

/** Rows the client holds + rows touched since its cursor -> the rows now. A row is replaced by key and keeps its place (the order things started in). */
export function mergeRows(held: Row[], touched: Row[]): Row[] {
  if (!touched.length) return held;
  const byKey = new Map(held.map(r => [r.key, r]));
  for (const r of touched) byKey.set(r.key, r);
  return [...byKey.values()].sort((a, b) => a.first - b.first);
}

/** A draft frame adds text at a position. Text the client does not have the start of is ignored until a frame that starts at 0 arrives (never show a reply with a hole in it). */
export function applyDraft(held: Draft | undefined, frame: { item: string; at: number; add: string; done: boolean }, now: number): Draft | undefined {
  if (frame.at === 0) return { item: frame.item, text: frame.add, done: frame.done, at: now };
  if (!held || held.item !== frame.item || held.text.length !== frame.at) return held;
  return { item: frame.item, text: held.text + frame.add, done: frame.done, at: now };
}

export const isOpen = (t: Pick<TaskSummary, 'phase'>) => t.phase !== 'ended';
/** Is Lumina working on it or about to (so: an orb, a live badge, faster refresh)? A paused task and one waiting for the customer are open but nothing is moving. */
/** What to say beside the status while the task waits for something the server named. A time shown is measured since the wait began, or is the server's own figure
 *  for such a wait; nothing is estimated here. */
export function waitLine(t: Pick<TaskSummary, 'waiting_for' | 'since_epoch' | 'expect_seconds'>, nowMs: number): string {
  if (!t.waiting_for) return '';
  if (t.waiting_for === 'workspace') return t.expect_seconds ? `Its workspace is starting up. This usually takes about ${duration(t.expect_seconds)}.` : 'Its workspace is starting up.';
  if (t.waiting_for === 'provider') return t.expect_seconds ? `It asked for a pause of about ${duration(t.expect_seconds)}. The task carries on by itself.` : 'It asked for a short pause. The task carries on by itself.';
  const waited = t.since_epoch ? Math.floor(nowMs / 1000) - t.since_epoch : 0;
  return waited >= 10 ? `${duration(waited)} so far` : '';
}
/** One line for a finished task that had a step fail with nothing making up for it. */
export const troubleLine = (t: { steps: number; why: string }) => `${t.steps} ${t.steps === 1 ? 'step' : 'steps'} did not work${t.why ? `: ${t.why}` : '.'}`;

export const isMoving = (t: Pick<TaskSummary, 'phase'>) => ['queued', 'starting', 'working', 'stopping', 'reconnecting'].includes(t.phase);

/** Which orb animation shows what the task is doing. Only a task that is really doing something gets a moving orb. */
export function orbFor(t: Pick<TaskSummary, 'phase' | 'activity'>): OrbState | null {
  if (t.phase === 'starting' || t.phase === 'reconnecting') return 'connecting';
  if (t.phase === 'queued') return 'breathing';
  if (t.phase !== 'working') return null;
  switch (t.activity?.category) {
    case 'search': return 'searching';
    case 'read': case 'browse': return 'connecting';
    case 'command': return 'working';
    case 'file': return 'composing';
    case 'subagent': return 'weaving';
    default: return 'breathing';
  }
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))}s`;
  const m = Math.floor(seconds / 60); const s = Math.round(seconds % 60);
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
const count = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`;

/** The short record of the work under a finished answer, from Lumina's own counts ("6 steps · 2 sites · 1 file · 1m 42s"). Empty when no tool was used. */
export function receipt(e: Evidence | undefined): string[] {
  if (!e) return [];
  const parts: string[] = [];
  if (e.steps) parts.push(count(e.steps, 'step'));
  if (e.sites.length) parts.push(count(e.sites.length, 'site'));
  if (e.saved.length) parts.push(count(e.saved.length, 'file'));
  if (e.failed_steps) parts.push(`${e.failed_steps} did not work`);
  if (e.duration_s) parts.push(duration(e.duration_s));
  return parts;
}

/** What "Done · not confirmed" and its neighbours mean, in a sentence. The words are fixed; the server's note (also from a fixed vocabulary) is preferred when it has one. */
export function verdict(t: Pick<TaskSummary, 'outcome' | 'verification' | 'note' | 'continuing'>): string {
  if (!t.outcome) return '';
  if (t.outcome === 'completed') {
    if (t.verification === 'verified') return 'Lumina checked the result against its own records.';
    if (t.verification === 'unverified') return t.note || 'The run finished, but nothing Lumina can check confirms the result.';
    return '';
  }
  if (t.outcome === 'partial') return t.note || (t.continuing ? 'The next turn is on its way.' : 'Some of this was not finished.');
  if (t.outcome === 'blocked') return t.note || 'Something stopped this that Lumina could not get past.';
  if (t.outcome === 'failed') return t.note || 'The run ended with an error before it finished.';
  return 'Stopped at your request. What was already done is kept.';
}

/** One line for a need that is not a permission prompt. */
export function needLine(n: Need): string {
  switch (n.kind) {
    case 'browser_question': return 'Lumina has a question about the page it is on.';
    case 'browser_control': return 'You have the browser. Lumina waits until you hand it back.';
    case 'browser_handoff': return n.before ? `Lumina stopped before: ${n.before}. This step is yours.` : 'Lumina reached a step only you can do (a sign-in, a payment, a human check).';
    case 'location_permission': return 'Your browser is asking whether Lumina may use your location.';
    default: return '';
  }
}

export const toolWords = (tool: string) => { const t = tool.replace(/[_-]+/g, ' ').trim(); return t ? t[0].toUpperCase() + t.slice(1) : 'A tool'; };
const short = (v: unknown) => { const s = typeof v === 'string' ? v : JSON.stringify(v); return s.length > 48 ? s.slice(0, 47) + '…' : s; };
/** The first few arguments of a call on one quiet line, so the customer sees at a glance what is being asked. */
export function argumentLine(args: unknown): string {
  if (!args || typeof args !== 'object' || Array.isArray(args)) return '';
  const entries = Object.entries(args as Record<string, unknown>);
  return entries.slice(0, 3).map(([k, v]) => `${k}: ${short(v)}`).join(' · ') + (entries.length > 3 ? ` · +${entries.length - 3} more` : '');
}

/** Rows as the timeline shows them: runs of rows that happened together are one group. */
export function grouped(rows: Row[]): { key: string; rows: Row[] }[] {
  const out: { key: string; rows: Row[] }[] = [];
  for (const r of rows) {
    const last = out[out.length - 1];
    if (r.group && last && last.rows[0].group === r.group) last.rows.push(r);
    else out.push({ key: r.key, rows: [r] });
  }
  return out;
}
