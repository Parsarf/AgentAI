import { NavLink, useMatch, useNavigate } from 'react-router-dom';
import * as I from './Icons';
import ChatList from './ChatList';
import { useData } from '../state/data';
import { useSettings } from '../state/settings';
import { displayName } from '../lib/format';

export const NAV = [
  { to: '/home', label: 'Home', icon: I.Home, end: true }, { to: '/chat', label: 'Chat', icon: I.Chat, end: false }, { to: '/history', label: 'Chat history', icon: I.Search }, { to: '/tasks', label: 'Task activity', icon: I.Tasks },
  { to: '/live', label: 'Live view', icon: I.Browser }, { to: '/files', label: 'Files', icon: I.Files }, { to: '/calendar', label: 'Calendar', icon: I.Calendar },
  { to: '/automations', label: 'Automations', icon: I.Bolt }, { to: '/integrations', label: 'Integrations', icon: I.Cube }, { to: '/settings', label: 'Settings', icon: I.Gear },
];

/** Left sidebar: menu on top, chat history below, one toggle to fold it to an icon rail (like ChatGPT and Claude). */
export default function Sidebar() {
  const { app, chats, signOut, refreshChats } = useData(); const { sidebarOpen, setSidebarOpen } = useSettings(); const nav = useNavigate();
  const match = useMatch('/chat/:id'); const name = displayName(app?.user.email ?? '');
  const toggle = () => setSidebarOpen(!sidebarOpen);
  return (
    <aside className={`panel side${sidebarOpen ? '' : ' collapsed'}`} aria-label="Sidebar">
      <div className="side-top">
        <div className="brand"><I.Spark /><span className="lbl">LUMINA</span></div>
        <button className="icon-toggle" onClick={toggle} aria-expanded={sidebarOpen} aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'} title={`${sidebarOpen ? 'Collapse' : 'Expand'} sidebar (Ctrl+B)`}><I.Panel width={20} height={20} /></button>
      </div>
      <button className="newchat-btn" onClick={() => nav('/chat')} title="New chat" aria-label="New chat"><I.Edit width={18} height={18} /><span className="lbl">New chat</span></button>
      <nav className="nav" aria-label="Primary">
        {NAV.map(n => <NavLink key={n.to} to={n.to} end={n.end} title={n.label}><n.icon width={20} height={20} /><span className="lbl">{n.label}</span></NavLink>)}
      </nav>
      {sidebarOpen && <div className="side-chats"><ChatList chats={chats} current={match?.params.id} onChanged={() => refreshChats()} /></div>}
      <div className="who">
        <div className="avatar" aria-hidden>{name[0]}</div>
        <div className="grow lbl"><div>{name}</div><small>{app?.features.billing_mode === 'paid_required' ? 'Subscriber' : app?.features.billing_mode === 'open' ? 'Free access' : 'Private beta'}</small></div>
        <button className="lbl" onClick={signOut} aria-label="Sign out" title="Sign out"><I.Out width={18} height={18} /></button>
      </div>
    </aside>);
}
