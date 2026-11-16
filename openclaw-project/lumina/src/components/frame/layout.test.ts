import { describe, expect, it } from 'vitest';
import { CANVAS_MIN, clampWidth, DEFAULT_WIDTHS, LIMITS, personTag, place, RAIL, roomFor, widthClass } from './layout';

const ALL = { context: true, inspector: true, assistant: true };

describe('frame layout', () => {
  it('names the four width classes at 600, 1200 and 1500 px', () => {
    expect([390, 599, 600, 820, 1199, 1200, 1280, 1499, 1500, 1600].map(widthClass)).toEqual(
      ['compact', 'compact', 'medium', 'medium', 'medium', 'expanded', 'expanded', 'expanded', 'large', 'large']);
  });

  it('docks what each width class allows: nothing on a phone, the context from 600, the inspector from 1200, the assistant from 1500', () => {
    expect(place(390, ALL, DEFAULT_WIDTHS).docked).toEqual({ context: false, inspector: false, assistant: false });
    expect(place(820, ALL, DEFAULT_WIDTHS).docked).toEqual({ context: true, inspector: false, assistant: false });
    expect(place(1280, ALL, DEFAULT_WIDTHS).docked).toEqual({ context: true, inspector: true, assistant: false });
    expect(place(1500, ALL, DEFAULT_WIDTHS).docked).toEqual({ context: true, inspector: true, assistant: true });
    expect(place(1900, ALL, DEFAULT_WIDTHS).docked).toEqual({ context: true, inspector: true, assistant: true });
  });

  it('never squeezes the canvas under its minimum: the assistant goes to a sheet first, then the inspector, then the context', () => {
    for (const px of [600, 700, 900, 1200, 1300, 1500, 1700, 2200]) {
      const { docked } = place(px, ALL, DEFAULT_WIDTHS);
      const canvas = px - RAIL - (docked.context ? DEFAULT_WIDTHS.context : 0) - (docked.inspector ? DEFAULT_WIDTHS.inspector : 0) - (docked.assistant ? DEFAULT_WIDTHS.assistant : 0);
      expect(canvas, `${px}px`).toBeGreaterThanOrEqual(CANVAS_MIN);
    }
    const wide = { context: 420, inspector: 720, assistant: 600 };     // the person widened every zone
    expect(place(1600, ALL, wide).docked).toEqual({ context: true, inspector: false, assistant: false });
    expect(place(1600, { context: false, inspector: true, assistant: true }, wide).docked).toEqual({ context: false, inspector: true, assistant: false });
  });

  it('leaves out a zone the page does not use or the person closed', () => {
    expect(place(1900, { context: false, inspector: true, assistant: false }, DEFAULT_WIDTHS).docked).toEqual({ context: false, inspector: true, assistant: false });
  });

  it('keeps widths inside each zone\'s minimum and maximum, and offers no more room than the canvas can give', () => {
    expect(clampWidth('context', 10)).toBe(LIMITS.context.min);
    expect(clampWidth('inspector', 9999)).toBe(LIMITS.inspector.max);
    const p = place(1280, ALL, DEFAULT_WIDTHS);
    expect(roomFor('inspector', 1280, p, DEFAULT_WIDTHS)).toBe(1280 - RAIL - DEFAULT_WIDTHS.context - CANVAS_MIN);
  });

  it('tags a person without keeping their address', () => {
    expect(personTag('a@example.com')).toBe(personTag('a@example.com'));
    expect(personTag('a@example.com')).not.toBe(personTag('b@example.com'));
    expect(personTag('a@example.com')).not.toContain('example');
  });
});
