import { describe, expect, it } from 'vitest';
// @ts-expect-error plain JavaScript module of the build scripts
import { generate, CONTRAST } from '../../scripts/tokens/generate.mjs';
// @ts-expect-error plain JavaScript module of the build scripts
import { contrast, deltaE, over } from '../../scripts/tokens/oklch.mjs';

// The hand-set dark theme as it was before the generator (tokens.css, 2026-11-16). Normal contrast must reproduce it: nobody should see a change.
const BEFORE: Record<string, string> = {
  'surface-base': '#060608', 'surface-sidebar': '#0a0a0d', surface: '#0e0f13', 'surface-raised': '#15161b', 'surface-overlay': '#191a20', 'surface-inset': '#07080b',
  'text-primary': '#f2f2f5', 'text-secondary': '#a3a5af', 'text-muted': '#868995', 'text-disabled': '#5d606b',
  accent: '#7455ff', 'accent-hover': '#9079ff', 'accent-pressed': '#6140ee', 'accent-text': '#b9abff', 'accent-2': '#a78bfa',
  success: '#34d3a0', warning: '#f5b942', danger: '#ef6a6a', 'on-danger': '#1b0606',
};
const SURFACES = ['surface-base', 'surface-sidebar', 'surface-canvas', 'surface', 'surface-raised', 'surface-overlay'];
const READ = ['text-primary', 'text-secondary', 'text-muted'];

describe('generated colour tokens', () => {
  it('reproduce the previous dark theme to the eye (OKLab distance under 0.005, a quarter of a just-visible step)', () => {
    const now = generate();
    for (const [name, hex] of Object.entries(BEFORE)) expect(deltaE(now[name], hex), name).toBeLessThan(0.005);
  });

  it('keep text readable on every surface step (WCAG 2.2 AA, 4.5:1), and at more contrast reach 7:1', () => {
    for (const [level, least] of [[CONTRAST.normal, 4.5], [CONTRAST.more, 7]] as const) {
      const t = generate({ contrast: level });
      for (const s of SURFACES) for (const name of READ) expect(contrast(t[name], t[s]), `${name} on ${s} at ${level}`).toBeGreaterThanOrEqual(least);
      // A hovered row is a translucent fill over a surface: text stays readable on it too.
      for (const s of SURFACES) expect(contrast(t['text-secondary'], over('#ffffff', 0.09 * level, t[s]))).toBeGreaterThanOrEqual(least);
    }
  });

  it('keep the accent visible as a control boundary and focus ring (3:1 on every surface)', () => {
    const t = generate();
    for (const s of SURFACES) expect(contrast(t.accent, t[s]), s).toBeGreaterThanOrEqual(3);
    for (const s of SURFACES) expect(contrast(t['accent-text'], t[s]), s).toBeGreaterThanOrEqual(4.5);
  });

  it('order the surfaces so the chrome sits below the canvas and cards above it', () => {
    const t = generate(); const lum = (hex: string) => contrast(hex, '#000000');
    expect(lum(t['surface-base'])).toBeLessThan(lum(t['surface-canvas']));
    expect(lum(t['surface-canvas'])).toBeLessThan(lum(t.surface));
  });
  // That theme.css is what the generator makes from its inputs is checked by the build (node scripts/tokens/generate.mjs --check), which CI runs.
});
