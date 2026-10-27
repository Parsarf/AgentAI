import { chartSpec, comparisonSpec, tableSpec } from './data';

/** Only bounded, schema-validated read-only cards may replace a JSON block. */
export function inlineCard(value: string) {
  if (value.length > 50_000 || !value.trim().startsWith('{')) return null;
  try {
    let spec: unknown = JSON.parse(value);
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null;
    const record = spec as Record<string, unknown>;
    // Older/generated responses sometimes put the chart subtype in `type`.
    if (['bar', 'line', 'pie', 'donut'].includes(String(record.type)) && !('chart' in record)) {
      spec = { ...record, type: 'chart', chart: record.type };
    }
    const chart = chartSpec.safeParse(spec);
    if (chart.success) return { kind: 'chart' as const, spec: chart.data };
    const table = tableSpec.safeParse(spec);
    if (table.success) return { kind: 'table' as const, spec: table.data };
    const comparison = comparisonSpec.safeParse(spec);
    if (comparison.success) return { kind: 'comparison' as const, spec: comparison.data };
  } catch { /* ordinary or malformed JSON stays literal; never execute it */ }
  return null;
}
