// The complete, typed, searchable inventory. Status is the truth about what exists today:
//   implemented  a renderer exists (directly, or `via` another implemented component with specific props/variant)
//   adapter      code exists that bridges a legacy surface or a provider contract, but it is not embeddable/live yet
//   planned      designed, not built
//   unsupported  deliberately not offered (no safe way, or no value, in generated UI)
// Only `implemented` entries are ever shown to the model.
import { IMPLEMENTED_TYPES, type BlockType } from './schemas';

export type Kind = 'primitive' | 'composite' | 'widget' | 'adapter';
export type Status = 'implemented' | 'adapter' | 'planned' | 'unsupported';
export interface Entry {
  id: string; name: string; category: string; kind: Kind; status: Status; via?: BlockType; how?: string;
  purpose: string; data: string; interactions: string; fallback: string; provider: boolean;
}

interface Defaults { data: string; interactions: string; fallback: string; provider?: boolean }
const CATS: Record<string, Defaults> = {
  'Text and content': { data: 'text or markdown', interactions: 'none, except copy on code and output, and collapse on long text', fallback: 'plain text' },
  'Cards and results': { data: 'title plus a few facts', interactions: 'expand, optional actions', fallback: 'plain text list of the facts' },
  'Tables and data': { data: 'columns plus rows, or a dataset reference', interactions: 'sort, filter, paginate (local)', fallback: 'plain text rows' },
  'Charts and analytics': { data: 'dataset with a category key and numeric series', interactions: 'legend toggle, data-table alternative', fallback: 'data table' },
  'Inputs and forms': { data: 'field definitions', interactions: 'local edit, submit as an agent request', fallback: 'plain text asking for the values' },
  'Navigation and layout': { data: 'child blocks', interactions: 'local switch/expand', fallback: 'children shown in order' },
  'Media and documents': { data: 'file reference in the customer files', interactions: 'open', fallback: 'link or caption' },
  'Maps and location': { data: 'coordinates from a provider', interactions: 'pan, zoom', fallback: 'table of places with links', provider: true },
  'Agent-native': { data: 'request or plan reference (state is read from Lumina records)', interactions: 'approve, deny, retry (validated server side)', fallback: 'plain status sentence' },
  'Decision tools': { data: 'inputs and rules', interactions: 'local recalculation', fallback: 'table of the options' },
  'Scheduling and productivity': { data: 'dated items', interactions: 'select, drag', fallback: 'timeline list' },
  'Domain adapters': { data: 'provider result', interactions: 'provider specific', fallback: 'metric cards and a table of the result', provider: true },
};

const list: Entry[] = [];
function add(category: string, kind: Kind, status: Status, id: string, name: string, purpose: string, extra: { via?: BlockType; how?: string; data?: string; interactions?: string; fallback?: string; provider?: boolean } = {}) {
  const d = CATS[category];
  list.push({ id, name, category, kind, status, purpose, via: extra.via, how: extra.how, data: extra.data ?? d.data, interactions: extra.interactions ?? d.interactions, fallback: extra.fallback ?? d.fallback, provider: extra.provider ?? d.provider ?? false });
}
const T = 'Text and content', C = 'Cards and results', D = 'Tables and data', H = 'Charts and analytics', F = 'Inputs and forms', N = 'Navigation and layout', M = 'Media and documents',
  G = 'Maps and location', A = 'Agent-native', X = 'Decision tools', S = 'Scheduling and productivity', P = 'Domain adapters';
const impl = (c: string, k: Kind, id: string, name: string, purpose: string, via?: BlockType, how?: string, o: Parameters<typeof add>[6] = {}) => add(c, k, 'implemented', id, name, purpose, { ...o, via: via ?? (id as BlockType), how });
const plan = (c: string, k: Kind, id: string, name: string, purpose = name) => add(c, k, 'planned', id, name, purpose);
const unsup = (c: string, k: Kind, id: string, name: string, purpose: string) => add(c, k, 'unsupported', id, name, purpose);

