import { describe, expect, it } from 'vitest';
import { formSpec, planSpec, type Plan } from './schema';
import { missingRequired, normalize, visibleFields } from './form';
import * as P from './plan';

const ph = (id: string, deps: string[] = [], extra = {}) => ({ id, title: id.toUpperCase(), description: '', enabled: true, optional: false, requiresApproval: false, dependsOn: deps, ...extra });
const base = (): Plan => ({ schemaVersion: '1.0', type: 'task_plan', title: 'T', phases: [ph('a'), ph('b', ['a']), ph('c', ['b']), ph('d', ['c'], { optional: true })] });
const ids = (p: Plan) => p.phases.map(x => x.id);

describe('schemas', () => {
  it('rejects unknown keys, types and oversize trees', () => {
    expect(planSpec.safeParse(base()).success).toBe(true);
    expect(planSpec.safeParse({ ...base(), onload: 'x' }).success).toBe(false);
    expect(planSpec.safeParse({ ...base(), phases: [{ ...ph('a'), html: '<b>' }] }).success).toBe(false);
    expect(planSpec.safeParse({ ...base(), phases: Array.from({ length: 26 }, (_, i) => ph('p' + i)) }).success).toBe(false);
    const f = { schemaVersion: '1.0', type: 'form', title: 'x', fields: [{ id: 'k', type: 'script', label: 'k' }], submit: { label: 's', action: 'submit_requirements' } };
    expect(formSpec.safeParse(f).success).toBe(false);
    expect(formSpec.safeParse({ ...f, fields: [{ id: 'k', type: 'toggle', label: 'k' }], submit: { label: 's', action: 'rm_rf' } }).success).toBe(false);
  });
});

describe('form logic', () => {
  const spec = formSpec.parse({ schemaVersion: '1.0', type: 'form', title: 'x', submit: { label: 'Go', action: 'submit_requirements' }, fields: [
    { id: 'kind', type: 'segmented', label: 'Kind', required: true, default: 'biz', options: [{ label: 'Biz', value: 'biz' }, { label: 'Shop', value: 'shop' }] },
    { id: 'pay', type: 'select', label: 'Pay', required: true, showIf: { field: 'kind', equals: 'shop' }, options: [{ label: 'A', value: 'a' }, { label: 'B', value: 'b' }] }] });
  it('shows fields conditionally and drops hidden answers', () => {
    expect(visibleFields(spec, { kind: 'biz' }).map(f => f.id)).toEqual(['kind']);
    expect(visibleFields(spec, { kind: 'shop' }).map(f => f.id)).toEqual(['kind', 'pay']);
    expect(normalize(spec, { kind: 'biz', pay: 'a' })).toEqual({ kind: 'biz' });
    expect(normalize(spec, {})).toEqual({ kind: 'biz' });
  });
  it('reports missing required visible answers only', () => {
    expect(missingRequired(spec, {})).toEqual([]);
    expect(missingRequired(spec, { kind: 'shop' })).toEqual(['Pay']);
  });
});

describe('plan editing', () => {
  it('validates dependencies, cycles and empty plans', () => {
    expect(P.validate(base())).toEqual([]);
    const off = P.setEnabled(base(), 'b', false);
    expect(P.validate(off).map(i => i.message)).toContain('"C" needs "B", which is switched off');
    const cyc = { ...base(), phases: [ph('a', ['b']), ph('b', ['a'])] };
    expect(P.hasCycle(cyc)).toBe(true); expect(P.validate(cyc).some(i => /circular/.test(i.message))).toBe(true);
    expect(P.validate({ ...base(), phases: [ph('a', [], { enabled: false })] }).map(i => i.message)).toContain('Switch on at least one phase');
  });
  it('prevents cycles when editing dependencies and ignores self links', () => {
    const p = base();
    expect(P.setDependencies(p, 'a', ['c', 'a']).phases[0].dependsOn).toEqual([]);          // c depends (transitively) on a
    expect(P.setDependencies(p, 'c', ['a']).phases[2].dependsOn).toEqual(['a']);
  });
  it('adds phases before and after with sensible links and unique ids', () => {
    const after = P.addPhase(base(), { after: 'b' }, 'Security review');
    expect(ids(after)).toEqual(['a', 'b', 'security-review', 'c', 'd']); expect(after.phases[2].dependsOn).toEqual(['b']);
    const before = P.addPhase(base(), { before: 'c' }, 'Security review');
    expect(before.phases[2].dependsOn).toEqual(['b']); expect(before.phases[3].dependsOn).toEqual(['security-review']);   // c now follows the new phase
    expect(P.validate(before)).toEqual([]);
    expect(ids(P.addPhase(after, { after: 'b' }, 'Security review'))).toContain('security-review-2');
    expect(P.addPhase(base(), null, 'Last').phases[4].dependsOn).toEqual(['d']);
  });
  it('removes with an impact check, reconnecting dependents by default', () => {
    expect(P.dependents(base(), 'b').map(p => p.id)).toEqual(['c']);
    const reconnected = P.removePhase(base(), 'b', true);
    expect(reconnected.phases.find(p => p.id === 'c')!.dependsOn).toEqual(['a']); expect(P.validate(reconnected)).toEqual([]);
    const loose = P.removePhase(base(), 'b', false);
    expect(loose.phases.find(p => p.id === 'c')!.dependsOn).toEqual([]);
    expect(P.removePhase(base(), 'zzz', true)).toEqual(base());
  });
  it('reorders by step and by drop, and keeps dependencies untouched', () => {
    const p = P.movePhase(base(), 'a', 1); expect(ids(p)).toEqual(['b', 'a', 'c', 'd']); expect(p.phases[1].dependsOn).toEqual([]);
    expect(ids(P.movePhase(base(), 'a', -1))).toEqual(['a', 'b', 'c', 'd']);
    expect(ids(P.movePhaseTo(base(), 'd', 'a'))).toEqual(['d', 'a', 'b', 'c']);
  });
  it('duplicates a phase and lays phases out in parallel rows', () => {
    expect(ids(P.duplicatePhase(base(), 'b'))).toEqual(['a', 'b', 'b-copy', 'c', 'd']);
    const par: Plan = { ...base(), phases: [ph('a'), ph('b', ['a']), ph('c', ['a']), ph('d', ['b', 'c'])] };
    expect(P.layers(par).map(r => r.map(x => x.id))).toEqual([['a'], ['b', 'c'], ['d']]);
  });
  it('keeps a bounded undo/redo history', () => {
    const h = new P.History(1, 3); h.push(2); h.push(3); h.push(4); h.push(5);
    expect(h.undo()).toBe(4); expect(h.undo()).toBe(3); expect(h.undo()).toBe(2); expect(h.undo()).toBeNull();   // oldest entry dropped
    expect(h.redo()).toBe(3); h.push(9); expect(h.canRedo).toBe(false);
  });
});
