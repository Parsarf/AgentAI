/** Historical API names only. There is one renderer; old cards migrate to registry documents. */
import { lazy, Suspense } from 'react';
import type { ChartSpec, ComparisonSpec, TableSpec } from '../../lib/genui/data';
const LegacyDocument = lazy(() => import('../../gen/legacy'));
const render = (spec: ChartSpec | ComparisonSpec | TableSpec) => <Suspense fallback={<p>Loading historical result…</p>}><LegacyDocument spec={spec} /></Suspense>;
export const TableCard = ({ spec }: { spec: TableSpec }) => render(spec);
export const ChartCard = ({ spec }: { spec: ChartSpec }) => render(spec);
export const ComparisonCard = ({ spec }: { spec: ComparisonSpec }) => render(spec);