// Text and content
impl(T, 'primitive', 'text', 'Plain text', 'A paragraph of prose.');
impl(T, 'primitive', 'markdown', 'Markdown', 'Prose with lists, emphasis and links; raw HTML is skipped.', 'text', 'format: markdown');
impl(T, 'composite', 'rich_text', 'Rich text (read-only)', 'Formatted prose; authoring is not offered.', 'text', 'format: markdown');
impl(T, 'primitive', 'heading', 'Heading', 'A section heading (levels 2-4).');
impl(T, 'primitive', 'list', 'List', 'Bulleted or numbered items.');
impl(T, 'composite', 'checklist', 'Checklist', 'Items with a checked state.', 'list', 'items[].checked');
impl(T, 'primitive', 'quote', 'Quote', 'A quotation with its source.');
impl(T, 'primitive', 'callout', 'Callout', 'A tip, warning or note set apart from the prose.');
impl(T, 'composite', 'citation_list', 'Citations', 'Numbered sources with links and snippets.');
plan(T, 'composite', 'source_preview', 'Source preview', 'Needs a server-side page fetch; links are shown instead.');
plan(T, 'widget', 'math', 'Math', 'Needs a typesetting library (KaTeX).');
impl(T, 'primitive', 'code_block', 'Code block', 'Monospaced code with a copy button.');
plan(T, 'composite', 'syntax_highlighting', 'Syntax highlighting', 'Code is shown monospaced without colours; needs a highlighter.');
impl(T, 'widget', 'diff_viewer', 'Diff viewer', 'A unified diff with added and removed lines marked.');
impl(T, 'widget', 'json_viewer', 'JSON viewer', 'Pretty-printed, collapsible-by-scroll JSON text.');
impl(T, 'widget', 'terminal_output', 'Terminal output', 'Command output lines.');
impl(T, 'composite', 'expandable_text', 'Expandable text', 'Long text collapsed to a few lines.', 'text', 'expansion: collapsed');
impl(T, 'composite', 'copyable_snippet', 'Copyable snippet', 'A short code or command with a copy button.', 'code_block', 'copyable');

// Cards
impl(C, 'composite', 'info_card', 'Information card', 'One entity: title, subtitle, facts, link, actions.');
impl(C, 'composite', 'metric_card', 'KPI / metric', 'One number with unit, change and optional trend line.');
impl(C, 'composite', 'profile_card', 'Profile card', 'A person or organisation.', 'info_card', 'facts');
impl(C, 'composite', 'product_card', 'Product card', 'A product with price and link as facts.', 'info_card', 'facts + link');
impl(C, 'composite', 'business_card', 'Business card', 'A place of business with address and hours as facts.', 'info_card', 'facts');
impl(C, 'composite', 'comparison_card', 'Comparison card', 'Options side by side.', 'card_grid', 'variant horizontal');
impl(C, 'composite', 'status_card', 'Status card', 'A state with a label and detail.');
impl(C, 'composite', 'progress_card', 'Progress card', 'A bounded value or steps.', 'progress');
plan(C, 'composite', 'file_card', 'File card', 'Needs the file.download host adapter (files are served by artifact id behind a ticket).');
plan(C, 'composite', 'media_card', 'Media card', 'Needs an asset resolver for the customer files.');
impl(C, 'composite', 'recommendation_card', 'Recommendation card', 'A suggested option with the reasons as facts.', 'info_card', 'badge + facts');
impl(C, 'composite', 'summary_card', 'Summary card', 'A short summary with key facts.', 'info_card', 'body + facts');
impl(C, 'composite', 'action_card', 'Action card', 'A card whose buttons send a request.', 'info_card', 'actions: agent.request');
impl(C, 'composite', 'expandable_card', 'Expandable card', 'A card that opens to show detail.', 'info_card', 'variant expandable');
impl(C, 'composite', 'result_collection', 'Result collection', 'A group of cards.', 'card_grid');

// Tables
impl(D, 'composite', 'table', 'Table', 'Rows and typed columns; sortable, searchable and paginated in the browser.');
impl(D, 'composite', 'sortable_table', 'Sortable table', 'Click a header to sort.', 'table', 'sortable');
impl(D, 'composite', 'filterable_table', 'Filterable table', 'Filter rows by text.', 'table', 'searchable');
impl(D, 'composite', 'searchable_table', 'Searchable table', 'Search across all cells.', 'table', 'searchable');
plan(D, 'composite', 'editable_table', 'Editable table', 'Needs cell-edit validation and a save path.');
impl(D, 'composite', 'paginated_table', 'Paginated table', 'Pages of rows.', 'table', 'pageSize');
plan(D, 'composite', 'pivot_table', 'Pivot table');
plan(D, 'composite', 'data_grid', 'Data grid', 'Virtualised grid for very large data; needs a backend dataRef provider.');
plan(D, 'composite', 'tree_table', 'Tree table');
impl(D, 'composite', 'comparison_matrix', 'Comparison matrix', 'Options as columns, criteria as rows.', 'table', 'rowHeader');
impl(D, 'composite', 'leaderboard', 'Leaderboard', 'Ranked rows.', 'table', 'defaultSort');
impl(D, 'composite', 'spreadsheet_preview', 'Spreadsheet preview', 'A read-only paged grid of a dataset.', 'table', 'dataRef');

