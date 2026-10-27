import type { OrbState } from '../vendor/thinking-orbs';

/** What Lumina is doing (the category of its latest tool use) -> which orb animation shows it. */
export function orbStateFor(category?: string | null): OrbState {
  switch (category) {
    case 'search': return 'searching';        // a scan sweeps a dotted globe
    case 'read': case 'browse': return 'connecting';   // opening pages: a constellation wires itself
    case 'command': return 'working';         // particles on orbits
    case 'file': return 'composing';          // an undulating sash
    case 'analyse': case 'analyze': case 'solve': case 'solving': return 'solving';
    case 'listen': case 'listening': return 'listening';
    case 'design': case 'shape': case 'shaping': return 'shaping';
    case 'write': case 'compose': case 'composing': return 'composing';
    case 'connect': case 'connecting': return 'connecting';
    case 'searching': return 'searching';
    case 'working': return 'working';
    case 'weaving': case 'plan': return 'weaving';            // strands plait together
    default: return 'breathing';              // thinking, nothing specific yet
  }
}

/** The category of the most recent event that has one (events arrive oldest first). */
export function latestCategory(events: { payload?: { category?: string } }[]): string | undefined {
  for (let i = events.length - 1; i >= 0; i--) { const c = events[i].payload?.category; if (c) return c; }
  return undefined;
}

/** At most this many orbs animate at once; any others show a still frame. Each one runs its own drawing loop, so this keeps the cost flat. */
export const MAX_ANIMATED_ORBS = 3;

/** All nine library animations have an explicit, accessible product label. */
export const ORB_LABELS: Record<OrbState, string> = {
  breathing: 'Thinking', searching: 'Searching', solving: 'Analysing',
  listening: 'Listening', connecting: 'Connecting', weaving: 'Planning',
  composing: 'Writing', shaping: 'Designing', working: 'Running a command',
};

export interface ActivityEvent {
  kind: string;
  payload?: { category?: string; status?: string; tool?: string; ref?: string };
}
export function agentActivityFor(taskState: string, events: ActivityEvent[]): { orb: OrbState; label: string } | null {
  if (['completed', 'failed', 'cancelled'].includes(taskState)) return null;
  if (taskState === 'waiting') return { orb: 'breathing', label: 'Queued' };
  if (taskState === 'starting') return { orb: 'connecting', label: 'Getting ready' };
  if (taskState === 'uncertain') return { orb: 'connecting', label: 'Reconnecting' };
  // Tool updates carry the same ref: a completion replaces its running event.
  // Retain other running calls so parallel activity still has a truthful state.
  const calls = new Map<string, ActivityEvent>();
  for (const [i, event] of events.entries()) {
    if (event.payload?.category || ['plan', 'search', 'progress', 'result', 'error', 'approval_request', 'approval_decision'].includes(event.kind)) {
      const key = event.payload?.ref ?? `event-${i}`;
      calls.delete(key); calls.set(key, event);
    }
  }
  const candidates = [...calls.values()];
  const event = candidates.filter(e => e.payload?.status === 'running').at(-1) ?? candidates.at(-1);
  if (event && !['done', 'failed'].includes(event.payload?.status ?? '')) {
    if (event.kind === 'approval_request') return { orb: 'listening', label: 'Waiting for your approval' };
    const category = event.payload?.category ?? ({ plan: 'plan', search: 'search' } as Record<string, string>)[event.kind];
    const orb = orbStateFor(category);
    if (event.payload?.tool === 'read' || category === 'read') return { orb: 'connecting', label: 'Reading' };
    return { orb, label: category === 'browse' ? 'Browsing' : ORB_LABELS[orb] };
  }
  return { orb: 'breathing', label: 'Thinking' };
}
