import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import * as I from '../Icons';
import AgentResponse from '../response/AgentResponse';
import TaskStrip from '../work/TaskStrip';
import Sheet from '../ui/Sheet';
import { api, ApiError } from '../../lib/api';
import { loadMessages, type Message } from '../../lib/conversations';
import { isOpen } from '../../lib/work';
import { useWork, useWorkOptional } from '../../state/work';
import { useFrame } from './FrameProvider';
import Split from './Split';

/** What is selected in the page beside the assistant, as ids for the server (which checks them) and as words for the person. */
export type Looking = { kind: 'thread'; connection: string; thread: string } | { kind: 'event'; connection: string; calendar: string; event: string }
  | { kind: 'days'; start: string; end: string } | { kind: 'mail'; label?: string; query?: string }
  | { kind: 'file'; source: 'upload' | 'made'; id: string } | { kind: 'folder'; id: string } | { kind: 'task'; id: string }
  | { kind: 'page'; page: 'home' | 'inbox' | 'calendar' | 'files' | 'activity' | 'settings' };
/** A one-tap action the page offers for what is selected. `draft` marks one whose answer is a draft: the assistant then offers one-step changes to it. */
export interface Action { label: string; message: string; draft?: boolean }
export interface Selection { looking: Looking | null; words: string; actions: Action[] }

/** One-step changes to a draft the assistant wrote (decision 6: no accordion editing). */
export const REFINE: Action[] = [
  { label: 'Shorter', message: 'Make that draft shorter. Keep what matters.' }, { label: 'Longer', message: 'Make that draft a little longer, with more detail.' },
  { label: 'More formal', message: 'Make that draft more formal.' }, { label: 'Simpler', message: 'Make that draft simpler, in plainer words.' },
];
const BACKGROUND_AFTER = 30;              // seconds: a task that runs longer can be sent to the background and followed in Activity
const CHAT_KEY = 'lumina.hub.chat';      // the same key the old mail and calendar dock used, so its conversation carries on here
const read = (key: string) => { try { return window.localStorage.getItem(key); } catch { return null; } };
const write = (key: string, value: string | null) => { try { if (value === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, value); } catch { /* private mode */ } };
const failed = (e: unknown) => (e instanceof ApiError && e.status === 402 ? 'Your allowance does not cover this right now. See Usage in Settings.'
  : e instanceof ApiError && e.status === 409 ? 'Your assistant is still busy with something else. Try again in a moment.' : 'That could not be sent. Try again.');

interface AssistantState {
  selection: Selection | null; setSelection(s: Selection | null): void;
  chat: string | null; messages: Message[]; requests: string[]; busy: boolean; error: string; draftFrom: string | null;
  send(message: string, action?: Action): Promise<boolean>; fresh(): void; stop(id: string): Promise<void>;
  background: string | null; sendToBackground(id: string): void; notice: { id: string; words: string } | null; dismiss(): void;
}
const Ctx = createContext<AssistantState | null>(null);