// Charts
impl(H, 'widget', 'line_chart', 'Line chart', 'A trend over an ordered axis.');
impl(H, 'widget', 'bar_chart', 'Bar chart', 'Compare categories.');
impl(H, 'widget', 'stacked_bar_chart', 'Stacked bar chart', 'Parts of a whole across categories.', 'bar_chart', 'variant stacked');
impl(H, 'widget', 'area_chart', 'Area chart', 'A trend with volume.');
impl(H, 'widget', 'pie_chart', 'Pie chart', 'Shares of one whole.');
impl(H, 'widget', 'donut_chart', 'Donut chart', 'Shares with a centre total.', 'pie_chart', 'donut');
impl(H, 'widget', 'scatter_chart', 'Scatter plot', 'The relationship between two measures.');
plan(H, 'widget', 'bubble_chart', 'Bubble chart');
impl(H, 'widget', 'histogram', 'Histogram', 'Distribution of one numeric measure in equal-width bins.', 'histogram_chart');
plan(H, 'widget', 'heatmap', 'Heatmap');
plan(H, 'widget', 'radar_chart', 'Radar chart');
plan(H, 'widget', 'funnel_chart', 'Funnel');
plan(H, 'widget', 'waterfall_chart', 'Waterfall');
plan(H, 'widget', 'candlestick_chart', 'Candlestick');
plan(H, 'widget', 'box_plot', 'Box plot');
impl(H, 'widget', 'gauge', 'Gauge', 'One value on a scale, with optional status zones.');
impl(H, 'widget', 'progress_chart', 'Progress chart', 'A bar showing a value out of a maximum.', 'progress');
plan(H, 'widget', 'treemap', 'Treemap');
unsup(H, 'widget', 'sankey', 'Sankey', 'Needs a layout library and rarely beats a table; not offered.');
plan(H, 'widget', 'network_graph', 'Network graph');
impl(H, 'widget', 'timeline_chart', 'Timeline', 'Events in order.', 'timeline');
plan(H, 'widget', 'gantt', 'Gantt chart');

// Inputs
impl(F, 'primitive', 'button', 'Button', 'Sends a validated action.', 'button_group');
plan(F, 'primitive', 'icon_button', 'Icon button');
impl(F, 'primitive', 'text_input', 'Text input', 'One line of text.', 'form', 'field type text');
impl(F, 'primitive', 'textarea', 'Textarea', 'Several lines of text.', 'form', 'field type textarea');
impl(F, 'primitive', 'checkbox', 'Checkbox', 'A yes/no choice.', 'form', 'field type checkbox');
impl(F, 'primitive', 'radio', 'Radio group', 'One of a few options.', 'form', 'field type radio');
impl(F, 'primitive', 'select', 'Select', 'One of many options.', 'form', 'field type select');
plan(F, 'primitive', 'multiselect', 'Multi-select');
impl(F, 'primitive', 'segmented_control', 'Segmented control', 'One of two to four options.', 'form', 'field type segmented');
impl(F, 'primitive', 'slider', 'Slider', 'A number in a range.', 'form', 'field type slider');
plan(F, 'primitive', 'range_slider', 'Range slider');
impl(F, 'primitive', 'switch', 'Switch', 'An on/off setting.', 'form', 'field type toggle');
impl(F, 'primitive', 'date_picker', 'Date picker', 'A calendar date (the browser control).', 'form', 'field type date');
impl(F, 'primitive', 'time_picker', 'Time picker', 'A time of day (the browser control).', 'form', 'field type time');
plan(F, 'composite', 'date_range', 'Date range');
impl(F, 'primitive', 'number_stepper', 'Number stepper', 'A number with steps.', 'form', 'field type number');
plan(F, 'primitive', 'search_input', 'Search input');
unsup(F, 'primitive', 'upload', 'Upload', 'File upload from generated UI would bypass the files pipeline checks.');
unsup(F, 'primitive', 'color_picker', 'Color picker', 'No task needs it.');
plan(F, 'primitive', 'rating', 'Rating input');
plan(F, 'primitive', 'tags', 'Tags input');
plan(F, 'primitive', 'autocomplete', 'Autocomplete');
impl(F, 'composite', 'grouped_form', 'Grouped form', 'Fields in labelled groups.', 'form', 'variant grouped, field group');
impl(F, 'composite', 'conditional_form', 'Conditional form', 'Fields that appear depending on earlier answers.', 'form', 'showIf');
impl(F, 'composite', 'confirmation', 'Confirmation', 'Asks before a consequential action; built into every action.', 'approval_request', 'internal confirm dialog');

