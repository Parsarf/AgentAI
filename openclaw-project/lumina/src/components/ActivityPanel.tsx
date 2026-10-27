import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { ICON } from '../lib/activity';
import { useActivity } from '../lib/useActivity';
import { elapsed } from '../lib/format';
import { useData } from '../state/data';

interface Shot { file?: string }

/** Live window onto what the assistant is doing for one task: searches, pages opened, commands, files, and the browser view. */
export default function ActivityPanel({ taskId, active, startedAt, onStop, onClose }: { taskId: string; active: boolean; startedAt: number; onStop(): void; onClose(): void }) {
  const { app } = useData();
  const { rows, err } = useActivity(taskId, active);
  const [shot, setShot] = useState<string | null>(null); const [now, setNow] = useState(Date.now());
  const list = useRef<HTMLOListElement>(null); const stick = useRef(true);

  useEffect(() => { setShot(null); }, [taskId]);
  useEffect(() => { if (!active) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [active]);
  useEffect(() => {
    if (!app?.features.browse) return; let stop = false; let timer: ReturnType<typeof setTimeout>;
    const look = async () => {
      try {
        const r = await api<{ events: (Shot & { kind: string })[]; status: string }>('GET', `/v1/browse/${taskId}?since=0`);
        const last = [...r.events].reverse().find(e => e.kind === 'screenshot' && e.file);
        if (!stop && last?.file) setShot(`/v1/browse/${taskId}/shot/${last.file}?t=${Date.now()}`);
        if (!stop && ['queued', 'running', 'handoff', 'paused'].includes(r.status)) timer = setTimeout(look, 2000);
      } catch { /* not a browser task */ }
    };
    void look(); return () => { stop = true; clearTimeout(timer); };
  }, [taskId, app?.features.browse]);

  useEffect(() => { if (stick.current) list.current?.scrollTo({ top: list.current.scrollHeight }); }, [rows.length, rows[rows.length - 1]?.status]);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [onClose]);

  return (
    <aside className="activity" aria-label="Activity">
      <header className="act-head">
        <h2>Activity</h2>
        <span className="faint">{active ? `Working · ${elapsed(startedAt, now)}` : 'Finished'}</span>
        {active && <button className="btn small danger" onClick={onStop}>Stop</button>}
        <button className="btn small" onClick={onClose} aria-label="Close activity">Close</button>
      </header>
      {shot && (
        <div className="act-shot"><img src={shot} alt="The page Lumina is working on" />
          <Link className="btn small" to={`/live/${taskId}`}>Open live view</Link></div>)}
      <ol className="act-list" ref={list} onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
        {rows.length === 0 && <li className="faint act-empty">{active ? 'Waiting for the assistant’s first step…' : 'No tool use was recorded for this task.'}</li>}
        {rows.map(r => (
          <li key={r.key} className={`act-row ${r.category} ${r.status}`}>
            <span className="act-ico" aria-hidden="true">{ICON[r.category] ?? ICON.other}</span>
            <div className="act-body">
              <div className="act-label">{r.label}{r.status === 'running' && <span className="dot-s running" aria-label="in progress" />}{r.status === 'failed' && r.category !== 'error' && <span className="act-bad"> · failed</span>}</div>
              {r.detail && <code className="act-detail">{r.detail}</code>}
              {r.output && <details><summary className="faint small">Output</summary><pre className="act-out">{r.output}</pre></details>}
            </div>
          </li>))}
      </ol>
      {err && <p className="faint small act-err" role="status">{err}</p>}
      <p className="faint small act-note">Shows searches, pages, commands and file names. File contents and secrets are never shown.</p>
    </aside>);
}
