import { useEffect, useRef, useState, type ReactNode } from 'react';
import { getAnswerStyle } from '../lib/answerStyle';
import * as I from './Icons';
import Menu from './ui/Menu';
import { api, ApiError } from '../lib/api';
import { useData } from '../state/data';
import { draftKey, readDraft, saveDraft } from '../lib/drafts';

export const TEMPLATES: Record<string, string> = {
  Web: 'Search the web and summarize: ', Code: 'Build or fix this in code: ', Data: 'Analyze this data and explain the key findings: ', Automate: 'Set up a recurring task that: ',
};
/** The tools menu: each choice starts the message from a template (TEMPLATES). Labels are what the customer sees. */
const TOOLS: Record<string, { label: string; icon: ReactNode }> = {
  Web: { label: 'Web search', icon: <I.Browser width={18} height={18} /> }, Code: { label: 'Build & code', icon: <I.Code width={18} height={18} /> },
  Data: { label: 'Analyze data', icon: <I.Chart width={18} height={18} /> }, Automate: { label: 'Automate', icon: <I.Bolt width={18} height={18} /> },
};
const RESPONSES: { id: 'auto' | 'text' | 'plan' | 'browse'; label: string; hint: string }[] = [
  { id: 'auto', label: 'Auto', hint: 'Lumina chooses: text, a short form, or an editable plan' }, { id: 'text', label: 'Text', hint: 'Answer in plain text only' },
  { id: 'plan', label: 'Plan', hint: 'Always draft an editable plan first' }, { id: 'browse', label: 'Browse', hint: 'Use a browser on websites; stops before any payment' },
];
const ERRORS: Record<string, string> = {
  budget_denied: 'Your plan allowance cannot fund this request right now.', queue_full: 'You already have the maximum number of waiting tasks.',
  request_conflict: 'That message conflicts with an earlier one. Try again.', rate_limited: 'Too many requests. Wait a moment.',
  conversation_conflict: 'You have too many chats. Clear some old ones and try again.',
};

/** A new chat needs no project: the server uses the account's first one. Created only when the first message is sent. */
export async function createChat(): Promise<string> {
  return (await api<{ conversation: { id: string } }>('POST', '/v1/conversations', {})).conversation.id;
}

