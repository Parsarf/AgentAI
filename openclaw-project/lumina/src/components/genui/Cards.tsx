import { useMemo, useState } from 'react';
import { filterRows, formatCell, niceMax, shares, sortRows, toCsv, type ChartSpec, type ComparisonSpec, type TableSpec } from '../../lib/genui/data';

const COLORS = ['#7b78ff', '#35d0ba', '#ffb454', '#ff6b8b', '#8fb4ff', '#b8f27c'];
const link = (href: string, text: string) => <a href={href} target="_blank" rel="noopener noreferrer nofollow">{text} ↗</a>;

export function TableCard({ spec }: { spec: TableSpec }) {
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 } | null>(null); const [q, setQ] = useState(''); const [copied, setCopied] = useState(false);
  const best = spec.highlightRow !== undefined ? spec.rows[spec.highlightRow] : undefined;
  const rows = useMemo(() => { const f = filterRows(spec.rows, q); return sort ? sortRows(f, sort.col, sort.dir) : f; }, [spec.rows, q, sort]);
  const click = (col: string) => setSort(s => (!s || s.col !== col ? { col, dir: 1 } : s.dir === 1 ? { col, dir: -1 } : null));
  const copy = async () => { try { await navigator.clipboard.writeText(toCsv(spec, rows)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ } };
  return (
    <section className="gcard" aria-label={spec.title}>
      <header className="gcard-h"><h3>{spec.title}</h3>
        <div className="gcard-tools">
          {spec.rows.length > 6 && <input className="gfilter" type="search" placeholder="Filter…" aria-label="Filter rows" value={q} onChange={e => setQ(e.target.value)} />}
          <button className="btn small" onClick={copy}>{copied ? 'Copied' : 'Copy CSV'}</button></div></header>
      <div className="gtable-wrap"><table className="gtable">
        <thead><tr>{spec.columns.map(c => {
          const on = sort?.col === c.id; const num = c.type !== 'text' && c.type !== 'link';
          return <th key={c.id} className={num ? 'num' : ''} aria-sort={on ? (sort!.dir === 1 ? 'ascending' : 'descending') : 'none'}>
            <button onClick={() => click(c.id)}>{c.label}<span aria-hidden className="arrow">{on ? (sort!.dir === 1 ? '↑' : '↓') : ''}</span></button></th>;
        })}</tr></thead>
        <tbody>{rows.map((r, n) => (
          <tr key={n} className={r === best ? 'best' : ''}>{spec.columns.map(c => {
            const v = r[c.id]; const num = c.type !== 'text' && c.type !== 'link';
            return <td key={c.id} className={num ? 'num' : ''}>{c.type === 'link' && typeof v === 'string' ? link(v, 'Open') : formatCell(v, c.type, c.unit)}</td>;
          })}</tr>))}
          {!rows.length && <tr><td colSpan={spec.columns.length} className="faint">No rows match.</td></tr>}</tbody></table></div>
      {(spec.caption || rows.length !== spec.rows.length) && <p className="gcard-cap">{spec.caption}{rows.length !== spec.rows.length ? ` Showing ${rows.length} of ${spec.rows.length}.` : ''}</p>}
    </section>);
}

