import { lazy, Suspense, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { FAMILIES } from '../catalog';
import { calculate } from '../operations';
import { safeInternalPath } from '../safety';
import { useGen, useLocal } from './context';
import { ActionButton } from './cards';
import { Prose, CodeBlock } from './text';
import { ExecutionTimeline, PlanViewer } from './agent';
import Menu from '../../components/ui/Menu';
import { LineChart, TableBlock } from './data';

const MathView = lazy(() => import('./math'));
const MermaidView = lazy(() => import('./mermaid'));
const Visual = lazy(() => import('./visuals'));
const Media = lazy(() => import('./media'));
type Props = { block: any; nested?: (blocks: unknown[]) => ReactNode[] };
export function Unavailable({ children }: { children: ReactNode }) { return <p className="gen-empty" role="status">{children}</p>; }
export default function Extended({ block, nested = () => [] }: Props) {
  const family = (FAMILIES as Record<string, string>)[block.type];
  const view = block.type === 'mermaid' ? <MermaidView source={block.props.source ?? ''} label={block.props.title ?? 'Mermaid diagram'} /> : block.type === 'math' ? <MathView source={block.props.content} /> : family === 'container' ? <Container block={block} nested={nested} />
    : family === 'grid' ? <Grid block={block} /> : family === 'domain' ? <Domain block={block} />
    : family === 'checklist' ? <Checklist block={block} /> : family === 'control' ? <Control block={block} /> : family === 'decision' ? (['decision_matrix', 'weighted_scoring'].includes(block.type) ? <DecisionMatrix block={block} /> : ['rule_builder', 'filter_builder'].includes(block.type) ? <RuleBuilder block={block} /> : <Decision block={block} />)
    : ['chart', 'graph', 'map', 'schedule'].includes(family) ? <Visual block={block} />
    : ['media', 'file'].includes(family) ? <Media block={block} />
    : family === 'runtime' ? <Runtime block={block} /> : family === 'menu' ? <ActionMenu block={block} />
    : family === 'tree' ? <Tree block={block} /> : family === 'timer' ? <Timer block={block} />
    : family === 'recurrence' ? <Recurrence block={block} /> : family === 'conversion' ? <Conversion block={block} />
    : family === 'wizard' ? <Wizard block={block} /> : family === 'prompt' ? <Prompt block={block} />
    : family === 'confirm' ? <><p>{block.props.message}</p><ActionButton label={block.props.label} action={block.props.action} destructiveStyle={true} /></>
    : family === 'upload' ? <Upload block={block} /> : family === 'pager' ? <Pager block={block} />
    : family === 'links' ? <Links block={block} /> : family === 'inspect' ? <Inspector block={block} />
    : family === 'code' ? <Highlighted block={block} /> : <Content block={block} />;
  return <Suspense fallback={<p role="status">Loading component…</p>}><fieldset className="gen-capability" disabled={block.disabled}>{view}</fieldset></Suspense>;
}
function Checklist({ block: b }: Props) {
  const [l, set] = useLocal(b.id, { checked: Object.fromEntries(b.props.items.map((i: any) => [i.id, !!i.checked])) });
  return <ul className="gen-checklist">{b.props.items.map((i: any) => <li key={i.id}><label className="gen-check"><input type="checkbox" checked={!!l.checked[i.id]} onChange={e => set({ checked: { ...l.checked, [i.id]: e.target.checked } })} />{i.label}</label></li>)}</ul>;
}
function Content({ block: b }: Props) {
  if (b.type === 'tooltip') return <span className="gen-tooltip" tabIndex={0} aria-describedby={`${b.id}-tip`}>{b.props.title ?? 'Details'}<span role="tooltip" id={`${b.id}-tip`}>{b.props.content}</span></span>;
  return <details open={b.type !== 'expandable_text'}><summary>{b.props.title ?? 'Details'}</summary><Prose>{b.props.content}</Prose>{b.props.source && <a href={b.props.source} target="_blank" rel="noopener noreferrer">Source</a>}</details>;
}
function Highlighted({ block: b }: Props) {
  // Tokens are React text nodes; code is never inserted as HTML.
  const chunks = b.props.code.split(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b(?:const|let|var|function|return|if|else|for|while|class|import|from|def|True|False|null|true|false)\b|\b\d+(?:\.\d+)?\b)/g);
  return <div><pre className="gen-code" tabIndex={0} aria-label={b.props.language ?? 'Code'}><code>{chunks.map((v: string, i: number) => <span key={i} className={i % 2 ? 'gen-token' : undefined}>{v}</span>)}</code></pre><Copy value={b.props.code} /></div>;
}
function Copy({ value }: { value: string }) { const [msg, set] = useState('Copy'); return <button className="btn small" onClick={async () => { try { await navigator.clipboard.writeText(value); set('Copied'); } catch { set('Copy failed'); } }}>{msg}</button>; }
function Container({ block: b, nested = () => [] }: Props) {
  const [l, set] = useLocal(b.id, { index: 0, open: false, ratio: 50 }); const dialog = useRef<HTMLDialogElement>(null); const uid = useId();
  useEffect(() => { if (!dialog.current) return; if (l.open && !dialog.current.open) dialog.current.showModal(); else if (!l.open && dialog.current.open) dialog.current.close(); }, [l.open]);
  const blocks = b.props.blocks as any[]; const index = Math.min(Number(l.index), blocks.length - 1);
  const pages = ['carousel', 'flip_card', 'tabbed_card'].includes(b.type);
  if (b.type === 'modal' || b.type === 'drawer') return <><button className="btn" onClick={() => set({ open: true })}>Open {b.props.title ?? 'details'}</button><dialog ref={dialog} className={`gen-dialog gen-${b.type}`} aria-labelledby={uid} onCancel={() => set({ open: false })} onClose={() => set({ open: false })}><h3 id={uid}>{b.props.title ?? 'Details'}</h3>{nested(blocks)}<button className="btn" onClick={() => set({ open: false })}>Close</button></dialog></>;
  if (b.type === 'popover') return <><button className="btn" popoverTarget={uid}>{b.props.title ?? 'Details'}</button><div className="gen-popover" id={uid} popover="auto">{nested(blocks)}</div></>;
  if (['collapsible', 'expandable_card'].includes(b.type)) return <details><summary>{b.props.title ?? 'Details'}</summary>{nested(blocks)}</details>;
  if (pages) return <section aria-label={b.props.title ?? 'Views'}><div className="gen-row">{blocks.map((_, i) => <button key={i} className="chip" aria-pressed={i === index} onClick={() => set({ index: i })}>{b.props.labels?.[i] ?? `View ${i + 1}`}</button>)}</div><div aria-live="polite">{nested([blocks[index]])}</div></section>;
  return <section>{b.type === 'resizable_panels' && <label>Panel width <input type="range" min={20} max={80} value={Number(l.ratio)} onChange={e => set({ ratio: +e.target.value })} /></label>}<div className="gen-split" style={{ gridTemplateColumns: `${l.ratio}% minmax(0,1fr)` }}>{nested(blocks)}</div></section>;
}
function Control({ block: b }: Props) {
  const p = b.props; const [l, set] = useLocal(b.id, { value: p.value ?? (['multiselect', 'tags', 'range_slider', 'date_range'].includes(b.type) ? [] : '') }); const uid = useId(); const val = l.value as any;
  if (b.type === 'multiselect') return <fieldset><legend>{p.label}</legend>{p.options?.map((o: any) => <label key={o.id} className="gen-check"><input type="checkbox" checked={Array.isArray(val) && val.includes(o.id)} onChange={e => set({ value: e.target.checked ? [...(Array.isArray(val) ? val : []), o.id] : val.filter((v: string) => v !== o.id) })} />{o.label}</label>)}</fieldset>;
  if (b.type === 'range_slider' || b.type === 'date_range') return <fieldset><legend>{p.label}</legend>{['Start', 'End'].map((label, i) => <label key={label}>{label}<input className="input" type={b.type === 'date_range' ? 'date' : 'range'} min={p.min} max={p.max} step={p.step} value={val[i] ?? (i ? p.max ?? 100 : p.min ?? 0)} onChange={e => { const next = [...val]; next[i] = b.type === 'date_range' ? e.target.value : +e.target.value; set({ value: next }); }} /><output>{val[i]}</output></label>)}{val.length === 2 && val[0] > val[1] && <p role="alert">Start must precede end.</p>}</fieldset>;
  if (b.type === 'rating') return <fieldset><legend>{p.label}</legend>{Array.from({ length: Math.min(10, p.max ?? 5) }, (_, i) => <label className="chip" key={i}><input type="radio" name={uid} checked={val === i + 1} onChange={() => set({ value: i + 1 })} />{i + 1}</label>)}</fieldset>;
  return <label className="gen-field">{p.label}<input className="input" type={b.type === 'color_picker' ? 'color' : b.type === 'search_input' ? 'search' : 'text'} list={b.type === 'autocomplete' ? uid : undefined} maxLength={500} value={Array.isArray(val) ? val.join(', ') : String(val)} onChange={e => set({ value: b.type === 'tags' ? e.target.value.split(',').map(v => v.trim()).slice(0, 50) : e.target.value })} />{b.type === 'autocomplete' && <datalist id={uid}>{p.options?.map((o: any) => <option key={o.id} value={o.label} />)}</datalist>}{b.type === 'tags' && <span className="faint">Separate tags with commas.</span>}</label>;
}
function Domain({ block: b }: Props) {
  const p = b.props; const [l, set] = useLocal(b.id, { selected: '' });
  if (p.provider.status === 'unavailable') return <Unavailable>{p.provider.reason ?? `${b.type} integration is unavailable.`}</Unavailable>;
  const series = p.columns.filter((c: any) => c.type === 'number').map((c: any) => ({ key: c.id, label: c.label }));
  return <section><p className="faint">{p.source ? `Source: ${p.source}` : 'Provided data'}{p.observedAt ? ` · Observed ${p.observedAt}` : ' · Observation time not supplied'}</p>{['stocks', 'health_trends'].includes(b.type) && series.length && p.rows.length >= 4 ? <LineChart block={{ ...b, type: 'line_chart', props: { xKey: p.columns[0].id, series, data: p.rows.slice(0, 60), summary: p.description } }} /> : null}<Grid block={b} />{b.type === 'reservations' && <><label>Select an available option<select className="input" value={String(l.selected)} onChange={e => set({ selected: e.target.value })}><option value="">Choose</option>{p.rows.map((r: any, i: number) => <option key={i} value={i}>{Object.values(r).join(' · ')}</option>)}</select></label><p className="faint">Selection saved here. A reservation has not been booked; booking requires an external integration.</p></>}</section>;
}
function TreeTable({ block: b }: Props) {
  const p = b.props, rows = p.rows as any[]; const [l, set] = useLocal(b.id, { open: [] as string[] }); const idKey = 'id', parent = p.parentKey ?? 'parent';
  const ids = new Set(rows.map(r => String(r[idKey]))); const children = (id: string) => rows.filter(r => String(r[parent]) === id);
  const flat: Array<{ row: any; depth: number }> = [];
  const walk = (row: any, depth: number, seen: Set<string>) => { const id = String(row[idKey]); if (seen.has(id)) return; flat.push({ row, depth }); if (l.open.includes(id)) children(id).forEach(c => walk(c, depth + 1, new Set([...seen, id]))); };
  rows.filter(r => r[parent] == null || r[parent] === '' || !ids.has(String(r[parent]))).forEach(r => walk(r, 0, new Set()));
  return <div className="gen-scroll" role="region" aria-label={p.title ?? 'Tree table'} tabIndex={0}><table className="gen-table"><thead><tr>{p.columns.map((c: any) => <th key={c.id} scope="col">{c.label}</th>)}</tr></thead><tbody>{flat.map(({ row, depth }) => <tr key={row[idKey]}>{p.columns.map((c: any, i: number) => <td key={c.id} style={i === 0 ? { paddingInlineStart: `calc(var(--space-3) + ${depth} * var(--space-4))` } : undefined}>{i === 0 && children(String(row[idKey])).length > 0 && <button className="btn small" aria-label={`Expand ${String(row[c.id])}`} aria-expanded={l.open.includes(String(row[idKey]))} onClick={() => { const id = String(row[idKey]); set({ open: l.open.includes(id) ? l.open.filter(v => v !== id) : [...l.open, id] }); }}>{l.open.includes(String(row[idKey])) ? 'Collapse' : 'Expand'}</button>} {String(row[c.id] ?? '')}</td>)}</tr>)}</tbody></table>{!flat.length && <Unavailable>No rooted rows are available. Tree rows require unique id and parent values.</Unavailable>}</div>;
}
function Grid({ block: b }: Props) {
  const p = b.props; const [l, set] = useLocal(b.id, { edits: {} as Record<string, unknown>, query: '', page: 0, expanded: [] as string[] });
  if (b.type === 'tree_table') return <TreeTable block={b} />;
  if (p.provider?.status === 'unavailable') return <Unavailable>{p.provider.reason ?? `${b.type} provider is not connected.`}</Unavailable>;
  let rows = p.rows as Record<string, any>[];
  if (b.type === 'pivot_table' && p.groupBy && p.valueKey) {
    const grouped = new Map<string, number>(); rows.forEach(r => { const key = String(r[p.groupBy]); grouped.set(key, (grouped.get(key) ?? 0) + (Number(r[p.valueKey]) || 0)); });
    rows = [...grouped].map(([group, sum]) => ({ [p.groupBy]: group, [p.valueKey]: sum }));
  }
  if (b.type !== 'editable_table' && b.type !== 'tree_table') return <>{p.source && <p className="faint">Source: {p.source}{p.observedAt && ` · ${p.observedAt}`}</p>}<TableBlock block={{ ...b, type: 'table', props: { ...p, rows, searchable: true, sortable: true, pageSize: 20 } }} /></>;
  const visible = rows.map((r, i) => ({ r, i })).filter(({ r }) => Object.values(r).some(v => String(v).toLowerCase().includes(String(l.query).toLowerCase())));
  const page = Math.min(Number(l.page), Math.max(0, Math.ceil(visible.length / 20) - 1));
  return <><label>Search rows<input className="input" value={String(l.query)} onChange={e => set({ query: e.target.value, page: 0 })} /></label><div className="gen-scroll" tabIndex={0} role="region" aria-label={p.title ?? 'Data grid'}><table className="gen-table"><thead><tr>{p.columns.map((c: any) => <th key={c.id} scope="col">{c.label}</th>)}</tr></thead><tbody>{visible.slice(page * 20, (page + 1) * 20).map(({ r, i }) => <tr key={i}>{p.columns.map((c: any) => <td key={c.id}>{b.type === 'editable_table' ? <input className="input" aria-label={`${c.label}, row ${i + 1}`} type={c.type === 'number' ? 'number' : 'text'} value={String((l.edits as any)[`${i}:${c.id}`] ?? r[c.id] ?? '')} maxLength={500} onChange={e => { const v = c.type === 'number' ? +e.target.value : e.target.value; if (typeof v !== 'number' || Number.isFinite(v)) set({ edits: { ...l.edits, [`${i}:${c.id}`]: v } }); }} /> : <>{c.id === p.parentKey ? <span className="faint">Parent: </span> : null}{String(r[c.id] ?? '')}</>}</td>)}</tr>)}</tbody></table></div>{!rows.length && <Unavailable>No rows available.</Unavailable>}<div className="gen-row"><button className="btn small" disabled={page === 0} onClick={() => set({ page: page - 1 })}>Previous</button><span>Page {page + 1}</span><button className="btn small" disabled={(page + 1) * 20 >= visible.length} onClick={() => set({ page: page + 1 })}>Next</button></div>{b.type === 'editable_table' && <p className="faint">Edits are saved in this artifact. They do not write to an external database.</p>}</>;
}
function DecisionMatrix({ block: b }: Props) {
  const p = b.props; const [l, set] = useLocal(b.id, { weights: Object.fromEntries(p.inputs.map((i: any) => [i.id, i.weight ?? 1])) });
  const scores = p.scenarios.map((s: any) => { try { return calculate('weighted_average', p.inputs.map((i: any) => s.values[i.id]), p.inputs.map((i: any) => l.weights[i.id])); } catch { return null; } });
  return <div className="gen-scroll" role="region" tabIndex={0} aria-label={p.title ?? 'Decision matrix'}><table className="gen-table"><thead><tr><th scope="col">Criterion</th><th scope="col">Weight</th>{p.scenarios.map((s: any) => <th key={s.label} scope="col">{s.label}</th>)}</tr></thead><tbody>{p.inputs.map((i: any) => <tr key={i.id}><th scope="row">{i.label}</th><td><input className="input" type="number" min={0} max={1000} step={.1} aria-label={`Weight for ${i.label}`} value={l.weights[i.id]} onChange={e => { const v = +e.target.value; if (Number.isFinite(v) && v >= 0 && v <= 1000) set({ weights: { ...l.weights, [i.id]: v } }); }} /></td>{p.scenarios.map((s: any) => <td key={s.label}>{s.values[i.id] ?? 'Unavailable'}</td>)}</tr>)}</tbody><tfoot><tr><th scope="row">Weighted score</th><td />{scores.map((score: number | null, i: number) => <td key={i}><output aria-live="polite">{score === null ? 'Unavailable: check scores and weights' : score.toFixed(2)}</output></td>)}</tr></tfoot></table><p className="faint">Scores use the supplied criterion values and adjustable nonnegative weights.</p></div>;
}
function RuleBuilder({ block: b }: Props) {
  const p = b.props; const [l, set] = useLocal(b.id, { rules: p.rules ?? [{ field: p.inputs[0].id, operator: 'at_least', value: 0 }], combinator: p.combinator ?? 'all' });
  const test = (rule: any) => { const v = p.inputs.find((i: any) => i.id === rule.field)?.value; switch (rule.operator) { case 'equal': return v === rule.value; case 'not_equal': return v !== rule.value; case 'greater': return v > rule.value; case 'less': return v < rule.value; case 'at_least': return v >= rule.value; case 'at_most': return v <= rule.value; default: return false; } };
  const outcomes = l.rules.map(test); const matched = l.combinator === 'all' ? outcomes.every(Boolean) : outcomes.some(Boolean);
  return <section><label>Match<select className="input" value={String(l.combinator)} onChange={e => set({ combinator: e.target.value })}><option value="all">All conditions</option><option value="any">Any condition</option></select></label>{l.rules.map((r: any, i: number) => <fieldset className="gen-row" key={i}><legend>Condition {i + 1}</legend><label>Field<select className="input" value={r.field} onChange={e => set({ rules: l.rules.map((x: any, j: number) => i === j ? { ...x, field: e.target.value } : x) })}>{p.inputs.map((x: any) => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label><label>Operator<select className="input" value={r.operator} onChange={e => set({ rules: l.rules.map((x: any, j: number) => i === j ? { ...x, operator: e.target.value } : x) })}>{['equal', 'not_equal', 'greater', 'less', 'at_least', 'at_most'].map(op => <option key={op} value={op}>{op.replaceAll('_', ' ')}</option>)}</select></label><label>Value<input className="input" type="number" value={r.value} onChange={e => { if (Number.isFinite(+e.target.value)) set({ rules: l.rules.map((x: any, j: number) => i === j ? { ...x, value: +e.target.value } : x) }); }} /></label><button className="btn small" disabled={l.rules.length === 1} onClick={() => set({ rules: l.rules.filter((_: any, j: number) => j !== i) })}>Remove condition {i + 1}</button></fieldset>)}<button className="btn" disabled={l.rules.length >= 20} onClick={() => set({ rules: [...l.rules, { field: p.inputs[0].id, operator: 'at_least', value: 0 }] })}>Add condition</button><output aria-live="polite">{matched ? 'Matches the provided values' : 'Does not match the provided values'}</output></section>;
}
function Decision({ block: b }: Props) {
  const p = b.props; const defaults = Object.fromEntries(p.inputs.map((v: any) => [v.id, v.value])); const [l, set] = useLocal(b.id, { values: defaults }); const values = { ...defaults, ...l.values };
  const compute = (v: Record<string, number>) => { try { return calculate(p.operation, p.inputs.map((x: any) => v[x.id]), p.inputs.map((x: any) => x.weight ?? 1), p.budget).toLocaleString(undefined, { maximumFractionDigits: 4 }); } catch (e) { return (e as Error).message; } };
  return <section><div className="gen-grid">{p.inputs.map((v: any) => <label key={v.id} className="gen-field">{v.label}<input className="input" type="number" min={v.min} max={v.max} step={v.step ?? 'any'} value={values[v.id]} onChange={e => { const n = +e.target.value; if (Number.isFinite(n) && n >= (v.min ?? -1e15) && n <= (v.max ?? 1e15)) set({ values: { ...values, [v.id]: n } }); }} /></label>)}</div><output aria-live="polite">{p.operation === 'budget' ? 'Remaining: ' : 'Result: '}{compute(values)} {p.unit}</output>{p.scenarios?.map((s: any) => <p key={s.label}>{s.label}: {compute({ ...values, ...s.values })} {p.unit}</p>)}<p className="faint">Calculated locally using {p.operation.replaceAll('_', ' ')}.</p></section>;
}
const DependencyGraph = lazy(() => import('./visuals').then(m => ({ default: m.Graph })));
function Runtime({ block: b }: Props) {
  const g = useGen();
  if (b.type === 'token_cost_monitor') return <UsageMonitor block={b} />;
  if (b.type === 'plan_editor') return <>{g.exec.planEditor?.(b.props.planBlockId) ?? <Unavailable>This plan is unavailable.</Unavailable>}</>;
  if (b.type === 'dependency_graph') {
    const plan = g.exec.plan(b.props.planBlockId);
    if (!plan) return <Unavailable>A plan in this conversation is required for its dependency graph.</Unavailable>;
    return <DependencyGraph block={{ ...b, type: 'network_graph', props: { nodes: plan.phases.map(p => ({ id: p.id, label: p.title, detail: plan.run[p.id]?.state ?? 'pending' })), edges: plan.phases.flatMap(p => (p.dependsOn ?? []).map(source => ({ source, target: p.id }))) } }} />;
  }
  return <RuntimeRecords block={b} />;
}
function UsageMonitor({ block: b }: Props) {
  const g = useGen(); const request = g.exec.request(b.props.requestId);
  const snapshot = g.exec.useSnapshot?.(b.props.requestId, request?.state === 'running');
  if (!request) return <Unavailable>That task is not part of this chat.</Unavailable>;
  const usage = snapshot?.usage;
  return <dl className="gen-facts"><div><dt>Tokens</dt><dd>{usage?.tokens == null ? 'Unavailable from this runtime' : usage.tokens.toLocaleString()}</dd></div><div><dt>{usage?.estimated ? 'Estimated cost' : 'Reported cost'}</dt><dd>{usage?.cost_microusd == null ? 'Unavailable; no usage receipt received' : new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 6 }).format(usage.cost_microusd / 1e6)}</dd></div>{snapshot?.error && <div role="status">{snapshot.error}</div>}</dl>;
}
function RuntimeRecords({ block: b }: Props) {
  const g = useGen(); const request = g.exec.request(b.props.requestId); const activity = g.exec.useActivity(b.props.requestId, request?.state === 'running');
  if (!request) return <Unavailable>That task is not part of this chat.</Unavailable>;
  if (b.type === 'checkpoints') {
    const events = activity.events?.filter(e => ['plan', 'progress', 'result'].includes(e.kind)) ?? [];
    return <section><p className="faint">Recorded task progress checkpoints</p>{events.length ? <ol>{events.map(e => <li key={e.sequence}><time>{e.created_at}</time> {String(e.payload?.summary ?? e.kind)}</li>)}</ol> : <Unavailable>No progress checkpoints recorded.</Unavailable>}</section>;
  }
  const rows = b.type === 'subagent_panel' ? activity.rows.filter(r => r.category === 'subagent') : activity.rows;
  return <section>{g.exec.label && <p className="gen-fixture">{g.exec.label}</p>}<details open><summary>{request.state}: {request.message ?? b.props.requestId}</summary>{rows.length ? <ul>{rows.map(r => <li key={r.key}><strong>{r.label}</strong> — {r.status}{r.detail && <p>{r.detail}</p>}{r.output && <pre tabIndex={0} aria-label="Recorded execution output">{r.output}</pre>}</li>)}</ul> : <Unavailable>{b.type === 'subagent_panel' ? 'No subagent events recorded.' : 'No execution events recorded.'}</Unavailable>}</details>{activity.err && <p role="status">{activity.err}</p>}</section>;
}
function ActionMenu({ block: b }: Props) {
  const g = useGen(); const [query, setQuery] = useState(''); const [msg, setMsg] = useState('');
  const items = b.props.items.filter((i: any) => i.label.toLowerCase().includes(query.toLowerCase()));
  return <>{b.type === 'command_palette' && <input className="input" type="search" aria-label="Search commands" value={query} onChange={e => setQuery(e.target.value)} />}<Menu label={b.props.title ?? 'Actions'} items={items.map((i: any) => ({ id: i.id, label: i.label, onSelect: async () => { const r = await g.act(i.action, { nonce: i.id }); setMsg(r.ok ? 'Done.' : r.message); } }))} trigger={({ props, open }) => <button className="btn" {...props} onContextMenu={b.type === 'context_menu' ? e => { e.preventDefault(); if (!open) (props.onClick as () => void)(); } : undefined} onKeyDown={e => { if (b.type === 'context_menu' && (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10'))) { e.preventDefault(); if (!open) (props.onClick as () => void)(); } else (props.onKeyDown as ((e: React.KeyboardEvent) => void) | undefined)?.(e); }}>{b.props.title ?? 'Actions'}</button>} /><span role="status">{msg}</span></>;
}
function Tree({ block: b }: Props) {
  const rows = b.props.nodes as any[]; const [l, set] = useLocal(b.id, { query: '' });
  const walk = (parent?: string, visited = new Set<string>()): ReactNode => <ul>{rows.filter(n => n.parent === parent || (!parent && n.parent && !rows.some(p => p.id === n.parent))).filter(n => !l.query || n.label.toLowerCase().includes(String(l.query).toLowerCase()) || rows.some(c => c.parent === n.id)).map(n => visited.has(n.id) ? null : <li key={n.id}>{rows.some(c => c.parent === n.id) ? <details open={!!l.query}><summary>{n.label}</summary>{walk(n.id, new Set([...visited, n.id]))}</details> : <span>{n.label}{n.detail && <small> — {n.detail}</small>}</span>}</li>)}</ul>;
  return <nav aria-label={b.props.title ?? 'File tree'}><input className="input" type="search" aria-label="Find node" value={String(l.query)} onChange={e => set({ query: e.target.value })} />{walk()}</nav>;
}
function Pager({ block: b }: Props) { const [l, set] = useLocal(b.id, { page: 0 }); const total = Math.ceil(b.props.total / b.props.pageSize); return <nav className="gen-row" aria-label="Pages"><button className="btn small" disabled={!l.page} onClick={() => set({ page: Number(l.page) - 1 })}>Previous</button><output>Page {Number(l.page) + 1} of {total}</output><button className="btn small" disabled={Number(l.page) >= total - 1} onClick={() => set({ page: Number(l.page) + 1 })}>Next</button></nav>; }
function Links({ block: b }: Props) { const g = useGen(); return <nav aria-label="Breadcrumbs"><ol className="gen-row">{b.props.links.map((l: any, i: number) => <li key={i}>{safeInternalPath(l.path) ? <a href={`/app${l.path}`} onClick={e => { e.preventDefault(); void g.act({ kind: 'navigate.internal', path: l.path }); }}>{l.label}</a> : <span>{l.label} (page unavailable)</span>}</li>)}</ol></nav>; }
function Timer({ block: b }: Props) {
  const [l, set] = useLocal(b.id, { elapsed: b.props.elapsedSeconds, started: 0 }); const [now, tick] = useState(Date.now());
  useEffect(() => { if (!l.started) return; const id = window.setInterval(() => tick(Date.now()), 1000); return () => clearInterval(id); }, [l.started]);
  const seconds = Number(l.elapsed) + (l.started ? Math.max(0, (now - Number(l.started)) / 1000) : 0);
  return <div className="gen-row"><output aria-label="Elapsed seconds">{Math.floor(seconds)}s</output><button className="btn" onClick={() => { const t = Date.now(); tick(t); set(l.started ? { elapsed: seconds, started: 0 } : { started: t }); }}>{l.started ? 'Pause' : 'Start'}</button><button className="btn" onClick={() => set({ elapsed: 0, started: 0 })}>Reset</button><span className="faint">Local timer</span></div>;
}
function Recurrence({ block: b }: Props) { const [l, set] = useLocal(b.id, { ...b.props }); return <section><label>Repeat<select className="input" value={String(l.frequency)} onChange={e => set({ frequency: e.target.value })}>{['daily', 'weekly', 'monthly'].map(f => <option key={f}>{f}</option>)}</select></label><label>Interval<input className="input" type="number" min={1} max={365} value={Number(l.interval)} onChange={e => { if (+e.target.value >= 1 && +e.target.value <= 365) set({ interval: +e.target.value }); }} /></label><label>Start<input className="input" type="date" value={String(l.start)} onChange={e => set({ start: e.target.value })} /></label><p className="faint">Schedule draft saved here. No scheduled job has been created.</p></section>; }
function Conversion({ block: b }: Props) { const p = b.props; const [l, set] = useLocal(b.id, { value: p.value }); return <section><label>{p.from}<input className="input" type="number" value={Number(l.value)} onChange={e => { if (Number.isFinite(+e.target.value)) set({ value: +e.target.value }); }} /></label>{p.rate === undefined ? <Unavailable>A verified conversion rate is required.</Unavailable> : <output aria-live="polite">{(Number(l.value) * p.rate + (p.offset ?? 0)).toLocaleString()} {p.to}</output>}{p.source && <p className="faint">Rate source: {p.source} {p.observedAt}</p>}</section>; }
function Wizard({ block: b }: Props) {
  const g = useGen(); const [l, set] = useLocal(b.id, { step: 0, values: {} as Record<string, string> }); const [msg, setMsg] = useState(''); const p = b.props; const index = Math.min(Number(l.step), p.steps.length - 1), step = p.steps[index];
  const valid = step.fields.every((f: any) => !f.required || (l.values as any)[f.id]?.trim());
  return <form onSubmit={async e => { e.preventDefault(); if (!valid) return; if (index < p.steps.length - 1) set({ step: index + 1 }); else { const r = g.submit ? await g.submit('submit', l.values) : await g.act(p.submit.action); setMsg(r.ok ? 'Sent.' : r.message); } }}><p>Step {index + 1} of {p.steps.length}: {step.label}</p>{step.fields.map((f: any) => <label className="gen-field" key={f.id}>{f.label}<input className="input" required={f.required} maxLength={500} value={(l.values as any)[f.id] ?? ''} onChange={e => set({ values: { ...l.values, [f.id]: e.target.value } })} /></label>)}<div className="gen-row"><button className="btn" type="button" disabled={!index} onClick={() => set({ step: index - 1 })}>Back</button><button className="btn primary" disabled={!valid}>{index < p.steps.length - 1 ? 'Next' : p.submit.label}</button><span role="status">{msg}</span></div></form>;
}
function Prompt({ block: b }: Props) { const [l, set] = useLocal(b.id, { value: '' }); const g = useGen(); const [msg, setMsg] = useState(''); return <form onSubmit={async e => { e.preventDefault(); const r = g.submit ? await g.submit('submit', { response: l.value }) : await g.act(b.props.submit.action); setMsg(r.ok ? 'Sent.' : r.message); }}><label className="gen-field">{b.props.message}<textarea className="input" maxLength={500} value={String(l.value)} onChange={e => set({ value: e.target.value })} /></label><button className="btn primary">{b.props.submit.label}</button><span role="status">{msg}</span></form>; }
function Upload({ block: b }: Props) { const g = useGen(); return <div><p>{b.props.label}</p><button className="btn" onClick={() => { void g.act({ kind: 'navigate.internal', path: '/files' }); }}>Upload through Files</button><p className="faint">Files uses the account’s upload scanning and access rules.</p></div>; }
function Inspector({ block: b }: Props) { const p = b.props; return <section><p>HTTP {p.status}</p><dl>{Object.entries(p.headers).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl><CodeBlock block={{ id: b.id, type: 'code_block', props: { code: p.body, copyable: true } }} /></section>; }
