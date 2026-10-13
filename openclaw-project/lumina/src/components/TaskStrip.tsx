import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useData } from '../state/data';
import { api, type EventRow } from '../lib/api';
import { elapsed } from '../lib/format';
import { isActive, phase, visibleEvents } from '../lib/tasks';

export interface ThreadTask { id: string; state: string; created_epoch: number; result?: string | null }

/** Shown inline under the message that started a task: what it is doing, for how long, and a way to stop it. */
export default function TaskStrip({ task, onCancel, onActivity }: { task: ThreadTask; onCancel(): void; onActivity?(): void }) {
  const { app } = useData(); const [browsing, setBrowsing] = useState(false);
  const active = isActive(task.state);
  useEffect(() => { if (active && app?.features.browse) api('GET', `/v1/browse/${task.id}`).then(() => setBrowsing(true)).catch(() => setBrowsing(false)); }, [task.id, active, app?.features.browse]); const [events, setEvents] = useState<EventRow[]>([]); const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t);
  }, [active]);
  useEffect(() => {
    if (!active) return; let stop = false;
    const load = async () => { try { const r = await api<{ events: EventRow[] }>('GET', `/v1/tasks/${task.id}/events?after=0&limit=50`); if (!stop) setEvents(visibleEvents(r.events)); } catch { /* keep last */ } };
    load(); const t = setInterval(load, 3000); return () => { stop = true; clearInterval(t); };
  }, [task.id, active]);
  const p = phase(task.state);
  if (p === 'completed') return null;
  if (p === 'failed' || p === 'cancelled') return <div className="taskstrip bad" role="status">{p === 'failed' ? 'This task failed. Nothing more is running.' : 'Cancelled.'}</div>;
  return (
    <div className="taskstrip" role="status" aria-live="polite">
      <div className="ts-head"><span className="dot-s running" /><b>{p === 'queued' ? 'Queued' : 'Working'}</b><span className="faint">· {elapsed(task.created_epoch, now)}</span>
        {onActivity && <button className="btn small" onClick={onActivity}>See activity</button>}{browsing && <Link className="btn small" to={`/browser/${task.id}`}>Watch live</Link>}<button className="btn small danger" onClick={onCancel}>Stop</button></div>
      {events.length > 0 && <ul className="ts-steps">{events.slice(-3).map((e, n) => { const q = e.payload as { summary?: string; label?: string; detail?: string } | undefined; return <li key={n}>{q?.summary ?? (q?.label ? `${q.label}${q.detail ? ': ' + q.detail.slice(0, 60) : ''}` : e.kind)}</li>; })}</ul>}
      {p === 'queued' && <p className="faint small">Waiting for your assistant to start. The first message after a pause takes about 30–40 seconds.</p>}
    </div>);
}
