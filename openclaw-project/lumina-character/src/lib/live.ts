import type { ActivityItem } from './activity';

export interface RunRow { request_id: string; goal: string; status: string; url: string | null; created_epoch: number }
export interface RunEvent { n: number; kind: string; [k: string]: unknown }
/** A choice the browser stopped for. The options are the page's own controls; the box can only send back one of their ids. */
export interface QField { id: string; label: string; key: string; sensitive: boolean; input_type: string; prefill: string }
export interface Question { id: string; title: string; field: string; menu: boolean; kind?: 'choice' | 'fields'; options: { id: string; label: string }[]; fields?: QField[] }
/** What the box sends back: a choice, the details of a form (and which of them to remember), or "I did it on the page". */
export type Answer = { option: string; remember: boolean } | { fields: Record<string, string>; remember_fields: string[] } | { resume: true };
export interface RunDetail extends RunRow { answer: string | null; reason: string | null; takeover: boolean; pausing?: boolean; pending_action: { label?: string } | null; question?: Question | null; events: RunEvent[] }

export type Mode = 'screen' | 'terminal' | 'files';
export const MODE_LABEL: Record<Mode, string> = { screen: 'Screen', terminal: 'Terminal', files: 'Files' };

/** Browser-task states in which the page is still alive: the live picture is worth showing. */
export const LIVE_STATES = ['queued', 'running', 'handoff', 'paused', 'asking'];
export const STATE_LABEL: Record<string, string> = {
  queued: 'Starting', running: 'Working', handoff: 'Waiting for you', paused: 'You have the wheel', asking: 'Waiting for your choice',
  done: 'Done', failed: 'Stopped', cancelled: 'Cancelled', completed: 'Done',
};

export const VIEW = { w: 1280, h: 800 };                        // the browser window the agent sees; clicks are mapped into it
/** Pixel position inside the shown picture -> browser window coordinates (the picture may be scaled, but keeps the window's shape). */
export const toBrowser = (clientX: number, clientY: number, r: { left: number; top: number; width: number; height: number }) =>
  ({ x: Math.round(((clientX - r.left) / r.width) * VIEW.w), y: Math.round(((clientY - r.top) / r.height) * VIEW.h) });

export const stepText = (e: RunEvent): string | null => {
  const s = (e.summary ?? e.message ?? e.label ?? e.reason) as string | undefined;
  if (e.kind === 'screenshot' || e.kind === 'control') return null;
  return s ? String(s) : e.kind === 'step' ? 'Acted on the page' : String(e.kind).replace(/_/g, ' ');
};

/** The mode that follows what Lumina is doing right now. Browser tasks show the screen unless the latest real work was a command or a file. */
export function followMode(rows: ActivityItem[], browseTask: boolean): Mode {
  const last = [...rows].reverse().find(r => r.category !== 'note' && r.category !== 'error');
  if (!browseTask) return last?.category === 'file' && !rows.some(r => r.category === 'command') ? 'files' : 'terminal';
  return last && (last.category === 'command' || last.category === 'file') ? 'terminal' : 'screen';
}

export const modesFor = (browseTask: boolean): Mode[] => (browseTask ? ['screen', 'terminal', 'files'] : ['terminal', 'files']);

/** Keyboard event -> what to send to the page. Printable text is batched by the caller; shortcuts and unknown keys are never forwarded. */
export type KeyAction = { kind: 'text'; text: string } | { kind: 'key'; text: string } | null;
export function keyAction(e: { key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean }): KeyAction {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (e.key.length === 1) return { kind: 'text', text: e.key };
  if (['Enter', 'Tab', 'Escape', 'Backspace', 'Delete', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageDown', 'PageUp'].includes(e.key)) return { kind: 'key', text: e.key };
  return null;
}

/** What was typed in the address bar -> a full address: a missing scheme becomes https. Empty or over-long input gives ''. The server and the browser check the address again. */
export function addressFrom(input: string): string {
  const raw = input.trim();
  if (!raw || /\s/.test(raw) || raw.length > 2000) return '';
  return /^[a-z][a-z0-9+.-]*:/i.test(raw) && !/^[^/]*:\d+(\/|$)/.test(raw) ? raw : 'https://' + raw;
}

/** Wait before the next frame request after `failures` problems in a row: quick at first, then calm, never a hammer. */
export const frameBackoff = (failures: number) => Math.min(10_000, 250 * 2 ** Math.max(0, failures - 1));
/** After this many failures in a row the page shows the latest snapshot instead of a live picture. */
export const FALLBACK_AFTER = 4;

/** Who is deciding right now, as the frame gateway reports it next to each picture (codes only: the words below are ours). */
export interface Now { seq: string; by: 'jev' | 'claude'; mode: 'controls' | 'picture'; note: '' | 'took' | 'back' | 'help' | 'picture' }
const NOW_NOTES = ['', 'took', 'back', 'help', 'picture'];
export const NOTE_TEXT: Record<string, string> = {
  took: 'Claude took over this page', back: 'JEV is back', help: 'Claude is helping with this step', picture: 'Looking at a picture',
};
/** Read the status from a frame response's headers; anything unexpected is ignored (nothing from the network is ever shown as written). */
export function parseNow(get: (name: string) => string | null): Now | null {
  const seq = get('X-Now-Seq'); const by = get('X-By'); const mode = get('X-Mode'); const note = get('X-Note') ?? '';
  if (!seq || !/^\d{1,12}$/.test(seq) || (by !== 'jev' && by !== 'claude') || (mode !== 'controls' && mode !== 'picture') || !NOW_NOTES.includes(note)) return null;
  return { seq, by, mode, note: note as Now['note'] };
}
/** The short label that stays on the screen: who is deciding, and a picture when that is what JEV is looking at. */
export const nowLabel = (n: Now) => n.by === 'claude' ? 'Claude' : n.mode === 'picture' ? 'JEV · picture' : 'JEV';
/** How long a notice stays before the pill goes back to its short label. */
export const NOTICE_MS = 4000;

/** What the box asks. A question with no list of options (Lumina could not read them) sends the customer to the page itself. */
export const questionTitle = (q: Question) => q.title || (q.options.length ? 'Which one do you want?' : 'Lumina needs you to choose on the page');
/** The line next to the tick box; empty when there is nothing sensible to remember (no field name, or no option picked). */
export const rememberText = (q: Question, optionId: string | null) => {
  const label = q.options.find(o => o.id === optionId)?.label;
  return q.field && label ? `Remember ${q.field}: ${label} for next time` : '';
};

/** The label of a field as a person would ask for it: no star, no trailing colon. */
export const fieldLabel = (label: string) => label.replace(/[*:]+\s*$/, '').replace(/\s+/g, ' ').trim() || 'Details';
/** Which kind of text box a field needs. */
export const inputKind = (t: string): 'email' | 'tel' | 'text' => (t === 'email' ? 'email' : t === 'tel' ? 'tel' : 'text');
