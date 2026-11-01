import { api } from './api';
import type { ThreadTask } from '../components/AgentThinking';
export interface Message { id: number; request_id: string | null; provenance: string; content: string; created_at: string; surface?: 'panel' | null }      // surface 'panel': typed in the side chat beside the agent's tab in the customer's own Chrome
interface Page { messages: Message[]; tasks: ThreadTask[]; has_more?: boolean; next_after?: number }
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
