import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import * as I from './Icons';
import { api, type EventRow } from '../lib/api';
import { activeTask, counts, phase, visibleEvents } from '../lib/tasks';
import { elapsed, title } from '../lib/format';
import { useData } from '../state/data';

function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (!active) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [active]);
  return now;
}

export function ActiveTask() {
  const { requests } = useData();
  const task = activeTask(requests);
  const [events, setEvents] = useState<EventRow[]>([]);
  const now = useNow(!!task);
  const id = task?.id;
  useEffect(() => {
    if (!id) { setEvents([]); return; }
    let stop = false;
    const load = async () => { try { const r = await api<{ events: EventRow[] }>('GET', `/v1/tasks/${id}/events?after=0&limit=50`); if (!stop) setEvents(visibleEvents(r.events)); } catch { /* keep last */ } };
    load(); const t = setInterval(load, 3000); return () => { stop = true; clearInterval(t); };
  }, [id]);
  return (
    <section className="panel card" aria-labelledby="at-h">
      <div className="card-h"><h2 id="at-h">Active Task</h2>{task && <span className={`pill${phase(task.state) === 'running' ? ' live' : ''}`}>{phase(task.state) === 'running' ? 'Live' : 'Queued'}</span>}</div>
      {!task ? <p className="muted">Nothing is running. Describe a task to get started.</p> : (
        <>
          <Link to={`/tasks/${task.id}`} style={{ display: 'block' }}>{title(task.message, 70)}</Link>
          <div className="bar" style={{ margin: '12px 0 6px' }} aria-hidden><i /></div>
          <p className="faint" style={{ fontSize: 12.5 }}>Working… {elapsed(task.created_epoch, now)}</p>
          <ul className="steps">
            {events.slice(-4).map((e, n, arr) => {
              const last = n === arr.length - 1;
              return <li key={`${e.created_at}-${n}`} className={last ? 'now' : 'done'}><span className="mk">{!last && <I.Check width={12} height={12} />}</span>{e.payload?.summary ?? e.kind}</li>;
            })}
            {!events.length && <li className="now"><span className="mk" />Waiting to start</li>}
          </ul>
        </>)}
    </section>);
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
  const { requests, health } = useData();
  const c = counts(requests); const total = c.running + c.queued + c.completed;
  return (
    <section className="panel card" aria-labelledby="ss-h">
      <div className="card-h"><h2 id="ss-h">System Status</h2>
        {health === 'ok' ? <span className="ok-text">● All systems operational</span> : health === 'degraded' ? <span className="warn-text">● Degraded</span> : <span className="faint">Checking…</span>}</div>
      <div className="rings"><Ring n={c.running} total={total} label="Running" color="var(--neon)" /><Ring n={c.queued} total={total} label="Queued" color="var(--warn)" /><Ring n={c.completed} total={total} label="Completed" color="var(--ok)" /></div>
    </section>);
}

export default function Rail() { return <><ActiveTask /><Today /><SystemStatus /></>; }
