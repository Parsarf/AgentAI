import { describe, expect, it } from 'vitest';
import { toActivity } from './activity';

describe('toActivity', () => {
  it('merges a running call with its result and keeps order', () => {
    const rows = toActivity([
      { sequence: 1, kind: 'progress', payload: { summary: '3 transcript update(s) recorded.' } },
      { sequence: 2, kind: 'activity', payload: { ref: 'c1', category: 'search', label: 'Searched the web', detail: 'paddles', status: 'running' } },
      { sequence: 3, kind: 'activity', payload: { ref: 'c2', category: 'command', label: 'Ran a command', detail: 'ls', status: 'running' } },
      { sequence: 4, kind: 'activity', payload: { ref: 'c1', category: 'search', label: 'Searched the web', detail: 'paddles', status: 'done' } },
    ]);
    expect(rows.map(r => [r.key, r.status])).toEqual([['c1', 'done'], ['c2', 'running']]);
  });
  it('drops noise, keeps notes and errors, ignores junk fields', () => {
    const rows = toActivity([
      { kind: 'progress', payload: { summary: 'Runtime accepted the request.' } },
      { sequence: 5, kind: 'progress', payload: { summary: 'Plan drafted.' } },
      { sequence: 6, kind: 'error', payload: { summary: 'Something failed' } },
      { kind: 'activity', payload: { label: 'no ref' } },
      { kind: 'activity', payload: { ref: 'x', status: 42, detail: 7 } },
    ]);
    expect(rows.map(r => [r.category, r.status])).toEqual([['note', 'note'], ['error', 'failed'], ['other', 'running']]);
    expect(rows[2].detail).toBe('');
  });
});
