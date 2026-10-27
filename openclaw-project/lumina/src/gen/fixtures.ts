// Clearly labelled SAMPLE data for the gallery and the tests. Nothing here is a real result, and the gallery says so on screen.
export const SAMPLE_NOTE = 'Sample data for the component gallery. Not a real result.';
const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'];
export const DATASETS = {
  revenue: { source: SAMPLE_NOTE, columns: [{ id: 'month', label: 'Month' }, { id: 'revenue', label: 'Revenue', type: 'currency' }, { id: 'costs', label: 'Costs', type: 'currency' }],
    rows: months.map((m, i) => ({ month: m, revenue: [18200, 19900, 21400, 20800, 23100, 24500][i], costs: [12100, 12600, 13300, 13100, 13900, 14200][i] })) },
  options: { source: SAMPLE_NOTE, columns: [{ id: 'name', label: 'Option' }, { id: 'price', label: 'Price', type: 'currency' }, { id: 'rating', label: 'Rating', type: 'rating' }, { id: 'status', label: 'Status', type: 'status' }],
    rows: [{ name: 'Alpha', price: 120, rating: 4.6, status: 'success' }, { name: 'Beta', price: 95, rating: 4.1, status: 'warning' }, { name: 'Gamma', price: 150, rating: 4.8, status: 'success' }, { name: 'Delta', price: 80, rating: 3.7, status: 'error' }] },
};

export const SAMPLE_CONVERSATION = {
  version: '1.0', responseId: 'resp_sample', datasets: DATASETS,
  blocks: [
    { id: 'intro', type: 'text', props: { content: `Revenue grew in five of six months. **${SAMPLE_NOTE}**` } },
    { id: 'metric', type: 'metric_card', variant: 'compact', props: { label: 'June revenue', value: 24500, format: 'currency', currency: 'USD', delta: { value: 6.1, label: 'vs May' }, trend: [18200, 19900, 21400, 20800, 23100, 24500], source: 'sample fixture' } },
    { id: 'trend', type: 'line_chart', variant: 'comparative', dataRef: 'revenue', props: { title: 'Revenue and costs', xKey: 'month', series: [{ key: 'revenue', label: 'Revenue' }, { key: 'costs', label: 'Costs' }], unit: '$' } },
    { id: 'compare', type: 'table', dataRef: 'options', props: { title: 'Options compared', sortable: true, highlightRow: 2, rowHeader: 'name' } },
    { id: 'approval', type: 'approval_request', props: { planBlockId: 'plan_demo', phaseId: 'deploy', reason: 'Publishing is visible to your customers.' } },
    { id: 'next', type: 'follow_up', props: { suggestions: ['Compare against last year', 'Show costs by category'] } },
  ],
};

