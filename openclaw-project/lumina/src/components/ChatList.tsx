import ChatActions from './ChatActions';
import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { chatTitle, groupLabel, sortRecent, type ChatSummary } from '../lib/chats';

/** Grouped, minimal chat history, in Chat's context column. Grouped by project when `projects` is given (more than one exists), by day otherwise. */
export default function ChatList({ chats, current, onPick, onChanged, projects }: { chats: ChatSummary[]; current?: string; onPick?: () => void; onChanged?: (action: 'rename' | 'archive' | 'restore' | 'delete', id: string) => void; projects?: { id: string; name: string }[] }) {
  const nav = useNavigate();
  const sorted = sortRecent(chats);
  const groups: { label: string; items: ChatSummary[] }[] = projects
    ? [...projects.map(p => ({ label: p.name, items: sorted.filter(c => c.project_id === p.id) })), { label: 'Other', items: sorted.filter(c => !projects.some(p => p.id === c.project_id)) }].filter(g => g.items.length)
    : (['Today', 'Yesterday', 'Earlier'] as const).map(label => ({ label, items: sorted.filter(c => groupLabel(c) === label) })).filter(g => g.items.length);
  if (!sorted.length) return <p className="faint small chat-empty">Your chats will appear here.</p>;
  return (
    <div className="chatlist" role="list" aria-label="Chat history">
      {groups.map(g => (
        <div key={g.label} role="listitem"><h4>{g.label}</h4>
          {g.items.map(c => (
            <div key={c.id} className="sidebar-chat-row"><Link to={`/chat/${c.id}`} className="chatitem" aria-current={c.id === current ? 'page' : undefined} onClick={onPick}>
              <span className="ct">{chatTitle(c)}</span>{c.active > 0 && <span className="dot-s running" title="Working" />}
            </Link><ChatActions chat={c} onChanged={action => { onChanged?.(action, c.id); if ((action === 'archive' || action === 'delete') && current === c.id) void nav('/history'); }} /></div>))}
        </div>))}
    </div>);
}
