export interface RunRow { request_id: string; goal: string; status: string; url: string | null; created_epoch: number }
export interface RunEvent { n: number; kind: string; [k: string]: unknown }
export interface RunDetail extends RunRow { answer: string | null; reason: string | null; takeover: boolean; pausing?: boolean; needs_you?: string | null; pending_action: { label?: string } | null; events: RunEvent[] }

/** Browser-task states in which the page is still alive: the live picture is worth showing. */
export const LIVE_STATES = ['queued', 'running', 'handoff', 'paused', 'asking'];      // the server's list: platform/agentai_platform/browse/job_states.py LIVE
export const VIEW = { w: 1280, h: 800 };                        // the browser window the agent sees; clicks are mapped into it
/** Pixel position inside the shown picture -> browser window coordinates (the picture may be scaled, but keeps the window's shape). */
export const toBrowser = (clientX: number, clientY: number, r: { left: number; top: number; width: number; height: number }) =>
  ({ x: Math.round(((clientX - r.left) / r.width) * VIEW.w), y: Math.round(((clientY - r.top) / r.height) * VIEW.h) });

/** Keyboard event -> what to send to the page. Printable text is batched by the caller; shortcuts and unknown keys are never forwarded. */
export type KeyAction = { kind: 'text'; text: string } | { kind: 'key'; text: string } | null;
export function keyAction(e: { key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean }): KeyAction {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (e.key.length === 1) return { kind: 'text', text: e.key };
  if (['Enter', 'Tab', 'Escape', 'Backspace', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return { kind: 'key', text: e.key };
  return null;
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