const act = (message: string) => ({ kind: 'agent.request', message });
const nestedText = (id: string, content: string) => ({ id, type: 'text', props: { content } });
/** One block of every offered type, with realistic props, used by the gallery and by the coverage tests. */
export const ALL_BLOCKS: unknown[] = [
  { id: 'a_text', type: 'text', variant: 'lead', props: { title: 'Text', content: 'Plain prose with **markdown**, a list and a [link](https://example.com/).\n\n- one\n- two' } },
  { id: 'a_heading', type: 'heading', props: { text: 'A heading', level: 3 } },
  { id: 'a_list', type: 'list', props: { title: 'Checklist', items: [{ text: 'Gather sources', checked: true }, { text: 'Compare prices', checked: false }] } },
  { id: 'a_callout', type: 'callout', props: { tone: 'warning', title: 'Heads up', content: 'This renders as an alert for assistive technology.' } },
  { id: 'a_quote', type: 'quote', props: { content: 'Simple answers stay simple.', source: 'Design principle' } },
  { id: 'a_cites', type: 'citation_list', variant: 'detailed', props: { title: 'Sources', sources: [{ label: 'Example page', url: 'https://example.com/a', snippet: 'A supporting snippet.', publisher: 'example.com' }, { label: 'Second source' }] } },
  { id: 'a_code', type: 'code_block', props: { language: 'python', filename: 'sum.py', code: 'def total(xs):\n    return sum(xs)\n' } },
  { id: 'a_term', type: 'terminal_output', props: { command: 'npm test', lines: ['> vitest run', ' ✓ 12 passed'] } },
  { id: 'a_json', type: 'json_viewer', props: { json: '{"ok":true,"items":[1,2,3]}' } },
  { id: 'a_diff', type: 'diff_viewer', props: { filename: 'a.txt', diff: '@@ -1,2 +1,2 @@\n-old line\n+new line\n unchanged' } },
  { id: 'a_info', type: 'info_card', variant: 'expandable', props: { title: 'Information card', subtitle: 'One entity', badge: 'New', body: 'Details open on demand.', facts: [{ label: 'Price', value: '$95' }, { label: 'Rating', value: '4.1' }], link: { label: 'Open page', url: 'https://example.com/' }, actions: [{ label: 'Tell me more', action: act('Tell me more about this option') }] } },
  { id: 'a_metric', type: 'metric_card', props: { label: 'Open tasks', value: 12, format: 'number', delta: { value: -3, label: 'this week' } } },
  { id: 'a_status', type: 'status_card', props: { status: 'success', label: 'All checks passed', detail: 'Verified from the task log.' } },
  { id: 'a_progress', type: 'progress', variant: 'annotated', props: { label: 'Migration', value: 6, max: 10, steps: [{ label: 'Export', done: true }, { label: 'Import', done: false }] } },
  { id: 'a_grid', type: 'card_grid', props: { title: 'Card grid', cards: [{ title: 'Alpha', subtitle: '$120', facts: [{ label: 'Rating', value: '4.6' }] }, { title: 'Beta', subtitle: '$95' }] } },
  { id: 'a_table', type: 'table', dataRef: 'options', variant: 'striped', props: { title: 'Table', searchable: true, rowHeader: 'name', defaultSort: { column: 'price', dir: 'asc' } } },
  { id: 'a_line', type: 'line_chart', dataRef: 'revenue', props: { title: 'Line chart', xKey: 'month', series: [{ key: 'revenue', label: 'Revenue' }], unit: '$' } },
  { id: 'a_area', type: 'area_chart', variant: 'stacked', dataRef: 'revenue', props: { title: 'Area chart (stacked)', xKey: 'month', series: [{ key: 'revenue' }, { key: 'costs' }], unit: '$' } },
  { id: 'a_bar', type: 'bar_chart', variant: 'comparative', dataRef: 'revenue', props: { title: 'Bar chart', xKey: 'month', series: [{ key: 'revenue' }, { key: 'costs' }], unit: '$' } },
  { id: 'a_pie', type: 'pie_chart', props: { title: 'Donut chart', donut: true, labelKey: 'part', valueKey: 'share', data: [{ part: 'Search', share: 45 }, { part: 'Direct', share: 30 }, { part: 'Social', share: 25 }] } },
  { id: 'a_scatter', type: 'scatter_chart', props: { title: 'Scatter plot', xKey: 'price', yKey: 'rating', labelKey: 'name', data: [{ name: 'A', price: 80, rating: 3.7 }, { name: 'B', price: 95, rating: 4.1 }, { name: 'C', price: 120, rating: 4.6 }, { name: 'D', price: 150, rating: 4.8 }] } },
  { id: 'a_hist', type: 'histogram_chart', props: { title: 'Histogram', valueKey: 'v', bins: 5, data: [1, 2, 2, 3, 3, 3, 4, 4, 5, 9].map(v => ({ v })) } },
  { id: 'a_gauge', type: 'gauge', props: { label: 'Utilisation', value: 72, unit: '%', zones: [{ upTo: 60, status: 'success' }, { upTo: 85, status: 'warning' }, { upTo: 100, status: 'error' }] } },
  { id: 'a_form', type: 'form', variant: 'grouped', props: { title: 'Form', fields: [
    { id: 'kind', type: 'segmented', label: 'Kind', group: 'Basics', required: true, default: 'a', options: [{ label: 'A', value: 'a' }, { label: 'B', value: 'b' }] },
    { id: 'budget', type: 'slider', label: 'Budget', group: 'Basics', min: 0, max: 500, step: 10, default: 100, unit: 'USD' },
    { id: 'extras', type: 'toggle', label: 'Include extras', group: 'Options', default: false },
    { id: 'when', type: 'date', label: 'Date', group: 'Options', showIf: { field: 'extras', equals: true } }], submit: { label: 'Send choices', action: act('Here are my choices:') } } },
  { id: 'a_buttons', type: 'button_group', props: { title: 'Next steps', buttons: [{ id: 'go', label: 'Show details', style: 'primary', action: act('Show the details') }, { id: 'open', label: 'Open files', style: 'ghost', action: { kind: 'navigate.internal', path: '/files' } }] } },
  { id: 'a_follow', type: 'follow_up', props: { suggestions: ['What changed since last month?'] } },
  { id: 'a_tabs', type: 'tabs', props: { title: 'Tabs', tabs: [{ id: 't1', label: 'Summary', blocks: [nestedText('t1a', 'First tab content.')] }, { id: 't2', label: 'Details', blocks: [nestedText('t2a', 'Second tab content.')] }] } },
  { id: 'a_acc', type: 'accordion', props: { title: 'Accordion', items: [{ id: 'i1', title: 'Open by default', open: true, blocks: [nestedText('i1a', 'Visible at first.')] }, { id: 'i2', title: 'Closed', blocks: [nestedText('i2a', 'Hidden at first.')] }] } },
  { id: 'a_section', type: 'section', layout: { columns: 2 }, props: { title: 'Section', blocks: [{ id: 's1', type: 'metric_card', props: { label: 'A', value: 1 } }, { id: 's2', type: 'metric_card', props: { label: 'B', value: 2 } }] } },
  { id: 'a_divider', type: 'divider', props: {} },
  { id: 'a_timeline', type: 'timeline', props: { title: 'Timeline', events: [{ title: 'Kick-off', time: 'Mon', state: 'done' }, { title: 'Review', time: 'Wed', state: 'active', detail: 'In progress' }, { title: 'Launch', time: 'Fri', state: 'pending' }] } },
  { id: 'a_exec', type: 'execution_timeline', variant: 'expanded', props: { title: 'Execution timeline', requestId: 'fixture_run' } },
  { id: 'a_inspect', type: 'tool_call_inspector', variant: 'inspector', props: { requestId: 'fixture_run' } },
  { id: 'a_agent', type: 'agent_status', props: { requestId: 'fixture_run' } },
  { id: 'a_plan', type: 'plan_viewer', variant: 'expanded', props: { planBlockId: 'plan_demo' } },
  { id: 'a_approval', type: 'approval_request', variant: 'approval', props: { planBlockId: 'plan_demo', phaseId: 'deploy', reason: 'Publishing is visible to your customers.' } },
  { id: 'a_retry', type: 'error_retry', props: { planBlockId: 'plan_demo', phaseId: 'checks' } },
  { id: 'a_done', type: 'completion_summary', props: { requestId: 'fixture_run' } },
];
/** A document holds at most 24 blocks, so the full set is shown as parts. */
export const ALL_PARTS = [ALL_BLOCKS.slice(0, 20), ALL_BLOCKS.slice(20)].map((blocks, n) => ({ version: '1.0', responseId: `resp_all_${n}`, datasets: DATASETS, blocks }));

