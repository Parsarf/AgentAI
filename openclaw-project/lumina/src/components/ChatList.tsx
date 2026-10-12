import { Link, useNavigate } from 'react-router-dom';
import * as I from './Icons';
import { chatTitle, groupLabel, sortRecent, type ChatSummary } from '../lib/chats';

export default function ChatList({ chats, current }: { chats: ChatSummary[]; current?: string }) {
  const nav = useNavigate(); const sorted = sortRecent(chats);
  const groups = (['Today', 'Yesterday', 'Earlier'] as const).map(label => ({ label, items: sorted.filter(c => groupLabel(c) === label) })).filter(g => g.items.length);
  return (
    <nav className="chatlist panel" aria-label="Chats">
      <button className="btn primary newchat" onClick={() => nav('/chat')}><I.Plus width={16} height={16} /> New chat</button>
      {groups.map(g => (
        <div key={g.label}><h4>{g.label}</h4>
          {g.items.map(c => (
            <Link key={c.id} to={`/chat/${c.id}`} className="chatitem" aria-current={c.id === current ? 'page' : undefined}>
              <span className="ct">{chatTitle(c)}</span>{c.active > 0 && <span className="dot-s running" title="Working" />}
            </Link>))}
        </div>))}
      {!sorted.length && <p className="faint small" style={{ padding: 8 }}>No chats yet. Start one with the box on the right.</p>}
    </nav>);
}
