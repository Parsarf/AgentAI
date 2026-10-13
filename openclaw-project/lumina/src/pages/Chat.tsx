import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Composer from '../components/Composer';
import AgentResponse from '../components/response/AgentResponse';
import ActivityPanel from '../components/ActivityPanel';
import TaskStrip, { type ThreadTask } from '../components/TaskStrip';
import BlockView from '../components/genui/BlockView';
import { api } from '../lib/api';
import type { Block } from '../lib/genui/schema';
import { isActive } from '../lib/tasks';
import { useData } from '../state/data';

interface Msg { id: number; request_id: string | null; provenance: string; content: string; created_at: string }

export default function Chat() {
  const { id } = useParams(); const nav = useNavigate(); const { refresh, chats, refreshChats } = useData();
  const [msgs, setMsgs] = useState<Msg[]>([]); const [tasks, setTasks] = useState<ThreadTask[]>([]);
  const [blocks, setBlocks] = useState<Block[]>([]); const [err, setErr] = useState(''); const [loaded, setLoaded] = useState(false);
  const bottom = useRef<HTMLDivElement>(null); const lastCount = useRef(0);

  const loadList = refreshChats;
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

  const [activityId, setActivityId] = useState<string | null>(null);
  const latest = [...tasks].reverse().find(t => isActive(t.state)) ?? tasks[tasks.length - 1];
  const toggleActivity = useCallback(() => setActivityId(cur => (cur ? null : latest?.id ?? null)), [latest?.id]);
  useEffect(() => { setActivityId(null); }, [id]);
  useEffect(() => { const k = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); toggleActivity(); } }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [toggleActivity]);
  const shown = tasks.find(t => t.id === activityId);
  const cancel = async (taskId: string) => { try { await api('POST', `/v1/requests/${taskId}/cancel`, {}); } finally { reload(); } };
  const [renaming, setRenaming] = useState(false);
  const rename = async (title: string) => { setRenaming(false); const t = title.trim(); if (t && t !== current?.title && id) { try { await api('POST', `/v1/conversations/${id}/rename`, { title: t }); await loadList(); } catch { /* keep old name */ } } };
  const clear = async () => { if (id) { await api('POST', `/v1/conversations/${id}/archive`, {}); await loadList(); nav('/chat'); } };
  const byRequest = new Map(tasks.map(t => [t.id, t]));
  const current = chats.find(c => c.id === id);

  const askAgain = async (message: string) => { if (!id) return; try { await api('POST', `/v1/conversations/${id}/send`, { message, key: crypto.randomUUID().replace(/-/g, ''), mode: 'text' }); } finally { reload(); } };
  const lastAgent = [...msgs].reverse().find(m => m.provenance === 'agent');
  const fresh = !id || (loaded && !msgs.length && !err);          // nothing said yet: the composer floats in the middle, then settles at the bottom
  const sent = (r: any) => {
    if (id) { reload(); return; }
    setMsgs([{ id: -1, request_id: r.id ?? null, provenance: 'customer', content: r.message ?? '', created_at: '' }]); setLoaded(true);   // show the message at once while the chat opens
    nav(`/chat/${r.conversation_id}`);
  };

  return (
    <div className="chatpage">
      <section className={`thread-col${fresh ? ' fresh' : ''}`}>
        {id && !fresh && <header className="thread-head">{renaming ? <input className="rename" autoFocus defaultValue={current?.title ?? ''} maxLength={90} aria-label="Chat name" onBlur={e => rename(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setRenaming(false); }} /> : <h1 title="Click to rename" onClick={() => msgs.length > 0 && setRenaming(true)}>{current?.title || 'Chat'}</h1>}{latest && <button className="btn small act-btn" onClick={toggleActivity} title="Ctrl+J">Activity</button>}{msgs.length > 0 && <button className="btn small" onClick={clear}>Clear chat</button>}</header>}
        {err && <p className="err" role="alert">{err}</p>}
        <div className="thread" aria-live="polite">
          {id && !loaded && <p className="muted">Loading…</p>}
          {msgs.map(m => (
            <div key={m.id} className="turn">
              <div className={`bubble ${m.provenance === 'agent' ? 'agent' : 'you'}`}>{m.provenance === 'agent' ? <AgentResponse content={m.content} /> : m.content}</div>
              {m.provenance !== 'agent' && m.request_id && byRequest.get(m.request_id) && <TaskStrip task={byRequest.get(m.request_id)!} onCancel={() => cancel(m.request_id!)} onActivity={() => setActivityId(m.request_id!)} />}
              {blocks.filter(b => b.anchor_message_id === m.id).map(b => <BlockView key={b.id} block={b} onChanged={reload} />)}
              {m === lastAgent && !working && m.id > 0 && m.content.length > 160 && !blocks.some(b => b.anchor_message_id === m.id) && (
                <div className="quick" aria-label="Show this differently">
                  <button className="chip small" onClick={() => askAgain('Show your last answer as a table.')}>Show as table</button>
                  <button className="chip small" onClick={() => askAgain('Show your last answer as a chart.')}>Show as chart</button>
                  <button className="chip small" onClick={() => askAgain('Compare the options from your last answer side by side.')}>Compare side by side</button>
                </div>)}
            </div>))}
          {drafting && <div className="bubble agent"><span className="muted">Drafting your plan…</span></div>}
          {blocks.filter(b => !msgs.some(m => m.id === b.anchor_message_id)).map(b => <BlockView key={b.id} block={b} onChanged={reload} />)}
          <div ref={bottom} />
        </div>
        <div className="dock"><h1 className="greeting" aria-hidden={!fresh}>What should we work on?</h1><Composer conversationId={id} autoFocus onSent={sent} /></div>
      </section>
    {shown && <ActivityPanel taskId={shown.id} active={isActive(shown.state)} startedAt={shown.created_epoch} onStop={() => cancel(shown.id)} onClose={() => setActivityId(null)} />}
    </div>);
}
