/** A raw request row, for the one place that still reads one: the chat thread (which request a message belongs to, before the shared work state has loaded). What a task is
 *  doing, how it ended and what can be done to it are NOT derived here: the server computes that once (platform/agentai_platform/work.py) and every screen reads it through
 *  lib/work.ts. This file used to hold a second set of phases of its own; the only question left for it is "is this request unfinished". */
const UNFINISHED = ['waiting', 'starting', 'running', 'uncertain'];      // the server's request states that are not an ending (request_states.py); `uncertain` is the system reconciling

/** A request as the chat thread lists it: enough to tie messages to the request they belong to. */
export interface ThreadTask { id: string; state: string; created_epoch: number; result?: string | null; paused?: boolean; cancel_requested?: boolean | number }

/** Is it unfinished and not held? Only used until the shared work state has loaded. */
export const isActive = (t: Pick<ThreadTask, 'state' | 'paused'>) => UNFINISHED.includes(t.state) && !t.paused;