export function ChartCard({ spec }: { spec: ChartSpec }) {
  const [off, setOff] = useState<Set<number>>(new Set()); const [hover, setHover] = useState<string | null>(null);
  const toggle = (i: number) => setOff(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n.size === spec.series.length ? s : n; });
  const fmt = (v: number) => `${spec.unit && spec.unit.length === 1 ? spec.unit : ''}${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}${spec.unit && spec.unit.length > 1 ? ' ' + spec.unit : ''}`;
  const W = 640, H = 280, L = 48, R = 12, T = 12, B = 34; const pw = W - L - R, ph = H - T - B;
  const visible = spec.series.map((s, i) => ({ s, i })).filter(x => !off.has(x.i));
  const max = niceMax(Math.max(0, ...visible.flatMap(x => x.s.values)));
  const min = Math.min(0, ...visible.flatMap(x => x.s.values)); const span = niceMax(max) - min || 1;
  const y = (v: number) => T + ph - ((v - min) / span) * ph; const n = spec.labels.length;
  const band = pw / n; const cx = (k: number) => L + band * k + band / 2;
  const pie = spec.chart === 'pie' || spec.chart === 'donut'; const vals = spec.series[0].values; const sh = shares(vals); const total = vals.reduce((a, b) => a + b, 0);
  const arcs = useMemo(() => { let a = -Math.PI / 2; return sh.map(f => { const s = a; a += f * 2 * Math.PI; return [s, a] as const; }); }, [sh.join(',')]);   // eslint-disable-line react-hooks/exhaustive-deps
  const R0 = 110, R1 = spec.chart === 'donut' ? 66 : 0; const pt = (r: number, a: number) => [140 + r * Math.cos(a), 130 + r * Math.sin(a)];
  const slice = (a0: number, a1: number) => {
    if (a1 - a0 >= 2 * Math.PI - 1e-6) a1 = a0 + 2 * Math.PI - 1e-3;
    const [x0, y0] = pt(R0, a0), [x1, y1] = pt(R0, a1), [x2, y2] = pt(R1, a1), [x3, y3] = pt(R1, a0); const big = a1 - a0 > Math.PI ? 1 : 0;
    return R1 ? `M${x0} ${y0}A${R0} ${R0} 0 ${big} 1 ${x1} ${y1}L${x2} ${y2}A${R1} ${R1} 0 ${big} 0 ${x3} ${y3}Z` : `M140 130L${x0} ${y0}A${R0} ${R0} 0 ${big} 1 ${x1} ${y1}Z`;
  };
  const ticks = [0, 1, 2, 3, 4].map(k => min + (span * k) / 4);
  return (
    <section className="gcard" aria-label={spec.title}>
      <header className="gcard-h"><h3>{spec.title}</h3><span className="gread" role="status">{hover ?? ' '}</span></header>
      {pie ? (
        <div className="gpie">
          <svg viewBox="0 0 280 260" role="img" aria-label={spec.title}>
            {arcs.map(([a0, a1], i) => <path key={i} d={slice(a0, a1)} fill={COLORS[i % COLORS.length]} stroke="var(--bg)" strokeWidth="2" opacity={hover && !hover.startsWith(spec.labels[i]) ? 0.45 : 1}
              onMouseEnter={() => setHover(`${spec.labels[i]}: ${fmt(vals[i])} (${(sh[i] * 100).toFixed(1)}%)`)} onMouseLeave={() => setHover(null)} style={{ transition: 'opacity .15s', cursor: 'default' }}><title>{`${spec.labels[i]}: ${fmt(vals[i])}`}</title></path>)}
            {spec.chart === 'donut' && <><text x="140" y="126" textAnchor="middle" className="gt-sub">Total</text><text x="140" y="148" textAnchor="middle" className="gt-big">{fmt(total)}</text></>}
          </svg>
          <ul className="glegend col">{spec.labels.map((l, i) => <li key={i} onMouseEnter={() => setHover(`${l}: ${fmt(vals[i])} (${(sh[i] * 100).toFixed(1)}%)`)} onMouseLeave={() => setHover(null)}><i style={{ background: COLORS[i % COLORS.length] }} />{l}<b>{(sh[i] * 100).toFixed(0)}%</b></li>)}</ul>
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={spec.title} className="gplot">
          {ticks.map((tv, k) => <g key={k}><line x1={L} x2={W - R} y1={y(tv)} y2={y(tv)} stroke="rgba(255,255,255,.08)" /><text x={L - 8} y={y(tv) + 4} textAnchor="end" className="gt-axis">{tv.toLocaleString(undefined, { maximumFractionDigits: 1 })}</text></g>)}
          {spec.labels.map((l, k) => (n <= 12 || k % Math.ceil(n / 12) === 0) && <text key={k} x={cx(k)} y={H - 12} textAnchor="middle" className="gt-axis">{l.length > 10 ? l.slice(0, 9) + '…' : l}</text>)}
          {spec.chart === 'bar' && visible.map(({ s, i }, vi) => s.values.map((v, k) => {
            const bw = Math.min(40, (band * 0.7) / visible.length); const x = cx(k) - (bw * visible.length) / 2 + vi * bw; const y0 = y(Math.max(v, 0)); const hgt = Math.abs(y(v) - y(0));
            return <rect key={`${i}-${k}`} x={x} y={y0} width={bw - 2} height={Math.max(hgt, 1)} rx="3" fill={COLORS[i % COLORS.length]} opacity={hover && hover !== `${s.name}|${k}` ? 0.5 : 1}
              onMouseEnter={() => setHover(`${spec.labels[k]} · ${s.name}: ${fmt(v)}`)} onMouseLeave={() => setHover(null)} className="gbar" style={{ ['--i' as any]: k }}><title>{`${spec.labels[k]}: ${fmt(v)}`}</title></rect>;
          }))}
          {spec.chart === 'line' && visible.map(({ s, i }) => <g key={i}>
            <polyline fill="none" stroke={COLORS[i % COLORS.length]} strokeWidth="2.5" strokeLinejoin="round" points={s.values.map((v, k) => `${cx(k)},${y(v)}`).join(' ')} className="gline" pathLength={1} />
            {s.values.map((v, k) => <circle key={k} cx={cx(k)} cy={y(v)} r="4.5" fill={COLORS[i % COLORS.length]} stroke="var(--bg)" strokeWidth="2"
              onMouseEnter={() => setHover(`${spec.labels[k]} · ${s.name}: ${fmt(v)}`)} onMouseLeave={() => setHover(null)}><title>{`${spec.labels[k]}: ${fmt(v)}`}</title></circle>)}</g>)}
        </svg>)}
      {!pie && spec.series.length > 1 && <ul className="glegend">{spec.series.map((s, i) => <li key={i}><button aria-pressed={!off.has(i)} onClick={() => toggle(i)}><i style={{ background: COLORS[i % COLORS.length], opacity: off.has(i) ? 0.3 : 1 }} />{s.name}</button></li>)}</ul>}
      {spec.caption && <p className="gcard-cap">{spec.caption}</p>}
    </section>);
}

