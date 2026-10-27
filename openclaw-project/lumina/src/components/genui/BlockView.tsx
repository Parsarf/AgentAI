import { formSpec, planSpec, type Block } from '../../lib/genui/schema';
import FormBlock from './FormBlock';
import PlanBlock from './PlanBlock';
import { ChartCard, ComparisonCard, TableCard } from './Cards';
import { chartSpec, comparisonSpec, tableSpec } from '../../lib/genui/data';
import { lazy, Suspense } from 'react';
import type { Bridge } from '../../gen/ChatBridge';

const GenBlock = lazy(() => import('../../gen/ChatBridge'));          // the generative-UI renderer loads only when a reply carries a document

/** Renders a server-validated block, re-checking it against the client schema. Anything unrecognised becomes a safe read-only note. */
export default function BlockView({ block, onChanged, bridge }: { block: Block; onChanged(): void; bridge?: Bridge }) {
  if (block.schema_version === '1.0') {
    if (block.kind === 'document' && bridge) return <Suspense fallback={null}><GenBlock key={block.id} block={block} bridge={bridge} /></Suspense>;
    if (block.kind === 'form') {
      const spec = formSpec.safeParse(block.spec);
      if (spec.success) return <FormBlock key={block.id} block={block} spec={spec.data} onChanged={onChanged} />;
    } else if (block.kind === 'table') {
      const spec = tableSpec.safeParse(block.spec); if (spec.success) return <TableCard key={block.id} spec={spec.data} />;
    } else if (block.kind === 'chart') {
      const spec = chartSpec.safeParse(block.spec); if (spec.success) return <ChartCard key={block.id} spec={spec.data} />;
    } else if (block.kind === 'comparison') {
      const spec = comparisonSpec.safeParse(block.spec); if (spec.success) return <ComparisonCard key={block.id} spec={spec.data} />;
    } else if (block.kind === 'task_plan') {
      const spec = planSpec.safeParse(block.spec);
      if (spec.success) return <PlanBlock key={block.id} block={block} original={spec.data} onChanged={onChanged} />;
    }
  }
  return <section className="gblock"><p className="muted">This interactive card can’t be shown in this version of Lumina. Your answers and history are kept.</p></section>;
}
