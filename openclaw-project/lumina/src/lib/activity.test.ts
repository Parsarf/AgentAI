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
      { kind: 'progress', payload: { summary: '3 transcript update(s) recorded.' } },
      { sequence: 5, kind: 'progress', payload: { summary: 'Plan drafted.' } },
      { sequence: 6, kind: 'error', payload: { summary: 'Something failed' } },
      { kind: 'activity', payload: { label: 'no ref' } },
      { kind: 'activity', payload: { ref: 'x', status: 42, detail: 7 } },
    ]);
    expect(rows.map(r => [r.category, r.status])).toEqual([['note', 'note'], ['error', 'failed'], ['other', 'running']]);
    expect(rows[2].detail).toBe('');
  });
  it('shows the stages from the moment a message is received', () => {
    const rows = toActivity([
      { sequence: 1, kind: 'task_queued', payload: { summary: 'Received. Getting your assistant ready.' } },
      { sequence: 2, kind: 'progress', payload: { summary: 'Waking your assistant. Its workspace is starting up.', step: 'waking' } },
      { sequence: 3, kind: 'task_started', payload: { summary: 'Your assistant is ready. Reading your message.' } },
      { sequence: 4, kind: 'progress', payload: { summary: 'The assistant has your message and is working on it.', step: 'working' } },
    ]);
    expect(rows.map(r => r.label)).toEqual(['Received. Getting your assistant ready.', 'Waking your assistant. Its workspace is starting up.', 'Your assistant is ready. Reading your message.', 'The assistant has your message and is working on it.']);
    expect(rows.every(r => r.category === 'note')).toBe(true);
  });
  it('shows the assistant\'s plan as one line with its numbered steps', () => {
    const rows = toActivity([{ sequence: 1, kind: 'plan', payload: { summary: 'Order the spiciest wings on Uber Eats', steps: ['Open ubereats.com', 'Sign in', 7, 'Search for wings'] } }, { kind: 'plan', payload: {} }]);
    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe('Plan: Order the spiciest wings on Uber Eats'); expect(rows[0].detail).toBe('1. Open ubereats.com  2. Sign in  3. Search for wings');
  });
});
