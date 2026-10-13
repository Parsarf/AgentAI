import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../lib/api';
import { ICON } from '../lib/activity';
import { ago, elapsed, title as clip } from '../lib/format';
import { LIVE_STATES, MODE_LABEL, STATE_LABEL, followMode, keyAction, modesFor, type Mode, type RunDetail, type RunEvent } from '../lib/live';
import { isActive, phase } from '../lib/tasks';
import { useActivity } from '../lib/useActivity';
import { useData } from '../state/data';
import LiveScreen from '../components/LiveScreen';
import { LiveFiles, LiveTerminal } from '../components/LiveTerminal';


/** Everything Lumina is doing, in one place: its browser, its terminal and its files, live. Hop in on a browser task at any time. */
function LiveList() {
  const { requests } = useData();
  const rows = [...requests].sort((a, b) => Number(isActive(b.state)) - Number(isActive(a.state)) || b.created_epoch - a.created_epoch).slice(0, 30);
  return (
    <div className="livepage"><h1 className="page-title">Live view</h1>
      <section className="panel card">
        <h2>Watch Lumina work</h2>
        {rows.length === 0 && <p className="faint" style={{ marginTop: 8 }}>Nothing yet. Ask Lumina to do something and you can watch it here, live.</p>}
        {rows.map(r => {
          const p = phase(r.state); const on = isActive(r.state);
          return (
            <p key={r.id} className="live-row"><Link to={`/live/${r.id}`}>{clip(r.message, 90)}</Link>
              <span className="faint"> · {on ? (p === 'queued' ? 'Queued' : 'Working now') : p === 'completed' ? 'Done' : p === 'failed' ? 'Stopped' : 'Cancelled'} · {ago(r.created_epoch)}</span>{on && <span className="pill live" style={{ marginLeft: 8 }}>Live</span>}</p>);
        })}
      </section></div>);
}

