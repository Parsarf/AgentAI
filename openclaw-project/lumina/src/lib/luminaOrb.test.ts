import { describe, expect, it } from 'vitest';
import { frameLumina } from './luminaOrb';

describe('Lumina spark geometry', () => {
  it.each([20, 48, 64])('keeps all particles inside the %spx canvas throughout a breath', size => {
    for (const time of [0, 0.6, 1, 3, 100]) {
      const { dots, lines } = frameLumina(size, time);
      expect(dots.length).toBeGreaterThan(20);
      expect(lines).toHaveLength(0);
      for (const dot of dots) {
        expect(dot.x - dot.r).toBeGreaterThan(0);
        expect(dot.y - dot.r).toBeGreaterThan(0);
        expect(dot.x + dot.r).toBeLessThan(size);
        expect(dot.y + dot.r).toBeLessThan(size);
        expect(dot.white).toBeGreaterThanOrEqual(0);
        expect(dot.white).toBeLessThan(1);
      }
    }
  });
  it('preserves the four centred tips and a stable particle count', () => {
    const a = frameLumina(64, 0), b = frameLumina(64, 2);
    expect(a.dots.length).toBe(b.dots.length);
    for (const [x, y] of [[32, 8], [56, 32], [32, 56], [8, 32]]) {
      expect(a.dots.some(d => Math.abs(d.x - x) < 0.01 && Math.abs(d.y - y) < 0.01)).toBe(true);
    }
    expect(a).toEqual(frameLumina(64, 0));
    expect(a).not.toEqual(b);
    expect(frameLumina(20, 0).dots.length).toBeLessThan(a.dots.length);
  });
});
