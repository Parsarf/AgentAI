import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Composer from '../components/Composer';
import AppPlayer, { runnableFile } from '../components/apps/AppPlayer';
import ChatActions from '../components/ChatActions';
import BrowserToggle from '../components/BrowserToggle';
import { loadMessages, type Message as Msg } from '../lib/conversations';
import type { ChatSummary } from '../lib/chats';
import AgentResponse from '../components/response/AgentResponse';
import { foldTrail } from '../lib/trail';
import TaskStrip from '../components/work/TaskStrip';
import { useTask, useWork } from '../state/work';
import { isOpen } from '../lib/work';
import BlockView from '../components/genui/BlockView';
import type { Bridge } from '../gen/ChatBridge';
import { getAnswerStyle } from '../lib/answerStyle';
import { api } from '../lib/api';
import { download } from './Files';
import { humanSize, type ArtifactRow } from '../lib/files';
import type { Block } from '../lib/genui/schema';
import { isActive, type ThreadTask } from '../lib/tasks';
import { useData } from '../state/data';
import Orb from '../components/Orb';
import { Emojified } from '../components/Emoji';

/** `next`, unless it is identical to `prev`, in which case `prev`: React then skips the update. */
const same = <T,>(prev: T, next: T): T => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next);

export default function Chat() {
  const { id } = useParams(); const nav = useNavigate(); const { refresh, chats, refreshChats, app } = useData(); const work = useWork();
  const [msgs, setMsgs] = useState<Msg[]>([]); const [tasks, setTasks] = useState<ThreadTask[]>([]);
  const [blocks, setBlocks] = useState<Block[]>([]); const [err, setErr] = useState(''); const [loaded, setLoaded] = useState(false);
  const [detail, setDetail] = useState<ChatSummary | null>(null);
  const threadId = useRef(id); threadId.current = id; const loadVersion = useRef(0); const cachedMessages = useRef<Msg[]>([]);
  const stick = useRef(true); const [newBelow, setNewBelow] = useState(false);
  useEffect(() => { const onScroll = () => { stick.current = document.documentElement.scrollHeight - window.innerHeight - window.scrollY < 260; if (stick.current) setNewBelow(false); }; window.addEventListener('scroll', onScroll, { passive: true }); return () => window.removeEventListener('scroll', onScroll); }, []);
  const bottom = useRef<HTMLDivElement>(null); const lastCount = useRef(0);
  // "The latest" is the true end of the page. Aligning a marker with the bottom edge of the window is not enough: the composer is pinned there and, on a small screen, is tall
  // enough to cover the newest lines (and the page then never counts as being at the bottom).
  const toEnd = useCallback((smooth: boolean) => { window.scrollTo({ top: document.documentElement.scrollHeight, behavior: smooth ? 'smooth' : 'auto' }); }, []);

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

  useEffect(() => { cachedMessages.current = []; setMade([]); setMsgs([]); setTasks([]); setBlocks([]); setDetail(null); setErr(''); setLoaded(false); lastCount.current = 0; stick.current = true; setNewBelow(false); void loadThread(); return () => { ++loadVersion.current; }; }, [loadThread]);
  useEffect(() => { void loadList(); }, [loadList]);
  const drafting = blocks.some(b => b.status === 'submitted');
  // What each task of this chat is doing comes from the shared work state (one source for every screen). The thread's own task rows only say which request a message belongs to;
  // until the shared state has loaded they also stand in for "is anything going on".
  const mine = useMemo(() => work.tasks.filter(t => t.conversation_id === id), [work.tasks, id]);
  const open = mine.filter(isOpen);
  const latestId = (open[0] ?? mine[0])?.id ?? tasks[tasks.length - 1]?.id ?? null;
  const live = useTask(latestId);
  const working = (work.loaded ? open.length > 0 : tasks.some(t => isActive(t))) || drafting || blocks.some(b => b.run_status === 'running');
  // New messages are fetched when the task says it has more (or changed phase), not on a fast timer. The slow timer is only a safety net for blocks and missed signals.
  const messageCount = live.full?.messages; const phase = live.task?.phase;
  const known = useRef<{ id: string | null; count?: number; phase?: string }>({ id: null });
  useEffect(() => {
    const before = known.current; known.current = { id: latestId, count: messageCount, phase };
    if (!latestId || before.id !== latestId) return;                                              // first sight of this task: the thread was just loaded
    if ((before.count !== undefined && messageCount !== before.count) || (before.phase !== undefined && phase !== before.phase)) { void loadThread(); void loadList(); }
  }, [latestId, messageCount, phase, loadThread, loadList]);
  useEffect(() => { if (!working) return; const t = setInterval(() => { void loadThread(); void loadList(); }, work.mode === 'stream' ? 8000 : 3000); return () => clearInterval(t); }, [working, work.mode, loadThread, loadList]);
  useEffect(() => { if (msgs.length !== lastCount.current) { lastCount.current = msgs.length; if (stick.current) toEnd(true); else setNewBelow(true); } }, [msgs.length, tasks.length]);
  const draftLength = live.draft?.text.length ?? 0; const liveLabel = live.task?.label; const liveNeeds = live.task?.needs.length ?? 0; const liveNow = live.task?.now.length ?? 0;
  // Follow the work as it happens (a reply being written, the status line changing, a prompt appearing), unless the reader scrolled up to read something.
  useEffect(() => { if (stick.current && latestId) toEnd(false); }, [draftLength, liveLabel, liveNeeds, liveNow, latestId]);

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
      await work.refresh();
    } catch { if (threadId.current === id) setErr('Could not stop this task. Please try again.'); }
    finally { if (threadId.current === id) { setStopping(null); reload(); } }
  };
  const byRequest = new Map(tasks.map(t => [t.id, t]));
  const ended = (rid: string) => { const shared = mine.find(t => t.id === rid); if (shared) return !isOpen(shared); const t = byRequest.get(rid); return !!t && !isActive(t); };
  const trail = useMemo(() => foldTrail(msgs, ended, m => blocks.some(b => b.anchor_message_id === m.id) || m.content.includes('```lumina-app')), [msgs, tasks, blocks, mine]);   // eslint-disable-line react-hooks/exhaustive-deps
  // The assistant's earlier messages for a finished request are part of that request's record: they fold into its strip, not into a button of their own.
  const notes = useMemo(() => { const by = new Map<string, Msg[]>(); for (const group of trail.hidden.values()) { const rid = group[0].request_id; if (rid) by.set(rid, [...(by.get(rid) ?? []), ...group]); } return by; }, [trail]);
  const eager = useMemo(() => new Set(tasks.slice(-3).map(t => t.id)), [tasks]);
  const asks = ['customer', 'telegram', 'system'];
  const stopTarget = open.find(t => t.controls.stop) ?? null;
  const current = chats.find(c => c.id === id) ?? detail;

  const askAgain = async (message: string) => { if (!id) return; try { await api('POST', `/v1/conversations/${id}/send`, { message, key: crypto.randomUUID().replace(/-/g, ''), mode: 'text', ui: getAnswerStyle() }); } finally { reload(); } };
  const lastAgent = [...msgs].reverse().find(m => m.provenance === 'agent');
  const appRequests = new Set([...msgs.filter(m => m.content.includes('```lumina-app')).map(m => m.request_id), ...made.filter(a => runnableFile(a)).map(a => a.task_id)].filter(Boolean));
  const fresh = !id || (loaded && !msgs.length && !err);          // nothing said yet: the composer floats in the middle, then settles at the bottom
  const sent = (r: any) => {
    stick.current = true; setNewBelow(false);                      // you just said something: the thread goes back to the bottom
    void work.refresh();
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
          {msgs.map(m => trail.skip.has(m.id) ? null : (
            <div key={m.id} className="turn">
              {!m.ui_answer && (m.provenance === 'system'
                ? <p className="chat-record">{m.content}</p>      /* something Lumina recorded (a decision you made, a goal carrying on): not a message from you or the assistant */
                : <div className={`bubble ${m.provenance === 'agent' ? 'agent' : 'you'}`}>{m.provenance === 'agent' ? <AgentResponse content={m.content} /> : <>{m.surface === 'panel' && <small>Sent from the side chat in your browser</small>}<Emojified text={m.content} /></>}</div>)}
              {asks.includes(m.provenance) && m.request_id && byRequest.get(m.request_id) && !msgs.some(next => next.id > m.id && next.request_id === m.request_id && asks.includes(next.provenance)) && (
                <div className="chat-work"><TaskStrip id={m.request_id} eager={eager.has(m.request_id)} notes={notes.get(m.request_id)} stopping={stopping === m.request_id} /></div>)}
              {m.provenance === 'agent' && m.request_id && !msgs.some(next => next.id > m.id && next.request_id === m.request_id && next.provenance === 'agent') && (() => { const mine = [...new Map(made.filter(a => a.task_id === m.request_id).map(a => [a.display_name, a])).values()]; return mine.length > 0 && (
                <div aria-label="Files from this answer"><div className="filechips">{mine.map(a => <button key={a.display_name} className="chip small" title={humanSize(a.size_bytes)} onClick={() => download(a.id, a.version).catch(() => undefined)}>⬇ {a.display_name}</button>)}</div>{mine.filter(a => runnableFile(a)).map(a => <AppPlayer key={`${a.id}-${a.version}`} file={a} />)}</div>); })()}
              {blocks.filter(b => b.anchor_message_id === m.id).map(b => <BlockView key={b.id} block={b} onChanged={reload} bridge={bridge} />)}
              {m === lastAgent && !working && !appRequests.has(m.request_id) && !m.content.includes('```lumina-app') && m.id > 0 && m.content.length > 160 && !blocks.some(b => b.anchor_message_id === m.id) && (
                <div className="quick" aria-label="Show this differently">
                  <button className="chip small" onClick={() => askAgain('Show your last answer as a table.')}>Show as table</button>
                  <button className="chip small" onClick={() => askAgain('Show your last answer as a chart.')}>Show as chart</button>
                  <button className="chip small" onClick={() => askAgain('Compare the options from your last answer side by side.')}>Compare side by side</button>
                </div>)}
            </div>))}
          {drafting && !tasks.some(t => isActive(t)) && <div className="agent-thinking" role="status" data-orb-state="weaving"><Orb state="weaving" size={48} /><span>Planning…</span></div>}
          {blocks.filter(b => !msgs.some(m => m.id === b.anchor_message_id)).map(b => <BlockView key={b.id} block={b} onChanged={reload} bridge={bridge} />)}
          {live.draft && live.draft.text && latestId && <div className="turn"><div className="bubble agent chat-draft" aria-live="off" aria-label="Lumina is writing"><AgentResponse content={live.draft.text} /></div></div>}
          <div ref={bottom} />
        </div>
        {newBelow && <button className="jump-latest btn" onClick={() => { stick.current = true; setNewBelow(false); toEnd(true); }}>Jump to latest ↓</button>}
        <div className="dock"><div className="greeting" aria-hidden={!fresh}>{fresh && <Orb state="breathing" size={64} />}<h1>What should we work on?</h1></div>{current?.archived_epoch ? <div className="archived-chat"><p>This chat is archived. Restore it to continue.</p><button className="btn primary" onClick={async () => { try { await api('POST', `/v1/conversations/${id}/restore`, {}); reload(); } catch { setErr('Could not restore this chat.'); } }}>Restore chat</button></div> : !err && <Composer key={id || 'new'} conversationId={id} autoFocus onSent={sent} onStop={stopTarget ? () => { void cancel(stopTarget.id); } : open.some(t => t.phase === 'stopping') ? () => {} : undefined} stopping={!!stopping || (!stopTarget && open.some(t => t.phase === 'stopping'))} />}</div>
      </section>
    </div>);
}
