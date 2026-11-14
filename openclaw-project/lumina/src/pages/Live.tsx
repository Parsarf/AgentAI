import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { api, ApiError } from '../lib/api';
import * as I from '../components/Icons';
import { LIVE_STATES, keyAction, type RunDetail, type RunEvent } from '../lib/live';
import { isOpen, needLine, verdict, type Approval, type TaskView } from '../lib/work';
import { useData } from '../state/data';
import { useTask, useWork } from '../state/work';
import LiveScreen from '../components/LiveScreen';
import Permission from '../components/work/Permission';
import TaskActions from '../components/work/TaskActions';
import TaskDetail from '../components/work/TaskDetail';
import { Elapsed, Status } from '../components/work/parts';

/** The browser of one task: its live picture, and the controls for stepping in. Only mounted for a task that has a browser session, so nothing probes for one. */
function BrowserStage({ task }: { task: TaskView }) {
  const id = task.id; const taskLive = isOpen(task);
  const [run, setRun] = useState<RunDetail | null>(null); const [events, setEvents] = useState<RunEvent[]>([]);
  const [err, setErr] = useState(''); const [text, setText] = useState(''); const [stamp, setStamp] = useState(0); const [showText, setShowText] = useState(false);
  const controlQueue = useRef<Promise<void>>(Promise.resolve()); const runStatus = useRef<string | undefined>(undefined);
  const since = useRef(0); const buffer = useRef(''); const flushTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const load = useCallback(async () => {
    try {
      const r = { ...await api<RunDetail>('GET', `/v1/browse/${id}?since=${since.current}`) };
      if (!taskLive && LIVE_STATES.includes(r.status)) { r.status = task.outcome === 'completed' ? 'done' : task.outcome ?? 'done'; r.takeover = false; }      // the task is over: so is its browser
      if (r.events.length) { since.current = Math.max(since.current, ...r.events.map(e => e.n)); setEvents(old => [...old, ...r.events.filter(e => !old.some(o => o.n === e.n))]); setStamp(Date.now()); }
      setRun(r); setErr('');
    } catch (e) { if (!(e instanceof ApiError && e.status === 404)) setErr('Could not refresh the browser. Retrying…'); }
  }, [id, taskLive, task.outcome]);
  useEffect(() => { since.current = 0; setEvents([]); setRun(null); setErr(''); }, [id]);
  useEffect(() => { void load(); }, [load, task.browser?.status]);

  runStatus.current = run?.status;
  const browseLive = !!run && LIVE_STATES.includes(run.status) && taskLive;
  useEffect(() => { if (!browseLive) return; const t = setInterval(load, run?.pausing || run?.status === 'paused' ? 800 : 2000); return () => clearInterval(t); }, [browseLive, load, run?.pausing, run?.status]);
  useEffect(() => () => clearTimeout(flushTimer.current), []);

  const send = useCallback((body: Record<string, unknown>) => {
    const next = controlQueue.current.then(async () => {
      try { await api('POST', `/v1/browse/${id}/control`, body); setErr(''); }
      catch (e) { setErr(e instanceof ApiError && e.status === 409
        ? (runStatus.current === 'running' ? 'Wait for Lumina to pause before taking control.' : 'The take-over window has closed, so that input was not sent.')
        : 'That input did not go through. Try again.'); throw e; }
    });
    controlQueue.current = next.catch(() => {});
    return next.catch(() => {});
  }, [id]);
  const act = async (path: 'pause' | 'resume' | 'release') => {
    try { await api('POST', `/v1/browse/${id}/${path}`, {}); setErr(''); } catch { setErr('That did not go through.'); }
    await load();
  };
  const flush = useCallback(() => { clearTimeout(flushTimer.current); const t = buffer.current; buffer.current = ''; return t ? send({ action: 'type', text: t.slice(0, 500) }) : controlQueue.current; }, [send]);
  const driving = browseLive && !!run?.takeover && (run.status === 'paused' || run.status === 'handoff');
  const onKey = (e: React.KeyboardEvent) => {
    if (!driving || (e.target as HTMLElement).tagName === 'INPUT') return;
    const a = keyAction(e); if (!a) return; e.preventDefault();
    if (a.kind === 'text') { buffer.current += a.text; clearTimeout(flushTimer.current); flushTimer.current = setTimeout(flush, 300); }
    else { void flush(); void send({ action: 'key', text: a.text }); }
  };
  const shots = events.filter(e => e.kind === 'screenshot'); const last = shots[shots.length - 1];
  const fallback = last ? `/v1/browse/${id}/shot/${last.file as string}?t=${stamp}` : null;

  return (
    <section className="ws-stage panel" aria-label="Lumina’s browser">
      {run && browseLive && run.status === 'running' && (
        <div className="ws-bar">{run.pausing
          ? <span className="muted" role="status">Pausing after Lumina’s current step…</span>
          : <><button className="btn" onClick={() => act('pause')}><I.Hand width={16} height={16} /> Take control</button><span className="faint">Lumina pauses, and you use the browser yourself.</span></>}</div>)}
      {run && driving && (
        <div className="ws-bar col" role="region" aria-label="You are in control of the browser">
          <h3>{run.needs_you || run.status !== 'paused' ? 'Lumina needs your help' : 'You are in control'}</h3>
          <p className="muted">{run.needs_you
            ? `${run.needs_you} Lumina waits, and carries on by itself when it sees the page has moved on.`
            : run.status === 'paused'
            ? 'Lumina is waiting. Click the picture to point, type to enter text, scroll with the wheel.'
            : `${run.pending_action?.label ? `Lumina stopped before: ${run.pending_action.label}. ` : 'Lumina stopped at a step that needs you. '}Finish the remaining steps in the browser below, then end the session.`}</p>
          <form className="live-type" autoComplete="off" onSubmit={e => { e.preventDefault(); if (text) { void flush(); void send({ action: 'type', text }); setText(''); } }}>
            <label className="sr" htmlFor="tk">Text to type into the page</label>
            <input id="tk" className="input" type={showText ? 'text' : 'password'} autoComplete="off" spellCheck={false} value={text} maxLength={500} onChange={e => setText(e.target.value)} placeholder="Type into the selected field" />
            <button className="btn small" type="submit" disabled={!text}>Type into page</button><label className="live-show-text"><input type="checkbox" checked={showText} onChange={e => setShowText(e.target.checked)} />Show text</label>
            <button className="btn small" type="button" onClick={() => { void flush(); void send({ action: 'key', text: 'Enter' }); }}>Enter</button>
            <button className="btn small" type="button" onClick={() => void send({ action: 'scroll', text: 'up' })}>Scroll up</button>
            <button className="btn small" type="button" onClick={() => void send({ action: 'scroll', text: 'down' })}>Scroll down</button>
            <button className="btn primary small" type="button" onClick={async () => { await flush(); await act(run.status === 'paused' ? 'resume' : 'release'); }}>{run.needs_you ? 'I’m done, continue' : run.status === 'paused' ? 'Hand back to Lumina' : 'End browser session'}</button>
          </form>
          <p className="faint small">What you type here is sent to the page and not kept. No pictures are saved while you are in control.</p>
        </div>)}
      <div className="live-stage" tabIndex={driving ? 0 : -1} onKeyDown={onKey} aria-label={driving ? 'The page you are controlling. Click to point, type to enter text.' : undefined}>
        <LiveScreen id={id} enabled={browseLive} fallback={fallback} interactive={driving} onPoint={p => { void flush(); void send({ action: 'click', ...p }); }} onWheel={dir => void send({ action: 'scroll', text: dir })} />
      </div>
      {run?.status === 'handoff' && !run.takeover && <p className="muted ws-note">The take-over window has closed.</p>}
      {!browseLive && run && <p className="faint small ws-note">{fallback ? 'The last picture saved for this task. Pictures are kept for 24 hours.' : 'This task’s browser has closed.'}</p>}
      {err && <p className="err small ws-note" role="alert">{err}</p>}
      {run?.reason && <p className="ws-note">{run.reason}</p>}
    </section>);
}

