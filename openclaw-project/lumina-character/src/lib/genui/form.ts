import type { Answers, FormField, FormSpec } from './schema';

export function visibleFields(spec: FormSpec, answers: Answers): FormField[] {
  return spec.fields.filter(f => !f.showIf || answers[f.showIf.field] === f.showIf.equals);
}

/** Defaults fill gaps; answers for hidden fields are dropped, exactly like the server does on save and submit. */
export function normalize(spec: FormSpec, answers: Answers): Answers {
  const merged: Answers = {};
  for (const f of spec.fields) if (f.default !== undefined) merged[f.id] = f.default;
  Object.assign(merged, answers);
  const shown = new Set(visibleFields(spec, merged).map(f => f.id));
  return Object.fromEntries(Object.entries(merged).filter(([k]) => shown.has(k)));
}

export function missingRequired(spec: FormSpec, answers: Answers): string[] {
  const a = normalize(spec, answers);
  return visibleFields(spec, a).filter(f => f.required && (a[f.id] === undefined || a[f.id] === '')).map(f => f.label);
}
