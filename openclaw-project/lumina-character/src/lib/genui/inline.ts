import type { z } from 'zod';
import { CARD_SCHEMAS, type CardKind } from './data';

/** One card, tagged with its kind so code can narrow on `kind` and get that kind's spec type. */
export type InlineCard = { [K in CardKind]: { kind: K; spec: z.infer<(typeof CARD_SCHEMAS)[K]> } }[CardKind];

/** Only bounded, schema-validated cards may replace a JSON block: the `type` picks the one schema it must pass. */
export function inlineCard(value: string): InlineCard | null {
  if (value.length > 50_000 || !value.trim().startsWith('{')) return null;
  try {
    let spec: unknown = JSON.parse(value);
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null;
    const record = spec as Record<string, unknown>;
    // Older/generated responses sometimes put the chart subtype in `type`.
    if (['bar', 'line', 'pie', 'donut'].includes(String(record.type)) && !('chart' in record)) {
      spec = { ...record, type: 'chart', chart: record.type };
    }
    const kind = String((spec as Record<string, unknown>).type) as CardKind;
    if (!(kind in CARD_SCHEMAS)) return null;
    const parsed = CARD_SCHEMAS[kind].safeParse(spec);
    if (parsed.success) return { kind, spec: parsed.data } as InlineCard;
  } catch { /* ordinary or malformed JSON stays literal; never execute it */ }
  return null;
}
