// Deterministic, registry-driven renderer: a validated document in, React out. No model-written code, markup or styles ever reaches the DOM.
import '../gen.css';import { Component, memo, useEffect, type CSSProperties, type ReactNode } from 'react';
import type { Block } from '../schemas';
import { isRenderable, REGISTRY } from '../registry';
import { slotFor, type GenDocument, type Slot } from '../protocol';
import { cx } from './types';
import { GenProvider, type ExecutionProvider, type Host } from './context';
import { Accordion, Divider, Gallery, ImageBlock, Section, Tabs, Timeline } from './layout';
import { CalloutBlock, CitationList, CodeBlock, DiffViewer, HeadingBlock, JsonViewer, ListBlock, QuoteBlock, TerminalOutput, TextBlock } from './text';
import { ButtonGroup, CardGrid, FollowUp, Gauge, InfoCard, MetricCard, ProgressBlock, StatusCard } from './cards';
import { AreaChart, BarChart, HistogramChart, LineChart, PieChart, ScatterChart, TableBlock } from './data';
import { FormBlock } from './forms';
import { AgentStatus, ApprovalRequest, CompletionSummary, ErrorRetry, ExecutionTimeline, PlanViewer, ToolCallInspector } from './agent';

type Diagnostic = (d: { id: string; type: string; reason: string }) => void;
const defaultDiagnostic: Diagnostic = d => { if (typeof console !== 'undefined') console.warn(`[lumina-gen] ${d.type} "${d.id}": ${d.reason}`); };

/** renderer key -> component. A test asserts this has exactly the registry's keys, so the registry can never advertise something that cannot draw. */
type Draw = (block: any, nested: (blocks: unknown[]) => ReactNode[]) => ReactNode;
export const RENDERERS: Record<string, Draw> = {
  text: b => <TextBlock block={b} />, heading: b => <HeadingBlock block={b} />, list: b => <ListBlock block={b} />, callout: b => <CalloutBlock block={b} />, quote: b => <QuoteBlock block={b} />,
  citation_list: b => <CitationList block={b} />, code_block: b => <CodeBlock block={b} />, terminal_output: b => <TerminalOutput block={b} />, json_viewer: b => <JsonViewer block={b} />, diff_viewer: b => <DiffViewer block={b} />,
  info_card: b => <InfoCard block={b} />, metric_card: b => <MetricCard block={b} />, status_card: b => <StatusCard block={b} />, progress: b => <ProgressBlock block={b} />, card_grid: b => <CardGrid block={b} />,
  table: b => <TableBlock block={b} />, line_chart: b => <LineChart block={b} />, area_chart: b => <AreaChart block={b} />, bar_chart: b => <BarChart block={b} />, pie_chart: b => <PieChart block={b} />, scatter_chart: b => <ScatterChart block={b} />, histogram_chart: b => <HistogramChart block={b} />, gauge: b => <Gauge block={b} />,
  form: b => <FormBlock block={b} />, button_group: b => <ButtonGroup block={b} />, follow_up: b => <FollowUp block={b} />,
  tabs: (b, n) => <Tabs block={b} panels={b.props.tabs.map((t: any) => <>{n(t.blocks)}</>)} />,
  accordion: (b, n) => <Accordion block={b} panels={b.props.items.map((t: any) => <>{n(t.blocks)}</>)} />,
  section: (b, n) => <Section block={b}>{n(b.props.blocks)}</Section>, divider: () => <Divider />,
  image: b => <ImageBlock block={b} />, gallery: b => <Gallery block={b} />, timeline: b => <Timeline block={b} />,
  execution_timeline: b => <ExecutionTimeline block={b} />, tool_call_inspector: b => <ToolCallInspector block={b} />, agent_status: b => <AgentStatus block={b} />, plan_viewer: b => <PlanViewer block={b} />,
  approval_request: b => <ApprovalRequest block={b} />, error_retry: b => <ErrorRetry block={b} />, completion_summary: b => <CompletionSummary block={b} />,
};

class Boundary extends Component<{ fallback: string; id: string; type: string; onError: Diagnostic; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { this.props.onError({ id: this.props.id, type: this.props.type, reason: `render error: ${error.message}` }); }
  render() { return this.state.failed ? <Fallback text={this.props.fallback} /> : this.props.children; }
}
export function Fallback({ text }: { text: string }) { return <p className="gen-fallback" role="note">{text}</p>; }

