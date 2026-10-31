// Connects a stored document block to the real chat: Lumina's own requests and plan blocks feed the agent-native widgets, and the host actions
// call the endpoints that already exist (send a message, approve/skip/retry a phase, retry a request). Nothing here invents a capability.
import { useMemo, useRef, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { reportDiagnostic } from './diagnostics';
import type { RequestRow } from '../lib/api';
import type { Block as StoredBlock, Phase, PhaseRun } from '../lib/genui/schema';
import { useActivity } from '../lib/useActivity';
import { getAnswerStyle } from '../lib/answerStyle';
import { parseDocument } from './protocol';
import { GenDocumentView } from './components/Renderer';
import type { ExecutionProvider, Host, PlanInfo, RequestInfo } from './components/context';
import type { PhaseState } from './actions';
import PlanBlock from '../components/genui/PlanBlock';
import { planSpec } from '../lib/genui/schema';
import { Fallback } from './components/Renderer';

export interface Bridge { conversationId: string; tasks: RequestRow[]; blocks: StoredBlock[]; reload(): void }

function planOf(b: StoredBlock | undefined): PlanInfo | undefined {
  if (!b || b.kind !== 'task_plan') return undefined;
  const spec = b.spec as { title?: string; phases?: Phase[] }; const phases = (b.state?.plan?.phases ?? spec.phases ?? []) as Phase[];
  const run = Object.fromEntries(Object.entries((b.run ?? {}) as Record<string, PhaseRun>).map(([k, v]) => [k, { state: v.state as PhaseState, summary: v.summary }]));
  return { id: b.id, title: spec.title ?? 'Plan', phases: phases.filter(p => p.enabled !== false).map(p => ({ id: p.id, title: p.title, description: p.description, dependsOn: p.dependsOn })), run, run_status: b.run_status };
}

export default function GenBlock({ block, bridge }: { block: StoredBlock; bridge: Bridge }) {
  const navigate = useNavigate();
  const revision = useRef((block as any).state_revision ?? 1);
  const version = useRef(block.version); if (version.current !== block.version) revision.current = (block as any).state_revision ?? 1; version.current = block.version;
  const doc = useMemo(() => parseDocument(block.spec), [block.spec]);
  useEffect(() => { if ('error' in doc) reportDiagnostic(block.id, block.version, 'invalid_document', 'validation'); }, [doc, block.id, block.version]);
  const exec = useMemo<ExecutionProvider>(() => ({
    request: (id): RequestInfo | undefined => { const r = bridge.tasks.find(t => t.id === id); return r && { id: r.id, state: r.state, result: r.result, message: r.message, outcome: r.outcome, outcome_note: r.outcome_note, created_epoch: r.created_epoch }; },
    planEditor: id => { const b = bridge.blocks.find(b => b.id === id && b.kind === 'task_plan'); const parsed = planSpec.safeParse(b?.spec); return b && parsed.success ? <PlanBlock block={b} original={parsed.data} onChanged={bridge.reload} /> : null; },
    plan: id => planOf(bridge.blocks.find(b => b.id === id)),
    useSnapshot: useTaskSnapshot,
    useActivity: (requestId, live) => useActivity(requestId, live),       // eslint-disable-line react-hooks/rules-of-hooks
  }), [bridge.tasks, bridge.blocks]);
  const host = useMemo<Host>(() => ({
    artifactVersion: block.version,
    initialState: block.state as any,
    loadState: async () => {
      const response = await api('GET', `/v1/conversations/${bridge.conversationId}/blocks`, undefined, { timeoutMs: 15000 });
      const current = response.blocks.find((b: StoredBlock) => b.id === block.id);
      if (!current) throw new Error('artifact unavailable');
      if (current.version === block.version) revision.current = current.state_revision ?? 1;
      return { version: current.version, state: current.state ?? {} };
    },
    diagnostic: (kind, category) => reportDiagnostic(block.id, block.version, kind, category),
    saveState: async state => { const r = await api('POST', `/v1/genui/artifacts/${block.id}/state`, { version: block.version, state_revision: revision.current, state }, { timeoutMs: 15000 }); revision.current = r.state_revision; },
    submit: async (node_id, action_id, values, id) => { const r = await api('POST', `/v1/genui/artifacts/${block.id}/events`, { id, node_id, action_id, values, version: block.version }, { timeoutMs: 20000 }); if (r.artifact_state_revision) revision.current = r.artifact_state_revision; bridge.reload(); },
    send: async (message, key) => { await api('POST', `/v1/conversations/${bridge.conversationId}/send`, { message, key, mode: 'text', ui: getAnswerStyle() }); bridge.reload(); },
    phase: async (planBlockId, phaseId, verb) => { await api('POST', `/v1/blocks/${planBlockId}/phase`, { phase_id: phaseId, action: verb }); bridge.reload(); },
    retryRequest: async requestId => { await api('POST', `/v1/requests/${requestId}/retry`, {}); bridge.reload(); },
    navigate: path => navigate(path),
    download: async path => { window.location.assign(`/v1/genui/artifacts/${block.id}/asset?path=${encodeURIComponent(path)}&download=1`); },
    assetUrl: ref => ref.startsWith('file:') ? `/v1/genui/artifacts/${block.id}/asset?path=${encodeURIComponent(ref.slice(5))}` : null,
    phaseState: (planBlockId, phaseId) => { const b = bridge.blocks.find(x => x.id === planBlockId); return (b?.run?.[phaseId]?.state as PhaseState | undefined) ?? null; },
    audit: e => { /* the server records approvals itself (plan_phase_runs.approved_epoch); this is the client-side trail for debugging */ if (import.meta.env.DEV) console.debug('[lumina-gen action]', e); },
  }), [bridge, navigate]);
  if ('error' in doc) return <Fallback text="This part of the answer can’t be shown in this version of Lumina." />;
  return <GenDocumentView key={`${block.id}:${block.version}`} doc={doc} exec={exec} host={host} scope={block.id} onDiagnostic={() => reportDiagnostic(block.id, block.version, 'render_failed', 'renderer')} />;
}

function useTaskSnapshot(id: string, live: boolean) {
  const [value, set] = useState<any>({});
  useEffect(() => {
    let stopped = false; let timer: ReturnType<typeof setTimeout>;
    const load = async () => { try { const r = await api('GET', `/v1/requests/${id}`); if (!stopped) set(r.task); } catch { if (!stopped) set({ error: 'Could not load task usage.' }); } if (!stopped && live) timer = setTimeout(load, 3000); };
    set({}); void load(); return () => { stopped = true; clearTimeout(timer); };
  }, [id, live]);
  return value;
}
