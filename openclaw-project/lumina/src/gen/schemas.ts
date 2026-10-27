// Versioned, discriminated block schemas: the contract between what the model writes and what the renderer draws.
// Python (platform/agentai_platform/genui/document.py) validates the same shapes from schema.generated.json, which `npm run gen:registry` derives from this file.
import { z } from 'zod';
import { APPEARANCE, COMPONENT_VARIANTS, DENSITY, EMPHASIS, EXPANSION, INTERACTION, SIZE, checkCombination, type ComponentType } from './variants';
import { assetRef, filePath, httpUrl, ident, md, text } from './safety';

export const SCHEMA_VERSION = '1.0';
export const LIMITS = { blocks: 24, nested: 60, depth: 3, datasetRows: 500, inlineRows: 60, bytes: 48 * 1024 } as const;

const refId = z.string().regex(/^[a-z][a-z0-9_.:-]{0,63}$/i, 'a reference id');
const requestId = z.string().regex(/^[A-Za-z0-9_-]{6,64}$/, 'a request id');
const num = z.number().finite().min(-1e15).max(1e15);

// ---- actions: declarative, allowlisted, never code ------------------------------------------------------------------------------------------
export const ACTION_KINDS = ['local.sort', 'local.filter', 'local.expand', 'local.select', 'local.update', 'navigate.internal', 'agent.request', 'agent.approve', 'agent.deny', 'agent.retry', 'file.download'] as const;
const target = ident;
export const actionSchema = z.discriminatedUnion('kind', [
  z.strictObject({ kind: z.literal('local.sort'), target, column: ident, dir: z.enum(['asc', 'desc']).default('asc') }),
  z.strictObject({ kind: z.literal('local.filter'), target, query: text(120, 0) }),
  z.strictObject({ kind: z.literal('local.expand'), target, expanded: z.boolean().default(true) }),
  z.strictObject({ kind: z.literal('local.select'), target, value: text(80) }),
  z.strictObject({ kind: z.literal('local.update'), target, field: ident, value: z.union([text(200, 0), num, z.boolean()]) }),
  z.strictObject({ kind: z.literal('navigate.internal'), path: text(200) }),
  z.strictObject({ kind: z.literal('agent.request'), message: text(1500, 4) }),
  z.strictObject({ kind: z.literal('agent.approve'), planBlockId: refId, phaseId: ident }),
  z.strictObject({ kind: z.literal('agent.deny'), planBlockId: refId, phaseId: ident }),
  z.strictObject({ kind: z.literal('agent.retry'), planBlockId: refId.optional(), phaseId: ident.optional(), requestId: requestId.optional() }),
  z.strictObject({ kind: z.literal('file.download'), path: filePath }),
]);
export type Action = z.infer<typeof actionSchema>;

// ---- shared shell and layout ----------------------------------------------------------------------------------------------------------------
const gap = z.enum(['xs', 'sm', 'md', 'lg', 'xl']);
const layoutBase = z.strictObject({
  span: z.number().int().min(1).max(12).optional(), columns: z.number().int().min(1).max(6).optional(), gap: gap.optional(),
  alignment: z.enum(['start', 'center', 'end', 'stretch']).optional(), justify: z.enum(['start', 'center', 'end', 'between']).optional(),
  direction: z.enum(['row', 'column']).optional(), overflow: z.enum(['wrap', 'scroll', 'clip']).optional(), sticky: z.boolean().optional(),
  width: z.enum(['auto', 'narrow', 'medium', 'wide', 'full']).optional(), height: z.enum(['auto', 'short', 'medium', 'tall']).optional(),
});
export const layoutSchema = layoutBase.extend({ responsive: z.strictObject({ phone: layoutBase.optional(), tablet: layoutBase.optional() }).optional() });
export type Layout = z.infer<typeof layoutSchema>;

const shell = {
  id: ident, size: z.enum(SIZE).optional(), density: z.enum(DENSITY).optional(), emphasis: z.enum(EMPHASIS).optional(),
  appearance: z.enum(APPEARANCE).optional(), expansion: z.enum(EXPANSION).optional(), interaction: z.enum(INTERACTION).optional(),
  layout: layoutSchema.optional(), visible: z.boolean().optional(), disabled: z.boolean().optional(), loading: z.boolean().optional(),
  dataRef: refId.optional(), accessibilityLabel: text(160).optional(), fallback: text(600).optional(),
};
const common = { title: text(120).optional(), description: text(400).optional() };

