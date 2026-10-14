import type { OrbState } from '../vendor/thinking-orbs';

/** What Lumina is doing (the category of its latest tool use) -> which orb animation shows it. */
export function orbStateFor(category?: string | null): OrbState {
  switch (category) {
    case 'search': return 'searching';        // a scan sweeps a dotted globe
    case 'read': case 'browse': return 'connecting';   // opening pages: a constellation wires itself
    case 'command': return 'working';         // particles on orbits
    case 'file': return 'composing';          // an undulating sash
    case 'plan': return 'weaving';            // strands plait together
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