/** Blocks every validator (browser and server) must refuse. The Python tests read the same list from platform/tests/fixtures/gen_parity.json. */
export const INVALID_BLOCKS: Array<[string, unknown]> = [
    ['html in text', { id: 'a', type: 'text', props: { content: 'hi <script>alert(1)</script>' } }],
    ['unknown prop', { id: 'a', type: 'text', props: { content: 'x', style: 'color:red' } }],
    ['css-like shell field', { id: 'a', type: 'text', style: 'x', props: { content: 'x' } }],
    ['javascript url', { id: 'a', type: 'citation_list', props: { sources: [{ label: 'x', url: 'javascript:alert(1)' }] } }],
    ['credentials in url', { id: 'a', type: 'citation_list', props: { sources: [{ label: 'x', url: 'https://u:p@example.com/' }] } }],
    ['bad variant', { id: 'a', type: 'metric_card', variant: 'horizontal', props: { label: 'x', value: 1 } }],
    ['unknown type', { id: 'a', type: 'iframe', props: {} }],
    ['bad id', { id: 'Bad Id', type: 'divider', props: {} }],
    ['bidi override', { id: 'a', type: 'text', props: { content: 'abc\u202edef' } }],
    ['absolute file path', { id: 'a', type: 'image', props: { assetRef: 'file:/etc/passwd', alt: 'x' } }],
    ['path traversal', { id: 'a', type: 'image', props: { assetRef: 'file:../secrets.png', alt: 'x' } }],
    ['remote image address', { id: 'a', type: 'image', props: { assetRef: 'https://evil.example/pixel.png?u=1', alt: 'x' } }],
    ['too many series', { id: 'a', type: 'line_chart', props: { xKey: 'x', series: Array.from({ length: 7 }, (_, i) => ({ key: `s${i}` })) } }],
    ['stacked with one series', { id: 'a', type: 'bar_chart', variant: 'stacked', props: { xKey: 'x', series: [{ key: 'y' }] } }]
];