export function ComparisonCard({ spec }: { spec: ComparisonSpec }) {
  const [pick, setPick] = useState<number | null>(spec.bestIndex ?? null);
  return (
    <section className="gcard gcard-comparison" aria-label={spec.title}>
      <header className="gcard-h"><h3>{spec.title}</h3><span className="gcompare-count">{spec.items.length} options</span></header>
      <div className="gcompare" data-count={spec.items.length}>
        {spec.items.map((it, i) => (
          <article key={i} className={`gopt${pick === i ? ' on' : ''}`}>
            <div className="gopt-heading">
              {(it.badge || spec.bestIndex === i) && <span className="gbadge">{it.badge ?? 'Best pick'}</span>}
              <h4>{it.name}</h4>{it.subtitle && <p className="gopt-subtitle">{it.subtitle}</p>}{it.price && <p className="gprice">{it.price}</p>}
            </div>
            {it.facts.length > 0 && <dl>{it.facts.map((f, k) => <div key={k}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl>}
            {it.pros.length > 0 && <ul className="pros" aria-label="Advantages">{it.pros.map((p, k) => <li key={k}>{p}</li>)}</ul>}
            {it.cons.length > 0 && <ul className="cons" aria-label="Tradeoffs">{it.cons.map((p, k) => <li key={k}>{p}</li>)}</ul>}
            <footer className="gopt-actions">
              <button className="gopt-pick" aria-pressed={pick === i} aria-label={`Select ${it.name}`} onClick={() => setPick(pick === i ? null : i)}>{pick === i ? 'Selected' : 'Select option'}</button>
              {it.link && link(it.link, 'View details')}
            </footer>
          </article>))}
      </div>
      {spec.caption && <p className="gcard-cap">{spec.caption}</p>}
    </section>);
}