function def<T extends ComponentType, P extends z.ZodRawShape>(type: T, props: P) {
  const variants = COMPONENT_VARIANTS[type] as readonly string[];
  return z.strictObject({
    ...shell, type: z.literal(type),
    variant: (variants.length ? z.enum(variants as [string, ...string[]]) : z.never()).optional(),
    props: z.strictObject({ ...common, ...props }),
  });
}

// ---- prop building blocks -------------------------------------------------------------------------------------------------------------------
const tone = z.enum(['info', 'tip', 'warning', 'success', 'danger']);
const status = z.enum(['idle', 'active', 'success', 'warning', 'error']);
const fact = z.strictObject({ label: text(40), value: text(160) });
const link = z.strictObject({ label: text(60), url: httpUrl });
const cardProps = {
  subtitle: text(160).optional(), badge: text(24).optional(), body: md(800).optional(), facts: z.array(fact).max(10).optional(),
  link: link.optional(), actions: z.array(z.strictObject({ label: text(40), action: actionSchema })).max(3).optional(),
};
const columnType = z.enum(['text', 'number', 'currency', 'percent', 'rating', 'link', 'status']);
const column = z.strictObject({ id: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/), label: text(60), type: columnType.optional(), unit: text(12).optional(), align: z.enum(['start', 'end']).optional() });
const cell = z.union([text(500, 0), num, z.boolean(), z.null()]);
export const datasetSchema = z.strictObject({
  columns: z.array(column).min(1).max(12), rows: z.array(z.record(z.string(), cell)).max(LIMITS.datasetRows), source: text(160).optional(),
});
export type Dataset = z.infer<typeof datasetSchema>;
const inlineRows = z.array(z.record(z.string(), cell)).max(LIMITS.inlineRows);
const series = z.strictObject({ key: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/), label: text(60).optional() });
const chartCommon = {
  columns: z.array(column).min(1).max(12).optional(), data: inlineRows.optional(), xKey: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/),
  series: z.array(series).min(1).max(6), unit: text(12).optional(), caption: text(240).optional(), summary: text(400).optional(),
};
const fieldType = z.enum(['select', 'radio', 'segmented', 'toggle', 'checkbox', 'slider', 'number', 'text', 'textarea', 'date', 'time']);
const formField = z.strictObject({
  id: ident, type: fieldType, label: text(120), help: text(240).optional(), group: text(60).optional(),
  options: z.array(z.strictObject({ label: text(80), value: ident })).min(2).max(12).optional(), default: z.union([text(500, 0), num, z.boolean()]).optional(),
  min: num.optional(), max: num.optional(), step: num.optional(), unit: text(12).optional(), required: z.boolean().optional(),
  showIf: z.strictObject({ field: ident, equals: z.union([text(80), num, z.boolean()]) }).optional(),
});
const buttonStyle = z.enum(['primary', 'secondary', 'outline', 'ghost', 'destructive']);
const event = z.strictObject({ id: ident.optional(), title: text(120), detail: text(400).optional(), time: text(40).optional(), state: z.enum(['done', 'active', 'pending', 'failed']).optional() });

// ---- nested blocks (tabs, accordion, section) ----------------------------------------------------------------------------------------------
export interface BlockLike { id: string; type: string; variant?: string; props: Record<string, unknown>; [k: string]: unknown }
const lazyBlock: z.ZodType<BlockLike> = z.lazy(() => blockSchema as unknown as z.ZodType<BlockLike>);
const nested = z.array(lazyBlock).min(1).max(12);

