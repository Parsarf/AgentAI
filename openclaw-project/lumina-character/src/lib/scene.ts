/** The chat background: which scene of the Lumina film matches what the assistant is really doing, and the order its clips play in. */

export type SceneState = 'sleeping' | 'idle' | 'planning' | 'working' | 'waiting' | 'blocked' | 'needs_user' | 'stopped';
export type SceneEvent = 'minor_obstacle' | 'moderate_obstacle' | 'completed' | 'failed';
export type Presence = 'asleep' | 'waking' | 'awake' | 'unknown';

export type Clip = { scene: SceneState; kind: 'enter' | 'loop' | 'exit' } | { scene: SceneState; kind: 'event'; event: SceneEvent };

const BASE = (import.meta.env?.BASE_URL ?? '/').replace(/\/?$/, '/');
export const clipUrl = (c: Clip) => `${BASE}scenes/${c.kind === 'event' ? `event-${c.event}` : `${c.scene}-${c.kind}`}.mp4`;
export const posterUrl = (scene: SceneState) => `${BASE}scenes/${scene}.jpg`;

interface TaskFacts { state: string; paused?: boolean }
interface EventFacts { kind: string; payload?: { category?: string; status?: string; ref?: string; step?: string } }

/** Tool calls keep one entry per `ref` (a later event replaces the earlier one), so only the newest status of each call counts. */
function calls(events: EventFacts[]) {
  const byRef = new Map<string, EventFacts>();
  for (const [i, e] of events.entries()) if (e.payload?.category || ['plan', 'search', 'approval_request', 'approval_decision'].includes(e.kind)) { byRef.delete(e.payload?.ref ?? `e${i}`); byRef.set(e.payload?.ref ?? `e${i}`, e); }
  return [...byRef.values()];
}

/** How many tool calls of this task ended in failure. Rising while the task is still running is an obstacle. */
export const failedCalls = (events: EventFacts[]) => calls(events).filter(e => e.payload?.status === 'failed').length;

/** The scene that tells the truth about now. Pure: the same facts always give the same scene. */
export function sceneFor(presence: Presence, task: TaskFacts | undefined, events: EventFacts[], active: boolean): SceneState {
  if (!task || !active) {
    if (task?.state === 'cancelled' && presence !== 'asleep') return 'stopped';
    return presence === 'asleep' ? 'sleeping' : 'idle';
  }
  if (task.state === 'waiting') {
    if (task.paused) return 'waiting';
    return presence === 'awake' ? 'waiting' : 'idle';                 // asleep with work queued: it is waking up
  }
  if (task.state === 'starting') return 'planning';
  if (task.state === 'uncertain') return 'blocked';                  // reconnecting: the way is not clear
  const step = [...events].reverse().find(e => e.kind === 'progress' && e.payload?.step)?.payload?.step;
  if (step === 'asking') return 'needs_user';
  const open = calls(events);
  const latest = open.filter(e => e.payload?.status === 'running').at(-1) ?? open.at(-1);
  if (latest?.kind === 'approval_request' && !['done', 'failed'].includes(latest.payload?.status ?? '')) return 'needs_user';
  if (latest && !['done', 'failed'].includes(latest.payload?.status ?? '') && (latest.payload?.category === 'plan' || latest.kind === 'plan')) return 'planning';
  return 'working';
}

/** The few plain words under the character. They name the same real state the scene shows, so a drawing is never the only carrier of it. */
export function captionFor(scene: SceneState, presence: Presence, task: TaskFacts | undefined, events: EventFacts[]): string {
  switch (scene) {
    case 'sleeping': return 'Asleep. Send a message to wake Lumina.';
    case 'idle': return task && ['waiting', 'starting'].includes(task.state) && presence !== 'awake' ? 'Waking up' : 'Ready when you are.';
    case 'planning': return 'Planning';
    case 'working': return 'Working';
    case 'waiting': return task?.paused ? 'Paused' : 'Waiting its turn';
    case 'blocked': return 'Reconnecting';
    case 'needs_user': return calls(events).some(e => e.kind === 'approval_request' && !['done', 'failed'].includes(e.payload?.status ?? '')) ? 'Needs your approval' : 'Needs your answer';
    case 'stopped': return 'Stopped. Send a message to continue.';
  }
}

/** What happens to the scene player when a clip ends: the next clip to play. A loop only ends its cycle for a new scene or a pending event. */
export function nextClip(head: Clip, want: SceneState, event: SceneEvent | null): Clip {
  switch (head.kind) {
    case 'enter': return { scene: head.scene, kind: 'loop' };
    case 'loop': return head.scene === want && !event ? head : { scene: head.scene, kind: 'exit' };
    case 'exit': return event ? { scene: want, kind: 'event', event } : { scene: want, kind: 'enter' };
    case 'event': return { scene: want, kind: 'enter' };
  }
}

/** The first clip when a chat opens: a sleeping assistant is simply asleep; any other scene walks in. */
export const firstClip = (want: SceneState): Clip => ({ scene: want, kind: want === 'sleeping' ? 'loop' : 'enter' });
