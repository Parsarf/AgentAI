// Single source of truth: the Python server validates documents against gen_registry.json, which is generated from the schemas here.
// `GEN_WRITE=1 npx vitest run src/gen/export.test.ts` rewrites it; a normal run fails when the committed file has drifted.
import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { ACTION_KINDS, LIMITS, SCHEMA_VERSION, blockSchema, datasetSchema, presentationPlanSchema } from './schemas';
import { OFFERED, REGISTRY, compactCatalog, modelCatalog } from './registry';
import { COMPONENT_VARIANTS } from './variants';
import { ALL_PARTS, INVALID_BLOCKS, SAMPLE_CONVERSATION } from './fixtures';
import { ADAPTER_ONLY } from './registry';
import { MANIFEST, categories } from './manifest';

const OUT = '../platform/agentai_platform/genui/gen_registry.json';
const OFFERED_ACTIONS = ACTION_KINDS.filter(k => k !== 'file.download');       // wired in the dispatcher, but no host adapter yet: not offered
const js = (s: z.ZodType) => z.toJSONSchema(s, { unrepresentable: 'any', target: 'draft-2020-12', io: 'input' } as any);

export function buildPayload() {
  return {
    generatedBy: 'lumina/src/gen/export.test.ts (do not edit by hand)', schemaVersion: SCHEMA_VERSION, limits: LIMITS,
    offered: OFFERED, variants: Object.fromEntries(OFFERED.map(t => [t, (COMPONENT_VARIANTS as Record<string, readonly string[]>)[t]])),
    actions: OFFERED_ACTIONS, supportedActions: Object.fromEntries(OFFERED.map(t => [t, REGISTRY[t].supportedActions])),
    catalog: modelCatalog(), catalogCompact: compactCatalog(), blockSchema: js(blockSchema), datasetSchema: js(datasetSchema), presentationPlanSchema: js(presentationPlanSchema),
  };
}
const PARITY = '../platform/tests/fixtures/gen_parity.json';
const parity = () => ({ generatedBy: 'lumina/src/gen/export.test.ts (do not edit by hand)', valid: [...ALL_PARTS, SAMPLE_CONVERSATION].map(d => ({ ...d, blocks: d.blocks.filter((b: any) => !ADAPTER_ONLY.has(b.type)) })), invalid: INVALID_BLOCKS.map(([name, block]) => ({ name, block })) });
const CATALOG = '../docs/generative-ui/component-catalog.md';
function catalogMarkdown(): string {
  const count = (st: string) => MANIFEST.filter(e => e.status === st).length;
  const lines = ['# Component catalog', '', '_Generated from `lumina/src/gen/manifest.ts` by `GEN_WRITE=1 npx vitest run src/gen/export.test.ts`. Do not edit by hand; a test fails when this file drifts._', '',
    `**${MANIFEST.length} entries: ${count('implemented')} implemented, ${count('adapter')} adapter, ${count('planned')} planned, ${count('unsupported')} unsupported.**`, '',
    '- **implemented**: a renderer exists, either directly or *via* another implemented component with specific props or a variant. Only these are ever shown to the model.',
    '- **adapter**: code exists (a renderer or a bridge) but a host capability or provider is missing, so it is not offered. The reason is in the Purpose column.',
    '- **planned**: designed, not built. **unsupported**: deliberately not offered.', '',
    'Kind: primitive (one control or text element), composite (built from primitives), widget (a specialised display), adapter (needs external data). "Live provider" says whether the entry needs a data provider that does not exist yet.', ''];
  for (const c of categories) {
    lines.push(`## ${c}`, '', '| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |', '|---|---|---|---|---|---|---|---|---|---|');
    for (const e of MANIFEST.filter(x => x.category === c)) lines.push(`| \`${e.id}\` | ${e.name} | ${e.kind} | ${e.status} | ${e.status === 'implemented' ? `\`${e.via ?? e.id}\`${e.how ? ` (${e.how})` : ''}` : '—'} | ${e.purpose} | ${e.data} | ${e.interactions} | ${e.fallback} | ${e.provider ? 'yes' : 'no'} |`);
    lines.push('');
  }
  return lines.join('\n');
}
describe('registry export', () => {
  it('matches the committed JSON the Python server loads', () => {
    const fs = (globalThis as any).process.getBuiltinModule('node:fs');
    const text = JSON.stringify(buildPayload()) + '\n';
    const par = JSON.stringify(parity(), null, 1) + '\n';
    if ((globalThis as any).process.env.GEN_WRITE) { fs.writeFileSync(OUT, text); fs.writeFileSync(PARITY, par); fs.writeFileSync(CATALOG, catalogMarkdown()); return; }
    expect(fs.readFileSync(OUT, 'utf8') === text, 'gen_registry.json is stale: run GEN_WRITE=1 npx vitest run src/gen/export.test.ts').toBe(true);
    expect(fs.readFileSync(CATALOG, 'utf8') === catalogMarkdown(), 'component-catalog.md is stale: run GEN_WRITE=1 npx vitest run src/gen/export.test.ts').toBe(true);
    expect(fs.readFileSync(PARITY, 'utf8') === par, 'gen_parity.json is stale: run GEN_WRITE=1 npx vitest run src/gen/export.test.ts').toBe(true);
  });
  it('uses only the JSON Schema keywords the Python validator implements', () => {
    const allowed = new Set(['$schema', 'type', 'properties', 'required', 'additionalProperties', 'enum', 'const', 'pattern', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minLength', 'maxLength', 'minItems', 'maxItems', 'items', 'oneOf', 'anyOf', 'default', 'propertyNames', '$ref', 'description', 'format', 'not']);
    const seen = new Set<string>(); const walk = (n: unknown, inProps = false) => { if (!n || typeof n !== 'object') return; if (Array.isArray(n)) return n.forEach(x => walk(x)); for (const [k, v] of Object.entries(n)) { if (!inProps) seen.add(k); walk(v, k === 'properties'); } };
    walk(buildPayload().blockSchema); walk(buildPayload().datasetSchema); walk(buildPayload().presentationPlanSchema);
    expect([...seen].filter(k => !allowed.has(k))).toEqual([]);
  });
});
