// One registry: component id -> schema, usage guidance, supported actions, fallback and renderer key. The model-facing catalog is derived from it.
import { COMPONENT_VARIANTS } from './variants';
import { IMPLEMENTED_TYPES, SCHEMA_VERSION, blockSchema, type BlockType } from './schemas';
import { MANIFEST } from './manifest';

export interface RegistryEntry {
  componentId: BlockType; schemaVersion: string; description: string; useWhen: string; avoidWhen: string; requiredData: string; supportedActions: readonly string[];
  fallback: string; status: 'implemented' | 'adapter'; rendererKey: string; supportedVariants: readonly string[]; schemaRef: string;
}
type Spec = [description: string, useWhen: string, avoidWhen: string, requiredData: string, actions?: string[], fallback?: string];
const LOCAL = ['local.sort', 'local.filter', 'local.expand', 'local.select', 'local.update'];
const SPEC: Record<BlockType, Spec> = {
  text: ['Prose; markdown allowed', 'every explanation', 'never avoid: it is the default', 'content'],
  heading: ['A section heading', 'a long answer with several parts', 'short answers', 'text'],
  list: ['Bullets, numbers or a checklist', 'steps or a few parallel items', 'items that need several attributes (use a table)', 'items'],
  callout: ['A tip, warning or note', 'one thing the reader must not miss', 'decoration', 'content'],
  quote: ['A quotation with source', 'quoting a source verbatim', 'paraphrase', 'content'],
  citation_list: ['Numbered sources', 'claims backed by pages you read', 'sources you did not open', 'sources with label and url'],
  code_block: ['Code or a command, copyable', 'code the reader will run or paste', 'prose', 'code'],
  terminal_output: ['Command output lines', 'output a command really produced', 'invented output', 'lines'],
  json_viewer: ['Pretty JSON text', 'a payload the reader will inspect', 'tabular data (use a table)', 'json'],
  diff_viewer: ['A unified diff', 'a change you actually produced or fetched', 'invented changes', 'diff'],
  info_card: ['One entity with facts', 'a single product, place, person or result', 'many items (use card_grid or table)', 'title and facts', ['agent.request', 'navigate.internal']],
  metric_card: ['One number with context', 'a headline figure from real data', 'a number you estimated without a source', 'label and value'],
  status_card: ['A state with a label', 'the state of a thing you checked', 'decoration', 'status and label'],
  progress: ['A value out of a maximum, or steps', 'a measured completion', 'unmeasured progress', 'value'],
  card_grid: ['2 to 12 small cards', 'a few options to scan', 'more than 12 or many attributes (use a table)', 'cards', ['agent.request', 'navigate.internal']],
  table: ['Rows and typed columns; sort, search and paging in the browser', 'comparing items across several attributes', 'two or three values; a single entity', 'columns and rows (or a dataset reference)', LOCAL],
  line_chart: ['A trend over an ordered axis', '5 or more points over time', 'fewer than 4 points or no ordering', 'xKey, series and data (or a dataset reference)', ['local.select']],
  area_chart: ['A trend with volume', 'cumulative or part-of-whole over time', 'when a line says the same', 'xKey, series and data', ['local.select']],
  bar_chart: ['Compare categories', 'values per category', 'trends over time (use a line)', 'xKey, series and data', ['local.select']],
  pie_chart: ['Shares of one whole', '2 to 6 parts that sum to a whole', 'more than 6 parts or negative values', 'labelKey, valueKey and data'],
  scatter_chart: ['Relationship between two measures', 'looking for correlation across 8 or more items', 'few points', 'xKey, yKey and data'],
  form: ['Fields the reader changes, then sends', 'you need several choices before you can continue', 'a single question (ask in text)', 'fields and a submit label', ['agent.request', ...LOCAL]],
  button_group: ['2 to 6 actions', 'clear next steps that map to real capabilities', 'decoration or actions you cannot perform', 'buttons with actions', ['agent.request', 'navigate.internal', 'agent.retry']],
  follow_up: ['Suggested next requests', 'the reader is likely to ask these next', 'filler suggestions', 'suggestions', ['agent.request']],
  tabs: ['Alternative views of one thing', 'two to eight parallel views', 'sequential content', 'tabs with blocks'],
  accordion: ['Collapsible sections', 'optional detail', 'content the reader needs first', 'items with blocks'],
  section: ['A titled group of blocks', 'grouping related blocks in a grid', 'a single block', 'blocks'],
  divider: ['A quiet separator', 'between unrelated parts', 'between every block', ''],
  image: ['An image from the customer files', 'a file the customer owns', 'an image from the web (use a link)', 'assetRef and alt'],
  gallery: ['Several images from the customer files', 'a set of the customer files', 'web images', 'images'],
  timeline: ['Events or steps in order', 'a schedule, history or sequence', 'unordered items', 'events'],
  execution_timeline: ['The real steps of a task', 'showing what a task did', 'tasks that have not started', 'requestId'],
  tool_call_inspector: ['One real tool call', 'the reader wants the raw detail', 'a summary is enough', 'requestId'],
  agent_status: ['State of a request', 'a task is queued or running', 'a finished answer', 'requestId'],
  plan_viewer: ['The phases of a plan', 'a plan block exists in this chat', 'no plan', 'planBlockId'],
  approval_request: ['Approve or skip a gated phase', 'a phase is waiting for approval', 'any phase that is not gated', 'planBlockId and phaseId', ['agent.approve', 'agent.deny']],
  error_retry: ['A failed step with retry', 'a request or phase failed', 'nothing failed', 'requestId or planBlockId and phaseId', ['agent.retry']],
  completion_summary: ['What a finished request reported', 'a task has finished', 'a task still running', 'requestId'],
};
/** Renderers that exist but cannot be offered: they need a host capability that is not wired (see docs/generative-ui/component-catalog.md). Never shown to the model, refused by the server. */
export const ADAPTER_ONLY: ReadonlySet<BlockType> = new Set<BlockType>(['image', 'gallery']);
const typeVariants = COMPONENT_VARIANTS as Record<string, readonly string[]>;
export const REGISTRY: Record<BlockType, RegistryEntry> = Object.fromEntries(IMPLEMENTED_TYPES.map(t => {
  const [description, useWhen, avoidWhen, requiredData, actions = [], fallback = 'the block fallback text, else its title and main values as plain text'] = SPEC[t];
  const entry: RegistryEntry = { componentId: t, schemaVersion: SCHEMA_VERSION, description, useWhen, avoidWhen, requiredData, supportedActions: actions, fallback, status: ADAPTER_ONLY.has(t) ? 'adapter' : 'implemented', rendererKey: t, supportedVariants: typeVariants[t] ?? [], schemaRef: `lumina-block/${SCHEMA_VERSION}/${t}` };
  return [t, entry];
})) as Record<BlockType, RegistryEntry>;

