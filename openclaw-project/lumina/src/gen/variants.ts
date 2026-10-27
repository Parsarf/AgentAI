// The shared variant vocabulary, and which subset each component accepts. Variants are enum tokens: a model can pick from this list and nothing else.
// A component only lists the variants it genuinely renders; the schema rejects the rest instead of allowing a meaningless Cartesian product.

export const APPEARANCE = ['minimal', 'outlined', 'elevated', 'filled', 'ghost'] as const;   // no 'glass': the Lumina surface system is opaque
export const DENSITY = ['compact', 'comfortable', 'spacious'] as const;
export const SIZE = ['xs', 'sm', 'md', 'lg', 'xl'] as const;
export const LAYOUT = ['inline', 'stacked', 'horizontal', 'vertical', 'grid'] as const;
export const EMPHASIS = ['subtle', 'normal', 'prominent'] as const;
export const EXPANSION = ['collapsed', 'expanded', 'full-screen'] as const;
export const INTERACTION = ['read-only', 'selectable', 'editable', 'actionable'] as const;
export const STATES = ['idle', 'hover', 'focus', 'active', 'selected', 'disabled', 'loading', 'empty', 'error', 'success'] as const;
export const RESPONSIVE = ['phone', 'tablet', 'desktop'] as const;

export type Appearance = (typeof APPEARANCE)[number];
export type Density = (typeof DENSITY)[number];
export type Size = (typeof SIZE)[number];
export type Emphasis = (typeof EMPHASIS)[number];
export type Expansion = (typeof EXPANSION)[number];
export type Interaction = (typeof INTERACTION)[number];

/** Family variants, as listed in the brief. */
export const FAMILY_VARIANTS = {
  card: ['compact', 'detailed', 'horizontal', 'expandable', 'media-led'],
  table: ['minimal', 'striped', 'dense', 'editable', 'hierarchical'],
  chart: ['minimal', 'annotated', 'comparative', 'stacked'],
  button: ['primary', 'secondary', 'outline', 'ghost', 'destructive', 'icon'],
  input: ['default', 'filled', 'underlined', 'compact', 'searchable'],
  navigation: ['tabs', 'pills', 'vertical', 'sidebar', 'nested'],
  media: ['contained', 'cover', 'thumbnail', 'immersive', 'gallery'],
  map: ['pins', 'clusters', 'routes', 'heatmap', 'layers'],
  agent: ['inline', 'timeline', 'expanded', 'inspector'],
  form: ['inline', 'grouped', 'multi-step', 'conditional'],
  dialog: ['confirmation', 'information', 'destructive', 'approval'],
  text: ['default', 'muted', 'lead'],
} as const;
export type Family = keyof typeof FAMILY_VARIANTS;

/** Subset of the family list each implemented component renders today. Anything not listed is not a variant of that component. */
export const COMPONENT_VARIANTS = {
  text: ['default', 'muted', 'lead'],
  heading: [],
  list: ['default', 'muted'],
  callout: [],
  quote: [],
  citation_list: ['compact', 'detailed'],
  code_block: [],
  terminal_output: [],
  json_viewer: [],
  diff_viewer: [],
  info_card: ['compact', 'detailed', 'horizontal', 'expandable'],
  metric_card: ['compact', 'detailed'],
  status_card: ['compact', 'detailed'],
  progress: ['minimal', 'annotated'],
  card_grid: ['compact', 'detailed', 'horizontal'],
  table: ['minimal', 'striped', 'dense'],
  line_chart: ['minimal', 'annotated', 'comparative'],
  area_chart: ['minimal', 'annotated', 'comparative', 'stacked'],
  bar_chart: ['minimal', 'annotated', 'comparative', 'stacked'],
  pie_chart: ['minimal', 'annotated'],
  scatter_chart: ['minimal', 'annotated'],
  form: ['inline', 'grouped', 'conditional'],
  button_group: ['primary', 'secondary', 'outline', 'ghost', 'destructive'],
  follow_up: [],
  tabs: ['tabs', 'pills'],
  accordion: ['nested'],
  section: [],
  divider: [],
  image: ['contained', 'cover', 'thumbnail'],
  gallery: ['gallery', 'thumbnail'],
  timeline: ['timeline', 'inline'],
  execution_timeline: ['timeline', 'inline', 'expanded'],
  tool_call_inspector: ['inspector'],
  agent_status: ['inline', 'expanded'],
  plan_viewer: ['expanded', 'inline'],
  approval_request: ['approval'],
  error_retry: ['inline', 'expanded'],
  completion_summary: ['inline', 'expanded'],
} as const satisfies Record<string, readonly string[]>;

export type ComponentType = keyof typeof COMPONENT_VARIANTS;

export interface Combination {
  type: string; variant?: string; appearance?: string; expansion?: string; interaction?: string; emphasis?: string; density?: string;
  seriesCount?: number; editable?: boolean;
}
/** Which axes make sense for which component. The checks below reject combinations that would render as nothing or mean nothing. */
const FULL_SCREEN_OK = new Set<string>(['table', 'line_chart', 'area_chart', 'bar_chart', 'scatter_chart', 'image', 'gallery', 'code_block', 'diff_viewer', 'json_viewer', 'terminal_output', 'execution_timeline']);
const EXPANDABLE = new Set<string>(['text', 'info_card', 'card_grid', 'code_block', 'json_viewer', 'terminal_output', 'diff_viewer', 'accordion', 'citation_list', 'plan_viewer', 'execution_timeline', 'tool_call_inspector']);
const EDITABLE = new Set<string>(['form']);
const ACTIONABLE = new Set<string>(['form', 'button_group', 'follow_up', 'approval_request', 'error_retry', 'info_card', 'card_grid', 'table']);

export function checkCombination(c: Combination): string | null {
  const allowed = (COMPONENT_VARIANTS as Record<string, readonly string[]>)[c.type];
  if (!allowed) return `unknown component ${c.type}`;
  if (c.variant && !allowed.includes(c.variant)) return `${c.type} has no variant "${c.variant}"`;
  if (c.expansion === 'full-screen' && !FULL_SCREEN_OK.has(c.type)) return `${c.type} cannot go full-screen`;
  if (c.expansion && c.expansion !== 'expanded' && !EXPANDABLE.has(c.type) && !FULL_SCREEN_OK.has(c.type)) return `${c.type} cannot be collapsed`;
  if (c.interaction === 'editable' && !EDITABLE.has(c.type)) return `${c.type} is not editable`;
  if (c.interaction === 'actionable' && !ACTIONABLE.has(c.type)) return `${c.type} has no actions`;
  if (c.variant === 'stacked' && (c.seriesCount ?? 0) < 2) return 'a stacked chart needs at least two series';
  if (c.variant === 'comparative' && (c.seriesCount ?? 0) < 2) return 'a comparative chart needs at least two series';
  if (c.appearance === 'ghost' && c.emphasis === 'prominent') return 'ghost appearance cannot be prominent';
  return null;
}
