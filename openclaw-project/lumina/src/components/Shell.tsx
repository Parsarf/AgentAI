import { useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import Rail from './Rail';
import LocationRequest from './LocationRequest';
import * as I from './Icons';
import Sidebar, { NAV } from './Sidebar';
import ChatList from './ChatList';
import Backdrop from './Backdrop';
import Menu from './ui/Menu';
import { useData } from '../state/data';
import { useSettings } from '../state/settings';
import { title } from '../lib/format';
import { useWork } from '../state/work';

function Command({ onClose }: { onClose(): void }) {
  const { chats } = useData(); const { tasks } = useWork(); const nav = useNavigate();
  const [q, setQ] = useState(''); const [i, setI] = useState(0); const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const items = useMemo(() => {
    const all = [...NAV.map(n => ({ label: n.label, hint: 'Go to', to: n.to })),
      ...chats.map(c => ({ label: c.title || 'New chat', hint: 'Chat', to: `/chat/${c.id}` })),
      ...tasks.slice(0, 40).map(t => ({ label: title(t.title, 70), hint: t.label, to: `/tasks/${t.id}` }))];
    const t = q.trim().toLowerCase();
    return (t ? [{ label: `Search all chats for “${q.trim()}”`, hint: 'Titles and messages', to: `/history?q=${encodeURIComponent(q.trim())}` }, ...all.filter(a => a.label.toLowerCase().includes(t))] : all).slice(0, 12);
  }, [q, tasks, chats]);
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

/** The label in the top bar: the navigation entry for the current page. */
function pageTitle(pathname: string) {
  if (pathname === '/') return 'Chat';
  if (pathname.startsWith('/live')) return 'Activity';      // a task's workspace belongs to Activity
  const hit = NAV.find(n => pathname === n.to || pathname.startsWith(n.to + '/'));
  return hit ? hit.label : 'Lumina';
}

export default function Shell() {
  const { pathname } = useLocation();
  const rail = pathname === '/home';
  const { app, chats, refreshChats } = useData(); const { tasks } = useWork(); const { reducedMotion, setReducedMotion, sidebarOpen, setSidebarOpen } = useSettings(); const [drawer, setDrawer] = useState(false);
  const [cmd, setCmd] = useState(false);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmd(true); }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); setSidebarOpen(!sidebarOpen); }
    };
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h);
  }, [sidebarOpen, setSidebarOpen]);
  // The bell lists what is waiting for the customer first, then recent failures: the same facts Activity shows.
  const attention = [...tasks.filter(t => t.attention), ...tasks.filter(t => t.outcome === 'failed' && !t.attention).slice(0, 3)].slice(0, 6);
  const nav = useNavigate();
  return (
    <div className={`shell${rail ? '' : ' no-right'}${sidebarOpen ? '' : ' side-collapsed'}`}>
      {!pathname.startsWith('/chat/') && !pathname.startsWith('/live') && <Backdrop />}
      <Sidebar />
      <main className="main">
        <div className="topbar">
          <button className="iconbtn only-mobile" aria-label="Chats" onClick={() => setDrawer(true)}><I.Chat /></button>
          <h2 className="topbar-title">{pageTitle(pathname)}</h2>
          <button className="iconbtn" aria-label="Search (Ctrl+K)" title="Search (Ctrl+K)" onClick={() => setCmd(true)}><I.Search width={20} height={20} /></button>
          <Menu label="Notifications" heading="Notifications" align="end"
            items={attention.length ? attention.map(t => ({ id: t.id, label: `${t.attention ? t.attention_label : 'Failed'}: ${title(t.title, 40)}`, onSelect: () => { void nav(`/tasks/${t.id}`); } }))
              : [{ id: 'none', label: 'Nothing needs your attention.', disabled: true, onSelect: () => {} }]}
            trigger={({ open, props }) => <button className="iconbtn" aria-label="Notifications" aria-expanded={open} {...props}><I.Bell width={20} height={20} />{attention.length > 0 && <span className="dot" />}</button>} />
          <button className="iconbtn" aria-label={reducedMotion ? 'Turn animations on' : 'Reduce motion'} aria-pressed={reducedMotion} title={reducedMotion ? 'Animations off' : 'Animations on'} onClick={() => setReducedMotion(!reducedMotion)}><I.Motion width={20} height={20} /></button>
        </div>
        {tasks.some(t => t.phase === 'working' || t.phase === 'needs_you' || t.phase === 'starting') && <LocationRequest key={app?.user.email} />}
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
