import { useMemo, useState } from 'react';
import { filterRows, formatCell, niceMax, shares, sortRows } from '../../lib/genui/data';
import { Emojified } from '../../components/Emoji';
import { safeHttpUrl } from '../safety';
import type { Block, Dataset } from '../schemas';
import { cx, type B, type P } from './types';
import { useGen, useLocal } from './context';
import { StatusPill } from './cards';

type Col = Dataset['columns'][number];
type Row = Record<string, string | number | boolean | null>;
export interface Resolved { columns: Col[]; rows: Row[]; source?: string }

/** Rows for a block: a dataset in the same response (dataRef, shared and sent once), else the rows the block carries. null when the reference does not resolve. */
export function useData(block: { dataRef?: string; props: Record<string, any> }): Resolved | null {
  const g = useGen();
  if (block.dataRef) { const d = g.datasets[block.dataRef]; return d ? { columns: d.columns, rows: d.rows as Row[], source: d.source } : null; }
  const rows = (block.props.rows ?? block.props.data ?? []) as Row[]; const columns = (block.props.columns as Col[] | undefined) ?? inferColumns(rows);
  return { columns, rows };
}
function inferColumns(rows: Row[]): Col[] {
  const keys = [...new Set(rows.flatMap(r => Object.keys(r)))].slice(0, 12);
  return keys.map(k => ({ id: k, label: k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()), type: rows.every(r => r[k] == null || typeof r[k] === 'number') ? 'number' : 'text' }));
}
const norm = (v: Row[string]): string | number | undefined => (v === null || v === undefined ? undefined : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : v);
const normRow = (r: Row): Record<string, string | number | undefined> => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, norm(v)]));
const STATUS = new Set(['idle', 'active', 'success', 'warning', 'error']);

export function Missing({ what }: { what: string }) { return <p className="gen-empty" role="status">{what}</p>; }

