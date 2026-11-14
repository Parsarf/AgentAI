import { Link } from 'react-router-dom';
import type { Message } from '../../lib/conversations';
import { type Row, type TaskView } from '../../lib/work';
import AgentResponse from '../response/AgentResponse';
import { Checklist, Timeline } from './parts';

/** What Lumina holds about a task, for reading: where it went, what it saved, the assistant's own checklist, and the timeline. Used inline in the chat and on the record page. */
export default function TaskDetail({ task, rows, notes = [], links = true }: { task: TaskView; rows: Row[]; notes?: Message[]; links?: boolean }) {
  const e = task.evidence; const live = task.phase !== 'ended';
  return (
    <div className="wk-detail">
      {(e.sites.length > 0 || e.saved.length > 0 || e.files.length > 0) && (
        <dl className="wk-facts">
          {e.sites.length > 0 && <div><dt>Sites</dt><dd>{e.sites.map(s => <span key={s} className="wk-chip">{s}</span>)}</dd></div>}
          {e.saved.length > 0 && <div><dt>Saved</dt><dd>{e.saved.map(f => <span key={f.id} className="wk-chip">{f.name}</span>)}</dd></div>}
          {e.saved.length === 0 && e.files.length > 0 && <div><dt>Files</dt><dd>{e.files.map(f => <span key={f} className="wk-chip">{f}</span>)}</dd></div>}
        </dl>)}
      {task.checklist && <Checklist checklist={task.checklist} />}
      <section aria-label="What happened"><h4>What happened<small>from Lumina’s own record</small></h4><Timeline rows={rows} live={live} /></section>
      {notes.length > 0 && (
        <section aria-label="What the assistant said along the way"><h4>Said along the way</h4>
          <div className="wk-notes">{notes.map(m => <div key={m.id} className="bubble agent"><AgentResponse content={m.content} /></div>)}</div></section>)}
      {links && (task.browser || true) && (
        <p className="wk-links">
          {task.browser && <Link className="btn small" to={`/live/${task.id}`}>{task.browser.live ? 'Open the browser' : 'Open the workspace'}</Link>}
          <Link className="btn tertiary small" to={`/tasks/${task.id}`}>Full record</Link>
        </p>)}
      <p className="wk-fine">Shows searches, pages, commands and file names. File contents and secrets are never shown.</p>
    </div>);
}
