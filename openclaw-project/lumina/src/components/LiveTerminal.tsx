import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ICON, type ActivityItem } from '../lib/activity';

/** Commands and their output as Lumina runs them, newest at the bottom, following along unless you scroll up to read. */
export function LiveTerminal({ rows, active }: { rows: ActivityItem[]; active: boolean }) {
  const box = useRef<HTMLDivElement>(null); const stick = useRef(true);
  useEffect(() => { if (stick.current) box.current?.scrollTo({ top: box.current.scrollHeight }); }, [rows.length, rows[rows.length - 1]?.status, rows[rows.length - 1]?.output]);
  const commands = rows.some(r => r.category === 'command');
  const lines = commands ? rows.filter(r => ['command', 'note', 'error'].includes(r.category)) : rows;
  return (
    <div className="live-term" ref={box} tabIndex={0} role="log" aria-label={commands ? 'Terminal' : 'Activity log'} aria-live="off"
      onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
      {lines.length === 0 && <p className="faint">{active ? 'Waiting for the first tool activity…' : 'No tool activity was recorded for this task.'}</p>}
      {lines.map(r => r.category === 'command'
        ? (<div key={r.key} className={`term-block ${r.status}`}>
            <div className="term-cmd"><span className="term-prompt" aria-hidden="true">$</span> <code>{r.detail || r.label}</code>{r.status === 'running' && <span className="term-cursor" aria-label="running" />}{r.status === 'failed' && <span className="act-bad"> · failed</span>}</div>
            {r.output && <pre className="term-out">{r.output}</pre>}
          </div>)
        : (<div key={r.key} className={`term-line ${r.category} ${r.status}`}>
            <span aria-hidden="true">{ICON[r.category] ?? ICON.other}</span> {r.label}{r.detail && <> <code>{r.detail}</code></>}{r.status === 'running' && <span className="term-cursor" aria-label="running" />}
          </div>))}
    </div>);
}

/** Files Lumina read or wrote. Names only: file contents are never shown here; finished files can be downloaded from Files. */
export function LiveFiles({ rows }: { rows: ActivityItem[] }) {
  const files = rows.filter(r => r.category === 'file');
  return (
    <div className="live-files">
      {files.length === 0 && <p className="faint">No files touched yet.</p>}
      <ul>{files.map(r => <li key={r.key} className={r.status}><span className="act-ico" aria-hidden="true">{ICON.file}</span><span>{r.label}</span> <code>{r.detail}</code>{r.status === 'running' && <span className="dot-s running" aria-label="in progress" />}</li>)}</ul>
      <p className="faint small">File contents are never shown. Finished files appear in <Link to="/files">Files</Link>.</p>
    </div>);
}
