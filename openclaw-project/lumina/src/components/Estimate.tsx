import { useEffect, useState } from 'react';
import { api } from '../lib/api';

export interface EstimateRange { kind: string; based_on: number; scope: 'yours' | 'all'; seconds: { typical: number; upper: number }; cost_microusd: { typical: number; upper: number } }

export const duration = (seconds: number) => (seconds < 90 ? 'a minute or less' : seconds < 5400 ? `${Math.round(seconds / 60)} minutes` : `${(seconds / 3600).toFixed(1).replace(/\.0$/, '')} hours`);
const money = (micro: number) => (micro < 10_000 ? 'under 1 cent' : `$${(micro / 1e6).toFixed(micro < 1e6 ? 2 : 1)}`);

/** What a task like this usually takes and costs, from tasks of the same kind that finished: a typical value and a "most take no longer than". Says how many tasks it rests on and shows
 *  nothing at all when there is too little history. Informational: it never limits, delays or blocks anything. */
export default function Estimate({ kind, label = 'Usually' }: { kind: string; label?: string }) {
  const [found, setFound] = useState<EstimateRange | null>(null);
  useEffect(() => {
    let alive = true;
    api<{ estimate: EstimateRange | null }>('GET', `/v1/estimates/${kind}`).then(r => { if (alive) setFound(r.estimate); }).catch(() => { /* no estimate: show nothing */ });
    return () => { alive = false; };
  }, [kind]);
  if (!found) return null;
  const { seconds, cost_microusd: cost } = found;
  return (
    <p className="est" role="note">
      {label} about {duration(seconds.typical)} and {money(cost.typical)}; most take no longer than {duration(seconds.upper)} and {money(cost.upper)}.
      <small> Based on {found.based_on} similar {found.based_on === 1 ? 'task' : 'tasks'}{found.scope === 'all' ? ' from all customers' : ' of yours'}.</small>
    </p>);
}
