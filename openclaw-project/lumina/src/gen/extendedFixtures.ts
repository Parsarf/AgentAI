/** Developer fixtures only. Never imported by production rendering or used as live data. */
import { ALIASES, FAMILIES, type Family } from './catalog';
export function extendedFixtures(base: any[]): any[] {
  const action = { kind: 'agent.request', message: 'Use my selected settings' };
  const cols = [{ id: 'name', label: 'Name' }, { id: 'value', label: 'Value', type: 'number' }];
  const rows = [{ name: 'Discovery', value: 12, low: 5, open: 8, close: 12, high: 15, min: 2, q1: 6, median: 9, q3: 12, max: 16 }, { name: 'Evaluation', value: 8, low: 3, open: 6, close: 8, high: 12, min: 1, q1: 3, median: 6, q3: 9, max: 13 }, { name: 'Selection', value: 5, low: 2, open: 3, close: 5, high: 9, min: 0, q1: 2, median: 4, q3: 6, max: 10 }];
  const families: Record<Family, any> = {
    checklist: { items: [{ id: 'research', label: 'Research options', checked: true }, { id: 'review', label: 'Review findings' }] },
    content: { content: 'Sample content with **emphasis** and supporting detail.' }, code: { code: 'const total = 12 + 8;\nreturn total;', language: 'javascript' },
    file: { assetRef: 'file:sample.png', label: 'Sample image', alt: 'Developer fixture; no live file attached' },
    container: { blocks: [{ id: 'details', type: 'text', props: { content: 'Sample summary' } }, { id: 'more', type: 'text', props: { content: 'Sample detail' } }] },
    grid: { columns: cols, rows: rows.map(({ name, value }) => ({ name, value })), groupBy: 'name', valueKey: 'value' },
    chart: { data: rows, labelKey: 'name', valueKey: 'value', summary: 'Illustrative funnel values: 12, 8 and 5.' },
    graph: { nodes: [{ id: 'a', label: 'Discover' }, { id: 'b', label: 'Evaluate' }, { id: 'c', label: 'Select' }], edges: [{ source: 'a', target: 'b', value: 8 }, { source: 'b', target: 'c', value: 5 }] },
    control: { label: 'Sample selection', options: [{ id: 'alpha', label: 'Alpha' }, { id: 'beta', label: 'Beta' }], min: 0, max: 5 },
    upload: { label: 'Attach a file using the account files flow' }, confirm: { message: 'Continue with these sample settings?', label: 'Continue', action },
    pager: { total: 60, pageSize: 10 }, links: { links: [{ label: 'Chat', path: '/chat' }, { label: 'Files', path: '/files' }] },
    tree: { nodes: [{ id: 'src', label: 'src' }, { id: 'app', label: 'App.tsx', parent: 'src', detail: 'Application entry' }] },
    menu: { items: [{ id: 'explain', label: 'Explain the selected option', action }] },
    media: { assets: [{ assetRef: 'file:sample.png', alt: 'Sample media; file not attached' }, { assetRef: 'file:sample-after.png', alt: 'Sample comparison' }], peaks: [.1, .3, .8, .9, .4, .2] },
    map: { points: [{ id: 'sf', label: 'San Francisco (sample)', lat: 37.77, lon: -122.42 }, { id: 'la', label: 'Los Angeles (sample)', lat: 34.05, lon: -118.24 }] },
    runtime: { requestId: 'fixture_run', planBlockId: 'plan_demo' }, prompt: { message: 'What should happen next?', submit: { label: 'Send', action } },
    decision: { inputs: [{ id: 'price', label: 'Price', value: 100, min: 0, max: 1000 }, { id: 'count', label: 'Quantity', value: 3, min: 0, max: 100 }], operation: 'multiply', scenarios: [{ label: 'One extra', values: { count: 4 } }] },
    wizard: { steps: [{ id: 'topic', label: 'Choose topic', fields: [{ id: 'topic', label: 'Topic', required: true }] }, { id: 'details', label: 'Add details', fields: [{ id: 'detail', label: 'Detail' }] }], submit: { label: 'Send', action } },
    schedule: { month: '2026-10', items: [{ id: 'research', label: 'Research', start: '2026-10-27', end: '2026-10-28', detail: 'Illustrative item' }, { id: 'review', label: 'Review', start: '2026-10-29' }] },
    recurrence: { frequency: 'weekly', interval: 1, start: '2026-10-27' }, timer: { elapsedSeconds: 0 },
    domain: { columns: cols, rows: [{ name: 'Sample result', value: 12 }], source: 'Developer fixture', provider: { id: 'fixture', status: 'provided' } },
    conversion: { value: 10, from: 'm', to: 'cm', rate: 100, source: 'SI scale' }, inspect: { status: 200, headers: { content_type: 'application/json' }, body: '{"sample":true}' },
  };
  return [...Object.entries(ALIASES).map(([id, [target]]) => {
    const original = base.find(b => b.type === target) ?? { props: { assetRef: 'file:sample.png', alt: 'Sample' } };
    const fieldTypes: Record<string, string> = { text_input: 'text', textarea: 'textarea', checkbox: 'checkbox', radio: 'radio', select: 'select', segmented_control: 'segmented', slider: 'slider', switch: 'toggle', date_picker: 'date', time_picker: 'time', number_stepper: 'number' };
    const props = fieldTypes[id] ? { ...original.props, fields: [{ id: 'sample', label: id.replaceAll('_', ' '), type: fieldTypes[id], ...(['radio', 'select', 'segmented'].includes(fieldTypes[id]) ? { options: [{ label: 'Alpha', value: 'alpha' }, { label: 'Beta', value: 'beta' }] } : {}) }] } : original.props;
    return { ...original, props, id: `fixture_${id}`, type: id, variant: undefined };
  }), ...Object.entries(FAMILIES).map(([id, family]) => ({ id: `fixture_${id.replace(/^3/, 'three')}`, type: id, props: { title: `${id.replaceAll('_', ' ')} (sample)`, ...families[family], ...(['decision_matrix', 'weighted_scoring'].includes(id) ? { inputs: [{ id: 'quality', label: 'Quality', value: 1, weight: 2 }, { id: 'speed', label: 'Speed', value: 1, weight: 1 }], operation: 'weighted_average', scenarios: [{ label: 'Option A (sample)', values: { quality: 8, speed: 6 } }, { label: 'Option B (sample)', values: { quality: 6, speed: 9 } }] } : {}), ...(id === 'budget_allocator' ? { operation: 'budget', budget: 500 } : {}), ...(id === 'mermaid' ? { source: 'flowchart LR\n a[Discover] --> b[Evaluate]\n b --> c[Select]' } : {}), ...(id === 'math' ? { content: 'E = mc^2' } : {}), ...(family === 'domain' ? domainFixture(id) : {}), ...(family === 'container' ? { blocks: families.container.blocks.map((b: any) => ({ ...b, id: `${id}_${b.id}` })) } : {}), ...(id === 'tree_table' ? { columns: [{ id: 'name', label: 'File' }, { id: 'size', label: 'Bytes', type: 'number' }], rows: [{ id: 'src', name: 'src', size: 0, parent: null }, { id: 'app', name: 'App.tsx', size: 2048, parent: 'src' }], parentKey: 'parent' } : {}) } }))];
}

