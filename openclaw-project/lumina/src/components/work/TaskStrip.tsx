import { useEffect, useId, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Message } from '../../lib/conversations';
import { isMoving, needLine, orbFor, receipt, verdict, type Approval, type TaskView } from '../../lib/work';
import { useTask } from '../../state/work';
import Orb from '../Orb';
import Permission from './Permission';
import TaskActions from './TaskActions';
import TaskDetail from './TaskDetail';
import { Elapsed, Status } from './parts';

/** A task as the chat shows it, under the message that asked for it. Not a card: one status line that sizes to its content, with the detail folding out below it.
 *
 *  While it works: the orb, what it is doing in the server's words, and how long it has been going. Several things at once are listed, each by name.
 *  When it needs the customer: the prompt itself, right here.
 *  When it is over: how it ended and whether that was confirmed (two different facts, worded apart), a short record of the work, and what can be done next.
 *  A plain answer that used no tools shows nothing at all: the answer is the record.
 *
 *  `eager` strips keep their full record current (the newest few); older ones read the list's line and load the record when opened. `notes` are the assistant's earlier
 *  messages for a finished request, folded into the same disclosure. */
export default function TaskStrip({ id, eager = true, notes = [], stopping = false }: { id: string; eager?: boolean; notes?: Message[]; stopping?: boolean }) {
  const [open, setOpen] = useState(false); const panel = useId();
  const { task, full, rows } = useTask(id, eager || open);
  useEffect(() => { setOpen(false); }, [id]);
  if (!task) return null;
  const view = stopping && task.phase !== 'ended' ? { ...task, phase: 'stopping' as const, label: 'Stopping', tone: 'pending' as const, activity: null, now: [] } : task;
  const ended = view.phase === 'ended'; const orb = orbFor(view);
  const approvals = view.needs.filter((n): n is Approval => n.kind === 'approval'); const others = view.needs.filter(n => n.kind !== 'approval');
  const parts = full ? receipt(full.evidence) : view.steps ? [`${view.steps} ${view.steps === 1 ? 'step' : 'steps'}`] : [];
  const words = verdict(view); const plain = ended && view.outcome === 'completed' && view.verification !== 'unverified';
  const quiet = plain && !view.steps && !notes.length && !approvals.length && !view.controls.goal_resume;
  if (quiet) return null;
  const hasDetail = view.steps > 0 || notes.length > 0 || !!full?.checklist || !ended;
  return (
    <div className={`wk-strip ${view.phase} tone-${view.tone}`} data-phase={view.phase}>
      {!ended && (
        <div className="agent-thinking wk-head" role="status" aria-live="polite" aria-atomic="true" data-orb-state={orb ?? 'none'}>
          {orb ? <Orb state={orb} size={48} /> : <span className="wk-still" aria-hidden="true"><Status task={{ label: '', tone: view.tone }} /></span>}
          <span className="wk-head-text">
            <span className="agent-state" key={view.label}>{view.label}{isMoving(view) ? '…' : ''}</span>
            {view.phase === 'working' && view.now.length === 1 && view.now[0].detail && <span className="wk-doing">{view.now[0].detail}</span>}
            {view.phase === 'queued' && typeof view.ahead === 'number' && view.ahead > 0 && <span className="wk-doing">{view.ahead} {view.ahead === 1 ? 'task is' : 'tasks are'} ahead of this one</span>}
            {view.phase === 'paused' && <span className="wk-doing">It keeps its place and will not start until you resume it.</span>}
            {view.phase === 'stopping' && <span className="wk-doing">Waiting for the assistant to confirm it has stopped.</span>}
          </span>
          <Elapsed task={view} />
        </div>)}
      {view.phase === 'working' && view.now.length > 1 && (
        <ul className="wk-now" aria-label="Happening at the same time">{view.now.map(n => <li key={n.key}><span className="wk-pulse" aria-hidden="true" />{n.label}{n.detail && <code>{n.detail}</code>}</li>)}</ul>)}
      {ended && (
        <p className="wk-receipt" role="status"><Status task={view} />{parts.map(p => <span key={p} className="wk-receipt-part">{p}</span>)}</p>)}
      {ended && words && <p className={`wk-verdict${view.tone === 'bad' ? ' bad' : ''}`}>{words}</p>}
      {approvals.map(a => <Permission key={a.id} call={a} />)}
      {others.map(n => (
        <div key={n.kind} className="wk-need"><p>{needLine(n)}</p>{n.kind !== 'location_permission' && <Link className="btn primary small" to={`/live/${view.id}`}>{n.kind === 'browser_control' ? 'Back to the browser' : 'Open the browser'}</Link>}</div>))}
      <div className="wk-foot">
        <TaskActions task={view} stop={false} />
        {hasDetail && <button type="button" className="btn tertiary small wk-more" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(o => !o)}>{open ? 'Hide details' : 'Details'}</button>}
      </div>
      {open && <div id={panel} className="wk-fold">{full ? <TaskDetail task={full as TaskView} rows={rows} notes={notes} /> : <p className="wk-empty" role="status">Loading the record…</p>}</div>}
    </div>);
}
