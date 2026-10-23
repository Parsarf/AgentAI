import { describe, expect, it } from 'vitest';
import { failedCalls, firstClip, nextClip, sceneFor, type Clip } from './scene';

const running = { state: 'running' };
const call = (ref: string, status: string, category = 'command') => ({ kind: 'tool', payload: { ref, status, category } });

describe('sceneFor', () => {
  it('follows the workspace when nothing is running', () => {
    expect(sceneFor('asleep', undefined, [], false)).toBe('sleeping');
    expect(sceneFor('awake', undefined, [], false)).toBe('idle');
    expect(sceneFor('unknown', { state: 'completed' }, [], false)).toBe('idle');
    expect(sceneFor('asleep', { state: 'completed' }, [], false)).toBe('sleeping');
  });
  it('wakes for queued work, and waits when it is held or behind others', () => {
    expect(sceneFor('asleep', { state: 'waiting' }, [], true)).toBe('idle');
    expect(sceneFor('waking', { state: 'waiting' }, [], true)).toBe('idle');
    expect(sceneFor('awake', { state: 'waiting' }, [], true)).toBe('waiting');
    expect(sceneFor('asleep', { state: 'waiting', paused: true }, [], true)).toBe('waiting');
  });
  it('maps running work to its scene', () => {
    expect(sceneFor('awake', { state: 'starting' }, [], true)).toBe('planning');
    expect(sceneFor('awake', { state: 'uncertain' }, [], true)).toBe('blocked');
    expect(sceneFor('awake', running, [call('a', 'running')], true)).toBe('working');
    expect(sceneFor('awake', running, [{ kind: 'plan', payload: { status: 'running' } }], true)).toBe('planning');
    expect(sceneFor('awake', running, [call('a', 'done')], true)).toBe('working');
  });
  it('asks the customer when the browser or an approval needs them', () => {
    expect(sceneFor('awake', running, [{ kind: 'progress', payload: { step: 'asking' } }], true)).toBe('needs_user');
    expect(sceneFor('awake', running, [{ kind: 'approval_request', payload: { ref: 'x' } }], true)).toBe('needs_user');
    expect(sceneFor('awake', running, [{ kind: 'approval_request', payload: { ref: 'x' } }, { kind: 'approval_decision', payload: { ref: 'x', status: 'done' } }], true)).toBe('working');
  });
  it('shows a stopped task, but never over a sleeping workspace', () => {
    expect(sceneFor('awake', { state: 'cancelled' }, [], false)).toBe('stopped');
    expect(sceneFor('asleep', { state: 'cancelled' }, [], false)).toBe('sleeping');
  });
});

describe('failedCalls', () => {
  it('counts the newest status of each call', () => {
    expect(failedCalls([call('a', 'running'), call('a', 'failed'), call('b', 'done')])).toBe(1);
    expect(failedCalls([call('a', 'failed'), call('a', 'done')])).toBe(0);
  });
});

describe('clip order', () => {
  const loop = (scene: Clip['scene']): Clip => ({ scene, kind: 'loop' });
  it('keeps looping while the scene is the one wanted', () => expect(nextClip(loop('idle'), 'idle', null)).toEqual(loop('idle')));
  it('finishes the loop, plays the exit, then the next entrance, then loops', () => {
    const exit = nextClip(loop('idle'), 'working', null); expect(exit).toEqual({ scene: 'idle', kind: 'exit' });
    const enter = nextClip(exit, 'working', null); expect(enter).toEqual({ scene: 'working', kind: 'enter' });
    expect(nextClip(enter, 'working', null)).toEqual(loop('working'));
  });
  it('plays an event between the exit and the entrance, and leaves the current scene for it', () => {
    expect(nextClip(loop('working'), 'working', 'minor_obstacle')).toEqual({ scene: 'working', kind: 'exit' });
    const ev = nextClip({ scene: 'working', kind: 'exit' }, 'working', 'minor_obstacle');
    expect(ev).toEqual({ scene: 'working', kind: 'event', event: 'minor_obstacle' });
    expect(nextClip(ev, 'idle', null)).toEqual({ scene: 'idle', kind: 'enter' });     // the scene wanted when it ends, not when it began
  });
  it('opens a sleeping assistant asleep and any other scene with its entrance', () => {
    expect(firstClip('sleeping')).toEqual(loop('sleeping'));
    expect(firstClip('idle')).toEqual({ scene: 'idle', kind: 'enter' });
  });
});