function domainFixture(id: string) {
  const records: Record<string, any[]> = {
    weather: [{ day: '2026-10-27', high_c: 22, low_c: 14, condition: 'Clear' }, { day: '2026-10-28', high_c: 20, low_c: 13, condition: 'Cloudy' }],
    sports: [{ team: 'Home (sample)', score: 2, status: 'Final' }, { team: 'Away (sample)', score: 1, status: 'Final' }],
    stocks: [10, 12, 11, 13, 15].map((close, i) => ({ date: `2026-10-${20 + i}`, close })),
    health_trends: [55, 56, 54, 58, 57].map((value, i) => ({ date: `2026-10-${20 + i}`, value })),
    financial_statement: [{ item: 'Revenue (sample)', usd: 12000 }, { item: 'Operating expenses (sample)', usd: 8000 }],
    shopping_comparison: [{ product: 'Option A (sample)', price_usd: 100, feature: 'Long battery life' }, { product: 'Option B (sample)', price_usd: 80, feature: 'Compact' }],
    restaurants: [{ name: 'Example cafe (sample)', cuisine: 'Cafe', rating: 4.2, price: '$$' }],
    reservations: [{ venue: 'Example cafe (sample)', date: '2026-10-27', time: '18:30', party_size: 2 }],
  };
  const rows = records[id] ?? [{ name: 'Example (sample)', value: 12 }];
  const columns = Object.keys(rows[0]).map(key => ({ id: key, label: key.replaceAll('_', ' '), type: typeof rows[0][key] === 'number' ? 'number' : 'text' }));
  return { columns, rows, source: 'Developer fixture; illustrative values', observedAt: '2026-10-27', provider: { id: 'fixture', status: 'provided' } };
}
