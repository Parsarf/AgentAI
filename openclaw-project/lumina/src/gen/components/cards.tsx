import { useState } from 'react';
import { formatCell } from '../../lib/genui/data';
import { safeHttpUrl } from '../safety';
import { cx, type B, type P } from './types';
import { useGen, useLocal } from './context';
import { Prose } from './text';
import type { Action } from '../schemas';

/** A button that runs one allowlisted action and says what happened. */
export function ActionButton({ label, action, style = 'secondary', disabled, nonce }: { label: string; action: Action; style?: string; disabled?: boolean; nonce?: string }) {
  const g = useGen(); const [state, setState] = useState<'idle' | 'busy' | 'done' | 'error'>('idle'); const [msg, setMsg] = useState('');
  const run = async () => {
    setState('busy'); const r = await g.act(action, { nonce, destructiveStyle: style === 'destructive' });
    if (r.ok) { setState('done'); setMsg(''); } else { setState(r.reason === 'declined' ? 'idle' : 'error'); setMsg(r.message); }
  };
  const cls = style === 'primary' ? 'btn primary' : style === 'destructive' ? 'btn danger' : style === 'ghost' ? 'btn tertiary' : 'btn';
  return <span className="gen-act"><button className={cx(cls, 'small')} disabled={disabled || g.readOnly || state === 'busy' || state === 'done'} onClick={run}>{state === 'done' ? `✓ ${label}` : label}</button>
    <span role="status" className={cx('gen-act-msg', state === 'error' && 'err')}>{state === 'error' ? msg : ''}</span></span>;
}

export function InfoCard({ block }: P<'info_card'>) {
  const p = block.props; const compact = block.variant === 'compact';
  const [l, set] = useLocal(block.id, { expanded: block.variant !== 'expandable' });
  const href = p.link ? safeHttpUrl(p.link.url) : null;
  return <CardBody b={block} title={p.title} p={p} compact={compact} href={href} open={!!l.expanded} toggle={block.variant === 'expandable' ? () => set({ expanded: !l.expanded }) : undefined} />;
}
type CardProps = B<'info_card'>['props'];
function CardBody({ b, title, p, compact, href, open, toggle }: { b: { id: string; variant?: string; disabled?: boolean }; title?: string; p: Omit<CardProps, 'title'> & { title?: string }; compact: boolean; href: string | null; open: boolean; toggle?: () => void }) {
  return <article className={cx('gen-card', compact && 'compact', b.variant === 'horizontal' && 'horizontal')} aria-labelledby={`${b.id}-t`}>
    <div className="gen-card-main">
      <header><h4 id={`${b.id}-t`}>{title}</h4>{p.badge && <span className="gen-badge">{p.badge}</span>}</header>
      {p.subtitle && <p className="faint">{p.subtitle}</p>}
      {toggle && <button className="btn tertiary small" aria-expanded={open} onClick={toggle}>{open ? 'Hide details' : 'Show details'}</button>}
      {open && <>
        {p.body && <Prose>{p.body}</Prose>}
        {p.facts && p.facts.length > 0 && <dl className="gen-facts">{p.facts.map((f, n) => <div key={n}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl>}
        {href && p.link && <a className="gen-link" href={href} target="_blank" rel="noopener noreferrer nofollow">{p.link.label} ↗<span className="sr"> (opens in a new tab)</span></a>}
        {p.actions && p.actions.length > 0 && <div className="gen-row">{p.actions.map((a, n) => <ActionButton key={n} label={a.label} action={a.action} disabled={b.disabled} />)}</div>}</>}
    </div></article>;
}
export function CardGrid({ block }: P<'card_grid'>) {
  const cols = block.layout?.columns;
  return <div className={cx('gen-grid', block.variant === 'horizontal' && 'one')} style={cols ? { ['--cols' as string]: cols } : undefined}>
    {block.props.cards.map((c, n) => <CardBody key={n} b={{ id: `${block.id}-${n}`, variant: block.variant === 'horizontal' ? 'horizontal' : undefined, disabled: block.disabled }} title={c.title} p={c} compact={block.variant === 'compact'} href={c.link ? safeHttpUrl(c.link.url) : null} open />)}</div>;
}
export function MetricCard({ block }: P<'metric_card'>) {
  const p = block.props;
  const shown = typeof p.value === 'number' ? (p.format === 'currency' ? new Intl.NumberFormat(undefined, { style: 'currency', currency: p.currency ?? 'USD', maximumFractionDigits: p.value % 1 ? 2 : 0 }).format(p.value)
    : formatCell(p.value, p.format === 'percent' ? 'percent' : 'number', p.unit)) : p.value;
  const d = p.delta; const dir = d ? (d.value > 0 ? 'up' : d.value < 0 ? 'down' : 'flat') : null;
  return <div className={cx('gen-metric', block.variant)} role="group" aria-label={`${p.label}: ${shown}`}>
    <span className="gen-metric-l">{p.label}</span><strong className="gen-metric-v">{shown}</strong>
    {d && <span className={cx('gen-delta', dir)}><span aria-hidden>{dir === 'up' ? '▲' : dir === 'down' ? '▼' : '–'}</span> {Math.abs(d.value).toLocaleString(undefined, { maximumFractionDigits: 2 })}{d.label ? ` ${d.label}` : ''}<span className="sr"> {dir === 'up' ? 'increase' : dir === 'down' ? 'decrease' : 'no change'}</span></span>}
    {p.trend && <Spark values={p.trend} />}{p.source && <span className="faint gen-src">Source: {p.source}</span>}</div>;
}
function Spark({ values }: { values: number[] }) {
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1; const W = 120, H = 28;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * W},${H - 2 - ((v - lo) / span) * (H - 4)}`).join(' ');
  return <svg className="gen-spark" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Trend from ${values[0]} to ${values[values.length - 1]}`}><polyline points={pts} fill="none" stroke="var(--chart-1)" strokeWidth="1.5" /></svg>;
}
const STATUS_LABEL = { idle: 'Idle', active: 'In progress', success: 'OK', warning: 'Needs attention', error: 'Problem' } as const;
export function StatusPill({ status, label }: { status: keyof typeof STATUS_LABEL; label?: string }) { return <span className={cx('gen-pill', status)}><span className="dot" aria-hidden />{label ?? STATUS_LABEL[status]}</span>; }
export function StatusCard({ block }: P<'status_card'>) {
  const p = block.props;
  return <div className="gen-status" role="status"><StatusPill status={p.status} /><div><strong>{p.label}</strong>{p.detail && <p className="faint">{p.detail}</p>}{p.updated && <p className="faint">Updated {p.updated}</p>}</div></div>;
}
export function ProgressBlock({ block }: P<'progress'>) {
  const p = block.props; const pct = Math.max(0, Math.min(100, (p.value / p.max) * 100));
  return <div className="gen-progress"><div className="gen-progress-h"><span>{p.label ?? p.title ?? 'Progress'}</span><span>{Math.round(pct)}%</span></div>
    <div className={cx('gen-bar', p.status)} role="progressbar" aria-valuemin={0} aria-valuemax={p.max} aria-valuenow={Math.min(p.value, p.max)} aria-label={p.label ?? p.title ?? 'Progress'}><i style={{ width: `${pct}%` }} /></div>
    {p.steps && <ul className="gen-steps">{p.steps.map((s, n) => <li key={n} className={s.done ? 'done' : ''}><span aria-hidden>{s.done ? '✓' : '○'}</span> {s.label}<span className="sr">{s.done ? ' (done)' : ' (not done)'}</span></li>)}</ul>}</div>;
}
export function ButtonGroup({ block }: P<'button_group'>) {
  return <div className="gen-row" role="group" aria-label={block.props.title ?? 'Actions'}>{block.props.buttons.map(b => <ActionButton key={b.id} label={b.label} action={b.action} style={b.style ?? (block.variant ?? 'secondary')} disabled={block.disabled} nonce={b.id} />)}</div>;
}
export function FollowUp({ block }: P<'follow_up'>) {
  return <div className="gen-row gen-follow" role="group" aria-label="Suggested next requests">{block.props.suggestions.map((s, n) => <ActionButton key={n} label={s} action={{ kind: 'agent.request', message: s }} style="ghost" />)}</div>;
}

