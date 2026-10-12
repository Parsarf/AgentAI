import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import ChatList from '../components/ChatList';
import Composer from '../components/Composer';
import TaskStrip, { type ThreadTask } from '../components/TaskStrip';
import BlockView from '../components/genui/BlockView';
import { api } from '../lib/api';
import type { ChatSummary } from '../lib/chats';
import type { Block } from '../lib/genui/schema';
import { isActive } from '../lib/tasks';
import { useData } from '../state/data';

interface Msg { id: number; request_id: string | null; provenance: string; content: string; created_at: string }

export default function Chat() {
  const { id } = useParams(); const nav = useNavigate(); const { refresh } = useData();
  const [chats, setChats] = useState<ChatSummary[]>([]); const [msgs, setMsgs] = useState<Msg[]>([]); const [tasks, setTasks] = useState<ThreadTask[]>([]);
  const [blocks, setBlocks] = useState<Block[]>([]); const [err, setErr] = useState(''); const [loaded, setLoaded] = useState(false);
  const bottom = useRef<HTMLDivElement>(null); const lastCount = useRef(0);

  const loadList = useCallback(async () => {
    try { setChats((await api<{ conversations: ChatSummary[] }>('GET', '/v1/conversations')).conversations); } catch { /* keep the old list */ }
  }, []);
  const loadThread = useCallback(async () => {
    if (!id) { setMsgs([]); setTasks([]); setBlocks([]); setLoaded(true); return; }
    try {
      const [m, b] = await Promise.all([api<{ messages: Msg[]; tasks: ThreadTask[] }>('GET', `/v1/conversations/${id}/messages`), api<{ blocks: Block[] }>('GET', `/v1/conversations/${id}/blocks`)]);
      setMsgs(m.messages); setTasks(m.tasks); setBlocks(b.blocks); setErr(''); setLoaded(true);
    } catch { setErr('This chat is not available.'); setLoaded(true); }
  }, [id]);
  const reload = useCallback(() => { loadThread(); loadList(); refresh(); }, [loadThread, loadList, refresh]);

  useEffect(() => { setLoaded(false); lastCount.current = 0; loadThread(); }, [loadThread]);
  useEffect(() => { loadList(); }, [loadList]);
  const drafting = blocks.some(b => b.status === 'submitted');
  const working = tasks.some(t => isActive(t.state)) || drafting || blocks.some(b => b.run_status === 'running');
  useEffect(() => { if (!working) return; const t = setInterval(() => { loadThread(); loadList(); }, 2500); return () => clearInterval(t); }, [working, loadThread, loadList]);
  useEffect(() => { if (msgs.length !== lastCount.current) { lastCount.current = msgs.length; bottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); } }, [msgs.length, tasks.length]);

  const cancel = async (taskId: string) => { try { await api('POST', `/v1/requests/${taskId}/cancel`, {}); } finally { reload(); } };
  const [renaming, setRenaming] = useState(false);
  const rename = async (title: string) => { setRenaming(false); const t = title.trim(); if (t && t !== current?.title && id) { try { await api('POST', `/v1/conversations/${id}/rename`, { title: t }); await loadList(); } catch { /* keep old name */ } } };
  const clear = async () => { if (id) { await api('POST', `/v1/conversations/${id}/archive`, {}); await loadList(); nav('/chat'); } };
  const byRequest = new Map(tasks.map(t => [t.id, t]));
  const current = chats.find(c => c.id === id);

  return (
    <div className="chatpage">
      <ChatList chats={chats} current={id} />
      <section className="thread-col">
        {!id ? (
          <div className="newchat-view">
            <h1 className="page-title" style={{ padding: '8px 0 6px' }}>New chat</h1>
            <p className="muted" style={{ marginBottom: 18 }}>Ask a question, or describe a task. You can keep chatting while it runs, and every chat is saved on the left.</p>
            <Composer autoFocus onSent={r => nav(`/chat/${r.conversation_id}`)} />
          </div>
        ) : (
          <>
            <header className="thread-head">{renaming ? <input className="rename" autoFocus defaultValue={current?.title ?? ''} maxLength={90} aria-label="Chat name" onBlur={e => rename(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setRenaming(false); }} /> : <h1 title="Click to rename" onClick={() => msgs.length > 0 && setRenaming(true)}>{current?.title || 'Chat'}</h1>}{msgs.length > 0 && <button className="btn small" onClick={clear}>Clear chat</button>}</header>
            {err && <p className="err" role="alert">{err}</p>}
            <div className="thread" aria-live="polite">
              {!loaded && <p className="muted">Loading…</p>}
              {msgs.map(m => (
                <div key={m.id} className="turn">
                  <div className={`bubble ${m.provenance === 'agent' ? 'agent' : 'you'}`}><small>{m.provenance === 'agent' ? 'Lumina' : 'You'}</small>{m.content}</div>
                  {m.provenance !== 'agent' && m.request_id && byRequest.get(m.request_id) && <TaskStrip task={byRequest.get(m.request_id)!} onCancel={() => cancel(m.request_id!)} />}
                  {blocks.filter(b => b.anchor_message_id === m.id).map(b => <BlockView key={b.id} block={b} onChanged={reload} />)}
                </div>))}
              {drafting && <div className="bubble agent"><small>Lumina</small><span className="muted">Drafting your plan…</span></div>}
              {blocks.filter(b => !msgs.some(m => m.id === b.anchor_message_id)).map(b => <BlockView key={b.id} block={b} onChanged={reload} />)}
              {loaded && !msgs.length && !err && <div className="empty">Nothing here yet. Send a message below.</div>}
              <div ref={bottom} />
            </div>
            <div className="thread-composer"><Composer conversationId={id} autoFocus onSent={() => reload()} /></div>
          </>)}
      </section>
    </div>);
}
