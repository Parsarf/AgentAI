import { api } from './api';
import type { ThreadTask } from '../components/AgentThinking';
export interface Message { id: number; request_id: string | null; provenance: string; content: string; created_at: string }
interface Page { messages: Message[]; tasks: ThreadTask[]; has_more?: boolean; next_after?: number }
/** Messages of tasks that have finished since we last read them, read again. While a task runs, its reply is cached as it arrives; when it finishes the server
 *  rewrites that reply (a card's data moves out into a stored card, a closing line may be added), and only re-reading it shows the final text.
 *  -> the merged list, or null when nothing needs re-reading. `settled` remembers which tasks were already re-read, so each is read again once. */
export async function refreshFinished(id: string, cached: Message[], tasks: ThreadTask[], settled: Set<string>, finished: (t: ThreadTask) => boolean,
                                      stillCurrent: () => boolean = () => true): Promise<Message[] | null> {
  const done = tasks.filter(t => finished(t) && !settled.has(t.id));
  const stale = cached.filter(m => m.id > 0 && m.request_id && done.some(t => t.id === m.request_id));
  done.forEach(t => settled.add(t.id));
  if (!stale.length) return null;
  const from = Math.min(...stale.map(m => m.id));
  const page = await loadMessages(id, from - 1, stillCurrent);
  if (!stillCurrent()) return null;
  return [...cached.filter(m => m.id > 0 && m.id < from), ...page.messages];
}

/** Read every persisted page; never silently truncate a resumed conversation. */
export async function loadMessages(id: string, after = 0, stillCurrent: () => boolean = () => true): Promise<Page> {
  const messages: Message[] = []; let cursor = after; let tasks: ThreadTask[] = [];
  do {
    const page = await api<Page>('GET', `/v1/conversations/${id}/messages${cursor ? `?after=${cursor}` : ''}`);
    if (!stillCurrent()) return { messages: [], tasks: [] };
    messages.push(...page.messages); tasks = page.tasks;
    if (!page.has_more) break;
    const next = page.next_after ?? page.messages.at(-1)?.id ?? cursor;
    if (next <= cursor) throw new Error('Invalid message cursor');
    cursor = next;
  } while (stillCurrent());
  return { messages, tasks };
}
