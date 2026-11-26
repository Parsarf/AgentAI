import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Message } from '../../lib/conversations';
import { browserPath, isMoving, isPrompt, needLine, orbFor, receipt, troubleLine, verdict, waitLine, type Approval, type TaskView } from '../../lib/work';
import { useTask } from '../../state/work';
import Orb from '../Orb';
import Permission from './Permission';
import Prompts from './ChangeApproval';
import TaskActions from './TaskActions';
import TaskDetail from './TaskDetail';
import { Elapsed, Status, useNow } from './parts';

/** A task as the chat shows it, under the message that asked for it. Not a card: one status line that sizes to its content, with the detail folding out below it.
 *
 *  While it works: the orb, what it is doing in the server's words, and how long it has been going. Several things at once are listed, each by name.
 *  When it needs the customer: the prompt itself, right here.
 *  When it is over: how it ended and whether that was confirmed (two different facts, worded apart), a short record of the work, and what can be done next.
 *  A plain answer that used no tools shows nothing at all: the answer is the record.
 *
 *  `eager` strips keep their full record current (the newest few); older ones read the list's line and load the record when opened. `notes` are the assistant's earlier
 *  messages for a finished request, folded into the same disclosure. */
/** One line of what the task is doing: ellipsized when the column is narrow, the whole of it in the tooltip and the accessible description. */
const Doing = ({ text }: { text: string }) => <span className="wk-doing" title={text}>{text}</span>;

export default function TaskStrip({ id, eager = true, notes = [], stopping = false }: { id: string; eager?: boolean; notes?: Message[]; stopping?: boolean }) {
  const [open, setOpen] = useState(false); const panel = useId();
  const { task, full, rows, draft } = useTask(id, eager || open);
  const now = useNow(!!task?.waiting_for && task.phase !== 'ended');
  // Another task in the same place folds its details again. Done while rendering (not in an effect), so a click that comes before effects have run is never undone.
  const [shownId, setShownId] = useState(id); if (shownId !== id) { setShownId(id); setOpen(false); }
  if (!task) return null;
  const view = stopping && task.phase !== 'ended' ? { ...task, phase: 'stopping' as const, label: 'Stopping', tone: 'pending' as const, activity: null, now: [] } : task;
  const ended = view.phase === 'ended'; const orb = orbFor(view);
  // The reply is being written when its text is arriving and no tool is running: that is known here (the text streams to this page), so it is said here.
  const writing = view.phase === 'working' && !view.activity && !!draft?.text && !draft.done;
  const label = writing ? 'Writing the answer' : view.label; const waiting = writing ? '' : waitLine(view, now);
  const approvals = view.needs.filter((n): n is Approval => n.kind === 'approval'); const others = view.needs.filter(n => !isPrompt(n));
  const prompts = view.needs.filter(isPrompt).length;
  const parts = full ? receipt(full.evidence) : view.steps ? [`${view.steps} ${view.steps === 1 ? 'step' : 'steps'}`] : [];
  const words = verdict(view); const plain = ended && view.outcome === 'completed' && view.verification !== 'unverified';
  const quiet = plain && !view.steps && !notes.length && !prompts && !view.controls.goal_resume;
  if (quiet) return null;
  const hasDetail = view.steps > 0 || notes.length > 0 || !!full?.checklist || !ended;
  return (
    <div className={`wk-strip ${view.phase} tone-${view.tone}`} data-phase={view.phase}>
      {!ended && (
        <div className="agent-thinking wk-head" role="status" aria-live="polite" aria-atomic="true" data-orb-state={orb ?? 'none'}>
          {orb ? <Orb state={orb} size={48} /> : <span className="wk-still" aria-hidden="true"><Status task={{ label: '', tone: view.tone }} /></span>}
          <span className="wk-head-text">
            <span className="agent-state" key={label}>{label}{isMoving(view) ? '…' : ''}</span>
            {waiting && <Doing text={waiting} />}
            {view.phase === 'working' && view.now.length === 1 && view.now[0].detail && <Doing text={view.now[0].detail} />}
            {view.phase === 'queued' && view.wait === 'assistant' && !waiting && <Doing text={typeof view.ahead === 'number' && view.ahead > 0 ? 'Every assistant is busy. Yours starts as soon as one is free.' : 'Getting your assistant ready.'} />}
            {view.phase === 'queued' && view.wait === 'your_task' && <Doing text="Waiting for your earlier task to finish." />}
            {view.phase === 'queued' && !view.wait && typeof view.ahead === 'number' && view.ahead > 0 && <Doing text={`${view.ahead} ${view.ahead === 1 ? 'task is' : 'tasks are'} ahead of this one`} />}
            {view.phase === 'paused' && <Doing text="It keeps its place and will not start until you resume it." />}
            {view.phase === 'stopping' && <Doing text="Waiting for the assistant to confirm it has stopped." />}
          </span>
          <Elapsed task={view} />
        </div>)}
      {view.phase === 'working' && view.now.length > 1 && (
        <ul className="wk-now" aria-label="Happening at the same time">{view.now.map(n => <li key={n.key}><span className="wk-pulse" aria-hidden="true" />{n.label}{n.detail && <code>{n.detail}</code>}</li>)}</ul>)}
      {ended && (
        <p className="wk-receipt" role="status"><Status task={view} />{parts.map(p => <span key={p} className="wk-receipt-part">{p}</span>)}</p>)}
      {ended && words && <p className={`wk-verdict${view.tone === 'bad' ? ' bad' : ''}`}>{words}</p>}
      {ended && full?.trouble && <p className="wk-verdict wk-trouble">{troubleLine(full.trouble)}</p>}
      {approvals.map(a => <Permission key={a.id} call={a} />)}
      <Prompts needs={view.needs} />
      {others.map(n => (
        <div key={n.kind} className="wk-need"><p>{needLine(n)}</p>{n.kind !== 'location_permission' && <Link className="btn primary small" to={browserPath(view)}>{n.kind === 'browser_control' ? 'Back to the browser' : 'Open the browser'}</Link>}</div>))}
      <div className="wk-foot">
        <TaskActions task={view} stop={false} />
        {hasDetail && <button type="button" className="btn tertiary small wk-more" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(o => !o)}>{open ? 'Hide details' : 'Details'}</button>}
      </div>
      {open && <div id={panel} className="wk-fold">{full ? <TaskDetail task={full as TaskView} rows={rows} notes={notes} /> : <p className="wk-empty" role="status">Loading the record…</p>}</div>}
    </div>);
}
