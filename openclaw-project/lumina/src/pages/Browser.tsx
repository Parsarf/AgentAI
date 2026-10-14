import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../lib/api';
import { useData } from '../state/data';

export interface RunRow { request_id: string; goal: string; status: string; url: string | null; created_epoch: number }
export interface RunEvent { n: number; kind: string; [k: string]: unknown }
interface RunDetail extends RunRow { answer: string | null; reason: string | null; takeover: boolean; pending_action: { label?: string } | null; events: RunEvent[] }

const LIVE = ['queued', 'running', 'handoff'];
const LABEL: Record<string, string> = { queued: 'Starting', running: 'Working', handoff: 'Waiting for you', done: 'Done', failed: 'Stopped', cancelled: 'Cancelled', completed: 'Done' };
export const VIEW = { w: 1280, h: 800 };                        // the browser window the agent sees; clicks are mapped into it
/** Pixel position inside the shown image -> browser window coordinates. */
export const toBrowser = (clientX: number, clientY: number, r: { left: number; top: number; width: number; height: number }) =>
  ({ x: Math.round(((clientX - r.left) / r.width) * VIEW.w), y: Math.round(((clientY - r.top) / r.height) * VIEW.h) });
export const stepText = (e: RunEvent): string | null => {
  const s = (e.summary ?? e.message ?? e.label ?? e.reason) as string | undefined;
  if (e.kind === 'screenshot') return null;
  return s ? String(s) : e.kind === 'step' ? 'Acted on the page' : String(e.kind).replace(/_/g, ' ');
};

function List() {
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  useEffect(() => { api('GET', '/v1/browse').then(r => setRuns(r.runs)).catch(() => setRuns([])); }, []);
  return (
    <div className="center"><h1 className="page-title">Browser</h1>
      <section className="panel card">
        <h2>Recent browser tasks</h2>
        {runs === null && <p className="muted" role="status" style={{ marginTop: 8 }}>Loading…</p>}
        {runs && runs.length === 0 && <p className="faint" style={{ marginTop: 8 }}>Nothing yet. Ask Lumina to do something on a website and it appears here, live.</p>}
        {runs && runs.map(r => (
          <p key={r.request_id} style={{ marginTop: 10 }}><Link to={`/browser/${r.request_id}`}>{r.goal}</Link> <span className="faint">· {LABEL[r.status] ?? r.status}{r.url ? ` · ${new URL(r.url, 'http://x').hostname}` : ''}</span></p>))}
      </section></div>);
}

