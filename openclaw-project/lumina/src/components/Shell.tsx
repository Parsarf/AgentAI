import { useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import Rail from './Rail';
import * as I from './Icons';
import Backdrop from './Backdrop';
import { useData } from '../state/data';
import { useSettings } from '../state/settings';
import { displayName, title } from '../lib/format';
import { phase } from '../lib/tasks';

export const NAV = [
  { to: '/', label: 'Home', icon: I.Home, end: true }, { to: '/chat', label: 'Chat', icon: I.Chat }, { to: '/tasks', label: 'Tasks', icon: I.Tasks },
  { to: '/browser', label: 'Browser', icon: I.Browser }, { to: '/files', label: 'Files', icon: I.Files }, { to: '/calendar', label: 'Calendar', icon: I.Calendar },
  { to: '/automations', label: 'Automations', icon: I.Bolt }, { to: '/integrations', label: 'Integrations', icon: I.Cube }, { to: '/settings', label: 'Settings', icon: I.Gear },
];

function Command({ onClose }: { onClose(): void }) {
  const { requests } = useData(); const nav = useNavigate();
  const [q, setQ] = useState(''); const [i, setI] = useState(0); const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const items = useMemo(() => {
    const all = [...NAV.map(n => ({ label: n.label, hint: 'Go to', to: n.to })),
      ...requests.slice(0, 40).map(r => ({ label: title(r.message, 70), hint: phase(r.state), to: `/tasks/${r.id}` }))];
    const t = q.trim().toLowerCase();
    return (t ? all.filter(a => a.label.toLowerCase().includes(t)) : all).slice(0, 12);
  }, [q, requests]);
  const go = (to: string) => { nav(to); onClose(); };
  return (
    <div className="cmd-back" onMouseDown={onClose} role="presentation">
      <div className="cmd" role="dialog" aria-label="Search" onMouseDown={e => e.stopPropagation()}>
        <input ref={input} value={q} placeholder="Search pages and tasks…" aria-label="Search pages and tasks"
          onChange={e => { setQ(e.target.value); setI(0); }}
          onKeyDown={e => {
            if (e.key === 'Escape') onClose();
            else if (e.key === 'ArrowDown') { e.preventDefault(); setI(x => Math.min(x + 1, items.length - 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setI(x => Math.max(x - 1, 0)); }
            else if (e.key === 'Enter' && items[i]) go(items[i].to);
          }} />
        <ul>{items.map((it, n) => <li key={it.to + n}><button aria-selected={n === i} onClick={() => go(it.to)}><span>{it.label}</span><span className="faint">{it.hint}</span></button></li>)}
          {!items.length && <li className="faint" style={{ padding: 12 }}>Nothing matches.</li>}</ul>
      </div>
    </div>);
}

export default function Shell() {
  const { pathname } = useLocation();
  const rail = pathname === '/' || pathname.startsWith('/tasks');
  const { app, requests, signOut } = useData(); const { reducedMotion, setReducedMotion } = useSettings();
  const [cmd, setCmd] = useState(false); const [bell, setBell] = useState(false);
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmd(true); } };
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h);
  }, []);
  const name = displayName(app?.user.email ?? '');
  const attention = requests.filter(r => phase(r.state) === 'failed').slice(0, 5);
  const nav = useNavigate();
  return (
    <div className={`shell${rail ? '' : ' no-right'}`}>
      <Backdrop />
      <aside className="panel side">
        <div className="brand"><I.Spark /> LUMINA</div>
        <nav className="nav" aria-label="Primary">
          {NAV.map(n => <NavLink key={n.to} to={n.to} end={n.end}><n.icon /><span>{n.label}</span></NavLink>)}
        </nav>
        <div className="who">
          <div className="avatar" aria-hidden>{name[0]}</div>
          <div className="grow"><div>{name}</div><small>{app?.features.billing_mode === 'paid_required' ? 'Subscriber' : app?.features.billing_mode === 'open' ? 'Free access' : 'Private beta'}</small></div>
          <button onClick={signOut} aria-label="Sign out" title="Sign out"><I.Out width={18} height={18} /></button>
        </div>
      </aside>
      <main className="main">
        <div className="topbar">
          <button className="iconbtn" aria-label="Search (Ctrl+K)" onClick={() => setCmd(true)}><I.Search /></button>
          <div style={{ position: 'relative' }}>
            <button className="iconbtn" aria-label="Notifications" aria-expanded={bell} onClick={() => setBell(b => !b)}><I.Bell />{attention.length > 0 && <span className="dot" />}</button>
            {bell && (
              <div className="panel" style={{ position: 'absolute', right: 0, top: 54, width: 300, padding: 12, zIndex: 20, background: 'var(--bg-2)' }}>
                {attention.length ? attention.map(r => <button key={r.id} className="btn" style={{ width: '100%', marginBottom: 6, textAlign: 'left' }} onClick={() => { setBell(false); nav(`/tasks/${r.id}`); }}>Failed: {title(r.message, 40)}</button>)
                  : <p className="muted" style={{ padding: 6 }}>Nothing needs your attention.</p>}
              </div>)}
          </div>
          <button className="iconbtn" aria-label={reducedMotion ? 'Turn animations on' : 'Reduce motion'} aria-pressed={reducedMotion} title={reducedMotion ? 'Animations off' : 'Animations on'} onClick={() => setReducedMotion(!reducedMotion)}><I.Motion /></button>
        </div>
        <Outlet />
      </main>
      {rail && <aside className="rail" aria-label="Activity"><Rail /></aside>}
      {cmd && <Command onClose={() => setCmd(false)} />}
    </div>);
}