export function TableBlock({ block }: P<'table'>) {
  const p = block.props; const data = useData(block);
  const [l, set] = useLocal(block.id, { sortColumn: p.defaultSort?.column ?? '', sortDir: p.defaultSort?.dir ?? 'asc', query: '', page: 0 });
  const rows = useMemo(() => {
    if (!data) return [];
    let r = data.rows.map(normRow); if (l.query) r = filterRows(r, String(l.query));
    return l.sortColumn ? sortRows(r, String(l.sortColumn), l.sortDir === 'desc' ? -1 : 1) : r;
  }, [data, l.query, l.sortColumn, l.sortDir]);
  if (!data) return <Missing what="The data for this table is not available." />;
  if (!data.rows.length) return <Missing what="No rows to show." />;
  const size = p.pageSize; const pages = Math.max(1, Math.ceil(rows.length / size)); const page = Math.min(Number(l.page) || 0, pages - 1);
  const shown = rows.slice(page * size, page * size + size);
  const searchable = p.searchable ?? data.rows.length > 10;
  const click = (id: string) => set(l.sortColumn !== id ? { sortColumn: id, sortDir: 'asc' } : l.sortDir === 'asc' ? { sortDir: 'desc' } : { sortColumn: '', sortDir: 'asc' });
  const best = p.highlightRow !== undefined ? data.rows[p.highlightRow] : undefined;
  return <div className={cx('gen-table-wrap', block.variant)}>
    {searchable && <div className="gen-tools"><input className="gen-input" type="search" placeholder="Search rows…" aria-label="Search rows" value={String(l.query)} onChange={e => set({ query: e.target.value, page: 0 })} />
      <span className="faint" role="status">{rows.length === data.rows.length ? `${rows.length} rows` : `${rows.length} of ${data.rows.length} rows`}</span></div>}
    <div className="gen-scroll" role="region" aria-label={p.title ?? 'Table'} tabIndex={0}><table className="gen-table">
      {p.caption && <caption>{p.caption}</caption>}
      <thead><tr>{data.columns.map(c => { const num = ['number', 'currency', 'percent', 'rating'].includes(c.type ?? 'text'); const on = l.sortColumn === c.id;
        return <th key={c.id} scope="col" className={cx((num || c.align === 'end') && 'num')} aria-sort={on ? (l.sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
          {p.sortable ? <button onClick={() => click(c.id)}>{c.label}<span aria-hidden className="arrow">{on ? (l.sortDir === 'asc' ? '↑' : '↓') : ''}</span></button> : c.label}</th>; })}</tr></thead>
      <tbody>{shown.map((r, n) => <tr key={n} className={cx(data.rows[0] && best && data.rows.indexOf(best) >= 0 && JSON.stringify(normRow(best)) === JSON.stringify(r) && 'best')}>{data.columns.map(c => {
        const v = r[c.id]; const num = ['number', 'currency', 'percent', 'rating'].includes(c.type ?? 'text'); const header = p.rowHeader === c.id;
        const cell = c.type === 'link' && typeof v === 'string' ? (safeHttpUrl(v) ? <a href={safeHttpUrl(v)!} target="_blank" rel="noopener noreferrer nofollow">Open<span className="sr"> (opens in a new tab)</span></a> : '—')
          : c.type === 'status' && typeof v === 'string' && STATUS.has(v) ? <StatusPill status={v as any} /> : <Emojified text={formatCell(v, c.type ?? 'text', c.unit)} />;
        return header ? <th key={c.id} scope="row">{cell}</th> : <td key={c.id} className={cx((num || c.align === 'end') && 'num')}>{cell}</td>; })}</tr>)}
        {!shown.length && <tr><td colSpan={data.columns.length} className="faint">No rows match.</td></tr>}</tbody></table></div>
    {pages > 1 && <nav className="gen-pager" aria-label="Table pages"><button className="btn tertiary small" disabled={page === 0} onClick={() => set({ page: page - 1 })}>Previous</button>
      <span aria-live="polite">Page {page + 1} of {pages}</span><button className="btn tertiary small" disabled={page >= pages - 1} onClick={() => set({ page: page + 1 })}>Next</button></nav>}
    {data.source && <p className="faint gen-src">Source: {data.source}</p>}
  </div>;
}

// ---- charts ---------------------------------------------------------------------------------------------------------------------------------
const W = 640, H = 280, L = 52, R = 14, T = 12, Bm = 34;
const color = (i: number) => `var(--chart-${(i % 6) + 1})`;
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : null);

function Legend({ items, hidden, toggle }: { items: Array<{ key: string; label: string }>; hidden: string[]; toggle(k: string): void }) {
  if (items.length < 2) return null;
  return <div className="gen-legend" role="group" aria-label="Series">{items.map((s, i) => <button key={s.key} aria-pressed={!hidden.includes(s.key)} onClick={() => toggle(s.key)}><i style={{ background: color(i) }} />{s.label}</button>)}</div>;
}
function DataTable({ columns, rows, label }: { columns: Col[]; rows: Row[]; label: string }) {
  const [page, setPage] = useState(0); const current = Math.min(page, Math.max(0, Math.ceil(rows.length / 60) - 1));
  return <details className="gen-alt"><summary>View as table</summary><div className="gen-scroll" tabIndex={0} role="region" aria-label={`${label} data`}><table className="gen-table"><thead><tr>{columns.map(c => <th key={c.id} scope="col">{c.label}</th>)}</tr></thead>
    <tbody>{rows.slice(current * 60, (current + 1) * 60).map((r, n) => <tr key={n}>{columns.map(c => <td key={c.id} className={typeof r[c.id] === 'number' ? 'num' : ''}>{formatCell(norm(r[c.id]), c.type ?? 'text', c.unit)}</td>)}</tr>)}</tbody></table></div>{rows.length > 60 && <nav className="gen-row" aria-label="Chart data pages"><button className="btn small" disabled={!current} onClick={() => setPage(current - 1)}>Previous data page</button><span>Page {current + 1} of {Math.ceil(rows.length / 60)}</span><button className="btn small" disabled={(current + 1) * 60 >= rows.length} onClick={() => setPage(current + 1)}>Next data page</button></nav>}</details>;
}
const fmt = (v: number, unit?: string) => formatCell(v, 'number', unit && unit.length > 1 ? unit : undefined).replace(/^/, unit && unit.length === 1 ? unit : '');
const kindName: Record<string, string> = { line_chart: 'Line chart', area_chart: 'Area chart', bar_chart: 'Bar chart', pie_chart: 'Pie chart', scatter_chart: 'Scatter plot' };

/** A one-sentence description for assistive technology, computed from the data, so it is never out of step with the picture. */
export function chartSummary(kind: string, title: string | undefined, labels: string[], series: Array<{ label: string; values: Array<number | null> }>, unit?: string): string {
  const s = series[0]; const vals = s.values.map((v, i) => [v, i] as const).filter((x): x is [number, number] => x[0] !== null);
  if (!vals.length) return `${kindName[kind] ?? 'Chart'}${title ? ` of ${title}` : ''} with no numeric data.`;
  const hi = vals.reduce((a, b) => (b[0] > a[0] ? b : a)), lo = vals.reduce((a, b) => (b[0] < a[0] ? b : a));
  return `${kindName[kind] ?? 'Chart'}${title ? `: ${title}` : ''}. ${labels.length} points, ${series.map(x => x.label).join(', ')}. ${s.label} is highest at ${fmt(hi[0], unit)} (${labels[hi[1]]}) and lowest at ${fmt(lo[0], unit)} (${labels[lo[1]]}).`;
}

function Axes({ max, min, y, labels, cx: cxf, unit }: { max: number; min: number; y(v: number): number; labels: string[]; cx(i: number): number; unit?: string }) {
  const ticks = [0, 1, 2, 3, 4].map(i => min + ((max - min) * i) / 4); const step = Math.ceil(labels.length / 7);
  return <g aria-hidden className="gen-axes">{ticks.map((t, i) => <g key={i}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" /><text x={L - 8} y={y(t) + 4} textAnchor="end">{fmt(t, unit)}</text></g>)}
    {labels.map((lb, i) => i % step === 0 && <text key={i} x={cxf(i)} y={H - 10} textAnchor="middle">{lb.length > 12 ? lb.slice(0, 11) + '…' : lb}</text>)}</g>;
}

function XYChart({ block, kind }: { block: B<'line_chart'> | B<'area_chart'> | B<'bar_chart'>; kind: 'line_chart' | 'area_chart' | 'bar_chart' }) {
  const p = block.props; const data = useData(block); const [l, set] = useLocal(block.id, { hidden: [] as string[] });
  if (!data) return <Missing what="The data for this chart is not available." />;
  const labels = data.rows.map(r => String(norm(r[p.xKey]) ?? ''));
  const all = p.series.map(s => ({ key: s.key, label: s.label ?? s.key, values: data.rows.map(r => num(r[s.key])) }));
  if (!data.rows.length || all.every(s => s.values.every(v => v === null))) return <Missing what="There are no numbers to chart." />;
  const hidden = l.hidden as string[]; const vis = all.filter(s => !hidden.includes(s.key)); const stacked = block.variant === 'stacked';
  const stackTop = (i: number, upto: number) => vis.slice(0, upto + 1).reduce((a, s) => a + (s.values[i] ?? 0), 0);
  const hiVal = stacked ? Math.max(0, ...labels.map((_, i) => stackTop(i, vis.length - 1))) : Math.max(0, ...vis.flatMap(s => s.values.map(v => v ?? 0)));
  const loVal = stacked ? 0 : Math.min(0, ...vis.flatMap(s => s.values.map(v => v ?? 0)));
  const max = niceMax(hiVal); const span = max - loVal || 1; const ph = H - T - Bm, pw = W - L - R;
  const y = (v: number) => T + ph - ((v - loVal) / span) * ph; const n = labels.length;
  const band = pw / n; const bx = (i: number) => L + band * i + band / 2; const lx = (i: number) => (n === 1 ? L + pw / 2 : L + (pw * i) / (n - 1));
  const summary = p.summary ?? chartSummary(kind, p.title, labels, all, p.unit);
  const toggle = (k: string) => { const next = hidden.includes(k) ? hidden.filter(x => x !== k) : [...hidden, k]; if (next.length < all.length) set({ hidden: next }); };
  const idx = (s: { key: string }) => all.findIndex(a => a.key === s.key);
  return <figure className="gen-chart">
    <div role="img" aria-label={summary}><svg viewBox={`0 0 ${W} ${H}`} className="gen-svg" focusable="false">
      <Axes max={max} min={loVal} y={y} labels={labels} cx={kind === 'bar_chart' ? bx : lx} unit={p.unit} />
      {kind === 'bar_chart' && vis.map((s, si) => { const w = stacked ? band * 0.6 : (band * 0.7) / vis.length;
        return <g key={s.key}>{s.values.map((v, i) => { if (v === null) return null; const base = stacked ? stackTop(i, si - 1) : 0; const x = stacked ? bx(i) - w / 2 : bx(i) - (w * vis.length) / 2 + si * w;
          return <rect key={i} x={x} width={Math.max(1, w - 1)} y={y(Math.max(base + v, base))} height={Math.max(1, Math.abs(y(base) - y(base + v)))} rx="2" fill={color(idx(s))}><title>{`${labels[i]}: ${s.label} ${fmt(v, p.unit)}`}</title></rect>; })}</g>; })}
      {kind !== 'bar_chart' && vis.map((s, si) => { const pts = s.values.map((v, i) => (v === null ? null : [lx(i), y(stacked && kind === 'area_chart' ? stackTop(i, si) : v)] as const));
        const run = pts.filter((q): q is readonly [number, number] => q !== null); const line = run.map(q => q.join(',')).join(' ');
        const baseRun = stacked && si > 0 ? labels.map((_, i) => [lx(i), y(stackTop(i, si - 1))] as const).reverse() : [[run[run.length - 1]?.[0] ?? 0, y(0)], [run[0]?.[0] ?? 0, y(0)]] as const;
        return <g key={s.key}>{kind === 'area_chart' && run.length > 1 && <polygon points={`${line} ${baseRun.map(q => q.join(',')).join(' ')}`} fill={color(idx(s))} opacity=".18" />}
          <polyline points={line} fill="none" stroke={color(idx(s))} strokeWidth="2" strokeLinejoin="round" />
          {run.length <= 24 && pts.map((q, i) => q && <circle key={i} cx={q[0]} cy={q[1]} r="3" fill={color(idx(s))}><title>{`${labels[i]}: ${s.label} ${fmt(s.values[i]!, p.unit)}`}</title></circle>)}</g>; })}
    </svg></div>
    <Legend items={all} hidden={hidden} toggle={toggle} />
    {p.caption && <figcaption className="faint">{p.caption}</figcaption>}
    <DataTable columns={data.columns.length ? data.columns : inferColumns(data.rows)} rows={data.rows} label={p.title ?? 'Chart'} />
  </figure>;
}
export const LineChart = ({ block }: P<'line_chart'>) => <XYChart block={block} kind="line_chart" />;
export const AreaChart = ({ block }: P<'area_chart'>) => <XYChart block={block} kind="area_chart" />;
export const BarChart = ({ block }: P<'bar_chart'>) => <XYChart block={block} kind="bar_chart" />;

export function PieChart({ block }: P<'pie_chart'>) {
  const p = block.props; const data = useData(block);
  if (!data) return <Missing what="The data for this chart is not available." />;
  const items = data.rows.map(r => ({ label: String(norm(r[p.labelKey]) ?? ''), v: num(r[p.valueKey]) })).filter((x): x is { label: string; v: number } => x.v !== null && x.v > 0);
  if (!items.length) return <Missing what="There are no positive numbers to chart." />;
  const sh = shares(items.map(i => i.v)); let a = -Math.PI / 2; const R0 = 100, R1 = p.donut ? 60 : 0;
  const pt = (r: number, ang: number) => `${130 + r * Math.cos(ang)},${130 + r * Math.sin(ang)}`;
  const arcs = sh.map(f => { const s = a; a += f * 2 * Math.PI; return [s, Math.min(a, s + 2 * Math.PI - 1e-4)] as const; });
  const total = items.reduce((x, i) => x + i.v, 0);
  const summary = p.summary ?? `Pie chart${p.title ? `: ${p.title}` : ''}. ${items.map((i, k) => `${i.label} ${Math.round(sh[k] * 100)}%`).join(', ')}.`;
  return <figure className="gen-chart pie"><div role="img" aria-label={summary}><svg viewBox="0 0 260 260" className="gen-svg pie" focusable="false">
    {arcs.map(([s, e], i) => { const big = e - s > Math.PI ? 1 : 0;
      const d = R1 ? `M${pt(R0, s)} A${R0},${R0} 0 ${big} 1 ${pt(R0, e)} L${pt(R1, e)} A${R1},${R1} 0 ${big} 0 ${pt(R1, s)} Z` : `M130,130 L${pt(R0, s)} A${R0},${R0} 0 ${big} 1 ${pt(R0, e)} Z`;
      return <path key={i} d={d} fill={color(i)} stroke="var(--surface)" strokeWidth="2"><title>{`${items[i].label}: ${fmt(items[i].v, p.unit)} (${Math.round(sh[i] * 100)}%)`}</title></path>; })}
    {p.donut && <text x="130" y="136" textAnchor="middle" className="gen-total">{fmt(total, p.unit)}</text>}</svg></div>
    <ul className="gen-legend static">{items.map((it, i) => <li key={i}><i style={{ background: color(i) }} />{it.label} <span className="faint">{Math.round(sh[i] * 100)}%</span></li>)}</ul>
    {p.caption && <figcaption className="faint">{p.caption}</figcaption>}
    <DataTable columns={[{ id: 'l', label: 'Item' }, { id: 'v', label: 'Value', type: 'number' }]} rows={items.map(i => ({ l: i.label, v: i.v }))} label={p.title ?? 'Chart'} /></figure>;
}

export function ScatterChart({ block }: P<'scatter_chart'>) {
  const p = block.props; const data = useData(block);
  if (!data) return <Missing what="The data for this chart is not available." />;
  const pts = data.rows.map(r => ({ x: num(r[p.xKey]), y: num(r[p.yKey]), l: p.labelKey ? String(norm(r[p.labelKey]) ?? '') : '' })).filter((q): q is { x: number; y: number; l: string } => q.x !== null && q.y !== null);
  if (pts.length < 2) return <Missing what="Not enough points to plot." />;
  const xs = pts.map(q => q.x), ys = pts.map(q => q.y); const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(0, ...ys), y1 = niceMax(Math.max(...ys));
  const pw = W - L - R, ph = H - T - Bm; const X = (v: number) => L + ((v - x0) / (x1 - x0 || 1)) * pw, Y = (v: number) => T + ph - ((v - y0) / (y1 - y0 || 1)) * ph;
  const labelsX = [0, 1, 2, 3, 4].map(i => x0 + ((x1 - x0) * i) / 4);
  const r = pearson(xs, ys); const summary = p.summary ?? `Scatter plot${p.title ? `: ${p.title}` : ''}. ${pts.length} points; ${p.xKey} against ${p.yKey}${r === null ? '' : `, correlation ${r.toFixed(2)}`}.`;
  return <figure className="gen-chart"><div role="img" aria-label={summary}><svg viewBox={`0 0 ${W} ${H}`} className="gen-svg" focusable="false">
    <g aria-hidden className="gen-axes">{[0, 1, 2, 3, 4].map(i => { const t = y0 + ((y1 - y0) * i) / 4; return <g key={i}><line x1={L} x2={W - R} y1={Y(t)} y2={Y(t)} stroke="var(--chart-grid)" /><text x={L - 8} y={Y(t) + 4} textAnchor="end">{fmt(t)}</text></g>; })}
      {labelsX.map((t, i) => <text key={i} x={X(t)} y={H - 10} textAnchor="middle">{fmt(t)}</text>)}</g>
    {pts.map((q, i) => <circle key={i} cx={X(q.x)} cy={Y(q.y)} r="4" fill="var(--chart-1)" opacity=".85"><title>{`${q.l ? q.l + ': ' : ''}${p.xKey} ${fmt(q.x)}, ${p.yKey} ${fmt(q.y, p.unit)}`}</title></circle>)}</svg></div>
    {p.caption && <figcaption className="faint">{p.caption}</figcaption>}
    <DataTable columns={data.columns.length ? data.columns : inferColumns(data.rows)} rows={data.rows} label={p.title ?? 'Chart'} /></figure>;
}
function pearson(a: number[], b: number[]): number | null {
  const n = a.length, ma = a.reduce((x, y) => x + y, 0) / n, mb = b.reduce((x, y) => x + y, 0) / n;
  let num2 = 0, da = 0, db = 0; for (let i = 0; i < n; i++) { num2 += (a[i] - ma) * (b[i] - mb); da += (a[i] - ma) ** 2; db += (b[i] - mb) ** 2; }
  return da && db ? num2 / Math.sqrt(da * db) : null;
}
export type { Block };

/** Equal-width bins over the numeric values of one column. Exported for tests. */
export function bin(values: number[], bins: number): Array<{ from: number; to: number; count: number }> {
  if (!values.length) return [];
  const lo = Math.min(...values), hi = Math.max(...values), width = (hi - lo) / bins || 1;
  const out = Array.from({ length: bins }, (_, i) => ({ from: lo + i * width, to: lo + (i + 1) * width, count: 0 }));
  for (const v of values) out[Math.min(bins - 1, Math.floor((v - lo) / width))].count++;
  return out;
}
export function HistogramChart({ block }: P<'histogram_chart'>) {
  const p = block.props; const data = useData(block);
  if (!data) return <Missing what="The data for this chart is not available." />;
  const vals = data.rows.map(r => num(r[p.valueKey])).filter((v): v is number => v !== null);
  if (vals.length < 5) return <Missing what="Not enough values for a distribution." />;
  const bins = bin(vals, p.bins); const top = niceMax(Math.max(...bins.map(b => b.count)));
  const pw = W - L - R, ph = H - T - Bm, band = pw / bins.length; const y = (v: number) => T + ph - (v / top) * ph;
  const peak = bins.reduce((a, b) => (b.count > a.count ? b : a));
  const summary = p.summary ?? `Histogram${p.title ? `: ${p.title}` : ''}. ${vals.length} values from ${fmt(Math.min(...vals), p.unit)} to ${fmt(Math.max(...vals), p.unit)}; most fall between ${fmt(peak.from, p.unit)} and ${fmt(peak.to, p.unit)} (${peak.count}).`;
  return <figure className="gen-chart"><div role="img" aria-label={summary}><svg viewBox={`0 0 ${W} ${H}`} className="gen-svg" focusable="false">
    <g aria-hidden className="gen-axes">{[0, 1, 2, 3, 4].map(i => { const t = (top * i) / 4; return <g key={i}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" /><text x={L - 8} y={y(t) + 4} textAnchor="end">{t}</text></g>; })}
      {bins.map((b, i) => i % Math.ceil(bins.length / 6) === 0 && <text key={i} x={L + band * i} y={H - 10} textAnchor="middle">{fmt(b.from, p.unit)}</text>)}</g>
    {bins.map((b, i) => <rect key={i} x={L + band * i + 1} width={Math.max(1, band - 2)} y={y(b.count)} height={Math.max(0, y(0) - y(b.count))} rx="2" fill="var(--chart-1)"><title>{`${fmt(b.from, p.unit)} to ${fmt(b.to, p.unit)}: ${b.count}`}</title></rect>)}</svg></div>
    {p.caption && <figcaption className="faint">{p.caption}</figcaption>}
    <DataTable columns={[{ id: 'r', label: 'Range' }, { id: 'c', label: 'Count', type: 'number' }]} rows={bins.map(b => ({ r: `${fmt(b.from, p.unit)} to ${fmt(b.to, p.unit)}`, c: b.count }))} label={p.title ?? 'Chart'} /></figure>;
}
