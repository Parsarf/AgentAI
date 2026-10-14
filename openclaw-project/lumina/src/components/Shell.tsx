import { useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import Rail from './Rail';
import * as I from './Icons';
import Sidebar, { NAV } from './Sidebar';
import ChatList from './ChatList';
import Backdrop from './Backdrop';
import { useData } from '../state/data';
import { useSettings } from '../state/settings';
import { title } from '../lib/format';
import { phase } from '../lib/tasks';

function Command({ onClose }: { onClose(): void }) {
  const { requests, chats } = useData(); const nav = useNavigate();
  const [q, setQ] = useState(''); const [i, setI] = useState(0); const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const items = useMemo(() => {
    const all = [...NAV.map(n => ({ label: n.label, hint: 'Go to', to: n.to })),
      ...chats.map(c => ({ label: c.title || 'New chat', hint: 'Chat', to: `/chat/${c.id}` })),
      ...requests.filter(r => !r.conversation_id).slice(0, 40).map(r => ({ label: title(r.message, 70), hint: phase(r.state), to: `/tasks/${r.id}` }))];
    const t = q.trim().toLowerCase();
    return (t ? [{ label: `Search all chats for “${q.trim()}”`, hint: 'Titles and messages', to: `/history?q=${encodeURIComponent(q.trim())}` }, ...all.filter(a => a.label.toLowerCase().includes(t))] : all).slice(0, 12);
  }, [q, requests, chats]);
  const go = (to: string) => { void nav(to); onClose(); };
  return (
    <div className="cmd-back" onMouseDown={onClose} role="presentation">
      <div className="cmd" role="dialog" aria-label="Search" onMouseDown={e => e.stopPropagation()}>
        <input ref={input} value={q} placeholder="Search chats and pages…" aria-label="Search chats and pages"
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
  const rail = pathname === '/home' || pathname.startsWith('/tasks');
  const { requests, chats, refreshChats } = useData(); const { reducedMotion, setReducedMotion, sidebarOpen, setSidebarOpen } = useSettings(); const [drawer, setDrawer] = useState(false);
  const [cmd, setCmd] = useState(false); const [bell, setBell] = useState(false);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmd(true); }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); setSidebarOpen(!sidebarOpen); }
    };
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h);
  }, [sidebarOpen, setSidebarOpen]);
  const attention = requests.filter(r => phase(r.state) === 'failed').slice(0, 5);
  const nav = useNavigate();
  return (
    <div className={`shell${rail ? '' : ' no-right'}${sidebarOpen ? '' : ' side-collapsed'}`}>
      {!pathname.startsWith('/chat/') && !pathname.startsWith('/live') && <Backdrop />}
      <Sidebar />
      <main className="main">
        <div className="topbar">
          <button className="iconbtn only-mobile" aria-label="Chats" onClick={() => setDrawer(true)}><I.Chat /></button>
          <span className="spacer" />
          <button className="iconbtn" aria-label="Search (Ctrl+K)" onClick={() => setCmd(true)}><I.Search /></button>
          <div style={{ position: 'relative' }}>
            <button className="iconbtn" aria-label="Notifications" aria-expanded={bell} onClick={() => setBell(b => !b)}><I.Bell />{attention.length > 0 && <span className="dot" />}</button>
            {bell && (
              <div className="panel" style={{ position: 'absolute', right: 0, top: 54, width: 300, padding: 12, zIndex: 20, background: 'var(--bg-2)' }}>
                {attention.length ? attention.map(r => <button key={r.id} className="btn" style={{ width: '100%', marginBottom: 6, textAlign: 'left' }} onClick={() => { setBell(false); void nav(r.conversation_id ? `/chat/${r.conversation_id}` : `/tasks/${r.id}`); }}>Failed: {title(r.message, 40)}</button>)
                  : <p className="muted" style={{ padding: 6 }}>Nothing needs your attention.</p>}
              </div>)}
          </div>
          <button className="iconbtn" aria-label={reducedMotion ? 'Turn animations on' : 'Reduce motion'} aria-pressed={reducedMotion} title={reducedMotion ? 'Animations off' : 'Animations on'} onClick={() => setReducedMotion(!reducedMotion)}><I.Motion /></button>
        </div>
        <Outlet />
      </main>
      {rail && <aside className="rail" aria-label="Activity"><Rail /></aside>}
      {cmd && <Command onClose={() => setCmd(false)} />}
      {drawer && (
        <div className="drawer-back left" onMouseDown={() => setDrawer(false)} role="presentation">
          <aside className="drawer" role="dialog" aria-label="Chats" onMouseDown={e => e.stopPropagation()}>
            <button className="btn primary" style={{ width: '100%', marginBottom: 12 }} onClick={() => { setDrawer(false); void nav('/chat'); }}>New chat</button>
            <ChatList chats={chats} onChanged={() => refreshChats()} onPick={() => setDrawer(false)} />
          </aside>
        </div>)}
    </div>);
}
