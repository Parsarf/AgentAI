import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import * as I from '../Icons';
import { api, ApiError } from '../../lib/api';
import { loadMessages, type Message } from '../../lib/conversations';
import { isActive, type ThreadTask } from '../../lib/tasks';
import AgentResponse from '../response/AgentResponse';

/** What the customer has open, as ids for the server (which checks them) and as words for the customer. */
export type Looking = { kind: 'thread'; connection: string; thread: string } | { kind: 'event'; connection: string; calendar: string; event: string }
  | { kind: 'days'; start: string; end: string } | { kind: 'mail'; label?: string; query?: string };
export interface Suggestion { label: string; message: string }

const CHAT_KEY = 'lumina.hub.chat', OPEN_KEY = 'lumina.hub.dock';
const read = (key: string) => { try { return window.localStorage.getItem(key); } catch { return null; } };
const write = (key: string, value: string | null) => { try { if (value === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, value); } catch { /* private mode: the dock still works for this visit */ } };
const failed = (e: unknown) => (e instanceof ApiError && e.status === 402 ? 'Your allowance does not cover this right now. See Usage in Settings.'
  : e instanceof ApiError && e.status === 409 ? 'Your assistant is still busy with something else. Try again in a moment.' : 'That could not be sent. Try again.');

/** The assistant, always beside the Inbox and the Calendar. It is the same assistant and the same chat as everywhere else (the conversation is an ordinary one and opens in
 *  Chat); what is different is that a message sent from here says what the customer has open, so "summarize this" means the open thread. The page works fully while the
 *  assistant is busy, asleep or closed. */
export default function Dock({ looking, lookingWords, suggestions }: { looking: Looking | null; lookingWords: string; suggestions: Suggestion[] }) {
  const [open, setOpen] = useState(() => read(OPEN_KEY) !== 'closed'); const [chat, setChat] = useState<string | null>(() => read(CHAT_KEY));
  const [msgs, setMsgs] = useState<Message[]>([]); const [tasks, setTasks] = useState<ThreadTask[]>([]); const [text, setText] = useState(''); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const last = useRef(0); const alive = useRef(true); const end = useRef<HTMLDivElement>(null); const current = useRef(chat); current.current = chat;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { write(OPEN_KEY, open ? null : 'closed'); }, [open]);

  const load = useCallback(async (id: string) => {
    try {
      const page = await loadMessages(id, last.current, () => alive.current && current.current === id);
      if (!alive.current || current.current !== id) return;
      // Two loads can overlap (the first message both creates the chat and reads it): a message is added once, by its id.
      if (page.messages.length) { last.current = Math.max(last.current, page.messages[page.messages.length - 1].id); setMsgs(prev => { const have = new Set(prev.map(m => m.id)); return [...prev, ...page.messages.filter(m => !have.has(m.id))]; }); }
      setTasks(page.tasks);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404 && alive.current) { write(CHAT_KEY, null); setChat(null); setMsgs([]); setTasks([]); last.current = 0; }      // that chat is gone: start a new one next time
    }
  }, []);
  useEffect(() => { last.current = 0; setMsgs([]); setTasks([]); if (chat) void load(chat); }, [chat, load]);
  const working = tasks.some(isActive);
  useEffect(() => { if (!chat || !working) return; const timer = window.setInterval(() => void load(chat), 2500); return () => window.clearInterval(timer); }, [chat, working, load]);
  useEffect(() => { if (open && typeof end.current?.scrollIntoView === 'function') end.current.scrollIntoView({ block: 'end' }); }, [msgs.length, working, open]);

  const send = async (message: string) => {
    const words = message.trim();
    if (!words || busy) return;
    setBusy(true); setErr('');
    try {
      let id = chat;
      if (!id) { id = (await api<{ conversation: { id: string } }>('POST', '/v1/conversations', {})).conversation.id; write(CHAT_KEY, id); current.current = id; setChat(id); }
      await api('POST', '/v1/hub/ask', { conversation_id: id, message: words, key: crypto.randomUUID().replace(/-/g, ''), ...(looking ? { looking_at: looking } : {}) });
      setText(''); setTasks(prev => [...prev, { id: 'pending', state: 'queued', created_epoch: Date.now() / 1000 }]);
      await load(id);
    } catch (e) { if (alive.current) setErr(failed(e)); }
    finally { if (alive.current) setBusy(false); }
  };
  const fresh = () => { write(CHAT_KEY, null); setChat(null); setErr(''); };

  if (!open) return <button type="button" className="hub-dock-tab" aria-label="Open the assistant" onClick={() => setOpen(true)}><I.Spark width={18} height={18} /><span>Assistant</span></button>;
  const shown = msgs.filter(m => !m.ui_answer);
  return (
    <aside className="hub-dock panel" aria-label="Assistant">
      <header className="hub-dock-head"><I.Spark width={18} height={18} /><h2>Assistant</h2>
        {chat && <Link className="btn small tertiary" to={`/chat/${chat}`}>Open in Chat</Link>}
        {chat && <button type="button" className="btn small tertiary" onClick={fresh}>New</button>}
        <button type="button" className="iconbtn small ghost" aria-label="Close the assistant" onClick={() => setOpen(false)}><I.Plus width={16} height={16} style={{ transform: 'rotate(45deg)' }} /></button></header>
      <div className="hub-dock-thread" aria-live="polite">
        {!shown.length && !working && <p className="muted small hub-dock-hello">Ask about your mail and calendar. Your assistant can read what you chose to show here; it cannot send or change anything.</p>}
        {shown.map(m => <div key={m.id} className={`hub-dock-msg ${m.provenance === 'agent' ? 'agent' : 'you'}`}>{m.provenance === 'agent' ? <AgentResponse content={m.content} /> : m.content}</div>)}
        {working && <p className="muted small" role="status">Working…</p>}
        <div ref={end} />
      </div>
      {err && <p className="notice warning" role="alert">{err}</p>}
      <p className="hub-dock-looking faint small" title={lookingWords}>Looking at: {lookingWords}</p>
      {suggestions.length > 0 && <div className="hub-dock-suggest">{suggestions.map(s => <button key={s.label} type="button" className="chip small" disabled={busy} onClick={() => send(s.message)}>{s.label}</button>)}</div>}
      <form className="hub-dock-form" onSubmit={e => { e.preventDefault(); void send(text); }}>
        <textarea className="input" rows={2} aria-label="Message to your assistant" placeholder="Ask your assistant" value={text} onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(text); } }} />
        <button type="submit" className="iconbtn send" aria-label="Send" disabled={busy || !text.trim()}><I.Up width={18} height={18} /></button>
      </form>
    </aside>);
}
