import { useEffect, useMemo, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import LocationRequest from './LocationRequest';
import { FrameProvider, useFrame } from './frame/FrameProvider';
import { BottomBar, NavRail, PLACES } from './frame/Nav';
import { useData } from '../state/data';
import { title } from '../lib/format';
import { useWork } from '../state/work';

function Command({ onClose }: { onClose(): void }) {
  const { chats } = useData(); const { tasks } = useWork(); const nav = useNavigate();
  const [q, setQ] = useState(''); const [i, setI] = useState(0); const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const items = useMemo(() => {
    const all = [...PLACES.map(n => ({ label: n.label, hint: 'Go to', to: n.to })),
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

function Body() {
  const frame = useFrame()!; const { pathname } = useLocation();
  useEffect(() => { frame.setSheet(null); }, [pathname]);   // eslint-disable-line react-hooks/exhaustive-deps -- a sheet belongs to the page it was opened on
  const { app } = useData(); const { tasks } = useWork();
  const [cmd, setCmd] = useState(false);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmd(true); }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); frame.toggle('context'); }
    };
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h);
  }, [frame]);
  const compact = frame.placement.widthClass === 'compact';
  return (
    <div className={`frame w-${frame.placement.widthClass}`}>
      <a className="skip" href="#canvas">Skip to content</a>
      {compact ? <BottomBar onSearch={() => setCmd(true)} /> : <NavRail onSearch={() => setCmd(true)} />}
      <div className="frame-work">
        {tasks.some(t => t.phase === 'working' || t.phase === 'needs_you' || t.phase === 'starting') && <LocationRequest key={app?.user.email} />}
        <Outlet />
      </div>
      {cmd && <Command onClose={() => setCmd(false)} />}
    </div>);
}

/** The workspace frame around every page: the rail (a bottom bar on a phone), the page's own zones, and the shared assistant panel. */
export default function Shell() {
  const { app } = useData();
  return <FrameProvider person={app?.user.email ?? ''}><Body /></FrameProvider>;
}
