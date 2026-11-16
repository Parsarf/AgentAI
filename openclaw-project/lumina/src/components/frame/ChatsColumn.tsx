import { useEffect, useMemo, useState } from 'react';
import { Link, useMatch, useNavigate } from 'react-router-dom';
import * as I from '../Icons';
import ChatList from '../ChatList';
import { api } from '../../lib/api';
import { chatTitle } from '../../lib/chats';
import { useData } from '../../state/data';
import { useFrame } from './FrameProvider';

/** Chat's context column: a new chat, a search over titles (Enter searches every message in Chat history), and the conversations grouped by project when there is
 *  more than one, by day otherwise. */
export default function ChatsColumn() {
  const { chats, refreshChats } = useData(); const nav = useNavigate(); const frame = useFrame();
  const match = useMatch('/chat/:id'); const [q, setQ] = useState('');
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => { let stop = false; api<{ projects: { id: string; name: string }[] }>('GET', '/v1/projects').then(r => { if (!stop) setProjects(r.projects ?? []); }).catch(() => undefined); return () => { stop = true; }; }, []);
  const term = q.trim().toLowerCase();
  const shown = useMemo(() => (term ? chats.filter(c => chatTitle(c).toLowerCase().includes(term)) : chats), [chats, term]);
  const picked = () => { if (frame?.sheet === 'context') frame.setSheet(null); };
  return <div className="chats-column">
    <button type="button" className="btn newchat" onClick={() => { picked(); void nav('/chat'); }}><I.Edit width={16} height={16} />New chat</button>
    <form role="search" className="chats-search" onSubmit={e => { e.preventDefault(); if (term) { picked(); void nav(`/history?q=${encodeURIComponent(q.trim())}`); } }}>
      <I.Search width={16} height={16} aria-hidden="true" />
      <input className="input" type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Find a chat" aria-label="Find a chat by its title" />
    </form>
    {term && !shown.length ? <p className="faint small chat-empty">No chat title matches. Press Enter to search every message.</p>
      : <ChatList chats={shown} current={match?.params.id} projects={projects.length > 1 ? projects : undefined} onPick={picked} onChanged={() => refreshChats()} />}
    <Link className="btn tertiary small chats-all" to={term ? `/history?q=${encodeURIComponent(q.trim())}` : '/history'} onClick={picked}>{term ? 'Search every message' : 'All chats and archive'}</Link>
  </div>;
}
