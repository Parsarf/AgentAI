import { describe, expect, it } from 'vitest';
import { applyDraft, argumentLine, duration, grouped, mergeRows, needLine, orbFor, receipt, verdict, isMoving, type Row } from './work';

const row = (key: string, first: number, over: Partial<Row> = {}): Row => ({ key, kind: 'tool', category: 'search', label: 'Searched the web', detail: '', output: '', status: 'running', at: 0, ended_at: null, first, seq: first, group: null, ...over });

describe('the cursor merge', () => {
  it('replaces a row by key, keeps the order things started in, and adds what is new', () => {
    const held = [row('a', 1), row('b', 2)];
    const next = mergeRows(held, [row('a', 1, { status: 'done', seq: 3 }), row('c', 4)]);
    expect(next.map(r => [r.key, r.status])).toEqual([['a', 'done'], ['b', 'running'], ['c', 'running']]);
    expect(mergeRows(held, [])).toBe(held);                                              // nothing new: the same object, so nothing re-renders
  });
  it('groups rows that ran together and leaves the rest alone', () => {
    const rows = [row('a', 1), row('b', 2, { group: 'b' }), row('c', 3, { group: 'b' }), row('d', 4)];
    expect(grouped(rows).map(g => g.rows.map(r => r.key))).toEqual([['a'], ['b', 'c'], ['d']]);
  });
});

describe('a reply being written', () => {
  it('grows by additions and never shows text with a hole in it', () => {
    let d = applyDraft(undefined, { item: 'm:1', at: 0, add: 'Hel', done: false }, 1);
    d = applyDraft(d, { item: 'm:1', at: 3, add: 'lo', done: false }, 2);
    expect(d?.text).toBe('Hello');
    expect(applyDraft(d, { item: 'm:1', at: 9, add: '!!', done: false }, 3)).toBe(d);     // a frame for text we do not have the start of
    expect(applyDraft(undefined, { item: 'm:2', at: 4, add: 'x', done: false }, 3)).toBeUndefined();
    expect(applyDraft(d, { item: 'm:2', at: 0, add: 'Next', done: true }, 4)).toEqual({ item: 'm:2', text: 'Next', done: true, at: 4 });
  });
});

describe('words composed on the screen', () => {
  it('gives a moving orb only to a task that is really doing something', () => {
    expect(orbFor({ phase: 'working', activity: { key: 'k', category: 'search', label: '', detail: '' } })).toBe('searching');
    expect(orbFor({ phase: 'working', activity: null })).toBe('breathing');
    expect(orbFor({ phase: 'starting', activity: null })).toBe('connecting');
    for (const phase of ['needs_you', 'paused', 'stopping', 'ended'] as const) expect(orbFor({ phase, activity: null })).toBeNull();
    expect(isMoving({ phase: 'needs_you' })).toBe(false); expect(isMoving({ phase: 'working' })).toBe(true);
  });
  it('writes the record of the work from counts, and nothing when no tool was used', () => {
    const e = { steps: 6, failed_steps: 1, searches: 2, commands: 1, sites: ['a.com', 'b.com'], files: [], saved: [{ id: 'f', version: 1, name: 'r.pdf', size: 1 }], approvals: [], duration_s: 102 };
    expect(receipt(e)).toEqual(['6 steps', '2 sites', '1 file', '1 did not work', '1m 42s']);
    expect(receipt({ ...e, steps: 0, failed_steps: 0, sites: [], saved: [], duration_s: null })).toEqual([]);
    expect([duration(4), duration(60), duration(3725)]).toEqual(['4s', '1m', '1h 2m']);
  });
  it('words finishing and being confirmed apart, preferring the server’s own note', () => {
    expect(verdict({ outcome: 'completed', verification: 'not_applicable', note: '', continuing: false })).toBe('');
    expect(verdict({ outcome: 'completed', verification: 'verified', note: '', continuing: false })).toMatch(/checked the result/);
    expect(verdict({ outcome: 'completed', verification: 'unverified', note: '', continuing: false })).toMatch(/nothing Lumina can check/);
    expect(verdict({ outcome: 'blocked', verification: 'unverified', note: 'The browser was not allowed to open that site.', continuing: false })).toBe('The browser was not allowed to open that site.');
    expect(verdict({ outcome: 'cancelled', verification: 'not_applicable', note: '', continuing: false })).toMatch(/Stopped at your request/);
    expect(verdict({ outcome: null, verification: null, note: '', continuing: false })).toBe('');
  });
  it('explains what is waiting and summarises a call’s arguments', () => {
    expect(needLine({ kind: 'browser_handoff', before: 'Pay now' })).toBe('Lumina stopped before: Pay now. This step is yours.');
    expect(needLine({ kind: 'location_permission' })).toMatch(/location/);
    expect(argumentLine({ a: 'x', b: 2, c: [1], d: 4 })).toBe('a: x · b: 2 · c: [1] · +1 more');
    expect(argumentLine(null)).toBe('');
  });
});
