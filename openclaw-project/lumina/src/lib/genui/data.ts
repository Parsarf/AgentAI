// Mirrors platform/agentai_platform/genui/data.py: read-only data cards. The server validates; this re-checks before drawing.
import { z } from 'zod';

const t = (max: number, min = 1) => z.string().min(min).max(max).refine(s => !(s.includes('<') && s.includes('>')));
const url = z.string().max(500).regex(/^https?:\/\/\S+$/i);
const colType = z.enum(['text', 'number', 'currency', 'percent', 'rating', 'link']);

export const tableSpec = z.object({
  schemaVersion: z.literal('1.0'), type: z.literal('table'), title: t(120), caption: t(240).optional(), highlightRow: z.number().int().min(0).optional(),
  columns: z.array(z.object({ id: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/), label: t(60), type: colType.default('text'), unit: t(12).optional() }).strict()).min(1).max(12),   // the server defaults a missing column type to text; so does this
  rows: z.array(z.record(z.string(), z.union([z.string().max(500), z.number()]))).min(1).max(200),
}).strict();

export const chartSpec = z.object({
  schemaVersion: z.literal('1.0'), type: z.literal('chart'), chart: z.enum(['bar', 'line', 'pie', 'donut']), title: t(120), caption: t(240).optional(), unit: t(12).optional(),
  labels: z.array(t(60)).min(1).max(40), series: z.array(z.object({ name: t(60), values: z.array(z.number()) }).strict()).min(1).max(4),
}).strict().refine(c => c.series.every(s => s.values.length === c.labels.length))
  .refine(c => !['pie', 'donut'].includes(c.chart) || (c.series.length === 1 && c.series[0].values.every(v => v >= 0)));

export const comparisonSpec = z.object({
  schemaVersion: z.literal('1.0'), type: z.literal('comparison'), title: t(120), caption: t(240).optional(), bestIndex: z.number().int().min(0).optional(),
  items: z.array(z.object({
    name: t(80), subtitle: t(120).optional(), badge: t(24).optional(), price: t(24).optional(), link: url.optional(),
    facts: z.array(z.object({ label: t(40), value: t(120) }).strict()).max(10).default([]), pros: z.array(t(120)).max(5).default([]), cons: z.array(t(120)).max(5).default([]),   // as on the server, all optional
  }).strict()).min(2).max(6),
}).strict();

export type TableSpec = z.infer<typeof tableSpec>;
export type ChartSpec = z.infer<typeof chartSpec>;
export type ComparisonSpec = z.infer<typeof comparisonSpec>;

type Cell = string | number | undefined;
export const formatCell = (v: Cell, type: string, unit?: string): string => {
  if (v === undefined || v === '') return '—';
  if (typeof v === 'number') {
    if (type === 'currency') return `${unit ?? '$'}${v.toLocaleString(undefined, { minimumFractionDigits: v % 1 ? 2 : 0, maximumFractionDigits: 2 })}`;
    if (type === 'percent') return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    if (type === 'rating') return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} ★`;
    return v.toLocaleString(undefined, { maximumFractionDigits: 2 }) + (unit ? ' ' + unit : '');
  }
  return v;
};

/** Sorts rows by one column (numbers numerically, text naturally); empty values always last. dir: 1 ascending, -1 descending. */
export function sortRows<T extends Record<string, Cell>>(rows: T[], col: string, dir: 1 | -1): T[] {
  return [...rows].sort((a, b) => {
    const x = a[col], y = b[col];
    if (x === undefined) return y === undefined ? 0 : 1;
    if (y === undefined) return -1;
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
    return String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: 'base' }) * dir;
  });
}

export const filterRows = <T extends Record<string, Cell>>(rows: T[], q: string): T[] => {
  const needle = q.trim().toLowerCase();
  return needle ? rows.filter(r => Object.values(r).some(v => String(v).toLowerCase().includes(needle))) : rows;
};

const csvCell = (v: Cell) => {
  let s = v === undefined ? '' : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;                        // a spreadsheet must never treat a cell as a formula
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
export const toCsv = (spec: TableSpec, rows = spec.rows): string =>
  [spec.columns.map(c => csvCell(c.label)).join(','), ...rows.map(r => spec.columns.map(c => csvCell(r[c.id])).join(','))].join('\n');

/** Angles for a pie/donut: fractions of the whole, in order. Zero total gives all zeros. */
export const shares = (values: number[]): number[] => { const sum = values.reduce((a, b) => a + b, 0); return values.map(v => (sum > 0 ? v / sum : 0)); };

/** An axis ceiling that is four round steps (1, 2, 2.5, 5 x 10^n), so gridlines land on tidy numbers and bars never touch the top. */
export function niceMax(max: number): number {
  if (max <= 0) return 1;
  const raw = max / 4; const pow = 10 ** Math.floor(Math.log10(raw)); const f = raw / pow;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * pow * 4;
}
