// Pure plan editing and validation. Mirrors the server's launch rules so the user sees problems immediately;
// the server re-validates everything on save and launch.
import type { Phase, Plan } from './schema';

export interface Issue { phaseId?: string; message: string }

export function validate(plan: Plan): Issue[] {
  const issues: Issue[] = []; const by = new Map(plan.phases.map(p => [p.id, p]));
  for (const p of plan.phases) for (const d of p.dependsOn) {
    if (d === p.id) issues.push({ phaseId: p.id, message: `"${p.title}" cannot depend on itself` });
    else if (!by.has(d)) issues.push({ phaseId: p.id, message: `"${p.title}" depends on a phase that no longer exists` });
    else if (p.enabled && !by.get(d)!.enabled) issues.push({ phaseId: p.id, message: `"${p.title}" needs "${by.get(d)!.title}", which is switched off` });
  }
  if (hasCycle(plan)) issues.push({ message: 'The plan has a circular dependency' });
  if (!plan.phases.some(p => p.enabled)) issues.push({ message: 'Switch on at least one phase' });
  return issues;
}

export function hasCycle(plan: Plan): boolean {
  const by = new Map(plan.phases.map(p => [p.id, p])); const state = new Map<string, number>();
  const visit = (i: string): boolean => {
    if (state.get(i) === 2) return false; if (state.get(i) === 1) return true;
    state.set(i, 1);
    for (const d of by.get(i)?.dependsOn ?? []) if (by.has(d) && visit(d)) return true;
    state.set(i, 2); return false;
  };
  return plan.phases.some(p => visit(p.id));
}

/** Would making `from` depend on `to` create a cycle? (i.e. is `from` already reachable from `to`) */
export function wouldCycle(plan: Plan, from: string, to: string): boolean {
  if (from === to) return true;
  const by = new Map(plan.phases.map(p => [p.id, p])); const seen = new Set<string>();
  const stack = [to];
  while (stack.length) { const c = stack.pop()!; if (c === from) return true; if (seen.has(c)) continue; seen.add(c); stack.push(...(by.get(c)?.dependsOn ?? [])); }
  return false;
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30) || 'phase';
export function freshId(plan: Plan, base: string): string {
  const taken = new Set(plan.phases.map(p => p.id)); const b = /^[a-z]/.test(slug(base)) ? slug(base) : 'p-' + slug(base);
  if (!taken.has(b)) return b;
  for (let n = 2; ; n++) if (!taken.has(`${b}-${n}`)) return `${b}-${n}`;
}

const mapPhases = (plan: Plan, fn: (p: Phase) => Phase): Plan => ({ ...plan, phases: plan.phases.map(fn) });

export function updatePhase(plan: Plan, id: string, patch: Partial<Phase>): Plan {
  return mapPhases(plan, p => (p.id === id ? { ...p, ...patch, id: p.id } : p));
}

export function setEnabled(plan: Plan, id: string, enabled: boolean): Plan { return updatePhase(plan, id, { enabled }); }

export function setDependencies(plan: Plan, id: string, deps: string[]): Plan {
  const next = deps.filter(d => d !== id && !wouldCycle(plan, id, d) && plan.phases.some(p => p.id === d));
  return updatePhase(plan, id, { dependsOn: next });
}

export function addPhase(plan: Plan, where: { before?: string; after?: string } | null, title: string): Plan {
  const phase: Phase = { id: freshId(plan, title), title: title.trim().slice(0, 80) || 'New phase', description: '', enabled: true, optional: false, requiresApproval: false, dependsOn: [] };
  const phases = [...plan.phases];
  const ref = where?.after ?? where?.before;
  const at = ref ? phases.findIndex(p => p.id === ref) : -1;
  if (at < 0) { phase.dependsOn = phases.length ? [phases[phases.length - 1].id] : []; phases.push(phase); }
  else if (where?.after) { phase.dependsOn = [phases[at].id]; phases.splice(at + 1, 0, phase); }
  else { phase.dependsOn = [...phases[at].dependsOn]; phases.splice(at, 0, phase); phases[at + 1] = { ...phases[at + 1], dependsOn: [...phases[at + 1].dependsOn.filter(d => !phase.dependsOn.includes(d)), phase.id] }; }
  // A phase inserted after X takes over X's dependents only if the user keeps that link; we do not rewire silently.
  return { ...plan, phases };
}

