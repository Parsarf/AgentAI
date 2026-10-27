/** Cross-field constraints exported alongside JSON Schema for the server interpreter. */
export const ORDERED_FIELDS: Record<string, readonly string[]> = { candlestick_chart: ['low', 'open', 'high'], box_plot: ['min', 'q1', 'median', 'q3', 'max'] };
export function semanticIssue(block: { type: string; props: Record<string, any> }): string | null {
  const p = block.props;
  for (const key of ['buttons', 'tabs']) if (p[key] && new Set(p[key].map((i: any) => i.id)).size !== p[key].length) return `${key} ids must be unique`;
  if (p.fields) {
    const ids = new Set<string>();
    for (const f of p.fields) {
      if (ids.has(f.id)) return 'field ids must be unique'; ids.add(f.id);
      if (['radio', 'segmented', 'select'].includes(f.type) && !f.options?.length) return `${f.id}: choice fields require options`;
      if (f.min !== undefined && f.max !== undefined && f.min > f.max) return `${f.id}: min exceeds max`;
    }
  }
  if (block.type === 'pivot_table' && p.rows.some((r: any) => typeof r[p.valueKey] !== 'number')) return 'pivot valueKey requires numeric values in every row';
  if (p.nodes && p.edges) {
    const ids = new Set(p.nodes.map((n: any) => n.id));
    if (ids.size !== p.nodes.length || p.edges.some((e: any) => !ids.has(e.source) || !ids.has(e.target))) return 'graph needs unique node ids and edges between known nodes';
  }
  const keys = ORDERED_FIELDS[block.type];
  if (keys) for (const row of p.data) {
    if (keys.some(k => typeof row[k] !== 'number') || keys.some((k, i) => i && row[k] < row[keys[i - 1]])) return `data requires ordered numeric fields: ${keys.join(', ')}`;
    if (block.type === 'candlestick_chart' && (typeof row.close !== 'number' || row.close < row.low || row.close > row.high)) return 'close must be between low and high';
  }
  if (p.items && ['calendar', 'agenda', 'gantt', 'event', 'availability_grid', 'kanban', 'reminder', 'travel_itinerary'].includes(block.type) && p.items.some((i: any) => i.end && i.end < i.start)) return 'schedule end precedes start';
  return null;
}
