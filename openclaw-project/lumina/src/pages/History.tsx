import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import ChatActions from '../components/ChatActions';
import { api } from '../lib/api';
import { chatTitle, chatPreview, groupLabel, type ChatSummary } from '../lib/chats';
import { useData } from '../state/data';
interface Listing { conversations: ChatSummary[]; has_more: boolean; next_offset: number }
export default function History() {
  const { refreshChats } = useData(); const [params, setParams] = useSearchParams(); const q = params.get('q') ?? ''; const setQ = (value: string) => setParams(value ? { q: value } : {}, { replace: true }); const [archived, setArchived] = useState(false);
  const [rows, setRows] = useState<ChatSummary[]>([]); const [more, setMore] = useState(false); const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true); const [err, setErr] = useState(''); const [revision, setRevision] = useState(0); const generation = useRef(0);
  useEffect(() => {
    const token = ++generation.current; setLoading(true); setErr(''); setRows([]); setMore(false);
    const timer = setTimeout(async () => {
      try { const r = await api<Listing>('GET', `/v1/conversations?q=${encodeURIComponent(q.trim())}&archived=${archived ? 1 : 0}&limit=50`); if (generation.current !== token) return; setRows(r.conversations); setMore(r.has_more); setOffset(r.next_offset); }
      catch { if (generation.current === token) setErr('Could not load your chat history.'); } finally { if (generation.current === token) setLoading(false); }
    }, q ? 250 : 0);
    return () => { clearTimeout(timer); ++generation.current; };
  }, [q, archived, revision]);
  const loadMore = async () => {
    if (loading) return; const token = generation.current; setLoading(true); setErr('');
    try { const r = await api<Listing>('GET', `/v1/conversations?q=${encodeURIComponent(q.trim())}&archived=${archived ? 1 : 0}&limit=50&offset=${offset}`); if (token !== generation.current) return; setRows(old => [...old, ...r.conversations]); setMore(r.has_more); setOffset(r.next_offset); }
    catch { if (token === generation.current) setErr('Could not load more chats.'); } finally { if (token === generation.current) setLoading(false); }
  };
  return <div className="history-page"><header className="history-head"><div><h1>Chat history</h1><p className="muted">Pick up where you left off.</p></div><Link to="/chat" className="btn primary">New chat</Link></header>
    <input type="search" className="history-search" autoFocus placeholder="Search titles and messages…" aria-label="Search chat history" value={q} onChange={e => setQ(e.target.value)} />
    <div className="filters" role="group" aria-label="History view"><button className="chip" aria-pressed={!archived} onClick={() => setArchived(false)}>Chats</button><button className="chip" aria-pressed={archived} onClick={() => setArchived(true)}>Archived</button></div>
    {err && <p role="alert" className="err">{err} <button className="btn small" onClick={() => setRevision(v => v + 1)}>Retry</button></p>}
    {(['Today', 'Yesterday', 'Earlier'] as const).map(label => {
      const group = rows.filter(c => groupLabel(c) === label); if (!group.length) return null;
      return <section className="history-group" key={label}><h2>{label}</h2>{group.map(chat => <div className="history-row" key={chat.id}><Link to={`/chat/${chat.id}`}><strong>{chatTitle(chat)}</strong><p>{chatPreview(chat.preview) || 'No messages yet'}</p>{chat.active > 0 && <span className="muted small">Working</span>}</Link><ChatActions chat={chat} onChanged={() => { void refreshChats(); setRevision(v => v + 1); }} /></div>)}</section>;
    })}
    {loading && <p className="muted" role="status">Loading chats…</p>}{!loading && !rows.length && !err && <div className="empty">{q ? 'No chats match your search.' : archived ? 'No archived chats.' : 'Your conversations will appear here after your first message.'}</div>}
    {more && <button className="btn" disabled={loading} onClick={loadMore}>Load more chats</button>}
  </div>;
}