export function duplicatePhase(plan: Plan, id: string): Plan {
  const i = plan.phases.findIndex(p => p.id === id); if (i < 0) return plan;
  const src = plan.phases[i]; const copy: Phase = { ...src, id: freshId(plan, src.title + ' copy'), title: (src.title + ' (copy)').slice(0, 80), dependsOn: [...src.dependsOn] };
  const phases = [...plan.phases]; phases.splice(i + 1, 0, copy); return { ...plan, phases };
}

export function dependents(plan: Plan, id: string): Phase[] { return plan.phases.filter(p => p.dependsOn.includes(id)); }

/** Removing a phase: dependents either inherit its prerequisites (reconnect) or simply lose the link. */
export function removePhase(plan: Plan, id: string, reconnect: boolean): Plan {
  const gone = plan.phases.find(p => p.id === id); if (!gone) return plan;
  const phases = plan.phases.filter(p => p.id !== id).map(p => {
    if (!p.dependsOn.includes(id)) return p;
    const rest = p.dependsOn.filter(d => d !== id);
    const inherited = reconnect ? gone.dependsOn.filter(d => !rest.includes(d) && d !== p.id) : [];
    return { ...p, dependsOn: [...rest, ...inherited] };
  });
  return { ...plan, phases };
}

/** Move one step in list order. List order only breaks ties between independent phases; dependencies decide what must come first. */
export function movePhase(plan: Plan, id: string, delta: -1 | 1): Plan {
  const i = plan.phases.findIndex(p => p.id === id); const j = i + delta;
  if (i < 0 || j < 0 || j >= plan.phases.length) return plan;
  const phases = [...plan.phases]; [phases[i], phases[j]] = [phases[j], phases[i]]; return { ...plan, phases };
}

export function movePhaseTo(plan: Plan, id: string, targetId: string): Plan {
  const from = plan.phases.findIndex(p => p.id === id); const to = plan.phases.findIndex(p => p.id === targetId);
  if (from < 0 || to < 0 || from === to) return plan;
  const phases = [...plan.phases]; const [m] = phases.splice(from, 1); phases.splice(to, 0, m); return { ...plan, phases };
}

/** Diagram rows: a phase sits one row below its deepest prerequisite; phases in the same row can run in parallel. */
export function layers(plan: Plan): Phase[][] {
  const by = new Map(plan.phases.map(p => [p.id, p])); const level = new Map<string, number>();
  const depth = (i: string, guard = 0): number => {
    if (level.has(i)) return level.get(i)!; if (guard > 30) return 0;
    const p = by.get(i)!; const l = p.dependsOn.filter(d => by.has(d) && d !== i).reduce((m, d) => Math.max(m, depth(d, guard + 1) + 1), 0);
    level.set(i, l); return l;
  };
  const rows: Phase[][] = [];
  for (const p of plan.phases) (rows[depth(p.id)] ??= []).push(p);
  return rows.filter(Boolean);
}

export function samePlan(a: Plan, b: Plan): boolean { return JSON.stringify(a) === JSON.stringify(b); }

/** Bounded undo/redo history (no network, no model). */
export class History<T> {
  private past: T[] = []; private future: T[] = [];
  constructor(public present: T, private limit = 50) {}
  push(next: T) { this.past.push(this.present); if (this.past.length > this.limit) this.past.shift(); this.present = next; this.future = []; }
  undo(): T | null { const p = this.past.pop(); if (p === undefined) return null; this.future.push(this.present); this.present = p; return p; }
  redo(): T | null { const f = this.future.pop(); if (f === undefined) return null; this.past.push(this.present); this.present = f; return f; }
  get canUndo() { return this.past.length > 0; }
  get canRedo() { return this.future.length > 0; }
  reset(value: T) { this.past = []; this.future = []; this.present = value; }
}
