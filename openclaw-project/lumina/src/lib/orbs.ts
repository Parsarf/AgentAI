import type { OrbState as LibraryOrbState } from '../vendor/thinking-orbs';

/** The nine thinking-orb animations (vendor/thinking-orbs). Which one shows follows what the task is doing: `orbFor` in lib/work.ts. */
export type OrbState = LibraryOrbState;

// Which orb shows what a task is doing is decided from the server's task state in lib/work.ts (`orbFor`): only a task that is really doing something gets a moving orb.

/** At most this many orbs animate at once; any others show a still frame. Each one runs its own drawing loop, so this keeps the cost flat. */
export const MAX_ANIMATED_ORBS = 3;

/** Every animation has an explicit, accessible product label. */
export const ORB_LABELS: Record<OrbState, string> = {
  breathing: 'Thinking', searching: 'Searching', solving: 'Analysing',
  listening: 'Listening', connecting: 'Connecting', weaving: 'Planning',
  composing: 'Writing', shaping: 'Designing', working: 'Running a command',
};