// Navigation
impl(N, 'composite', 'tabs', 'Tabs', 'Switch between groups of blocks.');
impl(N, 'composite', 'accordion', 'Accordion', 'Sections that open and close.');
impl(N, 'composite', 'collapsible', 'Collapsible', 'One section that opens and closes.', 'accordion', 'one item');
plan(N, 'widget', 'popover', 'Popover');
plan(N, 'widget', 'tooltip', 'Tooltip');
plan(N, 'widget', 'modal', 'Modal (generated)');
plan(N, 'widget', 'drawer', 'Drawer');
plan(N, 'widget', 'carousel', 'Carousel');
impl(N, 'composite', 'pagination', 'Pagination', 'Page through rows; part of the table.', 'table', 'pageSize');
plan(N, 'composite', 'breadcrumb', 'Breadcrumb');
impl(N, 'composite', 'stepper', 'Stepper', 'Steps with a state each.', 'timeline', 'events[].state');
plan(N, 'widget', 'split_view', 'Split view');
plan(N, 'widget', 'resizable_panels', 'Resizable panels');
plan(N, 'widget', 'tree_navigation', 'Tree navigation');
unsup(N, 'widget', 'command_palette', 'Command palette', 'An app-level control, not part of an answer.');
unsup(N, 'widget', 'context_menu', 'Context menu', 'An app-level control, not part of an answer.');
plan(N, 'widget', 'dropdown_menu', 'Dropdown menu');
impl(N, 'primitive', 'divider', 'Divider', 'A quiet separator.');
impl(N, 'composite', 'section', 'Section container', 'Groups blocks with a title and a grid.');

// Media
add(M, 'primitive', 'adapter', 'image', 'Image', 'Renderer exists; not offered until the host can turn a file reference into a loadable URL (never an arbitrary address).');
add(M, 'composite', 'adapter', 'gallery', 'Gallery', 'Same as image: renderer exists, host asset resolver missing.');
plan(M, 'composite', 'image_carousel', 'Image carousel');
plan(M, 'widget', 'image_comparison', 'Image comparison');
plan(M, 'widget', 'video', 'Video', 'Needs a safe playback policy for customer files.');
plan(M, 'widget', 'audio', 'Audio');
unsup(M, 'widget', 'waveform', 'Waveform', 'No task needs it.');
add(M, 'adapter', 'adapter', 'pdf_viewer', 'PDF / document viewer', 'Files already have a preview endpoint; embedding it in a document is not wired.', { provider: false });
unsup(M, 'widget', 'annotation', 'Annotation', 'Needs write paths that do not exist.');
plan(M, 'widget', 'zoom', 'Zoom');
plan(M, 'widget', '3d_model', '3D model', 'three is bundled for the Lumina orb only.');
plan(M, 'widget', 'mermaid', 'Mermaid diagram');
plan(M, 'widget', 'flowchart', 'Flowchart');
plan(M, 'widget', 'mind_map', 'Mind map');

// Maps (no map provider or tile source is configured)
for (const [id, name] of [['map', 'Map'], ['pins', 'Pins'], ['clustering', 'Clustering'], ['route', 'Route'], ['itinerary', 'Multi-stop itinerary'], ['geo_heatmap', 'Geo heatmap'], ['region_comparison', 'Region comparison'], ['distance', 'Distance'], ['map_layers', 'Map layers'], ['location_search', 'Location search']] as const)
  plan(G, 'widget', id, name, `${name}: needs a map provider and tile source (none configured). Places can already be shown as cards with map links.`);

