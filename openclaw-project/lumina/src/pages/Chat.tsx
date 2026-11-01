import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Composer from '../components/Composer';
import ChatActions from '../components/ChatActions';
import BrowserToggle from '../components/BrowserToggle';
import { loadMessages, type Message as Msg } from '../lib/conversations';
import type { ChatSummary } from '../lib/chats';
import AgentResponse from '../components/response/AgentResponse';
import WorkTrail from '../components/response/WorkTrail';
import { foldTrail } from '../lib/trail';
import { LiveRun } from './Live';
import AgentThinking, { type ThreadTask } from '../components/AgentThinking';
import BlockView from '../components/genui/BlockView';
import type { Bridge } from '../gen/ChatBridge';
import { getAnswerStyle } from '../lib/answerStyle';
import { api } from '../lib/api';
import { download } from './Files';
import { humanSize, type ArtifactRow } from '../lib/files';
import type { Block } from '../lib/genui/schema';
import { isActive } from '../lib/tasks';
import { useData } from '../state/data';
import Orb from '../components/Orb';
import { Emojified } from '../components/Emoji';

/** `next`, unless it is identical to `prev`, in which case `prev`: React then skips the update. */
const same = <T,>(prev: T, next: T): T => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next);

export default function Chat() {
  const { id } = useParams(); const nav = useNavigate(); const { refresh, chats, refreshChats, app } = useData();
  const [msgs, setMsgs] = useState<Msg[]>([]); const [tasks, setTasks] = useState<ThreadTask[]>([]);
  const [blocks, setBlocks] = useState<Block[]>([]); const [err, setErr] = useState(''); const [loaded, setLoaded] = useState(false);
  const [detail, setDetail] = useState<ChatSummary | null>(null);
  const threadId = useRef(id); threadId.current = id; const loadVersion = useRef(0); const cachedMessages = useRef<Msg[]>([]);
  const stick = useRef(true); const [newBelow, setNewBelow] = useState(false);
  useEffect(() => { const onScroll = () => { stick.current = document.documentElement.scrollHeight - window.innerHeight - window.scrollY < 260; if (stick.current) setNewBelow(false); }; window.addEventListener('scroll', onScroll, { passive: true }); return () => window.removeEventListener('scroll', onScroll); }, []);
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
      if (m.messages.length) { cachedMessages.current = [...cachedMessages.current, ...m.messages]; setMsgs(cachedMessages.current); }
      setTasks(prev => same(prev, [...m.tasks].sort((a, b) => a.created_epoch - b.created_epoch))); setBlocks(prev => same(prev, b.blocks)); setDetail(prev => same(prev, c.conversation)); setErr(''); setLoaded(true);
    } catch { if (currentLoad()) { setErr('This chat could not be loaded. Please try again.'); setLoaded(true); } }
  }, [id]);
  const reload = useCallback(() => { void loadThread(); void loadList(); void refresh(); }, [loadThread, loadList, refresh]);
  const bridge = useMemo<Bridge>(() => ({ conversationId: id ?? '', tasks: tasks as unknown as Bridge['tasks'], blocks, reload }), [id, tasks, blocks, reload]);

  useEffect(() => { cachedMessages.current = []; setMsgs([]); setTasks([]); setBlocks([]); setDetail(null); setErr(''); setLoaded(false); lastCount.current = 0; stick.current = true; setNewBelow(false); void loadThread(); return () => { ++loadVersion.current; }; }, [loadThread]);
  useEffect(() => { void loadList(); }, [loadList]);
  const drafting = blocks.some(b => b.status === 'submitted');
  const working = tasks.some(t => isActive(t)) || drafting || blocks.some(b => b.run_status === 'running');
  useEffect(() => { if (!working) return; const t = setInterval(() => { void loadThread(); void loadList(); }, 2500); return () => clearInterval(t); }, [working, loadThread, loadList]);
  useEffect(() => { if (msgs.length !== lastCount.current) { lastCount.current = msgs.length; if (stick.current) bottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); else setNewBelow(true); } }, [msgs.length, tasks.length]);

  const [activityId, setActivityId] = useState<string | null>(null);
  const latest = tasks.find(t => ['starting', 'running', 'uncertain'].includes(t.state)) ?? [...tasks].reverse().find(t => isActive(t)) ?? tasks[tasks.length - 1];
  const toggleActivity = useCallback(() => setActivityId(cur => (cur ? null : latest?.id ?? null)), [latest?.id]);
  useEffect(() => { setActivityId(null); }, [id]);
  useEffect(() => { const k = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); toggleActivity(); } }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [toggleActivity]);
  const [made, setMade] = useState<ArtifactRow[]>([]);
  useEffect(() => {                                    // files Lumina wrote during each answer, shown under that answer
    if (!id || !app?.features.files || working || !msgs.length) return; let stop = false;
    api<{ projects: { id: string }[] }>('GET', '/v1/projects').then(async ({ projects }) => {
      const r = await Promise.all(projects.map(p => api<{ artifacts: ArtifactRow[] }>('GET', `/v1/projects/${p.id}/files`)));
      if (!stop) setMade(r.flatMap(x => x.artifacts));
    }).catch(() => { /* chips are optional */ });
    return () => { stop = true; };
  }, [id, app?.features.files, working, msgs.length]);
  const [stopping, setStopping] = useState<string | null>(null);
  useEffect(() => { setStopping(null); }, [id]);
  const cancel = async (taskId: string) => {
    setStopping(taskId);
    try {
      await api('POST', `/v1/requests/${taskId}/cancel`, {});
      if (threadId.current === id) setTasks(ts => ts.map(t => t.id === taskId ? { ...t, cancel_requested: true } : t));
    } catch { if (threadId.current === id) setErr('Could not stop this task. Please try again.'); }
    finally { if (threadId.current === id) { setStopping(null); reload(); } }
  };
  const byRequest = new Map(tasks.map(t => [t.id, t]));
  const trail = useMemo(() => foldTrail(msgs, rid => { const t = byRequest.get(rid); return !!t && !isActive(t); }, m => blocks.some(b => b.anchor_message_id === m.id) || made.some(a => a.task_id === m.request_id)), [msgs, tasks, blocks, made]);   // eslint-disable-line react-hooks/exhaustive-deps
  const current = chats.find(c => c.id === id) ?? detail;

  const askAgain = async (message: string) => { if (!id) return; try { await api('POST', `/v1/conversations/${id}/send`, { message, key: crypto.randomUUID().replace(/-/g, ''), mode: 'text', ui: getAnswerStyle() }); } finally { reload(); } };
  const lastAgent = [...msgs].reverse().find(m => m.provenance === 'agent');
  const fresh = !id || (loaded && !msgs.length && !err);          // nothing said yet: the composer floats in the middle, then settles at the bottom
  const sent = (r: any) => {
    if (id) { reload(); return; }
    setMsgs([{ id: -1, request_id: r.id ?? null, provenance: 'customer', content: r.message ?? '', created_at: '' }]); setLoaded(true);   // show the message at once while the chat opens
    void nav(`/chat/${r.conversation_id}`);
  };

  return (
    <div className="chatpage">
      <section className={`thread-col${fresh ? ' fresh' : ''}`}>
        <div className="thread-tools"><BrowserToggle />{current && <ChatActions chat={current} onChanged={action => { void loadList(); if (action === 'archive') void nav('/history'); else void loadThread(); }} />}</div>
        {err && <p className="err" role="alert">{err} <button className="btn small" onClick={loadThread}>Retry</button></p>}
        <div className="thread" aria-live="polite">
          {id && !loaded && <p className="muted">Loading…</p>}
          {msgs.map(m => trail.skip.has(m.id) ? (trail.hidden.has(m.id) ? <div key={m.id} className="turn"><WorkTrail messages={trail.hidden.get(m.id)!} /></div> : null) : (
            <div key={m.id} className="turn">
              {!m.ui_answer && <div className={`bubble ${m.provenance === 'agent' || m.provenance === 'system' ? 'agent' : 'you'}`}>{m.provenance === 'agent' || m.provenance === 'system' ? <AgentResponse content={m.content} /> : <Emojified text={m.content} />}</div>}
              {['customer', 'telegram'].includes(m.provenance) && m.request_id && byRequest.get(m.request_id) && !msgs.some(next => next.id > m.id && next.request_id === m.request_id && ['customer', 'telegram'].includes(next.provenance)) && (
                <div className="chat-work">
                  <AgentThinking task={{ ...byRequest.get(m.request_id)!, cancel_requested: stopping === m.request_id || byRequest.get(m.request_id)!.cancel_requested }} />
                  <button className="btn tertiary small read-more" aria-expanded={activityId === m.request_id} aria-controls={`activity-${m.request_id}`} onClick={() => setActivityId(cur => cur === m.request_id ? null : m.request_id)}>{activityId === m.request_id ? 'Read less' : 'Read more'}</button>
                  {activityId === m.request_id && <section className="chat-activity" id={`activity-${m.request_id}`} aria-label="Live task activity"><LiveRun key={m.request_id} id={m.request_id} inline taskState={byRequest.get(m.request_id)!.state} /></section>}
                </div>)}
              {m.provenance === 'agent' && m.request_id && (() => { const mine = [...new Map(made.filter(a => a.task_id === m.request_id).map(a => [a.display_name, a])).values()]; return mine.length > 0 && (
                <div className="filechips" aria-label="Files from this answer">{mine.map(a => <button key={a.display_name} className="chip small" title={humanSize(a.size_bytes)} onClick={() => download(a.id, a.version).catch(() => undefined)}>⬇ {a.display_name}</button>)}</div>); })()}
              {blocks.filter(b => b.anchor_message_id === m.id).map(b => <BlockView key={b.id} block={b} onChanged={reload} bridge={bridge} />)}
              {m === lastAgent && !working && m.id > 0 && m.content.length > 160 && !blocks.some(b => b.anchor_message_id === m.id) && (
                <div className="quick" aria-label="Show this differently">
                  <button className="chip small" onClick={() => askAgain('Show your last answer as a table.')}>Show as table</button>
                  <button className="chip small" onClick={() => askAgain('Show your last answer as a chart.')}>Show as chart</button>
                  <button className="chip small" onClick={() => askAgain('Compare the options from your last answer side by side.')}>Compare side by side</button>
                </div>)}
            </div>))}
          {drafting && !tasks.some(t => isActive(t)) && <div className="agent-thinking" role="status" data-orb-state="weaving"><Orb state="weaving" size={48} /><span>Planning…</span></div>}
          {blocks.filter(b => !msgs.some(m => m.id === b.anchor_message_id)).map(b => <BlockView key={b.id} block={b} onChanged={reload} bridge={bridge} />)}
          <div ref={bottom} />
        </div>
        {newBelow && <button className="jump-latest btn" onClick={() => { stick.current = true; setNewBelow(false); bottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); }}>Jump to latest ↓</button>}
        <div className="dock"><div className="greeting" aria-hidden={!fresh}>{fresh && <Orb state="lumina" size={64} />}<h1>What should we work on?</h1></div>{current?.archived_epoch ? <div className="archived-chat"><p>This chat is archived. Restore it to continue.</p><button className="btn primary" onClick={async () => { try { await api('POST', `/v1/conversations/${id}/restore`, {}); reload(); } catch { setErr('Could not restore this chat.'); } }}>Restore chat</button></div> : !err && <Composer key={id || 'new'} conversationId={id} autoFocus onSent={sent} onStop={latest && isActive(latest) ? () => { void cancel(latest.id); } : undefined} stopping={!!latest && (stopping === latest.id || !!latest.cancel_requested)} />}</div>
      </section>
    </div>);
}
