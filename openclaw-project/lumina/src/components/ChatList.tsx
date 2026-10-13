import { Link } from 'react-router-dom';
import { chatTitle, groupLabel, sortRecent, type ChatSummary } from '../lib/chats';

/** Grouped, minimal chat history. Lives in the sidebar (and in the phone drawer). */
export default function ChatList({ chats, current, onPick }: { chats: ChatSummary[]; current?: string; onPick?: () => void }) {
  const sorted = sortRecent(chats);
  const groups = (['Today', 'Yesterday', 'Earlier'] as const).map(label => ({ label, items: sorted.filter(c => groupLabel(c) === label) })).filter(g => g.items.length);
  if (!sorted.length) return <p className="faint small chat-empty">Your chats will appear here.</p>;
  return (
    <div className="chatlist" role="list" aria-label="Chat history">
      {groups.map(g => (
        <div key={g.label} role="listitem"><h4>{g.label}</h4>
          {g.items.map(c => (
            <Link key={c.id} to={`/chat/${c.id}`} className="chatitem" aria-current={c.id === current ? 'page' : undefined} onClick={onPick}>
              <span className="ct">{chatTitle(c)}</span>{c.active > 0 && <span className="dot-s running" title="Working" />}
            </Link>))}
        </div>))}
    </div>);
}
