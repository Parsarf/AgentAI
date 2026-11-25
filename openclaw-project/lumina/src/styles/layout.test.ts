// The static layout check (scripts/check-layout.mjs, run by `npm run build`) must keep catching what it is for. Each case is a pattern that broke, or would break,
// a real screen when content changed; each allowed case is how a real exception is written. See LAYOUT.md.
import { describe, expect, it } from 'vitest';
// @ts-expect-error plain JavaScript module of the build scripts
import { check } from '../../scripts/check-layout.mjs';

const rules = (css: string, file = 'src/styles/x.css') => (check(file, css) as { rule: string }[]).map(p => p.rule);

describe('static layout check', () => {
  it('refuses a z-index that is not a layer token, and allows a small local order', () => {
    expect(rules('.panel { position: relative; z-index: 30; }')).toContain('z-index-raw');
    expect(rules('.panel { position: relative; z-index: 9999; }')).toContain('z-index-raw');
    expect(rules('.panel { position: relative; z-index: var(--z-menu); }')).toEqual([]);
    expect(rules('.cell { position: relative; z-index: 2; }')).toEqual([]);
  });

  it('refuses heights in vh (a phone hides the bottom of them) and accepts dvh', () => {
    expect(rules('.pane { min-height: calc(100vh - 56px); }')).toContain('vh-size');
    expect(rules('.pane { min-height: calc(100dvh - 56px); }')).toEqual([]);
  });

  it('refuses layout on a bare modifier class: the task Status mark was squeezed to 9px by MasterDetail\'s old ".md" rule', () => {
    expect(rules('.md { container-type: inline-size; display: flex; margin: 0 -24px; }')).toContain('modifier-root');
    expect(rules('.wk-status.md { display: inline-flex; }')).toEqual([]);
    expect(rules('.mail-compose-foot > .small { flex: 1; }')).toEqual([]);
    expect(rules('.small { font-size: var(--text-sm); }')).toEqual([]);                         // type only: no layout to leak
  });

  it('asks for a reason for fixed and absolute positioning, negative margins, clipping fixed heights and translate offsets', () => {
    expect(rules('.notice { position: fixed; bottom: 0; }')).toContain('position-fixed');
    expect(rules('.badge { position: absolute; top: 0; }')).toContain('position-absolute');
    expect(rules('.row { margin: 0 calc(-1 * var(--space-2)); }')).toContain('negative-margin');
    expect(rules('.row { margin-left: -4px; }')).toContain('negative-margin');
    expect(rules('.card { height: 120px; overflow: hidden; }')).toContain('clip-fixed-height');
    expect(rules('.tip { position: absolute; top: 50%; transform: translateY(-50%); }')).toEqual(expect.arrayContaining(['position-absolute', 'translate-offset']));
  });

  it('accepts the same patterns with a written reason, and the exempt ones without', () => {
    expect(rules('.notice { /* layer: drawer (--z-drawer) */ position: fixed; bottom: 0; }')).toEqual([]);
    expect(rules('/* layout: a count badge on the corner of its icon */\n.badge { position: absolute; top: 0; }')).toEqual([]);
    expect(rules('.row::before { content: ""; position: absolute; left: -8px; }')).toEqual([]);   // decoration
    expect(rules('.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }')).toEqual([]);
    expect(rules('.name { height: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }')).toEqual([]);
    expect(rules('.row { margin: 0 var(--space-2); gap: var(--space-2); }')).toEqual([]);           // a token name with a digit is not a negative margin
  });

  it('applies the same rules to inline styles in components', () => {
    expect(rules('<div style={{ position: \'absolute\', top: 0 }} />', 'src/x.tsx')).toContain('inline-position');
    expect(rules('<div style={{ zIndex: 50 }} />', 'src/x.tsx')).toContain('inline-z-index');
    expect(rules('// layout: the drag ghost follows the pointer\n<div style={{ position: \'fixed\', left: x }} />', 'src/x.tsx')).toEqual([]);
    expect(rules('<div style={{ maxWidth: 860 }} />', 'src/x.tsx')).toEqual([]);
  });
});
