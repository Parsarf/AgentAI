/** The request states the server names (platform/agentai_platform/request_states.py), for the two places that still read a raw request row: the chat thread (which request
 *  a message belongs to, before the shared work state has loaded) and plan blocks. What a task is doing, how it ended and what can be done to it are NOT derived here any more:
 *  the server computes that once (platform/agentai_platform/work.py) and every screen reads it through lib/work.ts. */
export type Phase = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

/** Backend request states -> the few states a person needs. `uncertain` is the system reconciling: still in flight. */
export function phase(state: string): Phase {
  switch (state) {
    case 'waiting': return 'queued';
    case 'starting': case 'running': case 'uncertain': return 'running';
    case 'completed': return 'completed';
    case 'failed': return 'failed';
    case 'cancelled': return 'cancelled';
    default: return 'queued';
  }
}

/** A request as the chat thread lists it: enough to tie messages to the request they belong to. */
export interface ThreadTask { id: string; state: string; created_epoch: number; result?: string | null; paused?: boolean; cancel_requested?: boolean | number }

/** Is it unfinished and not held? Only used until the shared work state has loaded. */
export const isActive = (t: Pick<ThreadTask, 'state' | 'paused'>) => ['queued', 'running'].includes(phase(t.state)) && !t.paused;
