import { Link } from 'react-router-dom';
import * as I from './Icons';
import { isMoving, isOpen, orbFor } from '../lib/work';
import { useData } from '../state/data';
import { useTask, useWork } from '../state/work';
import Orb from './Orb';
import { Checklist, Elapsed, Status } from './work/parts';

/** What Lumina is doing right now (or the last thing it did), from the same task state every other screen reads. */
export function ActiveTask() {
  const { tasks, loaded } = useWork();
  const pick = tasks.find(t => t.phase === 'working' || t.phase === 'needs_you') ?? tasks.find(isOpen) ?? tasks[0];
  const { task, full } = useTask(pick?.id);
  const orb = task ? orbFor(task) : null;
  return <section className="panel card active-task" aria-labelledby="at-h">
    <div className="card-h"><h2 id="at-h">{task && isOpen(task) ? 'Now' : 'Latest'}</h2>{task && <Elapsed task={full ?? task} />}</div>
    {!task ? <p className="muted">{loaded ? 'Nothing is running. Describe a task to get started.' : 'Loading…'}</p> : <>
      <Link to={isOpen(task) && task.conversation_id ? `/chat/${task.conversation_id}` : `/tasks/${task.id}`} className="active-task-title">{task.title}</Link>
      <p className="orb-row active-task-current" role="status">{orb ? <Orb state={orb} size={20} /> : null}<Status task={task} size="sm" /></p>
      {task.now.length > 1 && <ul className="wk-now rail-now">{task.now.map(n => <li key={n.key}><span className="wk-pulse" aria-hidden="true" />{n.label}</li>)}</ul>}
      {task.attention && <Link className="btn primary small" to={`/tasks/${task.id}`}>See what it needs</Link>}
      {full?.checklist && <Checklist checklist={full.checklist} />}
    </>}
  </section>;
}

export function Today() {
  const { app } = useData();
  return (
    <section className="panel card" aria-labelledby="td-h">
      <div className="card-h"><h2 id="td-h">Today</h2></div>
      <p className="muted">{app?.features.connectors ? 'No events to show yet.' : 'Calendar is not connected.'}</p>
      <p className="faint" style={{ fontSize: 12.5, marginTop: 8 }}>Scheduled tasks and calendar events will appear here once a calendar and automations are available. <Link to="/calendar" style={{ color: 'var(--neon)' }}>Details</Link></p>
    </section>);
}

function Ring({ n, total, label, color }: { n: number; total: number; label: string; color: string }) {
  const p = total ? Math.round((n / total) * 100) : 0;
  return <div><div className="ring" style={{ ['--p' as any]: p, ['--c' as any]: color }} role="img" aria-label={`${n} ${label}`}><b>{n}</b></div><div className="muted">{label}</div></div>;
}

export function SystemStatus() {
  const { health } = useData(); const { tasks } = useWork();
  const running = tasks.filter(t => isMoving(t) && t.phase !== 'queued').length; const queued = tasks.filter(t => t.phase === 'queued' || t.phase === 'paused').length;
  const done = tasks.filter(t => t.outcome === 'completed').length; const total = running + queued + done;
  return (
    <section className="panel card" aria-labelledby="ss-h">
      <div className="card-h"><h2 id="ss-h">System Status</h2>
        {health === 'ok' ? <span className="ok-text">● All systems operational</span> : health === 'degraded' ? <span className="warn-text">● Degraded</span> : <span className="faint">Checking…</span>}</div>
      <div className="rings"><Ring n={running} total={total} label="Running" color="var(--neon)" /><Ring n={queued} total={total} label="Queued" color="var(--warn)" /><Ring n={done} total={total} label="Completed" color="var(--ok)" /></div>
    </section>);
}

export default function Rail() { return <><ActiveTask /><Today /><SystemStatus /></>; }
