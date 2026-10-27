# Variants, properties and tokens

Source of truth: `lumina/src/gen/variants.ts` (vocabulary and per-component subsets), `schemas.ts` (property contracts), `lumina/src/styles/tokens.css` (values).

## Shared vocabulary (enum tokens only; nothing is free text or CSS)

| Axis | Values |
|---|---|
| appearance | minimal, outlined, elevated, filled, ghost (**no glass**: Lumina surfaces are opaque) |
| density | compact, comfortable, spacious (rows 28 / 36 / 46 px) |
| size | xs, sm, md, lg, xl |
| layout (block `layout.*`) | span 1-12, columns 1-6, gap xs-xl (4/8/12/16/24 px), alignment, justify, direction, overflow, sticky, width (auto, narrow 360, medium 560, wide 760, full), height, `responsive.phone` / `responsive.tablet` overrides |
| emphasis | subtle, normal, prominent |
| expansion | collapsed, expanded, full-screen |
| interaction | read-only, selectable, editable, actionable |
| states | idle, hover, focus, active, selected, disabled, loading, empty, error, success (loading / disabled are block fields; empty and error are rendered states) |
| responsiveness | phone, tablet, desktop (CSS breakpoint at 640 px; coarse pointers get 44 px targets) |

## Family variants and what each component actually accepts

Family lists (from the brief) live in `FAMILY_VARIANTS`. A component accepts only the subset it renders (`COMPONENT_VARIANTS`); anything else fails validation.

| Component | Variants |
|---|---|
| text | default, muted, lead |
| list | default, muted |
| citation_list | compact, detailed |
| info_card | compact, detailed, horizontal, expandable |
| metric_card, status_card | compact, detailed |
| card_grid | compact, detailed, horizontal |
| progress | minimal, annotated |
| table | minimal, striped, dense |
| line_chart | minimal, annotated, comparative |
| area_chart, bar_chart | minimal, annotated, comparative, stacked |
| pie_chart, scatter_chart | minimal, annotated |
| form | inline, grouped, conditional |
| button_group | primary, secondary, outline, ghost, destructive |
| tabs | tabs, pills |
| accordion | nested |
| timeline | timeline, inline |
| execution_timeline | timeline, inline, expanded |
| agent_status, error_retry, completion_summary, plan_viewer | inline / expanded (plan_viewer: expanded, inline) |
| tool_call_inspector | inspector |
| approval_request | approval |
| image, gallery | contained / cover / thumbnail; gallery / thumbnail |
| heading, callout, quote, code_block, terminal_output, json_viewer, diff_viewer, follow_up, section, divider | none |

Additional capabilities have stable component ids rather than adding ambiguous variants: `editable_table`, `tree_table`, `wizard`, `image_card`, `modal`, `confirmation`, and the map family. Their property contracts live in `extendedSchemas.ts`; inspect the generated component schema. Only variants actually listed for a schema are accepted.

### Combination rules (`checkCombination`)
`stacked` and `comparative` need at least two series; `full-screen` only for table, charts, media, code, diff, JSON, terminal and execution timeline; `collapsed` only for expandable kinds; `editable` only for `form`; `actionable` only for components that carry actions; `ghost` appearance cannot be `prominent`.

## Property contracts

Every block is `{ id, type, variant?, props, ...shell }`.

- **Shell (all components):** `id`, `variant`, `size`, `density`, `emphasis`, `appearance`, `expansion`, `interaction`, `layout`, `visible`, `disabled`, `loading`, `dataRef`, `accessibilityLabel`, `fallback`. `title` and `description` are in `props`.
- **Bounds:** document ≤ 24 top-level blocks, ≤ 60 total nodes, depth ≤ 3; ≤ 48 KB; inline rows ≤ 60 (more go in a dataset, ≤ 500 rows × 12 columns, sent once and shared by `dataRef`); text ≤ 8,000 chars; ids `^[a-z][a-z0-9_-]{0,47}$`.
- **Defaults:** `heading.level` 3, `text.format` markdown, `table.sortable` true, `table.pageSize` 10, `metric_card.format` number, `code_block.copyable` true, `execution_timeline.live` true, and so on (in the schemas).
- **Data-specific:** text `content/format`; cards `title/subtitle/badge/body/facts/link/actions`; table `columns/rows|dataRef`; charts `xKey/series/data|dataRef` (pie `labelKey/valueKey`, scatter `xKey/yKey/labelKey`); form `fields/submit`; timeline `events`; progress `value/max/status/steps`; agent blocks only `requestId` / `planBlockId` / `phaseId`.
- **Actions** (see `security.md`): `local.sort|filter|expand|select|update`, `navigate.internal`, `agent.request|approve|deny|retry`, `file.download` (schema + dispatcher only; not offered).

## Tokens

- Colours, type, radii (6/10/14/20 px), spacing (4 px base), motion (120 / 180 / 320 ms), focus ring: `tokens.css` (existing). Added: `--chart-1..6`, `--chart-grid`, `--gen-gap-*`, `--gen-row-*`, `--touch-min`.
- Type: system UI font first, bundled Inter fallback, monospace for code; sizes in rem.
- Contrast: text tokens are documented in `tokens.css` as 4.5:1 or better on every surface; chart colours are for non-text marks. Status is never colour only (pills carry a word, deltas carry sr-only text). Not machine-audited (see `testing.md`).
- Motion: `prefers-reduced-motion` and `data-motion='reduced'` disable all animation globally; the only animations in gen.css are a 120-180 ms bar fill and the loading pulse.
