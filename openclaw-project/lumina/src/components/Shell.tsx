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
  const hasRail = pathname === '/home' || pathname.startsWith('/tasks');
  const [railOpen, setRailOpen] = useState(false);
  const rail = hasRail && railOpen;
  const { requests, chats, refreshChats } = useData(); const { reducedMotion, setReducedMotion, sidebarOpen, setSidebarOpen } = useSettings(); const [drawer, setDrawer] = useState<'chats' | 'pages' | null>(null);
  const drawerOpener = useRef<HTMLElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!drawer) return;
    drawerOpener.current = document.activeElement as HTMLElement;
    const focusable = () => Array.from(drawerRef.current?.querySelectorAll<HTMLElement>('button, a[href], input, [tabindex="0"]') ?? []);
    focusable()[0]?.focus();
    const close = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDrawer(null);
      if (e.key === 'Tab') {
        const items = focusable(); const first = items[0]; const last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    };
    window.addEventListener('keydown', close);
    return () => { window.removeEventListener('keydown', close); drawerOpener.current?.focus(); };
  }, [drawer]);
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
      <Sidebar onMore={() => setDrawer('pages')} />
      <main className="main">
        <div className="topbar">
          <button className="iconbtn only-mobile" aria-label="Chats" onClick={() => setDrawer('chats')}><I.Chat /></button>
          <span className="workspace-title">{NAV.find(n => n.to === pathname || (n.to !== '/home' && pathname.startsWith(n.to + '/')))?.label ?? 'Lumina'}</span>
          <span className="spacer" />
          {hasRail && <button className="btn context-toggle" aria-expanded={rail} aria-controls="workspace-activity" onClick={() => setRailOpen(v => !v)}>Activity</button>}
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
      {rail && <aside id="workspace-activity" className="rail" aria-label="Workspace activity"><Rail /></aside>}
      {cmd && <Command onClose={() => setCmd(false)} />}
      {drawer && (
        <div className="drawer-back left" onMouseDown={() => setDrawer(null)} role="presentation">
          <aside ref={drawerRef} className="drawer" role="dialog" aria-modal="true" aria-label={drawer === 'pages' ? 'Pages' : 'Chats'} onMouseDown={e => e.stopPropagation()}>
            <button className="btn small drawer-close" onClick={() => setDrawer(null)}>Close</button>
            {drawer === 'pages' ? <nav className="nav page-menu" aria-label="All pages">{NAV.map(n => <NavLink key={n.to} to={n.to} end={n.end} onClick={() => setDrawer(null)}><n.icon width={20} height={20} />{n.label}</NavLink>)}</nav> : <>
            <button className="btn primary" style={{ width: '100%', marginBottom: 12 }} onClick={() => { setDrawer(null); void nav('/chat'); }}>New chat</button>
            <ChatList chats={chats} onChanged={() => refreshChats()} onPick={() => setDrawer(null)} />
            </>}
          </aside>
        </div>)}
    </div>);
}
