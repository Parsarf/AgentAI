import { describe, expect, it } from 'vitest';
import { activeTask, controls, dotClass, isActive, outcomeLine, phase, queueLine, statusLabel } from './tasks';

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
    expect(controls({ state: 'waiting' })).toEqual({ pause: true, resume: false, cancel: true, retry: false, goalResume: false });
    expect(controls({ state: 'waiting', paused: true })).toEqual({ pause: false, resume: true, cancel: true, retry: false, goalResume: false });
    expect(controls({ state: 'running' })).toEqual({ pause: false, resume: false, cancel: true, retry: false, goalResume: false });   // no safe place to stop a running task
    expect(controls({ state: 'uncertain' })).toEqual({ pause: false, resume: false, cancel: true, retry: false, goalResume: false });
    expect(controls({ state: 'failed' })).toEqual({ pause: false, resume: false, cancel: false, retry: true, goalResume: false });
    expect(controls({ state: 'cancelled' })).toEqual({ pause: false, resume: false, cancel: false, retry: true, goalResume: false });
    expect(controls({ state: 'completed' })).toEqual({ pause: false, resume: false, cancel: false, retry: false, goalResume: false });
  });

  it('says honestly how a task ended, apart from whether the run is over', () => {
    expect(statusLabel({ state: 'completed', outcome: 'completed' })).toBe('Completed');
    expect(statusLabel({ state: 'completed', outcome: 'partial' })).toBe('Partly done');
    expect(statusLabel({ state: 'completed', outcome: 'blocked' })).toBe('Blocked');
    expect(statusLabel({ state: 'completed', outcome: 'partial', goal: true, continuing: true })).toBe('Working towards your goal');
    expect(statusLabel({ state: 'running', goal: true })).toBe('Working towards your goal');
    expect(statusLabel({ state: 'running', parked: 'browser_question' })).toBe('Waiting for you');
    expect(dotClass({ state: 'completed', outcome: 'blocked' })).toBe('failed');
    expect(dotClass({ state: 'completed', outcome: 'partial' })).toBe('paused');
    expect(dotClass({ state: 'completed', outcome: 'completed' })).toBe('completed');
    expect(dotClass({ state: 'running', parked: 'browser_question' })).toBe('paused');
  });

  it('shows the fixed sentence for a task that did not simply succeed, and nothing for one that did', () => {
    expect(outcomeLine({ state: 'completed', outcome: 'partial', outcome_note: 'The browser stopped where it needs you.' })).toBe('The browser stopped where it needs you.');
    expect(outcomeLine({ state: 'completed', outcome: 'completed', verification: 'unverified', outcome_note: "Done, but I couldn't confirm it from the page." })).toMatch(/couldn't confirm/);
    expect(outcomeLine({ state: 'completed', outcome: 'completed', verification: 'verified', outcome_note: 'Done.' })).toBe('');
    expect(outcomeLine({ state: 'running', parked: 'browser_question' })).toMatch(/until you answer/);
    expect(outcomeLine({ state: 'failed' })).toBe('');
  });

  it('offers to resume a goal only when it is held, never while the next turn is on its way', () => {
    expect(controls({ state: 'completed', goal: true, outcome: 'partial' }).goalResume).toBe(true);
    expect(controls({ state: 'completed', goal: true, outcome: 'blocked' }).goalResume).toBe(true);
    expect(controls({ state: 'completed', goal: true, outcome: 'partial', continuing: true }).goalResume).toBe(false);
    expect(controls({ state: 'completed', goal: true, outcome: 'completed' }).goalResume).toBe(false);
    expect(controls({ state: 'completed', outcome: 'partial' }).goalResume).toBe(false);
  });
});
