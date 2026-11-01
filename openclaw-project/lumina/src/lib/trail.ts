import type { Message } from './conversations';

/** The assistant often writes several messages for one request: what it is about to do, what it found, and finally the answer. Once the task is over, everything before
 *  the last of them is "how it got there". `hidden` lists those earlier messages (keyed by the first of them, where the "Show steps" button goes); `skip` holds all their ids.
 *  A message that carries something the person needs on its own (an interactive block, a file) is never folded away. */
export function foldTrail(msgs: Message[], isDone: (requestId: string) => boolean, keep: (m: Message) => boolean = () => false) {
  const last = new Map<string, number>();
  for (const m of msgs) if (m.provenance === 'agent' && m.request_id) last.set(m.request_id, m.id);
  const hidden = new Map<number, Message[]>(); const skip = new Set<number>(); const first = new Map<string, number>();
  for (const m of msgs) {
    if (m.provenance !== 'agent' || !m.request_id || m.id === last.get(m.request_id) || !isDone(m.request_id) || keep(m)) continue;
    const head = first.get(m.request_id);
    if (head === undefined) { first.set(m.request_id, m.id); hidden.set(m.id, [m]); } else hidden.get(head)!.push(m);
    skip.add(m.id);
  }
  return { hidden, skip };
}