export const blockSchema = z.discriminatedUnion('type', [
  def('text', { content: md(8000), format: z.enum(['plain', 'markdown']).default('markdown') }),
  def('heading', { text: text(160), level: z.union([z.literal(2), z.literal(3), z.literal(4)]).default(3) }),
  def('list', { items: z.array(z.strictObject({ text: md(300), checked: z.boolean().optional() })).min(1).max(40), ordered: z.boolean().optional() }),
  def('callout', { tone: tone.default('info'), content: md(1200) }),
  def('quote', { content: md(800), source: text(120).optional() }),
  def('citation_list', { sources: z.array(z.strictObject({ label: text(120), url: httpUrl.optional(), snippet: text(400).optional(), publisher: text(80).optional() })).min(1).max(12) }),
  def('code_block', { code: z.string().min(1).max(8000), language: z.string().regex(/^[a-z0-9+#-]{1,20}$/i).optional(), filename: text(120).optional(), copyable: z.boolean().default(true) }),
  def('terminal_output', { lines: z.array(z.string().max(400)).min(1).max(200), command: text(200).optional() }),
  def('json_viewer', { json: z.string().min(2).max(8000) }),
  def('diff_viewer', { diff: z.string().min(1).max(12000), filename: text(120).optional() }),

  def('info_card', cardProps),
  def('metric_card', {
    label: text(80), value: z.union([num, text(80)]), format: z.enum(['number', 'currency', 'percent', 'text']).default('number'), currency: z.string().regex(/^[A-Z]{3}$/).optional(),
    unit: text(12).optional(), delta: z.strictObject({ value: num, label: text(60).optional() }).optional(), trend: z.array(num).min(2).max(40).optional(), source: text(120).optional(),
  }),
  def('status_card', { status, label: text(120), detail: text(400).optional(), updated: text(60).optional() }),
  def('progress', { value: num, max: num.positive().default(100), label: text(80).optional(), status: status.optional(), steps: z.array(z.strictObject({ label: text(80), done: z.boolean() })).max(12).optional() }),
  def('card_grid', { cards: z.array(z.strictObject({ title: text(120), ...cardProps })).min(1).max(12) }),

  def('table', {
    columns: z.array(column).min(1).max(12).optional(), rows: z.array(z.record(z.string(), cell)).max(LIMITS.inlineRows).optional(), caption: text(240).optional(),
    searchable: z.boolean().optional(), sortable: z.boolean().default(true), pageSize: z.number().int().min(5).max(50).default(10), highlightRow: z.number().int().min(0).optional(),
    defaultSort: z.strictObject({ column: ident.or(z.string().regex(/^[a-z][a-z0-9_]{0,31}$/)), dir: z.enum(['asc', 'desc']) }).optional(), rowHeader: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/).optional(),
  }),
  def('line_chart', chartCommon), def('area_chart', chartCommon), def('bar_chart', { ...chartCommon, horizontal: z.boolean().optional() }),
  def('pie_chart', { columns: chartCommon.columns, data: chartCommon.data, labelKey: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/), valueKey: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/), donut: z.boolean().optional(), unit: chartCommon.unit, caption: chartCommon.caption, summary: chartCommon.summary }),
  def('scatter_chart', { columns: chartCommon.columns, data: chartCommon.data, xKey: chartCommon.xKey, yKey: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/), labelKey: z.string().regex(/^[a-z][a-z0-9_]{0,31}$/).optional(), unit: chartCommon.unit, caption: chartCommon.caption, summary: chartCommon.summary }),

  def('form', {
    fields: z.array(formField).min(1).max(30), submit: z.strictObject({ label: text(40), action: actionSchema }),
  }),
  def('button_group', { buttons: z.array(z.strictObject({ id: ident, label: text(40), style: buttonStyle.optional(), action: actionSchema })).min(1).max(6) }),
  def('follow_up', { suggestions: z.array(text(90, 4)).min(1).max(4) }),

  def('tabs', { tabs: z.array(z.strictObject({ id: ident, label: text(40), blocks: nested })).min(2).max(8), initial: ident.optional() }),
  def('accordion', { items: z.array(z.strictObject({ id: ident, title: text(120), blocks: nested, open: z.boolean().optional() })).min(1).max(12), multiple: z.boolean().optional() }),
  def('section', { blocks: nested }),
  def('divider', {}),

  def('image', { assetRef, alt: text(200), fit: z.enum(['contain', 'cover']).default('contain'), caption: text(240).optional(), externalUrl: httpUrl.optional() }),
  def('gallery', { images: z.array(z.strictObject({ assetRef, alt: text(200), caption: text(160).optional() })).min(1).max(12) }),
  def('timeline', { events: z.array(event).min(1).max(30) }),

  // Agent-native blocks carry REFERENCES only. What they show (state, steps, results, timings) is read from Lumina's own records, never from the model's text.
  def('execution_timeline', { requestId, live: z.boolean().default(true), maxItems: z.number().int().min(3).max(100).default(30) }),
  def('tool_call_inspector', { requestId }),
  def('agent_status', { requestId }),
  def('plan_viewer', { planBlockId: refId }),
  def('approval_request', { planBlockId: refId, phaseId: ident, reason: text(300).optional() }),
  def('error_retry', { requestId: requestId.optional(), planBlockId: refId.optional(), phaseId: ident.optional() }),
  def('completion_summary', { requestId }),
]);
export type Block = z.infer<typeof blockSchema>;
export type BlockType = Block['type'];
export const IMPLEMENTED_TYPES = blockSchema.options.map(o => o.shape.type.value) as BlockType[];

