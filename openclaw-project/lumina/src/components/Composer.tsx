import { useEffect, useRef, useState } from 'react';
import { getAnswerStyle, setAnswerStyle, STYLES, STYLE_INFO, useAnswerStyle } from '../lib/answerStyle';
import * as I from './Icons';
import Menu, { type MenuItem } from './ui/Menu';
import { api, ApiError } from '../lib/api';
import { useData } from '../state/data';
import { draftKey, readDraft, saveDraft } from '../lib/drafts';

export const TEMPLATES: Record<string, string> = {
  Web: 'Search the web and summarize: ', Code: 'Build or fix this in code: ', Data: 'Analyze this data and explain the key findings: ', Automate: 'Set up a recurring task that: ',
};
const SHORT = { basic: 'Plain text, fastest', medium: 'Tables, charts and cards', interactive: 'Forms, buttons, live progress' } as const;
const RESPONSES: { id: 'auto' | 'text' | 'plan' | 'browse'; label: string; hint: string }[] = [
  { id: 'auto', label: 'Auto', hint: 'Executes directly, with a short checkpoint plan when useful' }, { id: 'text', label: 'Text', hint: 'Answer in plain text only' },
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
  const pending = useRef<{ conversation?: string; message: string; mode: string; goal: boolean; key: string } | null>(null);   const [busy, setBusy] = useState(false); const [err, setErr] = useState(''); const [listening, setListening] = useState(false);
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
  const [style] = useAnswerStyle();
  const start = (key: string) => { setText(TEMPLATES[key]); setTimeout(() => { box.current?.focus(); box.current?.setSelectionRange(TEMPLATES[key].length, TEMPLATES[key].length); }, 0); };
  const live = app?.features.execution;
  const pick = (m: 'auto' | 'text' | 'plan' | 'browse') => { setRespond(m); if (m === 'plan') setGoal(false); };
  // The tools menu: every row changes what is actually sent (mode, goal, answer style) or does something in the app. Nothing here only pastes text.
  const tools: MenuItem[] = [
    ...(app?.features.browse ? [{ id: 'browse', section: 'Do', label: 'Browse a website', hint: 'Uses a real browser. Stops before any payment.', icon: <I.Browser width={18} height={18} />, tint: 'var(--tile-blue)', checked: respond === 'browse', onSelect: () => pick(respond === 'browse' ? 'auto' : 'browse') }] : []),
    { id: 'plan', section: app?.features.browse ? undefined : 'Do', label: 'Plan first', hint: 'Drafts an editable plan, then waits for you.', icon: <I.Tasks width={18} height={18} />, tint: 'var(--tile-purple)', checked: respond === 'plan', onSelect: () => pick(respond === 'plan' ? 'auto' : 'plan') },
    { id: 'text', label: 'Text answer only', hint: 'A plain reply, no browser or interface.', icon: <I.Chat width={18} height={18} />, tint: 'var(--tile-gray)', checked: respond === 'text', onSelect: () => pick(respond === 'text' ? 'auto' : 'text') },
    ...(live ? [{ id: 'goal', label: 'Keep working until complete', hint: respond === 'plan' ? 'Not available while planning.' : 'Carries on within your plan limits.', icon: <I.Bolt width={18} height={18} />, tint: 'var(--tile-orange)', kind: 'switch' as const, disabled: respond === 'plan', checked: goal && respond !== 'plan', onSelect: () => setGoal(g => !g) }] : []),
    ...STYLES.map((k, i) => ({ id: `style-${k}`, section: i === 0 ? 'Answer style' : undefined, label: STYLE_INFO[k].label, hint: SHORT[k], icon: i === 0 ? <I.Cube width={18} height={18} /> : i === 1 ? <I.Chart width={18} height={18} /> : <I.Motion width={18} height={18} />, tint: ['var(--tile-gray)', 'var(--tile-green)', 'var(--tile-teal)'][i], checked: style === k, onSelect: () => setAnswerStyle(k) })),
    ...(!text.trim() ? [
      { id: 'start-Web', section: 'Start with', label: 'Research something', icon: <I.Search width={18} height={18} />, tint: 'var(--tile-blue)', onSelect: () => start('Web') },
      { id: 'start-Code', label: 'Build or fix code', icon: <I.Code width={18} height={18} />, tint: 'var(--tile-green)', onSelect: () => start('Code') },
      { id: 'start-Data', label: 'Analyze data', icon: <I.Chart width={18} height={18} />, tint: 'var(--tile-orange)', onSelect: () => start('Data') },
    ] : []),
    { id: 'files', section: 'Add', label: 'Attach files', icon: <I.Clip width={18} height={18} />, tint: 'var(--tile-gray)', trailing: 'Soon', disabled: true, onSelect: () => {} },
    ...(app?.features.connectors ? [{ id: 'apps', label: 'Connect apps', hint: 'Gmail, Calendar, Drive and GitHub, read-only.', icon: <I.Out width={18} height={18} />, tint: 'var(--tile-red)', onSelect: () => { window.location.assign('/account/connections/'); } }] : []),
  ];
  const active = respond !== 'auto' || goal;

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
      saveDraft(storageKey, ''); setText(''); setGoal(false); pending.current = null; onSent?.({ ...r.request, message, conversation_id: id }); await refresh();
    } catch (e) {
      const code = e instanceof ApiError ? e.code : 'unknown';
      setErr(ERRORS[code] ?? 'Could not send that. Please try again.');
    } finally { setBusy(false); }
  };
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
          <Menu label="Tools" heading="Tools" checkable rich side="top" items={tools}
            trigger={({ open, props }) => <button type="button" className="chip tools-chip" aria-expanded={open} {...props}><I.Grid width={18} height={18} />Tools{active && <span className="tool-dot" aria-hidden />}<I.ChevronDown width={14} height={14} /></button>} />
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