function Run({ id }: { id: string }) {
  const [run, setRun] = useState<RunDetail | null>(null); const [events, setEvents] = useState<RunEvent[]>([]);
  const [err, setErr] = useState(''); const [text, setText] = useState(''); const [stamp, setStamp] = useState(0);
  const since = useRef(0); const img = useRef<HTMLImageElement>(null);
  const load = useCallback(async () => {
    try {
      const r = await api<RunDetail>('GET', `/v1/browse/${id}?since=${since.current}`);
      if (r.events.length) { since.current = Math.max(since.current, ...r.events.map(e => e.n)); setEvents(old => [...old, ...r.events.filter(e => !old.some(o => o.n === e.n))]); setStamp(Date.now()); }
      setRun(r); setErr('');
    } catch (e) { setErr(e instanceof ApiError && e.status === 404 ? 'That browser task was not found.' : 'Could not load this browser task. Retrying…'); }
  }, [id]);
  useEffect(() => { since.current = 0; setEvents([]); setRun(null); void load(); }, [id, load]);
  const live = !run || LIVE.includes(run.status);
  useEffect(() => { if (!live) return; const t = setInterval(load, 2000); return () => clearInterval(t); }, [live, load]);

  const send = async (body: Record<string, unknown>) => {
    try { await api('POST', `/v1/browse/${id}/control`, body); setErr(''); await load(); }
    catch (e) { setErr(e instanceof ApiError && e.status === 409 ? 'Control is not open right now. It opens when Lumina hands the page over.' : 'That did not go through.'); }
  };
  const click = (e: React.MouseEvent) => { const r = img.current!.getBoundingClientRect(); void send({ action: 'click', ...toBrowser(e.clientX, e.clientY, r) }); };
  const shots = events.filter(e => e.kind === 'screenshot'); const last = shots[shots.length - 1];
  const steps = events.map(stepText).filter(Boolean) as string[];
  if (!run) return <div className="center"><h1 className="page-title">Browser</h1><p className={err ? 'err' : 'muted'} role={err ? 'alert' : 'status'}>{err || 'Loading…'}</p><p><Link to="/browser">All browser tasks</Link></p></div>;
  const control = run.takeover && run.status === 'handoff';
  return (
    <div className="center"><p><Link to="/browser" className="faint">← All browser tasks</Link></p>
      <h1 className="page-title">{run.goal.length > 80 ? run.goal.slice(0, 80) + '…' : run.goal}</h1>
      <section className="panel card">
        <div className="card-h"><h2>{LABEL[run.status] ?? run.status}</h2><span className="faint">{run.url ? new URL(run.url, 'http://x').hostname : ''}</span></div>
        {last
          ? <img ref={img} onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }} alt="The page Lumina is working on" src={`/v1/browse/${id}/shot/${last.file as string}?t=${stamp}`} onClick={control ? click : undefined}
              style={{ width: '100%', borderRadius: 10, cursor: control ? 'crosshair' : 'default', border: '1px solid var(--line)' }} />
          : <p className="faint">{live ? 'Waiting for the first view of the page…' : 'No screenshots were saved for this task.'}</p>}
        {run.status === 'handoff' && <p className="muted" style={{ marginTop: 12 }}>{run.pending_action?.label ? `Lumina stopped before: ${run.pending_action.label}. ` : 'Lumina stopped at a step that needs you. '}
          {control ? 'You can click on the page above or type below. Nothing is bought unless you do it yourself.' : 'The take-over window has closed.'}</p>}
        {control && (
          <form style={{ display: 'flex', gap: 8, marginTop: 10 }} onSubmit={e => { e.preventDefault(); if (text) { void send({ action: 'type', text }); setText(''); } }}>
            <label className="sr" htmlFor="tk">Text to type into the page</label>
            <input id="tk" value={text} maxLength={500} onChange={e => setText(e.target.value)} placeholder="Type into the selected field" style={{ flex: 1 }} />
            <button className="btn" type="submit">Type</button>
            <button className="btn" type="button" onClick={() => send({ action: 'key', text: 'Enter' })}>Enter</button>
            <button className="btn" type="button" onClick={() => send({ action: 'scroll', text: 'down' })}>Scroll</button>
            <button className="btn primary" type="button" onClick={() => api('POST', `/v1/browse/${id}/release`, {}).then(load)}>Return control</button>
          </form>)}
        {run.answer && <p style={{ marginTop: 12 }}>{run.answer}</p>}
        {run.reason && run.status !== 'done' && <p className="muted" style={{ marginTop: 8 }}>{run.reason}</p>}
        {err && <p className="err" role="alert" style={{ marginTop: 8 }}>{err}</p>}
      </section>
      {steps.length > 0 && <section className="panel card" style={{ marginTop: 16 }}><h2>Steps</h2><ol style={{ marginTop: 8, paddingLeft: 20 }}>{steps.map((s, n) => <li key={n} className="muted">{s}</li>)}</ol></section>}
    </div>);
}

export default function Browser() {
  const { id } = useParams(); const { app } = useData();
  if (app && !app.features.browse && !id) return (
    <div className="center"><h1 className="page-title">Browser</h1><section className="panel card"><h2>Not available yet</h2>
      <p className="muted" style={{ marginTop: 8 }}>Browser tasks (Lumina opening sites and filling carts for you) are switched off for now.</p></section></div>);
  return id ? <Run id={id} /> : <List />;
}
