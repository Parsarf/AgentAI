import { useEffect, useState } from 'react';
import * as I from '../Icons';
import { elapsed } from '../../lib/format';
import { duration, grouped, type Phase, type Row, type Step, type TaskSummary, type TaskView, type Tone } from '../../lib/work';

/** A clock that only runs while something on screen is counting. The time shown is real elapsed time since the task was created, never an estimate. */
export function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (!active) return; setNow(Date.now()); const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [active]);
  return now;
}

const TONE_ICON: Record<Tone, (p: { width: number; height: number }) => React.ReactNode> = {
  ok: p => <I.Check {...p} />, unsure: p => <I.Dash {...p} />, bad: p => <I.Alert {...p} />, attention: p => <I.Hand {...p} />,
  muted: p => <I.Stop {...p} />, pending: p => <I.Clock {...p} />, live: () => <span className="wk-pulse" />,
};
/** The status of a task: a mark and the server's own words. Never colour alone: every tone has its own shape. */
export function Status({ task, size = 'md' }: { task: Pick<TaskSummary, 'label' | 'tone'>; size?: 'sm' | 'md' }) {
  const px = size === 'sm' ? 12 : 14;
  return <span className={`wk-status ${task.tone} ${size}`}><span className="wk-mark" aria-hidden="true">{TONE_ICON[task.tone]({ width: px, height: px })}</span>{task.label}</span>;
}

const ROW_ICON: Record<string, typeof I.Search> = { search: I.Search, read: I.Page, browse: I.Browser, command: I.Terminal, file: I.Doc, subagent: I.Helper, note: I.Note, error: I.Alert, approval: I.Key, other: I.Cube };
export const RowIcon = ({ category }: { category: string }) => { const Icon = ROW_ICON[category] ?? I.Cube; return <Icon width={16} height={16} />; };

const ROW_END: Partial<Record<Row['status'], string>> = { failed: 'did not work', waiting: 'waiting for you', approved: 'you allowed it', declined: 'you declined', expired: 'not answered in time' };
function took(r: Row): string { return r.kind === 'tool' && r.ended_at && r.ended_at - r.at >= 1500 ? duration((r.ended_at - r.at) / 1000) : ''; }

function TimelineRow({ r, live }: { r: Row; live: boolean }) {
  const running = live && r.status === 'running';
  return (
    <li className={`wk-row ${r.kind} ${r.status}`}>
      <span className="wk-row-ico" aria-hidden="true"><RowIcon category={r.category} /></span>
      <div className="wk-row-body">
        <p className="wk-row-label">{r.label}{running && <span className="wk-running"><span className="wk-pulse" aria-hidden="true" />in progress</span>}
          {!running && r.status === 'running' && <span className="wk-row-end">no result was recorded</span>}
          {ROW_END[r.status] && <span className="wk-row-end">{ROW_END[r.status]}</span>}{took(r) && <span className="wk-row-took">{took(r)}</span>}</p>
        {r.detail && <code className="wk-row-detail">{r.detail}</code>}
        {r.output && <details className="wk-row-out"><summary>Output</summary><pre tabIndex={0}>{r.output}</pre></details>}
      </div>
    </li>);
}
/** What happened, in the order it started. Calls that ran at the same time are bracketed together, each with its own state. */
export function Timeline({ rows, live, empty }: { rows: Row[]; live: boolean; empty?: string }) {
  if (!rows.length) return <p className="wk-empty">{empty ?? (live ? 'Nothing to show yet. Steps appear here as they happen.' : 'No tool use was recorded for this task.')}</p>;
  return (
    <ol className="wk-timeline">
      {grouped(rows).map(g => g.rows.length > 1
        ? <li key={g.key} className="wk-together"><p className="wk-together-h">{g.rows.length} at the same time</p><ol>{g.rows.map(r => <TimelineRow key={r.key} r={r} live={live} />)}</ol></li>
        : <TimelineRow key={g.key} r={g.rows[0]} live={live} />)}
    </ol>);
}

const STEP_WORD: Record<Step['status'], string> = { pending: 'Next', running: 'In progress', done: 'Done', blocked: 'Blocked', failed: 'Failed', skipped: 'Skipped', stopped: 'Stopped', unreported: 'Not reported as finished' };
/** The assistant's own checklist. It is the assistant's report of its plan, not something Lumina checked, and it says so. */
export function Checklist({ checklist }: { checklist: NonNullable<TaskView['checklist']> }) {
  const steps = checklist.mode === 'direct' ? checklist.steps.slice(-6) : checklist.steps;
  return (
    <section className="wk-checklist" aria-label="The assistant’s own checklist">
      <h4>{checklist.mode === 'plan' ? 'Plan' : 'Steps'}<small>as reported by the assistant</small></h4>
      <ol>{steps.map(s => (
        <li key={s.id} className={s.status}>
          <span className="wk-step-mark" aria-hidden="true">{s.status === 'done' && <I.Check width={11} height={11} />}</span>
          <div><span className="wk-step-title">{s.title}</span><span className="wk-step-status">{STEP_WORD[s.status]}</span>
            {s.result ? <p>{s.result}</p> : s.checkpoint && <p>Done when: {s.checkpoint}</p>}</div>
        </li>))}</ol>
    </section>);
}

/** How long it has been going (a live count) or how long it took. */
export function Elapsed({ task }: { task: TaskSummary | TaskView }) {
  const counting = task.phase !== 'ended' && task.phase !== 'paused';
  const now = useNow(counting);
  if (counting) return <time className="wk-elapsed">{elapsed(task.created_epoch, now)}</time>;
  const took = 'evidence' in task ? task.evidence.duration_s : null;
  return took ? <time className="wk-elapsed">{duration(took)}</time> : null;
}

export const phaseBusy = (phase: Phase) => phase !== 'ended' && phase !== 'paused' && phase !== 'needs_you';
