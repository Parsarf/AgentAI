import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import * as I from '../components/Icons';
import Composer, { TEMPLATES } from '../components/Composer';
import { useData } from '../state/data';
import { ago, displayName, greeting, title } from '../lib/format';
import { dotClass, phase, statusLabel } from '../lib/tasks';

const CAPS = [
  { key: 'Web', name: 'Search Web', text: 'Find, analyze and summarize anything.', icon: I.Browser },
  { key: 'Code', name: 'Build & Code', text: 'Create and deploy applications.', icon: I.Code },
  { key: 'Data', name: 'Analyze Data', text: 'Turn your data into clear insights.', icon: I.Chart },
  { key: 'Automate', name: 'Automate', text: 'Create workflows and recurring tasks.', icon: I.Bolt },
];

export function TaskRow({ r, onOpen }: { r: { id: string; message: string; state: string; created_epoch: number; paused?: boolean; ahead?: number | null }; onOpen(): void }) {
  const p = phase(r.state);
  const label = statusLabel(r) + (p === 'queued' && !r.paused && typeof r.ahead === 'number' && r.ahead > 0 ? ` (${r.ahead} ahead)` : '');
  return (
    <button className="task" onClick={onOpen}>
      <span className="t-ico">{p === 'running' ? <I.Bolt width={18} height={18} /> : <I.Tasks width={18} height={18} />}</span>
      <span className="t-main"><span className="t-name" style={{ display: 'block' }}>{title(r.message, 90)}</span>
        <span className="t-meta"><span className={`dot-s ${dotClass(r)}`} />{label} · {ago(r.created_epoch)}</span></span>
      <I.Chevron width={18} height={18} />
    </button>);
}

export default function Home() {
  const { app, requests } = useData(); const nav = useNavigate();
  const [seed, setSeed] = useState<{ text: string; n: number } | null>(null);
  const name = displayName(app?.user.email ?? '');
  return (
    <div className="center">
      <header className="hero"><div><h1>{greeting(new Date())}, {name}</h1><p>What would you like to do today?</p></div><time className="hero-date" dateTime={new Date().toISOString().slice(0, 10)}>{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</time></header>
      <Composer seed={seed} onSent={r => nav(`/chat/${r.conversation_id}`)} />
      <div className="caps" role="list">
        {CAPS.map(c => (
          <button key={c.key} role="listitem" className="cap" onClick={() => setSeed({ text: TEMPLATES[c.key], n: Date.now() })}>
            <span className="ico"><c.icon width={30} height={30} /></span><span className="go"><I.Chevron width={16} height={16} /></span>
            <span><h3>{c.name}</h3><p>{c.text}</p></span>
          </button>))}
      </div>
      <div className="sect"><h2>Recent Tasks</h2><Link to="/tasks">View all →</Link></div>
      {requests.length === 0
        ? <div className="empty">No tasks yet. Describe what you need above and Lumina will get to work.</div>
        : <div className="tasks">{requests.slice(0, 5).map(r => <TaskRow key={r.id} r={r} onOpen={() => nav(r.conversation_id ? `/chat/${r.conversation_id}` : `/tasks/${r.id}`)} />)}</div>}
    </div>);
}