export const rendererKeys = new Set<string>(Object.values(REGISTRY).map(e => e.rendererKey));
export function isRenderable(type: string): type is BlockType { return type in REGISTRY; }
/** Types the model may write and the server accepts. */
export const OFFERED: BlockType[] = IMPLEMENTED_TYPES.filter(t => !ADAPTER_ONLY.has(t));
export function unsupportedReason(type: string): string {
  const m = MANIFEST.find(e => e.id === type);
  return m ? `${m.name} is ${m.status}` : `unknown component "${type}"`;
}

/** The compact catalog the responder sees: implemented components only, one line each. Full schemas stay server side. */
export function modelCatalog(): string {
  return OFFERED.map(t => { const r = REGISTRY[t];
    return `${t}: ${r.description}. Use when ${r.useWhen}. Avoid when ${r.avoidWhen}. Needs ${r.requiredData || 'nothing'}.${r.supportedVariants.length ? ` Variants: ${r.supportedVariants.join('/')}.` : ''}`; }).join('\n');
}

/** The always-injected form: one short line per offered component. The long form (avoid-when, required data, variants) is `modelCatalog()`, fetched only when needed. */
export function compactCatalog(): string {
  return OFFERED.map(t => `${t}: ${REGISTRY[t].description}; ${REGISTRY[t].useWhen}`).join('\n');
}

/** Schema lookup for advanced blocks (the optional tool call): the prop names and which are required, taken from the real schema. */
export function schemaSummary(type: string): string | null {
  if (!isRenderable(type)) return null;
  const option = blockSchema.options.find(o => o.shape.type.value === type)!;
  const props = option.shape.props.shape as Record<string, { isOptional(): boolean }>;
  const parts = Object.entries(props).map(([k, v]) => `${k}${v.isOptional() ? '?' : ''}`);
  return `${type} props: { ${parts.join(', ')} }`;
}
