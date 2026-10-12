import { describe, expect, it } from 'vitest';
import { chatTitle, groupLabel, sortRecent, type ChatSummary } from './chats';

const c = (id: string, last: string | null, created = '2026-10-01T00:00:00Z', title: string | null = 't'): ChatSummary => ({ id, project_id: 'p', created_at: created, title, last_activity: last, active: 0 });

describe('chats', () => {
  it('sorts by last activity, newest first, falling back to creation time', () => {
    const out = sortRecent([c('a', '2026-10-10T10:00:00Z'), c('b', null, '2026-10-12T00:00:00Z'), c('c', '2026-10-11T00:00:00Z')]);
    expect(out.map(x => x.id)).toEqual(['b', 'c', 'a']);
  });
  it('groups into Today / Yesterday / Earlier by local day', () => {
    const now = new Date(2026, 9, 12, 15, 0, 0);
    expect(groupLabel(c('a', new Date(2026, 9, 12, 9).toISOString()), now)).toBe('Today');
    expect(groupLabel(c('a', new Date(2026, 9, 11, 22).toISOString()), now)).toBe('Yesterday');
    expect(groupLabel(c('a', new Date(2026, 9, 1, 22).toISOString()), now)).toBe('Earlier');
    expect(groupLabel(c('a', 'garbage'), now)).toBe('Earlier');
  });
  it('titles an empty chat as New chat', () => { expect(chatTitle(c('a', null, undefined, null))).toBe('New chat'); expect(chatTitle(c('a', null, undefined, 'Hello'))).toBe('Hello'); });
});
