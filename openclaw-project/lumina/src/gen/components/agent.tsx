import { Emojified } from '../../components/Emoji';
import { useEffect, useState } from 'react';
import type { Tone } from '../../lib/work';
import { cx, type P } from './types';
import { useGen, type StepRow } from './context';
import { ActionButton, StatusPill } from './cards';
import { Missing } from './data';
import { Prose } from './text';

/** Shown on every agent-native block when its data is sample data, so a fixture can never pass for a real run. */
function Provenance() { const g = useGen(); return g.exec.label ? <p className="gen-fixture"><Emojified text={g.exec.label} /></p> : null; }
const ICON: Record<string, string> = { search: '⌕', read: '↗', command: '›_', file: '▤', browse: '◰', other: '•', note: '·', error: '!', approval: '?', limit: '·' };
/** The shared status line's tone as this pill's colour. A task that needs the customer, ended partly or could not be confirmed is never shown as plain success. */
const PILL: Record<Tone, 'success' | 'error' | 'active' | 'idle' | 'warning'> = { ok: 'success', bad: 'error', live: 'active', pending: 'active', attention: 'warning', unsure: 'warning', muted: 'idle' };
/** How a task stands: the server's own line where there is live task state, and the raw request state in the few words below only where there is none (fixtures). */
function useStanding(requestId: string, state: string): { status: 'success' | 'error' | 'active' | 'idle' | 'warning'; label: string } {
  const shared = useGen().exec.status?.(requestId);
  return shared ? { status: PILL[shared.tone] ?? 'idle', label: shared.label } : { status: toStatus(state), label: stateWord(state) };
}
const stateWord = (s: string) => (s === 'running' ? 'Working' : s === 'queued' ? 'Queued' : s === 'completed' || s === 'succeeded' || s === 'done' ? 'Done' : s === 'failed' || s === 'error' ? 'Failed' : s === 'cancelled' ? 'Stopped' : s);
const toStatus = (s: string) => (['completed', 'succeeded', 'done'].includes(s) ? 'success' : ['failed', 'error'].includes(s) ? 'error' : ['running', 'queued'].includes(s) ? 'active' : 'idle') as 'success' | 'error' | 'active' | 'idle';

