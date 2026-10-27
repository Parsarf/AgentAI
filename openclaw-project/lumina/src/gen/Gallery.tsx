// Component gallery: every offered block with sample data, in every density, plus loading / empty / error states and the full inventory.
// Route: /app/gen-gallery. Uses a sandbox host (no network): approvals change local sample state only, and the page says so.
import { useMemo, useState } from 'react';
import { GenDocumentView, Fallback } from './components/Renderer';
import type { ExecutionProvider, Host, PlanInfo } from './components/context';
import { parseDocument, type GenDocument } from './protocol';
import { ALL_PARTS, SAMPLE_CONVERSATION, SAMPLE_NOTE } from './fixtures';
import { MANIFEST, categories, search, type Status } from './manifest';
import { DENSITY } from './variants';
import type { ActivityItem } from '../lib/activity';

const ROWS: ActivityItem[] = [
  { key: 'r1', category: 'search', label: 'Searched the web', detail: 'pricing for the three options', output: '', status: 'done', at: '' },
  { key: 'r2', category: 'read', label: 'Opened a page', detail: 'example.com/pricing', output: 'Plan A costs $95 per month.', status: 'done', at: '' },
  { key: 'r3', category: 'command', label: 'Ran a check', detail: 'npm test', output: '12 passed', status: 'running', at: '' },
];
const mkPlan = (deploy: string): PlanInfo => ({ id: 'plan_demo', title: 'Launch the site (sample)', phases: [{ id: 'build', title: 'Build the site' }, { id: 'checks', title: 'Run checks', description: 'Fails in this sample so the retry state is visible.' }, { id: 'deploy', title: 'Publish to production', description: 'Makes the site public.' }],
  run: { build: { state: 'completed', summary: 'Built.' }, checks: { state: 'failed', summary: 'One check failed (sample).' }, deploy: { state: deploy as any, summary: null } }, run_status: 'running' });

function transform(doc: GenDocument, mode: string, density: string): GenDocument {
  const slots = doc.slots.map(s => {
    if (s.status !== 'ready') return s;
    let block: any = { ...s.block, density: density === 'default' ? s.block.density : density };
    if (mode === 'loading') block = { ...block, loading: true };
    if (mode === 'empty' && ['table', 'line_chart', 'bar_chart', 'area_chart'].includes(block.type)) { block = { ...block, dataRef: 'empty_set' }; }
    return { ...s, block };
  });
  const datasets = { ...doc.datasets, empty_set: { columns: [{ id: 'x', label: 'x' }], rows: [] } };
  if (mode === 'error') slots.push({ status: 'invalid', id: 'bad', type: 'bar_chart', reason: 'series: too many', fallback: 'A chart could not be shown; here is the data as text: Revenue 24,500.' } as any);
  return { ...doc, slots, datasets };
}

export default function Gallery() {
  const [which, setWhich] = useState<'conversation' | 'all'>('conversation'); const [mode, setMode] = useState('normal'); const [density, setDensity] = useState('default');
  const [deploy, setDeploy] = useState('awaiting_approval'); const [log, setLog] = useState<string[]>([]); const [q, setQ] = useState(''); const [status, setStatus] = useState<Status | ''>(''); const [cat, setCat] = useState('');
  const doc = useMemo(() => { const parts = (which === 'all' ? ALL_PARTS : [SAMPLE_CONVERSATION]).map(parseDocument); if (parts.some(p => 'error' in p)) return null; const ok = parts as GenDocument[];
    return transform({ ...ok[0], slots: ok.flatMap(p => p.slots) }, mode, density); }, [which, mode, density]);
  const exec = useMemo<ExecutionProvider>(() => ({
    label: SAMPLE_NOTE, request: id => (id === 'fixture_run' ? { id, state: 'completed', result: 'The three options were compared; Gamma is the best rated. (sample)', message: 'Compare the three options', created_epoch: 0 } : undefined),
    plan: id => (id === 'plan_demo' ? mkPlan(deploy) : undefined), useActivity: () => ({ rows: ROWS, err: '' }),
  }), [deploy]);
  const host = useMemo<Host>(() => ({
    send: async m => { setLog(l => [...l, `agent.request → "${m.replace(/\n/g, ' / ')}"`]); }, phase: async (_b, p, v) => { setLog(l => [...l, `phase ${p}: ${v}`]); if (p === 'deploy') setDeploy(v === 'approve' ? 'running' : 'skipped'); },
    retryRequest: async () => { setLog(l => [...l, 'retry request']); }, navigate: p => setLog(l => [...l, `navigate → ${p}`]), download: async () => { throw new Error('not wired'); },
    phaseState: (b, p) => (b === 'plan_demo' ? ((mkPlan(deploy).run[p]?.state ?? null) as any) : null),
  }), [deploy]);
  const entries = search(q, { status: status || undefined, category: cat || undefined });
  const counts = MANIFEST.reduce<Record<string, number>>((a, e) => ((a[e.status] = (a[e.status] ?? 0) + 1), a), {});
  return <main className="gen-gallery-page" style={{ maxWidth: 880, margin: '0 auto', padding: 'var(--space-5) var(--space-4)' }}>
    <h1>Generative UI gallery</h1><p className="faint">{SAMPLE_NOTE} Actions here only change this page.</p>
    <div className="gen-row" role="group" aria-label="Gallery controls">
      <label>Document <select className="gen-input" value={which} onChange={e => setWhich(e.target.value as any)}><option value="conversation">Sample conversation</option><option value="all">Every offered block</option></select></label>
      <label>State <select className="gen-input" value={mode} onChange={e => setMode(e.target.value)}>{['normal', 'loading', 'empty', 'error'].map(m => <option key={m}>{m}</option>)}</select></label>
      <label>Density <select className="gen-input" value={density} onChange={e => setDensity(e.target.value)}><option>default</option>{DENSITY.map(d => <option key={d}>{d}</option>)}</select></label></div>
    {doc ? <GenDocumentView doc={doc} exec={exec} host={host} scope="gallery" /> : <Fallback text="The sample could not be parsed." />}
    {log.length > 0 && <section aria-label="Action log"><h2>Action log</h2><ul>{log.map((l, n) => <li key={n}><code>{l}</code></li>)}</ul></section>}
    <h2>Inventory ({MANIFEST.length})</h2><p className="faint">{Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(' · ')}</p>
    <div className="gen-row"><input className="gen-input" style={{ maxWidth: 260 }} type="search" aria-label="Search components" placeholder="Search…" value={q} onChange={e => setQ(e.target.value)} />
      <select className="gen-input" style={{ maxWidth: 160 }} aria-label="Status" value={status} onChange={e => setStatus(e.target.value as any)}><option value="">any status</option>{['implemented', 'adapter', 'planned', 'unsupported'].map(s => <option key={s}>{s}</option>)}</select>
      <select className="gen-input" style={{ maxWidth: 220 }} aria-label="Category" value={cat} onChange={e => setCat(e.target.value)}><option value="">all categories</option>{categories.map(c => <option key={c}>{c}</option>)}</select></div>
    <div className="gen-scroll" role="region" aria-label="Component inventory" tabIndex={0}><table className="gen-table"><thead><tr><th scope="col">Component</th><th scope="col">Category</th><th scope="col">Status</th><th scope="col">How</th></tr></thead>
      <tbody>{entries.map(e => <tr key={e.id}><th scope="row">{e.name}</th><td>{e.category}</td><td>{e.status}</td><td className="faint">{e.via ? `${e.via}${e.how ? ` · ${e.how}` : ''}` : e.purpose}</td></tr>)}</tbody></table></div>
  </main>;
}
