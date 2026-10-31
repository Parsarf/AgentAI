import { describe, expect, it } from 'vitest';
import { ago, displayName, elapsed, greeting, title } from './format';
import { activeTask, counts, phase, visibleEvents } from './tasks';

describe('format', () => {
  it('greets by local hour', () => {
    expect(greeting(new Date(2026, 0, 1, 9))).toBe('Good morning');
    expect(greeting(new Date(2026, 0, 1, 15))).toBe('Good afternoon');
    expect(greeting(new Date(2026, 0, 1, 21))).toBe('Good evening');
    expect(greeting(new Date(2026, 0, 1, 2))).toBe('Good evening');
  });
  it('derives a display name from the email', () => {
    expect(displayName('parsa.raouf@gmail.com')).toBe('Parsa');
    expect(displayName('RAOUPARSA@x.io')).toBe('Raouparsa');
    expect(displayName('')).toBe('There');
  });
  it('formats relative and elapsed time', () => {
    const now = 1_000_000_000_000;
    expect(ago(now / 1000 - 30, now)).toBe('just now');
    expect(ago(now / 1000 - 7200, now)).toBe('2h ago');
    expect(ago(now / 1000 - 3 * 86400, now)).toBe('3d ago');
    expect(elapsed(now / 1000 - 125, now)).toBe('2m 05s');
  });
  it('shortens titles', () => {
    expect(title('  hello\n  world ')).toBe('hello world');
    expect(title('x'.repeat(100), 10)).toHaveLength(10);
  });
});

describe('tasks', () => {
  const row = (state: string, created = 1) => ({ id: state + created, message: 'm', state, cancel_requested: 0, result: null, created_epoch: created });
  it('maps backend states honestly', () => {
    expect(['waiting', 'starting', 'running', 'uncertain', 'completed', 'failed', 'cancelled'].map(phase))
      .toEqual(['queued', 'running', 'running', 'running', 'completed', 'failed', 'cancelled']);
  });
  it('counts and picks the newest active task', () => {
    const rows = [row('completed', 1), row('running', 5), row('waiting', 9), row('failed', 2)];
    expect(counts(rows)).toEqual({ running: 1, queued: 1, completed: 1, failed: 1 });
    expect(activeTask(rows)?.created_epoch).toBe(9);
    expect(activeTask([row('completed')])).toBeNull();
  });
  it('hides the transcript-update noise only', () => {
    const ev = [{ payload: { summary: '3 transcript update(s) recorded.' } }, { payload: { summary: 'Runtime accepted the request.' } }, {}];
    expect(visibleEvents(ev)).toHaveLength(2);
  });
});