export function AgentStatus({ block }: P<'agent_status'>) {
  const g = useGen(); const r = g.exec.request(block.props.requestId); const standing = useStanding(block.props.requestId, r?.state ?? '');
  if (!r) return <Missing what="That task is not part of this chat." />;
  return <div className="gen-status" role="status"><StatusPill status={standing.status} label={standing.label} /><div><strong>{r.message ? r.message.slice(0, 120) : 'Task'}</strong>{r.outcome_note && <p className="faint">{r.outcome_note}</p>}</div><Provenance /></div>;
}
const STEP_WORD: Record<string, string> = { failed: 'did not work', running: 'in progress', waiting: 'waiting for you', declined: 'you declined', expired: 'not answered in time' };
function Rows({ rows, expanded }: { rows: StepRow[]; expanded?: boolean }) {
  if (!rows.length) return <Missing what="No steps recorded yet." />;
  return <ol className="gen-exec">{rows.map(r => <li key={r.key} className={r.status}><span className="ico" aria-hidden>{ICON[r.category] ?? '•'}</span>
    <div><strong><Emojified text={r.label} /></strong>{STEP_WORD[r.status] ? <span className="faint"> · {STEP_WORD[r.status]}</span> : <span className="sr"> ({r.status})</span>}
      {r.detail && <p className="faint"><Emojified text={r.detail} /></p>}{r.why && <p className="faint">{r.why}</p>}
      {!!r.steps?.length && <ol className="gen-exec-steps" aria-label="Steps in the browser">{r.steps.map((s, i) => <li key={`${s.at}-${i}`} className={s.status}>{s.label}</li>)}</ol>}
      {expanded && r.output && <pre tabIndex={0} aria-label="Output">{r.output}</pre>}</div></li>)}</ol>;
}
export function ExecutionTimeline({ block }: P<'execution_timeline'>) {
  const g = useGen(); const r = g.exec.request(block.props.requestId);
  const live = block.props.live && !!r && ['queued', 'running'].includes(r.state);
  const { rows, err } = g.exec.useActivity(block.props.requestId, live); const standing = useStanding(block.props.requestId, r?.state ?? '');
  if (!r) return <Missing what="That task is not part of this chat." />;
  return <div className="gen-agent"><div className="gen-agent-h"><StatusPill status={standing.status} label={standing.label} />{live && <span className="faint" aria-live="polite">Updating…</span>}</div>
    <Rows rows={rows.slice(-block.props.maxItems)} expanded={block.variant === 'expanded'} />{err && <p className="gen-err" role="status">{err}</p>}<Provenance /></div>;
}
export function ToolCallInspector({ block }: P<'tool_call_inspector'>) {
  const g = useGen(); const r = g.exec.request(block.props.requestId); const { rows } = g.exec.useActivity(block.props.requestId, false);
  if (!r) return <Missing what="That task is not part of this chat." />;
  const calls = rows.filter(x => x.category !== 'note' && x.category !== 'error');
  return <div className="gen-agent">{calls.length ? <Rows rows={calls} expanded /> : <Missing what="No tool calls recorded." />}<Provenance /></div>;
}
export function PlanViewer({ block }: P<'plan_viewer'>) {
  const g = useGen(); const plan = g.exec.plan(block.props.planBlockId);
  if (!plan) return <Missing what="That plan is not part of this chat." />;
  return <div className="gen-agent"><strong><Emojified text={plan.title} /></strong><ol className="gen-exec">{plan.phases.map(p => { const st = plan.run[p.id]?.state ?? 'pending';
    return <li key={p.id} className={st}><span className="ico" aria-hidden>{st === 'completed' ? '✓' : st === 'failed' ? '!' : st === 'running' ? '…' : '○'}</span><div><strong><Emojified text={p.title} /></strong><span className="sr"> ({st.replace('_', ' ')})</span>{plan.run[p.id]?.summary && block.variant === 'expanded' && <p className="faint">{plan.run[p.id].summary}</p>}</div></li>; })}</ol><Provenance /></div>;
}
/** pending, approved, rejected (skipped), failed, expired (the plan stopped before this step was decided). Only `pending` offers buttons. */
export function approvalView(state: string | undefined, runStatus?: string): { label: string; tone: 'idle' | 'active' | 'success' | 'warning' | 'error'; can: boolean } {
  if (!state) return { label: 'Not available', tone: 'idle', can: false };
  if (state === 'awaiting_approval') return { label: 'Waiting for you', tone: 'warning', can: true };
  if (state === 'cancelled' || runStatus === 'stopped') return state === 'completed' ? { label: 'Approved', tone: 'success', can: false } : { label: 'Expired: the plan was stopped', tone: 'idle', can: false };
  if (state === 'skipped') return { label: 'Skipped', tone: 'idle', can: false };
  if (state === 'failed') return { label: 'Failed', tone: 'error', can: false };
  if (state === 'completed') return { label: 'Approved and done', tone: 'success', can: false };
  if (state === 'running') return { label: 'Approved, running', tone: 'active', can: false };
  return { label: 'Not reached yet', tone: 'idle', can: false };
}
export function ApprovalRequest({ block }: P<'approval_request'>) {
  const g = useGen(); const { planBlockId, phaseId, reason, expiresEpoch } = block.props; const plan = g.exec.plan(planBlockId);
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { if (!expiresEpoch) return; const id = window.setTimeout(() => setNow(Date.now() / 1000), Math.max(0, Math.min(2147483647, (expiresEpoch - Date.now() / 1000) * 1000))); return () => clearTimeout(id); }, [expiresEpoch]);
  const phase = plan?.phases.find(p => p.id === phaseId);
  if (!plan || !phase) return <Missing what="That step is not part of this chat." />;
  const v = expiresEpoch && now >= expiresEpoch ? { label: 'Expired', tone: 'idle' as const, can: false } : approvalView(plan.run[phaseId]?.state, plan.run_status);
  return <div className="gen-approval" role="group" aria-label={`Approval: ${phase.title}`}>
    <div className="gen-agent-h"><strong><Emojified text={phase.title} /></strong><StatusPill status={v.tone} label={v.label} /></div>
    {phase.description && <p><Emojified text={phase.description} /></p>}{reason && <p className="faint">Why: {reason}</p>}
    {v.can && <div className="gen-row"><ActionButton style="primary" label="Approve" action={{ kind: 'agent.approve', planBlockId, phaseId }} /><ActionButton style="ghost" label="Skip this step" action={{ kind: 'agent.deny', planBlockId, phaseId }} /></div>}<Provenance /></div>;
}
export function ErrorRetry({ block }: P<'error_retry'>) {
  const g = useGen(); const { requestId, planBlockId, phaseId } = block.props;
  if (planBlockId && phaseId) {
    const plan = g.exec.plan(planBlockId); const st = plan?.run[phaseId]?.state;
    if (!plan) return <Missing what="That plan is not part of this chat." />;
    return <div className={cx('gen-error', st !== 'failed' && 'calm')} role="group" aria-label="Failed step"><StatusPill status={st === 'failed' ? 'error' : 'idle'} label={st === 'failed' ? 'Failed' : (st ?? 'unknown').replace('_', ' ')} /><span>{plan.phases.find(p => p.id === phaseId)?.title}</span>
      {plan.run[phaseId]?.summary && st === 'failed' && <p className="faint">{plan.run[phaseId].summary}</p>}{st === 'failed' && <ActionButton label="Retry this step" action={{ kind: 'agent.retry', planBlockId, phaseId }} />}</div>;
  }
  const r = requestId ? g.exec.request(requestId) : undefined;
  if (!r) return <Missing what="That task is not part of this chat." />;
  const failed = toStatus(r.state) === 'error';
  return <div className={cx('gen-error', !failed && 'calm')} role="group" aria-label="Task result"><StatusPill status={toStatus(r.state)} label={stateWord(r.state)} />{failed && <>{r.outcome_note && <p className="faint">{r.outcome_note}</p>}<ActionButton label="Retry" action={{ kind: 'agent.retry', requestId: r.id }} /></>}<Provenance /></div>;
}
export function CompletionSummary({ block }: P<'completion_summary'>) {
  const g = useGen(); const r = g.exec.request(block.props.requestId);
  if (!r) return <Missing what="That task is not part of this chat." />;
  if (!['completed', 'succeeded', 'done', 'failed', 'error', 'cancelled'].includes(r.state)) return <Missing what="This task has not finished yet." />;
  return <div className="gen-agent"><div className="gen-agent-h"><StatusPill status={toStatus(r.state)} label={stateWord(r.state)} /></div>{r.result ? <Prose>{r.result.slice(0, 4000)}</Prose> : <p className="faint">No result text was recorded.</p>}<Provenance /></div>;
}
