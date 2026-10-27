import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { TaskRow } from './Home';
import { api, ApiError, type EventRow, type RequestRow } from '../lib/api';
import { elapsed, title } from '../lib/format';
import { controls, dotClass, outcomeLine, phase, queueLine, statusLabel, visibleEvents, type Phase } from '../lib/tasks';
import { useData } from '../state/data';

const FILTERS: { key: 'all' | Phase; label: string }[] = [
  { key: 'all', label: 'All' }, { key: 'running', label: 'Running' }, { key: 'queued', label: 'Queued' }, { key: 'completed', label: 'Completed' }, { key: 'failed', label: 'Failed' }, { key: 'cancelled', label: 'Cancelled' },
];

function Detail({ id, onClose }: { id: string; onClose(): void }) {
  const { requests, refresh } = useData();
  const row = requests.find(r => r.id === id) as RequestRow | undefined;
  const [events, setEvents] = useState<EventRow[]>([]); const [err, setErr] = useState('');
  useEffect(() => {
    let stop = false; const load = async () => { try { const r = await api<{ events: EventRow[] }>('GET', `/v1/tasks/${id}/events?after=0&limit=100`); if (!stop) setEvents(visibleEvents(r.events)); } catch { /* keep */ } };
    void load(); const t = setInterval(load, 4000); return () => { stop = true; clearInterval(t); };
  }, [id]);
  useEffect(() => { const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h); }, [onClose]);
  const cancel = async () => { try { await api('POST', `/v1/requests/${id}/cancel`, {}); await refresh(); } catch { setErr('Could not cancel this task.'); } };
  const [busy, setBusy] = useState(false);
  const hold = async (action: 'pause' | 'resume') => {
    setBusy(true); setErr('');
    try { await api('POST', `/v1/requests/${id}/${action}`, {}); await refresh(); }
    catch { setErr(action === 'pause' ? 'Could not pause this task. It may have just started.' : 'Could not resume this task.'); await refresh(); }
    setBusy(false);
  };
  const retry = async () => {
    setBusy(true); setErr('');
    try { const r = await api<{ request: { id: string } }>('POST', `/v1/requests/${id}/retry`, {}); await refresh(); nav(`/tasks/${r.request.id}`); }
    catch (e) { setErr(e instanceof ApiError && e.status === 402 ? 'Your plan allowance or task budget cannot fund another run right now.' : 'Could not retry this task.'); }
    setBusy(false);
  };
  const goal = async (action: 'resume' | 'clear') => {
    if (!conversation) return;
    setBusy(true); setErr('');
    try { await api('POST', `/v1/conversations/${conversation}/goal`, { action, key: crypto.randomUUID().replace(/-/g, '') }); await refresh(); }
    catch (e) { setErr(e instanceof ApiError && e.status === 402 ? 'Your plan allowance cannot fund another turn right now.' : action === 'resume' ? 'Could not resume the goal.' : 'Could not clear the goal.'); }
    setBusy(false);
  };
  const [conversation, setConversation] = useState<string | null>(null); const nav = useNavigate();
  useEffect(() => { let stop = false; setConversation(null); api<{ task: { conversation_id: string | null } }>('GET', `/v1/tasks/${id}`).then(r => { if (!stop) { setConversation(r.task.conversation_id); if (r.task.conversation_id) void nav(`/chat/${r.task.conversation_id}`, { replace: true }); } }).catch(() => {}); return () => { stop = true; }; }, [id, nav]);
  const p = row ? phase(row.state) : null; const can = row ? controls(row) : null;
  return (
    <div className="drawer-back" onMouseDown={onClose} role="presentation">
      <aside className="drawer" role="dialog" aria-label="Task details" onMouseDown={e => e.stopPropagation()}>
        {!row ? <p className="muted">This task is not available.</p> : (<>
          <h2>{title(row.message, 120)}</h2>
          <p className="muted"><span className={`dot-s ${dotClass(row)}`} /> {statusLabel(row)} · {p === 'running' || p === 'queued' ? `elapsed ${elapsed(row.created_epoch)}` : new Date(row.created_epoch * 1000).toLocaleString()}</p>
          {queueLine(row) && <p className="muted" role="status">{queueLine(row)}</p>}
          {outcomeLine(row) && <p className="muted" role="status">{outcomeLine(row)}</p>}
          {p === 'running' && <p className="faint" style={{ fontSize: 13 }}>A running task cannot be paused, because the assistant has no safe place to stop partway. You can cancel it.</p>}
          {row.retry_of && <p className="faint" style={{ fontSize: 13 }}>This is a retry of an earlier task.</p>}
          <div className="result" style={{ marginTop: 14 }}><small className="faint">Your request</small><br />{row.message}</div>
          {row.result && <div className="result"><small className="faint">Result</small><br />{row.result}</div>}
          <h3 style={{ marginTop: 22 }}>Activity</h3>
          <div className="log">{events.length ? events.map((e, n) => <div key={n}><time>{(e.created_at || '').slice(11, 16)} UTC</time>{e.payload?.summary ?? e.kind}</div>) : <span className="faint">No activity recorded yet.</span>}</div>
          {err && <p className="err" role="alert">{err}</p>}
          <p style={{ marginTop: 22, display: 'flex', gap: 10 }}>
            {can?.pause && <button className="btn" disabled={busy} onClick={() => hold('pause')}>Pause</button>}
            {can?.resume && <button className="btn primary" disabled={busy} onClick={() => hold('resume')}>Resume</button>}
            {can?.retry && <button className="btn primary" disabled={busy} onClick={retry}>Retry</button>}
            {can?.goalResume && <button className="btn primary" disabled={busy || !conversation} onClick={() => goal('resume')}>Resume goal</button>}
            {can?.goalResume && <button className="btn" disabled={busy || !conversation} onClick={() => goal('clear')}>Clear goal</button>}
            {can?.cancel && <button className="btn danger" onClick={cancel}>Cancel task</button>}
            <button className="btn" onClick={onClose}>Close</button>{conversation && <button className="btn primary" onClick={() => nav(`/chat/${conversation}`)}>Continue chat</button>}
          </p></>)}
      </aside>
    </div>);
}

export default function Tasks() {
  const { requests } = useData(); const { id } = useParams(); const nav = useNavigate();
  const [filter, setFilter] = useState<'all' | Phase>('all');
  const rows = requests.filter(r => filter === 'all' || phase(r.state) === filter);
  return (
    <div className="center">
      <h1 className="page-title">Tasks</h1>
      <div className="filters" role="group" aria-label="Filter tasks">{FILTERS.map(f => <button key={f.key} className="chip" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>{f.label}</button>)}</div>
      {rows.length ? <div className="tasks">{rows.map(r => <TaskRow key={r.id} r={r} onOpen={() => nav(r.conversation_id ? `/chat/${r.conversation_id}` : `/tasks/${r.id}`)} />)}</div> : <div className="empty">No tasks here yet.</div>}
      {id && <Detail id={id} onClose={() => nav('/tasks')} />}
    </div>);
}
