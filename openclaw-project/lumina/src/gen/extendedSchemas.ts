import { z } from 'zod';
import { FAMILIES, type Family } from './catalog';
import { assetRef, httpUrl, ident, text } from './safety';

export function extendedSchemas(shell: z.ZodRawShape, action: z.ZodType, child: z.ZodType) {
  const n = z.number().finite().min(-1e15).max(1e15);
  const value = z.union([text(500, 0), n, z.boolean(), z.null()]);
  const row = z.record(ident, value);
  const column = z.strictObject({ id: ident, label: text(80), type: z.enum(['text', 'number']).optional() });
  const option = z.strictObject({ id: ident, label: text(120), value: n.optional(), group: text(80).optional() });
  const item = z.strictObject({ id: ident, label: text(160), start: z.string().date(), end: z.string().date().optional(), time: text(40).optional(), status: text(40).optional(), detail: text(500).optional(), column: ident.optional() });
  const variable = z.strictObject({ id: ident, label: text(80), value: n, min: n.optional(), max: n.optional(), step: n.positive().optional(), weight: n.optional() });
  const point = z.strictObject({ id: ident, label: text(120), lat: n.min(-90).max(90), lon: n.min(-180).max(180), value: n.optional(), region: text(80).optional() });
  const node = z.strictObject({ id: ident, label: text(160), parent: ident.optional(), value: n.optional(), detail: text(500).optional() });
  const edge = z.strictObject({ source: ident, target: ident, value: n.nonnegative().optional(), label: text(80).optional() });
  const families: Record<Family, z.ZodRawShape> = {
    checklist: { items: z.array(z.strictObject({ id: ident, label: text(160), checked: z.boolean().optional() })).max(100) },
    content: { content: text(8000), source: httpUrl.optional() }, code: { code: z.string().max(12000), language: text(30).optional() },
    file: { assetRef, label: text(160), alt: text(200).optional() },
    container: { blocks: z.array(child).min(1).max(12), labels: z.array(text(80)).max(12).optional() },
    grid: { columns: z.array(column).min(1).max(12), rows: z.array(row).max(500), groupBy: ident.optional(), valueKey: ident.optional(), parentKey: ident.optional() },
    chart: { data: z.array(row).max(500), labelKey: ident, valueKey: ident, xKey: ident.optional(), yKey: ident.optional(), sizeKey: ident.optional(), series: z.array(ident).max(6).optional(), summary: text(400).optional() },
    graph: { nodes: z.array(node).min(1).max(80), edges: z.array(edge).max(160), direction: z.enum(['horizontal', 'vertical']).optional(), source: text(8000).optional() },
    control: { label: text(120), options: z.array(option).max(50).optional(), value: z.union([value, z.array(value).max(50)]).optional(), min: n.optional(), max: n.optional(), step: n.positive().optional() },
    upload: { label: text(120), accept: z.enum(['image', 'document', 'any']).default('any') },
    confirm: { message: text(500), action, label: text(80).default('Continue') },
    pager: { total: z.number().int().min(1).max(10000), pageSize: z.number().int().min(1).max(100).default(10) },
    links: { links: z.array(z.strictObject({ label: text(120), path: text(200) })).min(1).max(20) },
    tree: { nodes: z.array(node).max(200) }, menu: { items: z.array(z.strictObject({ id: ident, label: text(120), action })).min(1).max(40) },
    media: { assets: z.array(z.strictObject({ assetRef, alt: text(200) })).min(1).max(12), caption: text(400).optional(), peaks: z.array(n.min(0).max(1)).max(500).optional() },
    map: { points: z.array(point).max(200), layers: z.array(z.strictObject({ id: ident, label: text(80) })).max(10).optional(), provider: z.strictObject({ id: ident, status: z.literal('unavailable'), reason: text(300) }).optional() },
    runtime: { requestId: z.string().regex(/^[A-Za-z0-9_-]{6,64}$/), planBlockId: z.string().regex(/^[A-Za-z0-9_.:-]{1,64}$/).optional() },
    prompt: { message: text(500), submit: z.strictObject({ label: text(80), action }) },
    decision: { inputs: z.array(variable).min(1).max(20), operation: z.enum(['sum', 'subtract', 'multiply', 'divide', 'weighted_average', 'compound', 'budget', 'compare', 'filter', 'rule']), scenarios: z.array(z.strictObject({ label: text(80), values: z.record(ident, n) })).max(8).optional(), budget: n.nonnegative().optional(), rules: z.array(z.strictObject({ field: ident, operator: z.enum(['equal', 'not_equal', 'greater', 'less', 'at_least', 'at_most']), value: n })).max(20).optional(), combinator: z.enum(['all', 'any']).optional(), unit: text(20).optional() },
    wizard: { steps: z.array(z.strictObject({ id: ident, label: text(80), fields: z.array(z.strictObject({ id: ident, label: text(120), required: z.boolean().optional() })).min(1).max(10) })).min(1).max(10), submit: z.strictObject({ label: text(80), action }) },
    schedule: { items: z.array(item).max(200), month: z.string().regex(/^\d{4}-\d{2}$/).optional(), columns: z.array(z.strictObject({ id: ident, label: text(80) })).max(10).optional() },
    recurrence: { frequency: z.enum(['daily', 'weekly', 'monthly']), interval: z.number().int().min(1).max(365).default(1), start: z.string().date(), weekdays: z.array(z.number().int().min(0).max(6)).max(7).optional() },
    timer: { elapsedSeconds: z.number().min(0).max(1e9).default(0) },
    domain: { columns: z.array(column).min(1).max(12), rows: z.array(row).max(500), source: text(160).optional(), observedAt: text(80).optional(), provider: z.strictObject({ id: ident, status: z.enum(['provided', 'unavailable']), reason: text(300).optional() }) },
    conversion: { value: n, from: text(12), to: text(12), rate: n.positive().optional(), offset: n.optional(), source: text(160).optional(), observedAt: text(80).optional() },
    inspect: { status: z.number().int().min(100).max(599), headers: z.record(ident, text(500, 0)), body: z.string().max(12000) },
  };
  return Object.entries(FAMILIES).map(([type, family]) => z.strictObject({ ...shell, type: z.literal(type), props: z.strictObject({ title: text(120).optional(), description: text(400).optional(), ...families[family], ...(type === 'pivot_table' ? { groupBy: ident, valueKey: ident } : {}), ...(type === 'budget_allocator' ? { operation: z.literal('budget').default('budget'), budget: n.nonnegative() } : {}), ...(['decision_matrix', 'weighted_scoring'].includes(type) ? { operation: z.literal('weighted_average').default('weighted_average'), scenarios: z.array(z.strictObject({ label: text(80), values: z.record(ident, n) })).min(1).max(8) } : {}), ...(type === 'mermaid' ? { source: text(8000), nodes: z.array(node).max(80).optional(), edges: z.array(edge).max(160).optional() } : {}) }) }));
}