/** Holds the one conversation of the assistant panel for the whole app. Asks the server nothing while the panel is closed and nothing is running. */
export function AssistantProvider({ children }: { children: ReactNode }) {
  const frame = useFrame(); const work = useWorkOptional();
  const [selection, setSel] = useState<Selection | null>(null);
  const setSelection = useCallback((s: Selection | null) => setSel(prev => (JSON.stringify(prev) === JSON.stringify(s) ? prev : s)), []);
  const [chat, setChat] = useState<string | null>(() => read(CHAT_KEY));
  const [messages, setMessages] = useState<Message[]>([]); const [requests, setRequests] = useState<string[]>([]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [draftFrom, setDraftFrom] = useState<string | null>(null);
  const [background, setBackground] = useState<string | null>(null); const [notice, setNotice] = useState<{ id: string; words: string } | null>(null);
  const last = useRef(0); const current = useRef(chat); current.current = chat; const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const open = !!frame && (frame.placement.docked.assistant || frame.sheet === 'assistant');

  const load = useCallback(async (id: string) => {
    try {
      const page = await loadMessages(id, last.current, () => alive.current && current.current === id);
      if (!alive.current || current.current !== id) return;
      if (page.messages.length) { last.current = Math.max(last.current, page.messages[page.messages.length - 1].id); setMessages(prev => { const have = new Set(prev.map(m => m.id)); return [...prev, ...page.messages.filter(m => !have.has(m.id))]; }); }
      setRequests(page.tasks.map(t => t.id));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404 && alive.current) { write(CHAT_KEY, null); setChat(null); setMessages([]); setRequests([]); last.current = 0; }   // that chat is gone: a new one next time
    }
  }, []);
  // Loaded when the panel opens (not before), and again whenever one of its tasks changes in the shared task state (which is pushed): no timer of its own.
  const mine = useMemo(() => (work?.tasks ?? []).filter(t => chat && t.conversation_id === chat), [work?.tasks, chat]);
  const signal = mine.map(t => `${t.id}:${t.phase}`).join('|');
  useEffect(() => { last.current = 0; setMessages([]); setRequests([]); }, [chat]);
  useEffect(() => { if (chat && open) void load(chat); }, [chat, open, signal, load]);

  // A task sent to the background: when it ends or needs a decision, say so once, wherever the person is.
  useEffect(() => {
    if (!background) return;
    const t = work?.tasks.find(x => x.id === background);
    if (!t) return;
    if (t.phase === 'ended' || t.phase === 'needs_you') { setNotice({ id: t.id, words: t.phase === 'ended' ? 'Your assistant finished a task.' : 'Your assistant needs a decision from you.' }); setBackground(null); }
  }, [background, work?.tasks]);

  const send = useCallback(async (message: string, action?: Action) => {
    const words = message.trim(); if (!words || busy) return false;
    setBusy(true); setError('');
    try {
      let id = chat;
      if (!id) { id = (await api<{ conversation: { id: string } }>('POST', '/v1/conversations', {})).conversation.id; write(CHAT_KEY, id); current.current = id; setChat(id); }
      const r = await api<{ request: { id: string } }>('POST', '/v1/assistant/ask', { conversation_id: id, message: words, key: crypto.randomUUID().replace(/-/g, ''), ...(selection?.looking ? { looking_at: selection.looking } : {}) });
      setDraftFrom(action?.draft || (draftFrom && REFINE.some(x => x.message === words)) ? r.request?.id ?? null : null);
      await load(id);
      return true;
    } catch (e) { if (alive.current) setError(failed(e)); return false; }
    finally { if (alive.current) setBusy(false); }
  }, [busy, chat, selection, load, draftFrom]);
  const stop = useCallback(async (id: string) => { try { await api('POST', `/v1/requests/${id}/cancel`, {}); } catch { setError('Could not stop this task. Try again.'); } }, []);
  const fresh = useCallback(() => { write(CHAT_KEY, null); setChat(null); setError(''); setDraftFrom(null); }, []);
  const sendToBackground = useCallback((id: string) => { setBackground(id); frame?.setAssistantOpen(false); }, [frame]);
  const value = useMemo<AssistantState>(() => ({ selection, setSelection, chat, messages, requests, busy, error, draftFrom, send, fresh, stop, background, sendToBackground, notice, dismiss: () => setNotice(null) }),
    [selection, setSelection, chat, messages, requests, busy, error, draftFrom, send, fresh, stop, background, sendToBackground, notice]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export const useAssistant = () => useContext(Ctx);

/** A page says what is selected (ids only), how to word it, and which one-tap actions fit. Cleared when the page goes away. */
export function useSelection(selection: Selection | null) {
  const a = useContext(Ctx); const key = JSON.stringify(selection);
  useEffect(() => { a?.setSelection(selection); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => a?.setSelection(null), []);          // eslint-disable-line react-hooks/exhaustive-deps
}

function Body({ onClose }: { onClose(): void }) {
  const a = useAssistant()!; const { tasks } = useWork(); const [text, setText] = useState(''); const end = useRef<HTMLDivElement>(null);
  const shown = a.messages.filter(m => !m.ui_answer);
  const mine = tasks.filter(t => a.chat && t.conversation_id === a.chat);
  const running = mine.find(isOpen);
  const stopTarget = running?.controls.stop ? running : null;
  const long = running && Date.now() / 1000 - running.created_epoch > BACKGROUND_AFTER;
  const lastAgent = [...shown].reverse().find(m => m.provenance === 'agent');
  const refine = !!a.draftFrom && !running && lastAgent?.request_id === a.draftFrom;
  useEffect(() => { if (typeof end.current?.scrollIntoView === 'function') end.current.scrollIntoView({ block: 'end' }); }, [shown.length, running?.phase]);
  const asked = (m: Message) => ['customer', 'telegram', 'system'].includes(m.provenance) && m.request_id && a.requests.includes(m.request_id)
    && !shown.some(n => n.id > m.id && n.request_id === m.request_id && ['customer', 'telegram', 'system'].includes(n.provenance));
  return <div className="assistant">
    <header className="assistant-head"><I.Spark width={18} height={18} aria-hidden="true" /><h2>Assistant</h2>
      {a.chat && <Link className="btn small tertiary" to={`/chat/${a.chat}`} onClick={() => onClose()}>Open in Chat</Link>}
      {a.chat && <button type="button" className="btn small tertiary" onClick={a.fresh}>New</button>}
      <button type="button" className="iconbtn small ghost" aria-label="Close the assistant" onClick={onClose}><I.Plus width={16} height={16} className="rot45" /></button></header>
    <div className="assistant-thread" aria-live="polite">
      {!shown.length && !running && <p className="muted small assistant-hello">Ask about what is on this page. Your assistant sees what you have selected here, and asks before it does anything that cannot be undone.</p>}
      {shown.map(m => <div key={m.id} className="assistant-turn">
        <div className={`assistant-msg ${m.provenance === 'agent' ? 'agent' : 'you'}`}>{m.provenance === 'agent' ? <AgentResponse content={m.content} /> : m.content}</div>
        {asked(m) && <TaskStrip id={m.request_id!} />}
      </div>)}
      {refine && <div className="assistant-refine" role="group" aria-label="Change the draft">{REFINE.map(r => <button key={r.label} type="button" className="chip small" disabled={a.busy} onClick={() => void a.send(r.message, r)}>{r.label}</button>)}</div>}
      {long && running && <p className="assistant-long small">This is taking a while. <button type="button" className="linkish" onClick={() => a.sendToBackground(running.id)}>Keep it going in the background</button> and follow it in <Link to={`/activity/${running.id}`} onClick={onClose}>Activity</Link>.</p>}
      <div ref={end} />
    </div>
    {a.error && <p className="notice warning" role="alert">{a.error}</p>}
    <p className="assistant-looking faint small" title={a.selection?.words || ''}>{a.selection?.words ? `Looking at: ${a.selection.words}` : 'Nothing selected on this page.'}</p>
    {!!a.selection?.actions.length && <div className="assistant-actions" role="group" aria-label="Suggested for what is selected">{a.selection.actions.map(s => <button key={s.label} type="button" className="chip small" disabled={a.busy || !!running} onClick={() => void a.send(s.message, s)}>{s.label}</button>)}</div>}
    <form className="assistant-form" onSubmit={e => { e.preventDefault(); void a.send(text).then(ok => { if (ok) setText(''); }); }}>
      <textarea className="input" rows={2} aria-label="Message to your assistant" placeholder="Ask your assistant" value={text} onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void a.send(text).then(ok => { if (ok) setText(''); }); } }} />
      {stopTarget && !text.trim() ? <button type="button" className="iconbtn send" aria-label="Stop" onClick={() => void a.stop(stopTarget.id)}><I.Stop width={18} height={18} /></button>
        : <button type="submit" className="iconbtn send" aria-label="Send" disabled={a.busy || !text.trim()}><I.Up width={18} height={18} /></button>}
    </form>
  </div>;
}