/** Status of a gauge value from its zones (ascending `upTo`); no zones means neutral. */
export function zoneStatus(value: number, zones?: Array<{ upTo: number; status: 'idle' | 'active' | 'success' | 'warning' | 'error' }>) {
  if (!zones?.length) return 'idle' as const;
  return ([...zones].sort((a, b) => a.upTo - b.upTo).find(z => value <= z.upTo) ?? zones[zones.length - 1]).status;
}
export function Gauge({ block }: P<'gauge'>) {
  const p = block.props; const span = p.max - p.min || 1; const frac = Math.max(0, Math.min(1, (p.value - p.min) / span)); const st = zoneStatus(p.value, p.zones);
  const a = Math.PI * (1 - frac); const pt = (r: number, ang: number) => `${100 + r * Math.cos(ang)},${100 - r * Math.sin(ang)}`;
  const shown = `${p.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}${p.unit ? ' ' + p.unit : ''}`;
  return <div className={cx('gen-gauge', st)} role="meter" aria-valuemin={p.min} aria-valuemax={p.max} aria-valuenow={Math.max(p.min, Math.min(p.max, p.value))} aria-label={`${p.label ?? p.title ?? 'Value'}: ${shown}`}>
    <svg viewBox="0 0 200 116" aria-hidden focusable="false"><path d={`M${pt(80, Math.PI)} A80,80 0 0 1 ${pt(80, 0)}`} className="track" fill="none" strokeWidth="14" strokeLinecap="round" />
      {frac > 0 && <path d={`M${pt(80, Math.PI)} A80,80 0 0 1 ${pt(80, a)}`} className="fill" fill="none" strokeWidth="14" strokeLinecap="round" />}</svg>
    <strong>{shown}</strong>{p.label && <span className="gen-metric-l">{p.label}</span>}
    <span className="faint gen-src">{p.min} to {p.max}{p.zones ? ` · ${STATUS_LABEL[st]}` : ''}{p.source ? ` · Source: ${p.source}` : ''}</span></div>;
}