export default function Composer({ conversationId, seed, onSent, autoFocus }: {
  conversationId?: string | null; seed?: { text: string; n: number } | null; onSent?: (result: any) => void; autoFocus?: boolean;
}) {
  const { app, refresh } = useData();
  const storageKey = draftKey(app?.user.email ?? '', conversationId);
  const [text, setText] = useState(() => readDraft(storageKey));
  const pending = useRef<{ conversation?: string; message: string; mode: string; goal: boolean; key: string } | null>(null); const [mode, setMode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(''); const [listening, setListening] = useState(false);
  const [respond, setRespond] = useState<'auto' | 'text' | 'plan' | 'browse'>('auto');
  const [goal, setGoal] = useState(false);       // Keep working until complete: the message becomes the objective of a goal that carries on turn after turn within the plan limits
  const box = useRef<HTMLTextAreaElement>(null); const rec = useRef<any>(null);
  useEffect(() => { saveDraft(storageKey, text); }, [storageKey, text]);
  useEffect(() => () => rec.current?.stop(), []);
  const max = app?.limits.max_message_chars ?? 16000;
  useEffect(() => { if (seed) { setText(seed.text); setTimeout(() => { box.current?.focus(); box.current?.setSelectionRange(seed.text.length, seed.text.length); }, 0); } }, [seed]);
  useEffect(() => { if (autoFocus) box.current?.focus(); }, [autoFocus, conversationId]);
  useEffect(() => { const el = box.current; if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 260) + 'px'; } }, [text]);
  const speech = typeof window !== 'undefined' ? ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition) : null;

  const toggleVoice = () => {
    if (!speech) return;
    if (listening) { rec.current?.stop(); return; }
    const r = new speech(); r.interimResults = false; r.lang = navigator.language || 'en-US';
    r.onresult = (e: any) => setText(t => (t ? t + ' ' : '') + e.results[0][0].transcript);
    r.onend = () => setListening(false); r.onerror = () => setListening(false);
    rec.current = r; setListening(true); r.start();
  };
  const choose = (m: string) => { const next = mode === m ? null : m; setMode(next); if (next && !text.trim()) setText(TEMPLATES[next]); };

  const submit = async () => {
    const message = text.trim(); if (!message || busy) return;
    setBusy(true); setErr('');
    try {
      const wantsGoal = goal && respond !== 'plan';
      if (!pending.current || pending.current.message !== message || pending.current.mode !== respond || pending.current.goal !== wantsGoal) pending.current = { conversation: conversationId || pending.current?.conversation, message, mode: respond, goal: wantsGoal, key: crypto.randomUUID().replace(/-/g, '') };
      const attempt = pending.current;
      const id = attempt.conversation || await createChat();
      attempt.conversation = id;
      const r = await api('POST', `/v1/conversations/${id}/send`, { message, key: attempt.key, mode: respond, ui: getAnswerStyle(), ...(attempt.goal ? { goal: 'true' } : {}) });
      saveDraft(storageKey, ''); setText(''); setMode(null); setGoal(false); pending.current = null; onSent?.({ ...r.request, message, conversation_id: id }); await refresh();
    } catch (e) {
      const code = e instanceof ApiError ? e.code : 'unknown';
      setErr(ERRORS[code] ?? 'Could not send that. Please try again.');
    } finally { setBusy(false); }
  };
  const live = app?.features.execution;
  return (
    <div>
      <form className="composer" onSubmit={e => { e.preventDefault(); void submit(); }}>
        <label className="sr" htmlFor="ask">Message Lumina</label>
        <textarea id="ask" ref={box} rows={2} value={text} maxLength={max} placeholder={conversationId ? 'Reply or ask a follow-up…' : 'Ask anything or give Lumina a task…'}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || (!e.shiftKey && !e.nativeEvent.isComposing))) { e.preventDefault(); void submit(); } }}
          onPaste={e => { if (e.clipboardData.files.length) { e.preventDefault(); setErr('File attachments are not enabled yet; paste text instead.'); } }} />
        <div className="row">
          <button type="button" className="iconbtn" disabled aria-label="Use Files" title={app?.features.uploads ? '' : 'File uploads are not enabled yet'}><I.Clip width={18} height={18} /></button>
          {!conversationId && (
            <Menu label="Tools" heading="Tools" checkable items={Object.keys(TOOLS).map(k => ({ id: k, label: TOOLS[k].label, icon: TOOLS[k].icon, checked: mode === k, onSelect: () => choose(k) }))}
              trigger={({ open, props }) => <button type="button" className="chip" aria-expanded={open} {...props}><I.Grid width={18} height={18} />{mode ? TOOLS[mode].label : 'Tools'}<I.ChevronDown width={14} height={14} /></button>} />)}
          <span className="spacer" />
          <Menu label="How should Lumina respond" heading="Respond with" checkable side="top" align="end" items={RESPONSES.filter(r => r.id !== 'browse' || app?.features.browse).map(r => ({ id: r.id, label: r.label, hint: r.hint, checked: respond === r.id, onSelect: () => setRespond(r.id) }))}
            trigger={({ open, props }) => <button type="button" className="chip" aria-expanded={open} {...props}>{RESPONSES.find(r => r.id === respond)?.label}<I.ChevronDown width={14} height={14} /></button>} />
          {respond !== 'plan' && live && <button type="button" className="chip" aria-pressed={goal} onClick={() => setGoal(g => !g)} title="Lumina keeps working, turn after turn, until the goal is met, you stop it, or your plan limit is reached">Keep working until complete</button>}
          <span className="actions">
          {speech && <button type="button" className="iconbtn" aria-label={listening ? 'Stop dictation' : 'Dictate'} aria-pressed={listening} onClick={toggleVoice}><I.Mic width={18} height={18} /></button>}
          <button type="submit" className="iconbtn send" disabled={!text.trim() || busy} aria-label="Send message"><I.Up width={20} height={20} /></button>
          </span>
        </div>
      </form>
      <p className={`hint${err ? ' err' : ''}`} role={err ? 'alert' : undefined}>{err || (live ? 'Enter to send · Shift+Enter for a new line · you can keep chatting while a task runs.' : 'Execution is off right now: your message is saved and waits.')}</p>
    </div>);
}