/** The assistant zone: docked at the right from 1500 px, a sheet below that (a button in the rail or the phone's More opens it). Not on Chat, which is the full-size form. */
export function AssistantZone() {
  const frame = useFrame(); const a = useAssistant();
  if (!frame || !a) return null;
  const docked = frame.placement.docked.assistant && frame.declared.assistant;
  const close = () => frame.setAssistantOpen(false);
  return <>
    {docked && <><Split zone="assistant" edge="start" /><aside className="zone zone-assistant" aria-label="Assistant" style={{ ['--wsp-assistant' as string]: `${frame.widths.assistant}px` }}><Body onClose={close} /></aside></>}
    {!docked && frame.sheet === 'assistant' && frame.declared.assistant && <Sheet side="right" title="Assistant" label="Assistant" className="zone-sheet zone-sheet-wide assistant-sheet" onClose={() => frame.setSheet(null)}><Body onClose={() => frame.setSheet(null)} /></Sheet>}
    {a.notice && <div className="float-notice" role="status"><span>{a.notice.words}</span><Link className="btn small" to={`/activity/${a.notice.id}`} onClick={a.dismiss}>See it</Link>
      <button type="button" className="iconbtn small ghost" aria-label="Dismiss" onClick={a.dismiss}><I.Plus width={14} height={14} className="rot45" /></button></div>}
  </>;
}
