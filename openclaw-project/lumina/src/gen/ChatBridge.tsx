// Connects a stored document block to the real chat: Lumina's own requests and plan blocks feed the agent-native widgets, and the host actions
// call the endpoints that already exist (send a message, approve/skip/retry a phase, retry a request). Nothing here invents a capability.
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import type { RequestRow } from '../lib/api';
import type { Block as StoredBlock, Phase, PhaseRun } from '../lib/genui/schema';
import { useActivity } from '../lib/useActivity';
import { parseDocument } from './protocol';
import { GenDocumentView } from './components/Renderer';
import type { ExecutionProvider, Host, PlanInfo, RequestInfo } from './components/context';
import type { PhaseState } from './actions';
import { Fallback } from './components/Renderer';

export interface Bridge { conversationId: string; tasks: RequestRow[]; blocks: StoredBlock[]; reload(): void }

function planOf(b: StoredBlock | undefined): PlanInfo | undefined {
  if (!b || b.kind !== 'task_plan') return undefined;
  const spec = b.spec as { title?: string; phases?: Phase[] }; const phases = (b.state?.plan?.phases ?? spec.phases ?? []) as Phase[];
  const run = Object.fromEntries(Object.entries((b.run ?? {}) as Record<string, PhaseRun>).map(([k, v]) => [k, { state: v.state as PhaseState, summary: v.summary }]));
  return { id: b.id, title: spec.title ?? 'Plan', phases: phases.filter(p => p.enabled !== false).map(p => ({ id: p.id, title: p.title, description: p.description })), run, run_status: b.run_status };
}

export default function GenBlock({ block, bridge }: { block: StoredBlock; bridge: Bridge }) {
  const navigate = useNavigate();
  const doc = useMemo(() => parseDocument(block.spec), [block.spec]);
  const exec = useMemo<ExecutionProvider>(() => ({
    request: (id): RequestInfo | undefined => { const r = bridge.tasks.find(t => t.id === id); return r && { id: r.id, state: r.state, result: r.result, message: r.message, outcome: r.outcome, outcome_note: r.outcome_note, created_epoch: r.created_epoch }; },
    plan: id => planOf(bridge.blocks.find(b => b.id === id)),
    useActivity: (requestId, live) => useActivity(requestId, live),       // eslint-disable-line react-hooks/rules-of-hooks
  }), [bridge.tasks, bridge.blocks]);
  const host = useMemo<Host>(() => ({
    send: async (message, key) => { await api('POST', `/v1/conversations/${bridge.conversationId}/send`, { message, key, mode: 'text' }); bridge.reload(); },
    phase: async (planBlockId, phaseId, verb) => { await api('POST', `/v1/blocks/${planBlockId}/phase`, { phase_id: phaseId, action: verb }); bridge.reload(); },
    retryRequest: async requestId => { await api('POST', `/v1/requests/${requestId}/retry`, {}); bridge.reload(); },
    navigate: path => navigate(path),
    download: async () => { throw new Error('file.download is not wired in the chat host yet'); },
    phaseState: (planBlockId, phaseId) => { const b = bridge.blocks.find(x => x.id === planBlockId); return (b?.run?.[phaseId]?.state as PhaseState | undefined) ?? null; },
    audit: e => { /* the server records approvals itself (plan_phase_runs.approved_epoch); this is the client-side trail for debugging */ if (import.meta.env.DEV) console.debug('[lumina-gen action]', e); },
  }), [bridge, navigate]);
  if ('error' in doc) return <Fallback text="This part of the answer can’t be shown in this version of Lumina." />;
  return <GenDocumentView doc={doc} exec={exec} host={host} scope={block.id} />;
}
