/** Read-only migration adapter for historical cards. All drawing uses the current registry. */
import { GenDocumentView } from './components/Renderer';
import { parseDocument } from './protocol';
import type { ChartSpec, ComparisonSpec, TableSpec } from '../lib/genui/data';
import type { Host, ExecutionProvider } from './components/context';

const host: Host = { send: async () => { throw new Error('Historical card is read-only'); }, phase: async () => {}, retryRequest: async () => {}, navigate: () => {}, download: async () => {}, phaseState: () => null };
const exec: ExecutionProvider = { request: () => undefined, plan: () => undefined, useActivity: () => ({ rows: [], err: '' }) };
export default function LegacyDocument({ spec }: { spec: ChartSpec | ComparisonSpec | TableSpec }) {
  let block: any;
  if (spec.type === 'table') block = { id: 'historical', type: 'table', props: { title: spec.title, columns: spec.columns, rows: spec.rows.slice(0, 60), pageSize: 10, searchable: true, sortable: true, highlightRow: spec.highlightRow } };
  else if (spec.type === 'comparison') block = { id: 'historical', type: 'card_grid', props: { title: spec.title, cards: spec.items.map(i => ({ title: i.name, subtitle: i.price, badge: i.badge, facts: i.facts, body: [...i.pros.map(p => `Benefit: ${p}`), ...i.cons.map(p => `Tradeoff: ${p}`)].join('\n\n') || undefined, link: i.link ? { label: 'Source', url: i.link } : undefined })) } };
  else {
    const data = spec.labels.map((label, i) => Object.fromEntries([['label', label], ...spec.series.map((s, j) => [`series${j}`, s.values[i]])]));
    block = { id: 'historical', type: spec.chart === 'pie' || spec.chart === 'donut' ? 'pie_chart' : spec.chart === 'line' ? 'line_chart' : 'bar_chart', props: { title: spec.title, data, unit: spec.unit, ...(spec.chart === 'pie' || spec.chart === 'donut' ? { labelKey: 'label', valueKey: 'series0', donut: spec.chart === 'donut' } : { xKey: 'label', series: spec.series.map((s, j) => ({ key: `series${j}`, label: s.name })) }) } };
  }
  if (spec.type === 'table') { delete block.props.rows; block.dataRef = 'historical'; }
  const doc = parseDocument({ version: '1.0', responseId: 'historical', blocks: [block], ...(spec.type === 'table' ? { datasets: { historical: { columns: spec.columns, rows: spec.rows } } } : {}) });
  if ('error' in doc || doc.slots.some(s => s.status === 'invalid')) return <details open><summary>Historical result: {spec.title}</summary><pre className="gen-code" role="region" aria-label="Original stored result" tabIndex={0}>{JSON.stringify(spec, null, 2)}</pre></details>;
  return <GenDocumentView doc={doc} exec={exec} host={host} scope="historical" readOnly />;
}