// Agent-native
impl(A, 'widget', 'task_progress', 'Task progress', 'Where a task is, read from its real events.', 'execution_timeline', 'variant inline');
impl(A, 'widget', 'execution_timeline', 'Execution timeline', 'The real tool calls and notes of a task, in order.');
impl(A, 'widget', 'live_activity', 'Live activity', 'The same timeline, refreshed while the task runs.', 'execution_timeline', 'live');
impl(A, 'widget', 'tool_call_inspector', 'Tool-call inspector', 'One tool call: label, detail and output.');
impl(A, 'widget', 'agent_status', 'Agent status', 'Queued, working, done or failed, from the request record.');
impl(A, 'widget', 'plan_viewer', 'Plan viewer', 'The phases of a plan and where each is.');
add(A, 'adapter', 'adapter', 'plan_editor', 'Plan editor', 'Exists as the standalone task_plan block (PlanBlock); not embeddable in a document yet.');
plan(A, 'widget', 'execution_tree', 'Execution tree');
plan(A, 'widget', 'subagent_panel', 'Subagent panel');
plan(A, 'widget', 'dependency_graph', 'Dependency graph');
impl(A, 'widget', 'error_retry', 'Error and retry', 'A failed step or request with a retry.');
impl(A, 'widget', 'approval_request', 'Approval request', 'Approve or skip a gated phase; pending, approved, skipped, failed and expired states.');
impl(A, 'widget', 'evidence_viewer', 'Evidence viewer', 'Sources and the snippets that support a claim.', 'citation_list', 'snippet');
impl(A, 'widget', 'logs', 'Logs', 'Output lines.', 'terminal_output');
plan(A, 'widget', 'checkpoints', 'Checkpoints');
plan(A, 'widget', 'token_cost_monitor', 'Token and cost monitor', 'No per-request token/cost record is exposed to the UI yet; nothing is invented.');
impl(A, 'widget', 'completion_summary', 'Completion summary', 'What a finished request reported.');

// Decision tools
plan(X, 'widget', 'calculator', 'Calculator');
plan(X, 'widget', 'scenario_simulator', 'Scenario simulator');
plan(X, 'widget', 'decision_matrix', 'Decision matrix');
plan(X, 'widget', 'weighted_scoring', 'Weighted scoring');
impl(X, 'composite', 'questionnaire', 'Questionnaire', 'A few questions whose answers are sent as a request.', 'form');
plan(X, 'widget', 'wizard', 'Wizard', 'Multi-step forms are not built.');
plan(X, 'widget', 'budget_allocator', 'Budget allocator');
plan(X, 'widget', 'filter_builder', 'Filter builder');
plan(X, 'widget', 'rule_builder', 'Rule builder');
impl(X, 'composite', 'parameter_configurator', 'Parameter configurator', 'Sliders and selects whose values are sent as a request.', 'form');
impl(X, 'composite', 'recommendation_selector', 'Recommendation selector', 'Suggested next requests as buttons.', 'follow_up');

// Scheduling
for (const [id, name] of [['calendar', 'Calendar'], ['agenda', 'Agenda'], ['event', 'Event'], ['availability_grid', 'Availability grid'], ['kanban', 'Kanban'], ['reminder', 'Reminder'], ['recurring_schedule', 'Recurring schedule'], ['time_tracker', 'Time tracker']] as const)
  plan(S, 'widget', id, name, `${name}: the Calendar and Automations pages exist but are not embeddable in a document.`);
impl(S, 'composite', 'project_timeline', 'Project timeline', 'Dated steps in order.', 'timeline');
impl(S, 'composite', 'milestones', 'Milestones', 'Key dates with a state.', 'timeline', 'events[].state');

// Domain adapters
for (const [id, name] of [['weather', 'Weather'], ['sports', 'Sports'], ['stocks', 'Stocks'], ['financial_statement', 'Financial statement'], ['currency_conversion', 'Currency / unit conversion'], ['shopping_comparison', 'Shopping comparison'], ['restaurants', 'Restaurants'], ['reservations', 'Reservations'], ['travel_itinerary', 'Travel itinerary'], ['health_trends', 'Health trends']] as const)
  plan(P, 'adapter', id, name, `${name}: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched.`);
add(P, 'adapter', 'adapter', 'database_result', 'Database result', 'Renders through the table with a dataRef; datasets embedded in the document work today, a server-side dataRef provider does not exist.');
plan(P, 'adapter', 'repository_tree', 'Repository tree');
impl(P, 'adapter', 'pull_request_diff', 'Pull-request diff', 'A diff the assistant already fetched.', 'diff_viewer');
plan(P, 'adapter', 'api_inspector', 'API inspector');

export const MANIFEST: readonly Entry[] = list;
export const byId = new Map(list.map(e => [e.id, e]));

export function search(query: string, filter: { status?: Status; category?: string } = {}): Entry[] {
  const q = query.trim().toLowerCase();
  return list.filter(e => (!filter.status || e.status === filter.status) && (!filter.category || e.category === filter.category)
    && (!q || `${e.id} ${e.name} ${e.purpose} ${e.category}`.toLowerCase().includes(q)));
}
export const categories = [...new Set(list.map(e => e.category))];
export const implementedTypes = new Set<string>(IMPLEMENTED_TYPES);
/** Entries the model may be told about: implemented only. */
export const offerable = () => list.filter(e => e.status === 'implemented');