function LiveRun({ id }: { id: string }) {
  const { app, requests } = useData();
  const request = requests.find(r => r.id === id);
  const [run, setRun] = useState<RunDetail | null>(null); const [isBrowse, setIsBrowse] = useState<boolean | null>(app?.features.browse ? null : false);
  const [events, setEvents] = useState<RunEvent[]>([]); const [err, setErr] = useState(''); const [text, setText] = useState(''); const [stamp, setStamp] = useState(0);
  const [pinned, setPinned] = useState<Mode | null>(null); const [now, setNow] = useState(Date.now());
  const since = useRef(0); const buffer = useRef(''); const flushTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const load = useCallback(async () => {
    if (isBrowse === false) return;
    try {
      const r = await api<RunDetail>('GET', `/v1/browse/${id}?since=${since.current}`);
      if (r.events.length) { since.current = Math.max(since.current, ...r.events.map(e => e.n)); setEvents(old => [...old, ...r.events.filter(e => !old.some(o => o.n === e.n))]); setStamp(Date.now()); }
      setRun(r); setIsBrowse(true); setErr('');
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setIsBrowse(false);          // not a browser task: terminal and files only
      else setErr('Could not refresh. Retrying…');
    }
  }, [id, isBrowse]);
  useEffect(() => { since.current = 0; setEvents([]); setRun(null); setPinned(null); setErr(''); setIsBrowse(app?.features.browse ? null : false); }, [id, app?.features.browse]);
  useEffect(() => { load(); }, [load]);

  const browseLive = !!run && LIVE_STATES.includes(run.status);
  const taskLive = isBrowse ? browseLive : !!request && isActive(request.state);
  const { rows, err: actErr } = useActivity(id, taskLive);
  useEffect(() => { if (isBrowse === false || !browseLive) return; const t = setInterval(load, run?.pausing || run?.status === 'paused' ? 800 : 2000); return () => clearInterval(t); }, [isBrowse, browseLive, load, run?.pausing, run?.status]);
  useEffect(() => { if (!taskLive) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [taskLive]);
  useEffect(() => () => clearTimeout(flushTimer.current), []);

  const browse = isBrowse === true;
  const modes = modesFor(browse); const followed = followMode(rows, browse);
  const mode: Mode = pinned && modes.includes(pinned) ? pinned : followed;

  const send = useCallback(async (body: Record<string, unknown>) => {
    try { await api('POST', `/v1/browse/${id}/control`, body); setErr(''); }
    catch (e) { setErr(e instanceof ApiError && e.status === 409 ? 'You do not have the wheel right now. Press “Hop in” and wait for Lumina to pause.' : 'That did not go through.'); }
  }, [id]);
  const act = async (path: 'pause' | 'resume' | 'release') => {
    try { await api('POST', `/v1/browse/${id}/${path}`, {}); setErr(''); } catch { setErr('That did not go through.'); }
    await load();
  };
  const flush = useCallback(() => { clearTimeout(flushTimer.current); const t = buffer.current; buffer.current = ''; if (t) send({ action: 'type', text: t.slice(0, 500) }); }, [send]);
  const driving = !!run?.takeover && (run.status === 'paused' || run.status === 'handoff');
  const onKey = (e: React.KeyboardEvent) => {
    if (!driving || mode !== 'screen' || (e.target as HTMLElement).tagName === 'INPUT') return;
    const a = keyAction(e); if (!a) return; e.preventDefault();
    if (a.kind === 'text') { buffer.current += a.text; clearTimeout(flushTimer.current); flushTimer.current = setTimeout(flush, 300); }
    else { flush(); send({ action: 'key', text: a.text }); }
  };
  const stop = async () => { try { await api('POST', `/v1/requests/${id}/cancel`, {}); } catch { setErr('That did not go through.'); } };

  const shots = events.filter(e => e.kind === 'screenshot'); const last = shots[shots.length - 1];
  const fallback = last ? `/v1/browse/${id}/shot/${last.file as string}?t=${stamp}` : null;
  const heading = run?.goal ?? request?.message ?? 'Live view';
  const status = browse && run ? STATE_LABEL[run.status] ?? run.status : request ? (phase(request.state) === 'running' ? 'Working' : phase(request.state) === 'queued' ? 'Queued' : phase(request.state) === 'completed' ? 'Done' : phase(request.state) === 'failed' ? 'Stopped' : 'Cancelled') : '';
  const started = run?.created_epoch ?? request?.created_epoch ?? 0;

  if (isBrowse === null && !request) return <div className="livepage"><h1 className="page-title">Live view</h1><p className={err ? 'err' : 'muted'} role={err ? 'alert' : 'status'}>{err || 'Loading…'}</p><p><Link to="/live">All live tasks</Link></p></div>;
  if (isBrowse === false && !request) return <div className="livepage"><h1 className="page-title">Live view</h1><p className="err" role="alert">That task was not found.</p><p><Link to="/live">All live tasks</Link></p></div>;

  return (
    <div className="livepage">
      <p><Link to="/live" className="faint">← All live tasks</Link></p>
      <header className="live-head">
        <h1 className="page-title">{heading.length > 90 ? heading.slice(0, 90) + '…' : heading}</h1>
        <div className="live-meta"><span className={`pill${taskLive ? ' live' : ''}`}>{status}</span>{taskLive && started > 0 && <span className="faint">{elapsed(started, now)}</span>}{run?.url && <span className="faint">{new URL(run.url, 'http://x').hostname}</span>}
          {taskLive && <button className="btn small danger" onClick={stop}>Stop</button>}</div>
      </header>
      <div className="live-grid">
        <section className="panel live-main">
          <div className="live-tabs" role="tablist" aria-label="What to watch">
            {modes.map(m => <button key={m} role="tab" aria-selected={mode === m} className="chip" aria-pressed={mode === m} onClick={() => setPinned(m)}>{MODE_LABEL[m]}</button>)}
            <span className="spacer" />
            <button className="chip small" aria-pressed={pinned === null} onClick={() => setPinned(pinned === null ? mode : null)} title="Switch between screen, terminal and files as Lumina moves between them">Follow Lumina</button>
          </div>
          <div className="live-stage" tabIndex={driving && mode === 'screen' ? 0 : -1} onKeyDown={onKey} aria-label={driving ? 'The page you are controlling. Click to point, type to enter text.' : undefined}>
            {mode === 'screen' && <LiveScreen id={id} enabled={browse && browseLive} fallback={fallback} interactive={driving} onPoint={p => { flush(); send({ action: 'click', ...p }); }} onWheel={dir => send({ action: 'scroll', text: dir })} />}
            {mode === 'terminal' && <LiveTerminal rows={rows} active={taskLive} />}
            {mode === 'files' && <LiveFiles rows={rows} />}
          </div>

          {browse && run && run.status === 'running' && (
            <div className="live-bar">{run.pausing
              ? <span className="muted" role="status">Pausing after Lumina’s current step…</span>
              : <><button className="btn primary" onClick={() => act('pause')}>Hop in</button><span className="faint">Take the wheel any time. Lumina waits for you.</span></>}</div>)}
          {browse && run && driving && (
            <div className="live-bar col">
              <p className="muted">{run.status === 'paused'
                ? 'You have the wheel. Lumina is waiting. Click the screen to point, type to enter text, scroll with the wheel.'
                : `${run.pending_action?.label ? `Lumina stopped before: ${run.pending_action.label}. ` : 'Lumina stopped at a step that needs you. '}Nothing is bought unless you do it yourself.`}</p>
              <form className="live-type" onSubmit={e => { e.preventDefault(); if (text) { flush(); send({ action: 'type', text }); setText(''); } }}>
                <label className="sr" htmlFor="tk">Text to type into the page</label>
                <input id="tk" value={text} maxLength={500} onChange={e => setText(e.target.value)} placeholder="Type into the selected field" />
                <button className="btn" type="submit">Type</button>
                <button className="btn" type="button" onClick={() => { flush(); send({ action: 'key', text: 'Enter' }); }}>Enter</button>
                <button className="btn" type="button" onClick={() => send({ action: 'scroll', text: 'up' })}>Scroll up</button>
                <button className="btn" type="button" onClick={() => send({ action: 'scroll', text: 'down' })}>Scroll down</button>
                <button className="btn primary" type="button" onClick={() => { flush(); act(run.status === 'paused' ? 'resume' : 'release'); }}>{run.status === 'paused' ? 'Hand back to Lumina' : 'Return control'}</button>
              </form>
            </div>)}
          {browse && run?.status === 'handoff' && !run.takeover && <p className="muted live-note">The take-over window has closed.</p>}
          {isBrowse === false && taskLive && <p className="faint small live-note">You can watch and stop this task here. Hopping in with the mouse and keyboard works on browser tasks; to steer this one, tell Lumina in the chat.</p>}
          {(err || actErr) && <p className="err small live-note" role="alert">{err || actErr}</p>}
          {run?.answer && <p className="live-note">{run.answer}</p>}
        </section>

        <aside className="panel card live-side" aria-label="Activity">
          <div className="card-h"><h2>Activity</h2><span className="faint">{taskLive ? 'Live' : 'Finished'}</span></div>
          <ol className="act-list live-list">
            {rows.length === 0 && <li className="faint act-empty">{taskLive ? 'Waiting for the first step…' : 'No tool use was recorded for this task.'}</li>}
            {rows.map(r => (
              <li key={r.key} className={`act-row ${r.category} ${r.status}`}>
                <span className="act-ico" aria-hidden="true">{ICON[r.category] ?? ICON.other}</span>
                <div className="act-body"><div className="act-label">{r.label}{r.status === 'running' && <span className="dot-s running" aria-label="in progress" />}{r.status === 'failed' && r.category !== 'error' && <span className="act-bad"> · failed</span>}</div>
                  {r.detail && <code className="act-detail">{r.detail}</code>}</div>
              </li>))}
          </ol>
        </aside>
      </div>
    </div>);
}

export default function Live() {
  const { id } = useParams();
  return id ? <LiveRun id={id} /> : <LiveList />;
}
