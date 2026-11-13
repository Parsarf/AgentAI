import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import * as I from '../components/Icons';
import Composer, { TEMPLATES } from '../components/Composer';
import { useData } from '../state/data';
import { ago, displayName, greeting } from '../lib/format';
import type { TaskSummary } from '../lib/work';
import { useWork } from '../state/work';
import { Status } from '../components/work/parts';

const CAPS = [
  { key: 'Web', name: 'Search Web', text: 'Find, analyze and summarize anything.', icon: I.Browser },
  { key: 'Code', name: 'Build & Code', text: 'Create and deploy applications.', icon: I.Code },
  { key: 'Data', name: 'Analyze Data', text: 'Turn your data into clear insights.', icon: I.Chart },
  { key: 'Automate', name: 'Automate', text: 'Create workflows and recurring tasks.', icon: I.Bolt },
];

export function TaskRow({ task }: { task: TaskSummary }) {
  return (
    <Link className="task" to={task.conversation_id && task.phase !== 'ended' ? `/chat/${task.conversation_id}` : `/tasks/${task.id}`}>
      <span className="t-main"><span className="t-name" style={{ display: 'block' }}>{task.title}</span>
        <span className="t-meta"><Status task={task} size="sm" /><span>{ago(task.created_epoch)}</span></span></span>
      <I.Chevron width={18} height={18} />
    </Link>);
}

export default function Home() {
  const { app } = useData(); const { tasks, loaded } = useWork(); const nav = useNavigate();
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
      <div className="sect"><h2>Recent work</h2><Link to="/tasks">All activity</Link></div>
      {tasks.length === 0
        ? <div className="empty">{loaded ? 'No tasks yet. Describe what you need above and Lumina will get to work.' : 'Loading…'}</div>
        : <div className="tasks">{tasks.slice(0, 5).map(t => <TaskRow key={t.id} task={t} />)}</div>}
    </div>);
}
