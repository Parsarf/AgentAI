import { describe, expect, it } from 'vitest';
import { activeTask, controls, dotClass, isActive, phase, queueLine, statusLabel } from './tasks';

describe('task control wording and rules', () => {
  it('says where a waiting task stands in the line', () => {
    expect(queueLine({ state: 'waiting', ahead: 0 })).toBe('Next in line.');
    expect(queueLine({ state: 'waiting', ahead: 1 })).toBe('1 task is ahead of this one.');
    expect(queueLine({ state: 'waiting', ahead: 3 })).toBe('3 tasks are ahead of this one.');
    expect(queueLine({ state: 'waiting', ahead: null })).toBe('');
    expect(queueLine({ state: 'waiting', paused: true, ahead: null })).toMatch(/keeps its place/);
    for (const state of ['running', 'completed', 'failed', 'cancelled']) expect(queueLine({ state, ahead: 2 })).toBe('');
  });

  it('labels a held task as Paused but keeps it in the Queued filter', () => {
    expect(statusLabel({ state: 'waiting' })).toBe('Queued');
    expect(statusLabel({ state: 'waiting', paused: true })).toBe('Paused');
    expect(phase('waiting')).toBe('queued');
    expect(dotClass({ state: 'waiting', paused: true })).toBe('paused');
    expect(dotClass({ state: 'waiting' })).toBe('queued');
    expect(dotClass({ state: 'running', paused: true })).toBe('running');
  });

  it('does not call a held task active: nothing is happening, so no orb, no live badge, no active-task panel', () => {
    expect(isActive('waiting')).toBe(true); expect(isActive('running')).toBe(true); expect(isActive('completed')).toBe(false);
    expect(isActive({ state: 'waiting', paused: true })).toBe(false);
    expect(isActive({ state: 'waiting', paused: false })).toBe(true);
    const row = (over: object) => ({ id: 'x', message: 'm', state: 'waiting', cancel_requested: 0, result: null, created_epoch: 1, ...over });
    expect(activeTask([row({ paused: true, created_epoch: 9 }), row({ id: 'y', created_epoch: 5 })])?.id).toBe('y');
    expect(activeTask([row({ paused: true })])).toBeNull();
  });

  it('offers only what the backend will accept', () => {
    expect(controls({ state: 'waiting' })).toEqual({ pause: true, resume: false, cancel: true, retry: false });
    expect(controls({ state: 'waiting', paused: true })).toEqual({ pause: false, resume: true, cancel: true, retry: false });
    expect(controls({ state: 'running' })).toEqual({ pause: false, resume: false, cancel: true, retry: false });   // no safe place to stop a running task
    expect(controls({ state: 'uncertain' })).toEqual({ pause: false, resume: false, cancel: true, retry: false });
    expect(controls({ state: 'failed' })).toEqual({ pause: false, resume: false, cancel: false, retry: true });
    expect(controls({ state: 'cancelled' })).toEqual({ pause: false, resume: false, cancel: false, retry: true });
    expect(controls({ state: 'completed' })).toEqual({ pause: false, resume: false, cancel: false, retry: false });
  });
});
