import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MAX_ANIMATED_ORBS, latestCategory, orbStateFor } from './orbs';
type Loop = typeof import('./orbLoop');
type Clock = typeof import('./frameClock');

describe('orb states', () => {
  it('shows what Lumina is doing', () => {
    expect(orbStateFor('search')).toBe('searching');
    expect(orbStateFor('read')).toBe('connecting');
    expect(orbStateFor('browse')).toBe('connecting');
    expect(orbStateFor('command')).toBe('working');
    expect(orbStateFor('file')).toBe('composing');
    expect(orbStateFor('plan')).toBe('weaving');
    for (const c of [undefined, null, '', 'other', 'note', 'error']) expect(orbStateFor(c)).toBe('breathing');
  });

  it('follows the most recent event that names a category', () => {
    expect(latestCategory([])).toBeUndefined();
    expect(latestCategory([{ payload: { category: 'search' } }, { payload: {} }, { payload: { category: 'command' } }, {}])).toBe('command');
    expect(latestCategory([{ payload: { category: 'file' } }, { payload: { category: undefined } }])).toBe('file');
  });

  it('limits how many orbs animate at once', () => { expect(MAX_ANIMATED_ORBS).toBeGreaterThan(0); expect(MAX_ANIMATED_ORBS).toBeLessThanOrEqual(4); });
});

describe('shared orb loop', () => {
  let addOrb: Loop['addOrb']; let onFrame: Clock['onFrame']; let ORB_FPS: number; let SCROLL_QUIET_MS: number;
  beforeEach(async () => {
    vi.useFakeTimers(); vi.setSystemTime(0); vi.resetModules();          // a fresh loop per test: it keeps its own scroll/timer state
    ({ addOrb } = await import('./orbLoop'));
    ({ onFrame, FRAME_FPS: ORB_FPS, SCROLL_QUIET_MS } = await import('./frameClock'));
  });
  afterEach(() => { vi.useRealTimers(); });

  it('draws every orb from one low-rate timer, and stops when the orb is removed', () => {
    const a = vi.fn(), b = vi.fn(); const ea = document.createElement('canvas'), eb = document.createElement('canvas');
    const stopA = addOrb(ea, { draw: a }), stopB = addOrb(eb, { draw: b });
    vi.advanceTimersByTime(1000);
    expect(a.mock.calls.length).toBeGreaterThanOrEqual(ORB_FPS - 2); expect(a.mock.calls.length).toBeLessThanOrEqual(ORB_FPS + 2);   // about 24 a second, not 60
    expect(b.mock.calls.length).toBe(a.mock.calls.length);
    stopA(); const before = a.mock.calls.length; vi.advanceTimersByTime(500);
    expect(a.mock.calls.length).toBe(before); expect(b.mock.calls.length).toBeGreaterThan(before);
    stopB(); const after = b.mock.calls.length; vi.advanceTimersByTime(500);
    expect(b.mock.calls.length).toBe(after);                     // nothing left to draw: the timer has stopped
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not draw while the page is scrolling, and resumes right after', () => {
    const draw = vi.fn(); const stop = addOrb(document.createElement('canvas'), { draw });
    vi.advanceTimersByTime(200); draw.mockClear();
    document.dispatchEvent(new Event('scroll'));
    vi.advanceTimersByTime(SCROLL_QUIET_MS - 20); expect(draw).not.toHaveBeenCalled();
    vi.advanceTimersByTime(200); expect(draw).toHaveBeenCalled();
    stop();
  });

  it('runs the planet and every orb from ONE timer, so the page paints one frame per tick', () => {
    const planet = vi.fn(), orb = vi.fn(); const stopPlanet = onFrame(planet); const stopOrb = addOrb(document.createElement('canvas'), { draw: orb });
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(1000);
    expect(Math.abs(planet.mock.calls.length - orb.mock.calls.length)).toBeLessThanOrEqual(1);       // they tick together
    expect(planet.mock.calls.length).toBeLessThanOrEqual(ORB_FPS + 2);
    stopOrb(); stopPlanet(); vi.advanceTimersByTime(200); expect(vi.getTimerCount()).toBe(0);
  });

  it('does not draw while the user is typing', () => {
    const draw = vi.fn(); const stop = addOrb(document.createElement('canvas'), { draw });
    vi.advanceTimersByTime(200); draw.mockClear();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }));
    vi.advanceTimersByTime(SCROLL_QUIET_MS - 20); expect(draw).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300); expect(draw).toHaveBeenCalled();
    stop();
  });

  it('does not draw in a hidden tab', () => {
    const draw = vi.fn(); const stop = addOrb(document.createElement('canvas'), { draw });
    const hidden = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(300); draw.mockClear(); vi.advanceTimersByTime(500); expect(draw).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);                          // a hidden tab costs nothing: the timer is not even running
    hidden.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(300); expect(draw).toHaveBeenCalled();
    hidden.mockRestore(); stop();
  });
});