/** One task's workspace: what Lumina is doing (or did), its browser when it has one, and what it needs from you. The same view while it runs and afterwards as the record. */
export function Workspace({ id }: { id: string }) {
  const { app } = useData(); const { loaded } = useWork();
  const { task, full, rows } = useTask(id);
  if (!task) return <div className="wk-record"><Link className="wk-back" to="/tasks"><I.Chevron width={14} height={14} />Activity</Link>
    <p className={loaded ? 'err' : 'muted'} role={loaded ? 'alert' : 'status'}>{loaded ? 'That task was not found.' : 'Loading…'}</p></div>;
  const approvals = task.needs.filter((n): n is Approval => n.kind === 'approval'); const others = task.needs.filter(n => n.kind !== 'approval');
  const browser = !!full?.browser && !!app?.features.browse; const words = verdict(task);
  return (
    <div className={`ws${browser ? ' with-browser' : ''}`}>
      <header className="ws-head">
        <Link className="wk-back" to={task.conversation_id ? `/chat/${task.conversation_id}` : '/tasks'}><I.Chevron width={14} height={14} />{task.conversation_id ? 'Back to the chat' : 'Activity'}</Link>
        <h1>{task.title}</h1>
        <div className="wk-record-status"><Status task={task} /><Elapsed task={full ?? task} />{full?.browser?.host && <span>{full.browser.host}</span>}<TaskActions task={task} /></div>
        {words && <p className="wk-verdict">{words}</p>}
      </header>
      {(approvals.length > 0 || others.some(n => n.kind === 'location_permission')) && (
        <div className="ws-needs">{approvals.map(a => <Permission key={a.id} call={a} />)}{others.filter(n => n.kind === 'location_permission').map(n => <div key={n.kind} className="wk-need"><p>{needLine(n)}</p></div>)}</div>)}
      <div className="ws-grid">
        {browser && full && <BrowserStage task={full} />}
        <aside className="ws-side" aria-label="What Lumina is doing">
          {full ? <TaskDetail task={full} rows={rows} links={false} /> : <p className="wk-empty" role="status">Loading the record…</p>}
          {isOpen(task) && task.conversation_id && <p className="wk-fine">To change direction or answer a question, <Link to={`/chat/${task.conversation_id}`}>send a message in the chat</Link>. It joins the task that is running.</p>}
        </aside>
      </div>
    </div>);
}

/** /live/:id is a task's workspace. /live on its own is not a destination any more: it goes to the task that is running, or to Activity. */
export default function Live() {
  const { id } = useParams(); const { tasks, loaded } = useWork();
  if (id) return <Workspace key={id} id={id} />;
  if (!loaded) return <p className="muted" role="status">Loading…</p>;
  const current = tasks.find(t => t.phase === 'needs_you' || t.phase === 'working') ?? tasks.find(isOpen);      // what is going on or waiting on you, before anything merely queued or held
  return <Navigate to={current ? `/live/${current.id}` : '/tasks'} replace />;
}
