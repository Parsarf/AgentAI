import { useEffect, useRef, useState } from 'react';
import * as I from './Icons';
import { api, ApiError } from '../lib/api';
import { useData } from '../state/data';
import { draftKey, readDraft, saveDraft } from '../lib/drafts';

export const TEMPLATES: Record<string, string> = {
  Web: 'Search the web and summarize: ', Code: 'Build or fix this in code: ', Data: 'Analyze this data and explain the key findings: ', Automate: 'Set up a recurring task that: ',
};
const ERRORS: Record<string, string> = {
  budget_denied: 'Your plan allowance cannot fund this request right now.', queue_full: 'You already have the maximum number of waiting tasks.',
  request_conflict: 'That message conflicts with an earlier one. Try again.', rate_limited: 'Too many requests. Wait a moment.',
  conversation_conflict: 'You have too many chats. Clear some old ones and try again.',
};

/** A new chat needs no project: the server uses the account's first one. Created only when the first message is sent. */
export async function createChat(): Promise<string> {
  return (await api<{ conversation: { id: string } }>('POST', '/v1/conversations', {})).conversation.id;
}

export default function Composer({ conversationId, seed, onSent, autoFocus, showCapabilities = true }: {
  conversationId?: string | null; seed?: { text: string; n: number } | null; onSent?: (result: any) => void; autoFocus?: boolean; showCapabilities?: boolean;
}) {
  const { app, refresh } = useData();
  const storageKey = draftKey(app?.user.email ?? '', conversationId);
  const [text, setText] = useState(() => readDraft(storageKey));
  const pending = useRef<{ conversation?: string; message: string; mode: string; key: string } | null>(null); const [mode, setMode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(''); const [listening, setListening] = useState(false);
  const [respond, setRespond] = useState<'auto' | 'text' | 'plan' | 'browse'>('auto');
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
      if (!pending.current || pending.current.message !== message || pending.current.mode !== respond) pending.current = { conversation: conversationId || pending.current?.conversation, message, mode: respond, key: crypto.randomUUID().replace(/-/g, '') };
      const attempt = pending.current;
      const id = attempt.conversation || await createChat();
      attempt.conversation = id;
      const r = await api('POST', `/v1/conversations/${id}/send`, { message, key: attempt.key, mode: respond });
      saveDraft(storageKey, ''); setText(''); setMode(null); pending.current = null; onSent?.({ ...r.request, message, conversation_id: id }); await refresh();
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
          {showCapabilities && !conversationId && Object.keys(TEMPLATES).map(k => (
            <button type="button" key={k} className="chip" data-capability={k.toLowerCase()} aria-pressed={mode === k} onClick={() => choose(k)}>
              {k === 'Web' && <I.Browser width={16} height={16} />}{k === 'Code' && <I.Code width={16} height={16} />}{k === 'Data' && <I.Chart width={16} height={16} />}{k === 'Automate' && <I.Bolt width={16} height={16} />}{k}
            </button>))}
          <button type="button" className="chip" disabled title={app?.features.uploads ? '' : 'File uploads are not enabled yet'}><I.Clip width={16} height={16} />Use Files</button>
          <span className="spacer" />
          <span className="respond" role="group" aria-label="How should Lumina respond">
            {((app?.features.browse ? ['auto', 'text', 'plan', 'browse'] : ['auto', 'text', 'plan']) as ('auto' | 'text' | 'plan' | 'browse')[]).map(m => <button type="button" key={m} className="chip small" aria-pressed={respond === m} onClick={() => setRespond(m)} title={m === 'auto' ? 'Lumina chooses: text, a short form, or an editable plan' : m === 'text' ? 'Answer in plain text only' : m === 'browse' ? 'Use a browser on websites; stops before any payment' : 'Always draft an editable plan first'}>{m === 'auto' ? 'Auto' : m === 'text' ? 'Text' : m === 'plan' ? 'Plan' : 'Browse'}</button>)}
          </span>
          <span className="actions">
          {speech && <button type="button" className="iconbtn" aria-label={listening ? 'Stop dictation' : 'Dictate'} aria-pressed={listening} style={{ width: 44, height: 44, borderRadius: '50%' }} onClick={toggleVoice}><I.Mic /></button>}
          <button type="submit" className="send" disabled={!text.trim() || busy} aria-label="Send message"><I.Up /></button>
          </span>
        </div>
      </form>
      <p className={`hint${err ? ' err' : live ? ' keys' : ''}`} role={err ? 'alert' : undefined}>{err || (live ? 'Enter to send · Shift+Enter for a new line · you can keep chatting while a task runs.' : 'Execution is off right now: your message is saved and waits.')}</p>
    </div>);
}
