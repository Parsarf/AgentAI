import type { B } from './components/types';
type Field = B<'form'>['props']['fields'][number];
const validDate = (v: unknown) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(`${v}T00:00:00Z`)) && new Date(`${v}T00:00:00Z`).toISOString().slice(0, 10) === v;
export function fieldError(f: Field, value: unknown): string | undefined {
  if (value === '' || value == null || (Array.isArray(value) && value.length === 0)) return f.required ? 'Enter a value.' : undefined;
  const numeric = ['number', 'slider', 'rating'].includes(f.type);
  const inBounds = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v >= (f.min ?? -1e15) && v <= (f.max ?? 1e15);
  if (numeric) {
    if (!inBounds(value)) return `Enter a number${f.min != null ? ` from ${f.min}` : ''}${f.max != null ? ` up to ${f.max}` : ''}.`;
    if (f.step != null && f.step > 0) { const count = ((value as number) - (f.min ?? 0)) / f.step; if (Math.abs(count - Math.round(count)) > 1e-7) return `Use increments of ${f.step}.`; }
  }
  if (f.type === 'range' || f.type === 'date-range') {
    if (!Array.isArray(value) || value.length !== 2 || (f.type === 'range' ? !value.every(inBounds) : !value.every(validDate))) return f.type === 'range' ? 'Enter both ends within the allowed range.' : 'Enter a valid start and end date.';
    if (value[0] > value[1]) return 'Start must be before or equal to end.';
  }
  if (f.type === 'date' && !validDate(value)) return 'Enter a valid calendar date.';
  if (f.type === 'time' && (typeof value !== 'string' || !/^([01]\d|2[0-3]):[0-5]\d$/.test(value))) return 'Enter a valid time.';
  if (f.type === 'color' && (typeof value !== 'string' || !/^#[0-9a-f]{6}$/i.test(value))) return 'Choose a valid color.';
  if (['select', 'radio', 'segmented', 'multiselect'].includes(f.type) && f.options) {
    const values = Array.isArray(value) ? value : [value];
    if (values.some(v => !f.options!.some(o => o.value === v))) return 'Choose an available option.';
  }
  if (typeof value === 'string' && (value.length > 500 || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(value))) return 'Use at most 500 characters without control characters.';
  if (Array.isArray(value) && (value.length > 50 || value.some(v => typeof v === 'string' && v.length > 80))) return 'Use at most 50 items, with at most 80 characters each.';
  return undefined;
}
export function validateFields(fields: Field[], values: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(fields.flatMap(f => { const error = fieldError(f, values[f.id]); return error ? [[f.id, error]] : []; }));
}
