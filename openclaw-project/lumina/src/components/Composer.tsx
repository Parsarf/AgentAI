import { useEffect, useRef, useState } from 'react';
import * as I from './Icons';
import { api, ApiError } from '../lib/api';
import { useData } from '../state/data';

export const TEMPLATES: Record<string, string> = {
  Web: 'Search the web and summarize: ', Code: 'Build or fix this in code: ', Data: 'Analyze this data and explain the key findings: ', Automate: 'Set up a recurring task that: ',
};
const ERRORS: Record<string, string> = {
  budget_denied: 'Your plan allowance cannot fund this request right now.', queue_full: 'You already have the maximum number of waiting tasks.',
  request_conflict: 'That message conflicts with an earlier one. Try again.', rate_limited: 'Too many requests. Wait a moment.',
};

export async function ensureConversation(): Promise<string> {
  const list = (await api<{ conversations: { id: string }[] }>('GET', '/v1/conversations')).conversations;
  if (list.length) return list[list.length - 1].id;
  const projects = (await api<{ projects: { id: string }[] }>('GET', '/v1/projects')).projects;
  return (await api<{ conversation: { id: string } }>('POST', '/v1/conversations', { project_id: projects[0].id })).conversation.id;
}

export default function Composer({ seed, onSent }: { seed?: { text: string; n: number } | null; onSent?: (result: any) => void }) {
  const { app, refresh } = useData();
  const [text, setText] = useState(''); const [mode, setMode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(''); const [listening, setListening] = useState(false);
  const [respond, setRespond] = useState<'auto' | 'text' | 'plan'>('auto');
  const box = useRef<HTMLTextAreaElement>(null); const rec = useRef<any>(null);
  const max = app?.limits.max_message_chars ?? 16000;
  useEffect(() => { if (seed) { setText(seed.text); setTimeout(() => { box.current?.focus(); box.current?.setSelectionRange(seed.text.length, seed.text.length); }, 0); } }, [seed]);
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
      const id = await ensureConversation();
      const r = await api('POST', `/v1/conversations/${id}/send`, { message, key: crypto.randomUUID().replace(/-/g, ''), mode: respond });
      setText(''); setMode(null); await refresh(); onSent?.(r.request);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : 'unknown';
      setErr(ERRORS[code] ?? 'Could not send that. Please try again.');
    } finally { setBusy(false); }
  };
  const live = app?.features.execution;
  return (
    <div>
      <form className="composer" onSubmit={e => { e.preventDefault(); submit(); }}>
        <label className="sr" htmlFor="ask">Ask anything or give Lumina a task</label>
        <textarea id="ask" ref={box} rows={2} value={text} maxLength={max} placeholder="Ask anything or give Lumina a task…"
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || (!e.shiftKey && !e.nativeEvent.isComposing))) { e.preventDefault(); submit(); } }}
          onPaste={e => { if (e.clipboardData.files.length) { e.preventDefault(); setErr('File attachments are not enabled yet; paste text instead.'); } }} />
        <div className="row">
          {Object.keys(TEMPLATES).map(k => (
            <button type="button" key={k} className="chip" aria-pressed={mode === k} onClick={() => choose(k)}>
              {k === 'Web' && <I.Browser width={16} height={16} />}{k === 'Code' && <I.Code width={16} height={16} />}{k === 'Data' && <I.Chart width={16} height={16} />}{k === 'Automate' && <I.Bolt width={16} height={16} />}{k}
            </button>))}
          <button type="button" className="chip" disabled title={app?.features.uploads ? '' : 'File uploads are not enabled yet'}><I.Clip width={16} height={16} />Use Files</button>
          <span className="spacer" />
          <span className="respond" role="group" aria-label="How should Lumina respond">
            {(['auto', 'text', 'plan'] as const).map(m => <button type="button" key={m} className="chip small" aria-pressed={respond === m} onClick={() => setRespond(m)} title={m === 'auto' ? 'Lumina chooses: text, a short form, or an editable plan' : m === 'text' ? 'Answer in plain text only' : 'Always draft an editable plan first'}>{m === 'auto' ? 'Auto' : m === 'text' ? 'Text' : 'Plan'}</button>)}
          </span>
          <span className="actions">
          {speech && <button type="button" className="iconbtn" aria-label={listening ? 'Stop dictation' : 'Dictate'} aria-pressed={listening} style={{ width: 44, height: 44, borderRadius: '50%' }} onClick={toggleVoice}><I.Mic /></button>}
          <button className="send" disabled={!text.trim() || busy} aria-label="Send task"><I.Up /></button>
          </span>
        </div>
      </form>
      <p className={`hint${err ? ' err' : ''}`} role={err ? 'alert' : undefined}>{err || (live ? 'Enter to send · Shift+Enter for a new line · the first reply after a pause takes ~30–40 s while your assistant wakes up.' : 'Execution is off right now: your task is saved and waits.')}</p>
    </div>);
}
