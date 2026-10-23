import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Composer from '../components/Composer';
import ChatActions from '../components/ChatActions';
import { loadMessages, refreshFinished, type Message as Msg } from '../lib/conversations';
import type { ChatSummary } from '../lib/chats';
import AgentResponse, { type ReplyLayout } from '../components/response/AgentResponse';
import ActivityPanel from '../components/ActivityPanel';
import AgentThinking, { type ThreadTask } from '../components/AgentThinking';
import ChatQuestion from '../components/ChatQuestion';
import { ChatActionsContext } from '../lib/chatActions';
import BlockView from '../components/genui/BlockView';
import { api } from '../lib/api';
import { download } from './Files';
import { humanSize, type ArtifactRow } from '../lib/files';
import type { Block } from '../lib/genui/schema';
import { isActive } from '../lib/tasks';
import { useData } from '../state/data';
import Orb from '../components/Orb';
import SceneBackground from '../components/SceneBackground';
import { Emojified } from '../components/Emoji';

/** `next`, unless it is identical to `prev`, in which case `prev`: React then skips the update. */
const same = <T,>(prev: T, next: T): T => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next);

export default function Chat() {
  const { id } = useParams(); const nav = useNavigate(); const { refresh, chats, refreshChats, app } = useData();
  const [msgs, setMsgs] = useState<Msg[]>([]); const [tasks, setTasks] = useState<ThreadTask[]>([]);
  const [blocks, setBlocks] = useState<Block[]>([]); const [err, setErr] = useState(''); const [loaded, setLoaded] = useState(false);
  const [detail, setDetail] = useState<ChatSummary | null>(null);
  const threadId = useRef(id); threadId.current = id; const loadVersion = useRef(0); const cachedMessages = useRef<Msg[]>([]); const settled = useRef<Set<string>>(new Set());
  const stick = useRef(true); const [newBelow, setNewBelow] = useState(false);
  const onTranscriptScroll = (el: HTMLDivElement) => { stick.current = el.scrollHeight - el.clientHeight - el.scrollTop < 260; if (stick.current) setNewBelow(false); };
  const bottom = useRef<HTMLDivElement>(null); const lastCount = useRef(0);

  const loadList = refreshChats;
  const loadThread = useCallback(async () => {
    const version = ++loadVersion.current;
    const currentLoad = () => threadId.current === id && loadVersion.current === version;
    if (!id) { setMsgs([]); setTasks([]); setBlocks([]); setDetail(null); setErr(''); setLoaded(true); return; }
    try {
      const [m, b, c] = await Promise.all([
        loadMessages(id, cachedMessages.current.at(-1)?.id ?? 0, currentLoad),
        api<{ blocks: Block[] }>('GET', `/v1/conversations/${id}/blocks`),
        api<{ conversation: ChatSummary }>('GET', `/v1/conversations/${id}`),
      ]);
      if (!currentLoad()) return;
      // A refresh while a task runs usually changes nothing: keep the same objects so the thread does not re-render (that froze scrolling).
      const firstRead = cachedMessages.current.length === 0;
      if (m.messages.length) { cachedMessages.current = [...cachedMessages.current, ...m.messages]; setMsgs(cachedMessages.current); }
      if (firstRead) m.tasks.forEach(t => { if (!isActive(t)) settled.current.add(t.id); });          // read after they finished: already final
      else {
        const merged = await refreshFinished(id, cachedMessages.current, m.tasks, settled.current, t => !isActive(t), currentLoad);
        if (merged) { cachedMessages.current = merged; setMsgs(merged); }
      }
      setTasks(prev => same(prev, [...m.tasks].sort((a, b) => a.created_epoch - b.created_epoch))); setBlocks(prev => same(prev, b.blocks)); setDetail(prev => same(prev, c.conversation)); setErr(''); setLoaded(true);
    } catch { if (currentLoad()) { setErr('This chat could not be loaded. Please try again.'); setLoaded(true); } }
  }, [id]);
  const reload = useCallback(() => { void loadThread(); void loadList(); void refresh(); }, [loadThread, loadList, refresh]);

  useEffect(() => { cachedMessages.current = []; settled.current = new Set(); setMsgs([]); setTasks([]); setBlocks([]); setDetail(null); setErr(''); setLoaded(false); lastCount.current = 0; stick.current = true; setNewBelow(false); void loadThread(); return () => { ++loadVersion.current; }; }, [loadThread]);
  useEffect(() => { void loadList(); }, [loadList]);
  const drafting = blocks.some(b => b.status === 'submitted');
  const working = tasks.some(t => isActive(t)) || drafting || blocks.some(b => b.run_status === 'running');
  useEffect(() => { if (!working) return; const t = setInterval(() => { void loadThread(); void loadList(); }, 2500); return () => clearInterval(t); }, [working, loadThread, loadList]);
  useEffect(() => { if (msgs.length !== lastCount.current) { lastCount.current = msgs.length; if (stick.current) bottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); else setNewBelow(true); } }, [msgs.length, tasks.length]);

  const [activityId, setActivityId] = useState<string | null>(null);
  const latest = [...tasks].reverse().find(t => isActive(t)) ?? tasks[tasks.length - 1];
  const toggleActivity = useCallback(() => setActivityId(cur => (cur ? null : latest?.id ?? null)), [latest?.id]);
  useEffect(() => { setActivityId(null); }, [id]);
  useEffect(() => { const k = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); toggleActivity(); } }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [toggleActivity]);
  const shown = tasks.find(t => t.id === activityId);
  const [made, setMade] = useState<ArtifactRow[]>([]);
  useEffect(() => {                                    // files Lumina wrote during each answer, shown under that answer
    if (!id || !app?.features.files || working || !msgs.length) return; let stop = false;
    api<{ projects: { id: string }[] }>('GET', '/v1/projects').then(async ({ projects }) => {
      const r = await Promise.all(projects.map(p => api<{ artifacts: ArtifactRow[] }>('GET', `/v1/projects/${p.id}/files`)));
      if (!stop) setMade(r.flatMap(x => x.artifacts));
    }).catch(() => { /* chips are optional */ });
    return () => { stop = true; };
  }, [id, app?.features.files, working, msgs.length]);
  const cancel = async (taskId: string) => { try { await api('POST', `/v1/requests/${taskId}/cancel`, {}); } finally { reload(); } };
  const [renaming, setRenaming] = useState(false);
  const rename = async (title: string) => { setRenaming(false); const t = title.trim(); if (t && t !== current?.title && id) { try { await api('POST', `/v1/conversations/${id}/rename`, { title: t }); await loadList(); } catch { /* keep old name */ } } };
  const byRequest = new Map(tasks.map(t => [t.id, t]));
  const current = chats.find(c => c.id === id) ?? detail;

  const cardActions = useMemo(() => ({
    send: async (message: string) => { if (!id) throw new Error('no chat'); try { await api('POST', `/v1/conversations/${id}/send`, { message, key: crypto.randomUUID().replace(/-/g, ''), mode: 'auto' }); } finally { reload(); } },
  }), [id, reload]);
  /** The layout JEV chose for a plain-text reply (a `display` block anchored to it), if any. Unknown values are ignored: the reply then shows as it is. */
  const layoutOf = (messageId: number): ReplyLayout | undefined => {
    const style = (blocks.find(b => b.kind === 'display' && b.anchor_message_id === messageId)?.spec as { style?: string } | undefined)?.style;
    return style === 'steps' || style === 'answer' || style === 'list' ? style : undefined;
  };
  const fresh = !id || (loaded && !msgs.length && !err);          // nothing said yet: the composer floats in the middle, then settles at the bottom
  const sent = (r: any) => {
    if (id) { reload(); return; }
    setMsgs([{ id: -1, request_id: r.id ?? null, provenance: 'customer', content: r.message ?? '', created_at: '' }]); setLoaded(true);   // show the message at once while the chat opens
    void nav(`/chat/${r.conversation_id}`);
  };

  return (
    <div className="chatpage">
      <SceneBackground task={latest} ready={loaded || !id} />
      <section className={`thread-col${fresh ? ' fresh' : ''}`}>
        {id && !fresh && <header className="thread-head">{renaming ? <input className="rename" autoFocus defaultValue={current?.title ?? ''} maxLength={90} aria-label="Chat name" onBlur={e => rename(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setRenaming(false); }} /> : <h1 title="Click to rename" onClick={() => msgs.length > 0 && setRenaming(true)}>{current?.title || 'Chat'}</h1>}{latest && <button className="btn small act-btn" onClick={toggleActivity} title="Ctrl+J">Activity</button>}{latest && isActive(latest.state) && <button className="btn small danger" onClick={() => cancel(latest.id)}>Stop</button>}{current && <ChatActions chat={current} onChanged={action => { void loadList(); if (action === 'archive') void nav('/history'); else void loadThread(); }} />}</header>}
        {err && <p className="err" role="alert">{err} <button className="btn small" onClick={loadThread}>Retry</button></p>}
        <ChatActionsContext.Provider value={cardActions}>
        <div className="thread" role="region" aria-label="Conversation" tabIndex={0} aria-live="polite" onScroll={e => onTranscriptScroll(e.currentTarget)}>
          {id && !loaded && <p className="muted">Loading…</p>}
          {msgs.map(m => (
            <div key={m.id} className="turn">
              <div className={`bubble ${m.provenance === 'agent' ? 'agent' : 'you'}`}>{m.provenance === 'agent' ? <AgentResponse content={m.content} layout={layoutOf(m.id)} cardsStored={blocks.some(b => b.anchor_message_id === m.id && b.kind !== 'display')} /> : <Emojified text={m.content} />}</div>
              {m.provenance !== 'agent' && m.request_id && byRequest.get(m.request_id) && <AgentThinking task={byRequest.get(m.request_id)!} />}
              {m.provenance !== 'agent' && m.request_id && byRequest.get(m.request_id) && isActive(byRequest.get(m.request_id)!) && <ChatQuestion taskId={m.request_id} active onChanged={reload} />}
              {m.provenance === 'agent' && m.request_id && (() => { const mine = [...new Map(made.filter(a => a.task_id === m.request_id).map(a => [a.display_name, a])).values()]; return mine.length > 0 && (
                <div className="filechips" aria-label="Files from this answer">{mine.map(a => <button key={a.display_name} className="chip small" title={humanSize(a.size_bytes)} onClick={() => download(a.id, a.version).catch(() => undefined)}>⬇ {a.display_name}</button>)}</div>); })()}
              {blocks.filter(b => b.anchor_message_id === m.id).map(b => <BlockView key={b.id} block={b} onChanged={reload} />)}
            </div>))}
          {drafting && !tasks.some(t => isActive(t)) && <div className="agent-thinking" role="status" data-orb-state="weaving"><Orb state="weaving" size={48} /><span>Planning…</span></div>}
          {blocks.filter(b => !msgs.some(m => m.id === b.anchor_message_id)).map(b => <BlockView key={b.id} block={b} onChanged={reload} />)}
          <div ref={bottom} />
        </div>
        </ChatActionsContext.Provider>
        {newBelow && <button className="jump-latest btn" onClick={() => { stick.current = true; setNewBelow(false); bottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); }}>Jump to latest ↓</button>}
        <div className="dock"><div className="greeting" aria-hidden={!fresh}>{fresh && <Orb state="breathing" size={64} />}<h1>What should we work on?</h1></div>{current?.archived_epoch ? <div className="archived-chat"><p>This chat is archived. Restore it to continue.</p><button className="btn primary" onClick={async () => { try { await api('POST', `/v1/conversations/${id}/restore`, {}); reload(); } catch { setErr('Could not restore this chat.'); } }}>Restore chat</button></div> : !err && <Composer key={id || 'new'} conversationId={id} autoFocus onSent={sent} />}</div>
      </section>
    {shown && <ActivityPanel taskId={shown.id} active={isActive(shown)} startedAt={shown.created_epoch} onStop={() => cancel(shown.id)} onClose={() => setActivityId(null)} />}
    </div>);
}