const layoutStyle = (b: Block): CSSProperties | undefined => {
  const l = b.layout; if (!l) return undefined;
  return { gridColumn: l.span ? `span ${l.span}` : undefined, alignSelf: l.alignment === 'stretch' ? 'stretch' : undefined };
};
const layoutClasses = (b: Block) => { const l = b.layout; return cx(l?.width && `w-${l.width}`, l?.height && `h-${l.height}`, l?.gap && `gap-${l.gap}`, l?.sticky && 'sticky', l?.overflow && `of-${l.overflow}`, l?.direction === 'row' && 'dir-row', l?.alignment && `al-${l.alignment}`, l?.justify && `ju-${l.justify}`); };

function BlockShell({ block, fallback, onDiagnostic }: { block: Block; fallback: string; onDiagnostic: Diagnostic }) {
  if (block.visible === false) return null;
  const draw = RENDERERS[REGISTRY[block.type]?.rendererKey];
  if (!draw) { return <Fallback text={fallback} />; }
  const nested = (list: unknown[]) => list.map(raw => <SlotView key={(raw as any)?.id} slot={slotFor(raw)} onDiagnostic={onDiagnostic} />);
  return <div className={cx('gen-block', `t-${block.type}`, block.appearance && `ap-${block.appearance}`, block.density && `d-${block.density}`, block.size && `sz-${block.size}`, block.emphasis && `em-${block.emphasis}`, block.disabled && 'is-disabled', layoutClasses(block))}
    data-block={block.id} style={layoutStyle(block)} aria-label={block.accessibilityLabel} aria-busy={block.loading || undefined}>
    {block.props.title && !['heading', 'section', 'form', 'info_card'].includes(block.type) && <h4 className="gen-title">{block.props.title}</h4>}
    {block.props.description && !['section', 'form', 'callout'].includes(block.type) && <p className="gen-desc faint">{block.props.description}</p>}
    {block.loading ? <Skeleton /> : (
      <Boundary fallback={fallback} id={block.id} type={block.type} onError={onDiagnostic}><Draw draw={draw} block={block} nested={nested} /></Boundary>)}
  </div>;
}
/** Calls the renderer inside the boundary, so even a renderer function that throws cannot take the answer down. */
function Draw({ draw, block, nested }: { draw: Draw; block: Block; nested: (blocks: unknown[]) => ReactNode[] }) { return <>{draw(block, nested)}</>; }
function Skeleton() { return <div className="gen-skel" role="status" aria-label="Loading"><i /><i /><i /></div>; }

function SlotViewBase({ slot, onDiagnostic }: { slot: Slot; onDiagnostic: Diagnostic }) {
  useEffect(() => { if (slot.status === 'invalid') onDiagnostic({ id: slot.id, type: slot.type, reason: slot.reason }); }, [slot.status === 'invalid' ? slot.reason : '', slot.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (slot.status === 'pending') return slot.type === 'text' ? null : <div className="gen-block" data-block={slot.id}><div className="gen-skel" role="status" aria-label={`Preparing ${slot.type.replace('_', ' ')}`}><i /><i /><i /></div></div>;
  if (slot.status === 'invalid') return <Fallback text={slot.fallback} />;
  return <BlockShell block={slot.block} fallback={slot.fallback} onDiagnostic={onDiagnostic} />;
}
const SlotView = memo(SlotViewBase, (a, b) => a.slot === b.slot);

export function allBlockIds(slots: Slot[]): string[] {
  const out: string[] = [];
  const walk = (raw: any) => { if (raw?.id) out.push(raw.id); const p = raw?.props ?? {}; [...(p.tabs ?? []), ...(p.items ?? [])].forEach((x: any) => (x.blocks ?? []).forEach(walk)); (p.blocks ?? []).forEach(walk); };
  slots.forEach(s => (s.status === 'ready' ? walk(s.block) : out.push(s.id)));
  return out;
}

export interface GenDocumentViewProps { doc: Pick<GenDocument, 'slots' | 'datasets'>; exec: ExecutionProvider; host: Host; scope: string; readOnly?: boolean; onDiagnostic?: Diagnostic; className?: string }
export function GenDocumentView({ doc, exec, host, scope, readOnly, onDiagnostic = defaultDiagnostic, className }: GenDocumentViewProps) {
  return <GenProvider datasets={doc.datasets} blockIds={allBlockIds(doc.slots)} exec={exec} host={host} scope={scope} readOnly={readOnly}>
    <div className={cx('gen-doc', className)}>{doc.slots.map(s => <SlotView key={s.id} slot={s} onDiagnostic={onDiagnostic} />)}</div></GenProvider>;
}
export { isRenderable };