export const presentationPlanSchema = z.strictObject({
  advisory: z.literal(true),
  blocks: z.array(z.strictObject({
    blockId: ident, componentId: z.string().regex(/^[a-z][a-z0-9_]{0,47}$/), variant: z.string().regex(/^[a-z-]{2,20}$/).optional(), layout: z.enum(['inline', 'stacked', 'horizontal', 'vertical', 'grid']).optional(),
    purpose: text(160), dataRequirements: z.array(text(80)).max(6).optional(),
  })).min(1).max(8),
});
export type PresentationPlan = z.infer<typeof presentationPlanSchema>;

export const documentSchema = z.strictObject({
  version: z.literal(SCHEMA_VERSION), responseId: z.string().regex(/^[A-Za-z0-9_-]{1,64}$/),
  blocks: z.array(z.unknown()).max(LIMITS.blocks),                   // each block is validated on its own (parseDocument), so one bad block never hides the rest
  datasets: z.record(refId, datasetSchema).optional(), presentationPlan: presentationPlanSchema.optional(),
});
export type RawDocument = z.infer<typeof documentSchema>;

/** Children of a container block, for depth and count bounds. */
export function children(block: { type?: unknown; props?: unknown }): unknown[] {
  const p = (block.props ?? {}) as Record<string, unknown>;
  if (block.type === 'tabs' && Array.isArray(p.tabs)) return p.tabs.flatMap((t: any) => t?.blocks ?? []);
  if (block.type === 'accordion' && Array.isArray(p.items)) return p.items.flatMap((t: any) => t?.blocks ?? []);
  if (block.type === 'section' && Array.isArray(p.blocks)) return p.blocks;
  return [];
}
export function treeShape(blocks: unknown[]): { count: number; depth: number } {
  let count = 0, deepest = 0;
  const walk = (list: unknown[], depth: number) => {
    for (const b of list) { count++; deepest = Math.max(deepest, depth); if (b && typeof b === 'object') walk(children(b as any), depth + 1); }
  };
  walk(blocks, 1);
  return { count, depth: deepest };
}

export type BlockIssue = { id: string; type: string; reason: string };
/** One block: schema, variant combination, container bounds, dataset references. Returns the block or why it was refused. */
export function parseBlock(raw: unknown): { ok: true; block: Block } | { ok: false; issue: BlockIssue } {
  const rec = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const id = typeof rec.id === 'string' ? rec.id.slice(0, 48) : '?'; const type = typeof rec.type === 'string' ? rec.type.slice(0, 48) : '?';
  const parsed = blockSchema.safeParse(raw);
  if (!parsed.success) {
    const first = parsed.error.issues[0];
    return { ok: false, issue: { id, type, reason: `${first?.path.join('.') || 'block'}: ${first?.message ?? 'invalid'}`.slice(0, 200) } };
  }
  const block = parsed.data;
  const props = block.props as Record<string, unknown>;
  const clash = checkCombination({
    type: block.type, variant: block.variant, appearance: block.appearance, expansion: block.expansion, interaction: block.interaction, emphasis: block.emphasis, density: block.density,
    seriesCount: Array.isArray(props.series) ? props.series.length : undefined,
  });
  if (clash) return { ok: false, issue: { id, type, reason: clash } };
  const shape = treeShape(children(block));
  if (shape.depth > LIMITS.depth - 1 || shape.count > LIMITS.nested) return { ok: false, issue: { id, type, reason: 'nested blocks are too deep or too many' } };
  return { ok: true, block };
}
