import type { z } from 'zod';
import { CARD_SCHEMAS, type CardKind } from '../../lib/genui/data';
import { ChartCard, ComparisonCard, TableCard } from './Cards';
import { AnswerCard, CalloutCard, ChoiceCard, PlacesCard, ProductsCard, SourcesCard, StepsCard, TimelineCard } from './RichCards';

type Spec<K extends CardKind> = z.infer<(typeof CARD_SCHEMAS)[K]>;

/** Draws one card of any kind from an already validated spec (stored blocks and inline JSON both come through here). */
export function CardFor({ kind, spec }: { kind: CardKind; spec: unknown }) {
  switch (kind) {
    case 'table': return <TableCard spec={spec as Spec<'table'>} />;
    case 'chart': return <ChartCard spec={spec as Spec<'chart'>} />;
    case 'comparison': return <ComparisonCard spec={spec as Spec<'comparison'>} />;
    case 'places': return <PlacesCard spec={spec as Spec<'places'>} />;
    case 'products': return <ProductsCard spec={spec as Spec<'products'>} />;
    case 'steps': return <StepsCard spec={spec as Spec<'steps'>} />;
    case 'answer': return <AnswerCard spec={spec as Spec<'answer'>} />;
    case 'choice': return <ChoiceCard spec={spec as Spec<'choice'>} />;
    case 'callout': return <CalloutCard spec={spec as Spec<'callout'>} />;
    case 'timeline': return <TimelineCard spec={spec as Spec<'timeline'>} />;
    case 'sources': return <SourcesCard spec={spec as Spec<'sources'>} />;
  }
}

/** Re-checks a spec against its kind's schema before drawing it; anything that does not pass is not drawn. */
export function checkedCard(kind: string, spec: unknown) {
  if (!(kind in CARD_SCHEMAS)) return null;
  const parsed = CARD_SCHEMAS[kind as CardKind].safeParse(spec);
  return parsed.success ? <CardFor kind={kind as CardKind} spec={parsed.data} /> : null;
}
