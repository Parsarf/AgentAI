import { formSpec, planSpec, type Block } from '../../lib/genui/schema';
import FormBlock from './FormBlock';
import PlanBlock from './PlanBlock';
import { checkedCard } from './CardView';

/** Renders a server-validated block, re-checking it against the client schema. Anything unrecognised becomes a safe read-only note. */
export default function BlockView({ block, onChanged }: { block: Block; onChanged(): void }) {
  if (block.schema_version === '1.0') {
    if (block.kind === 'form') {
      const spec = formSpec.safeParse(block.spec);
      if (spec.success) return <FormBlock key={block.id} block={block} spec={spec.data} onChanged={onChanged} />;
    } else if (block.kind === 'task_plan') {
      const spec = planSpec.safeParse(block.spec);
      if (spec.success) return <PlanBlock key={block.id} block={block} original={spec.data} onChanged={onChanged} />;
    } else if (block.kind === 'display') {
      return null;                                                  // a layout hint for the reply above it, drawn by the reply itself
    } else {
      const card = checkedCard(block.kind, block.spec);
      if (card) return <div key={block.id}>{card}</div>;
    }
  }
  return <section className="gblock"><p className="muted">This interactive card can’t be shown in this version of Lumina. Your answers and history are kept.</p></section>;
}
