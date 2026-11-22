import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import * as I from '../Icons';
import Menu from '../ui/Menu';
import AllowChanges from './AllowChanges';
import { addresses, failed, hub, type Draft, type HubAccount, type HubAction, type Person } from '../../lib/hub';
import { ApiError } from '../../lib/api';

/** What a new draft starts from: a reply (to one or all), a forward, or a new message from one account. */
export interface DraftStart { account: string; thread: string | null; to: string[]; cc?: string[]; subject: string; body?: string }
const SAVE_AFTER = 1800;                 // ms of quiet before what was typed is saved (so at most about thirty saves a minute, however someone types)

/** A line of addresses with suggestions from the people the customer's own mail is with. What is typed is always taken as it is: a suggestion only fills in the address
 *  being typed. Arrow keys move, Enter or Tab takes one, Escape closes the list. */
function PeopleField({ label, value, onChange, disabled, autoFocus }: { label: string; value: string; onChange(v: string): void; disabled?: boolean; autoFocus?: boolean }) {
  const [found, setFound] = useState<Person[]>([]); const [at, setAt] = useState(0); const [open, setOpen] = useState(false);
  const list = useId(); const asked = useRef(0); const timer = useRef(0);
  const typing = (text: string) => { const cut = Math.max(text.lastIndexOf(','), text.lastIndexOf(';')); return text.slice(cut + 1).trim(); };
  const look = (text: string) => {
    window.clearTimeout(timer.current);
    const word = typing(text);
    if (word.length < 2 || /\s/.test(word)) { setOpen(false); return; }
    const mine = ++asked.current;
    timer.current = window.setTimeout(() => {
      hub.people(word).then(r => { if (mine !== asked.current) return; const taken = new Set(addresses(text).map(a => a.toLowerCase())); const rest = r.people.filter(p => !taken.has(p.address));
        setFound(rest); setAt(0); setOpen(rest.length > 0); }).catch(() => setOpen(false));
    }, 140);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const take = (p: Person) => {
    const cut = Math.max(value.lastIndexOf(','), value.lastIndexOf(';'));
    const before = value.slice(0, cut + 1).trim();
    onChange(`${before}${before ? ' ' : ''}${p.address}, `); setOpen(false);
  };
  return <div className="mail-people">
    <input className="mail-field-input" value={value} disabled={disabled} autoFocus={autoFocus} aria-label={label} role="combobox" aria-expanded={open} aria-controls={list} aria-autocomplete="list"
      aria-activedescendant={open ? `${list}-${at}` : undefined} autoComplete="off" spellCheck={false}
      onChange={e => { onChange(e.target.value); look(e.target.value); }} onBlur={() => window.setTimeout(() => setOpen(false), 120)}
      onKeyDown={e => {
        if (!open) return;
        if (e.key === 'ArrowDown') { e.preventDefault(); setAt(n => (n + 1) % found.length); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); setAt(n => (n - 1 + found.length) % found.length); }
        else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); take(found[at]); }
        else if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); }
      }} />
    {open && <ul id={list} className="mail-suggest" role="listbox" aria-label={`People for ${label}`}>{found.map((p, n) => (
      <li key={p.address} id={`${list}-${n}`} role="option" aria-selected={n === at} className={n === at ? 'on' : undefined} onMouseDown={e => { e.preventDefault(); take(p); }} onMouseEnter={() => setAt(n)}>
        <b>{p.name || p.address}</b>{p.name && <span className="faint">{p.address}</span>}</li>))}</ul>}
  </div>;
}

/** Writing a message: a reply in its conversation, a forward, or a new message. It is kept in Lumina as it is written (saved by itself a moment after the last
 *  keystroke) and is in no mailbox until it is sent. Send: what the customer should know about its people is shown first (people never written to, a large audience,
 *  people outside their organization), then their press sends it from the account shown, after "Undo send" (their setting) in which it can be stopped. An account that
 *  may not send from Lumina yet says so here and offers the permission; the draft can still be copied or opened in the mail service's own compose screen. */
export default function DraftEditor({ draft, start, accounts, writes, title, onSaved, onDiscarded, onSent, onClose, autoFocus }: {
  draft?: Draft; start?: DraftStart; accounts: HubAccount[]; writes: boolean; title?: string; onSaved(d: Draft): void; onDiscarded(id: string | null): void;
  onSent?(id: string, action: HubAction): void; onClose?(): void; autoFocus?: boolean;
}) {
  const [account, setAccount] = useState(draft?.account ?? start?.account ?? accounts[0]?.id ?? '');
  const [to, setTo] = useState((draft?.to ?? start?.to ?? []).join(', ')); const [cc, setCc] = useState((draft?.cc ?? start?.cc ?? []).join(', '));
  const [showCc, setShowCc] = useState(!!(draft?.cc ?? start?.cc ?? []).length);
  const [subject, setSubject] = useState(draft?.subject ?? start?.subject ?? ''); const [body, setBody] = useState(draft?.body ?? start?.body ?? '');
  const [busy, setBusy] = useState(false); const [state, setState] = useState<'new' | 'typing' | 'saving' | 'saved' | 'unsaved'>(draft ? 'saved' : 'new');
  const [note, setNote] = useState(''); const [err, setErr] = useState(''); const [confirm, setConfirm] = useState(false);
  const [checking, setChecking] = useState<string[] | null>(null); const [sending, setSending] = useState<{ action: HubAction; until: number } | null>(null); const [left, setLeft] = useState(0);
  const id = useRef<string | null>(draft?.id ?? null); const seen = useRef(draft?.updated_epoch ?? 0);
  const thread = draft?.thread ?? start?.thread ?? null;
  const from = accounts.find(a => a.id === account); const fromLabel = from?.identity ?? 'this account';
  const canSend = writes && !!from?.capabilities.send; const needsGrant = writes && !!from?.capabilities.missing?.send;
  // The assistant changed this draft ("shorter", "more formal"): show its version unless the customer is in the middle of their own edit.
  const dirty = useRef(false);
  useEffect(() => {
    if (!draft || draft.updated_epoch <= seen.current || dirty.current) return;
    seen.current = draft.updated_epoch; id.current = draft.id;
    setTo(draft.to.join(', ')); setCc(draft.cc.join(', ')); setSubject(draft.subject); setBody(draft.body); setState('saved');
  }, [draft]);
  const latest = useRef({ to, cc, subject, body, account }); latest.current = { to, cc, subject, body, account };
  const worth = () => { const v = latest.current; return !!(v.to.trim() || v.cc.trim() || v.subject.trim() || v.body.trim()); };

  const saving = useRef<Promise<Draft | null> | null>(null);
  const save = async (): Promise<Draft | null> => {
    if (saving.current) await saving.current;
    const v = latest.current;
    const run = (async () => {
      setState('saving'); setErr('');
      try {
        const change = { to: addresses(v.to), cc: addresses(v.cc), subject: v.subject, body: v.body };
        const r = await hub.saveDraft(id.current ? { draft: id.current, ...change } : { connection_id: v.account, thread_id: thread, ...change });
        id.current = r.draft.id; seen.current = r.draft.updated_epoch;
        const same = latest.current; if (same.to === v.to && same.cc === v.cc && same.subject === v.subject && same.body === v.body) { dirty.current = false; setState('saved'); } else setState('typing');
        onSaved(r.draft);
        return r.draft;
      } catch (e) {
        setState('unsaved');
        setErr(e instanceof ApiError && e.status === 400 ? 'This cannot be saved yet: check that every address is a complete email address.' : failed(e));
        return null;
      }
    })();
    saving.current = run;
    try { return await run; } finally { if (saving.current === run) saving.current = null; }
  };
  // Saved by itself a moment after the last keystroke, and when the editor goes away with something unsaved in it.
  const timer = useRef(0);
  const edit = <T,>(set: (v: T) => void) => (v: T) => {
    dirty.current = true; setNote(''); setChecking(null); setState('typing'); set(v);
    window.clearTimeout(timer.current); timer.current = window.setTimeout(() => { if (worth()) void save(); }, SAVE_AFTER);
  };
  useEffect(() => () => { window.clearTimeout(timer.current); if (dirty.current && worth()) void save(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const saved = async () => { window.clearTimeout(timer.current); return dirty.current || !id.current ? await save() : true; };
  // A new message can leave from any account until it is sent: choosing another one moves the draft there.
  const changeAccount = async (next: string) => {
    window.clearTimeout(timer.current);
    const old = id.current; id.current = null; setAccount(next); latest.current = { ...latest.current, account: next }; dirty.current = true;
    if (old) { try { await hub.discardDraft(old); onDiscarded(old); } catch { /* the old copy stays listed; nothing was sent */ } }
    if (worth()) void save(); else setState('new');
  };

  // "Undo send": the seconds left, then the outcome as the provider confirmed it (read back from the change itself, never assumed).
  useEffect(() => {
    if (!sending) return;
    const tick = window.setInterval(async () => {
      const remaining = Math.max(0, Math.ceil((sending.until - Date.now()) / 1000)); setLeft(remaining);
      if (remaining > 0) return;
      try {
        const r = await hub.action(sending.action.id);
        if (r.action.state === 'done') { window.clearInterval(tick); setSending(null); setNote('Sent.'); onSent?.(id.current!, r.action); }
        else if (['failed', 'declined', 'expired'].includes(r.action.state)) { window.clearInterval(tick); setSending(null); setErr(r.action.ended_words || 'It was not sent. The draft is still here.'); }
      } catch { /* asked again on the next tick */ }
    }, 1000);
    return () => window.clearInterval(tick);
  }, [sending]);   // eslint-disable-line react-hooks/exhaustive-deps

  const copy = async () => {
    const head = [to.trim() ? `To: ${addresses(to).join(', ')}` : '', cc.trim() ? `Cc: ${addresses(cc).join(', ')}` : '', subject.trim() ? `Subject: ${subject}` : ''].filter(Boolean);
    const text = head.length ? `${head.join('\n')}\n\n${body}` : body;
    try { await navigator.clipboard.writeText(text); setNote('Copied. Paste it into your mail service to send it.'); } catch { setErr('Copying did not work here. Select the text and copy it.'); }
  };
  const openInService = async () => {
    if (!(await saved())) return;
    setBusy(true); setErr('');
    try {
      const r = await hub.composeLink(id.current!);
      if (r.link) { window.open(r.link, '_blank', 'noopener,noreferrer'); setNote('Opened in your mail service. Send it from there.'); }
      else setErr('This account has no compose screen to open. Copy the draft instead.');
    } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };
  // Send, step 1: save, and show what the customer should know about the people first. Step 2 (send) only from what was shown.
  const check = async () => {
    if (!(await saved())) return;
    setBusy(true); setErr('');
    try {
      const r = await hub.checkDraft(id.current!);
      if (r.limit) { setErr(r.limit); return; }
      if (r.notes.length) setChecking(r.notes); else await send();
    } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };
  const send = async () => {
    setBusy(true); setErr(''); setChecking(null);
    try {
      const r = await hub.sendDraft(id.current!);
      if (r.action.state === 'done') { setNote('Sent.'); onSent?.(id.current!, r.action); }
      else if (r.action.state === 'approved' && r.undo_send_seconds > 0) { setSending({ action: r.action, until: Date.now() + r.undo_send_seconds * 1000 }); setLeft(r.undo_send_seconds); setNote(''); }
      else setErr(r.action.ended_words || 'It was not sent. The draft is still here.');
    } catch (e) { setErr(e instanceof ApiError && e.status === 409 && e.detail ? e.detail : failed(e)); }
    finally { setBusy(false); }
  };
  const undoSend = async () => {
    if (!sending) return;
    try { await hub.stop(sending.action.id); setSending(null); setNote('Not sent. The draft is still here.'); }
    catch (e) { setErr(failed(e)); }
  };
  const discard = async () => {
    setConfirm(false); window.clearTimeout(timer.current); dirty.current = false;
    if (saving.current) await saving.current;
    if (!id.current) { onDiscarded(null); return; }
    setBusy(true); setErr('');
    try { await hub.discardDraft(id.current); onDiscarded(id.current); } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };

  // The text box is as tall as what is in it (within the pane), so a short reply is a short box and a long one does not scroll inside a small one.
  const area = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => { const el = area.current; if (!el) return; el.style.height = 'auto'; el.style.height = `${Math.min(Math.max(el.scrollHeight + 2, 140), 520)}px`; }, [body]);

  const label = title ?? (draft?.origin === 'assistant' ? 'Draft by your assistant' : thread ? 'Your reply' : 'New message');
  const locked = busy || !!sending;
  const ready = addresses(to + ',' + cc).length > 0 && !!(subject.trim() || body.trim());
  const status = state === 'saving' ? 'Saving…' : state === 'saved' ? 'Saved in Lumina' : state === 'unsaved' ? 'Not saved' : state === 'typing' ? 'Saving…' : 'Kept in Lumina until it is sent';
  const more = [{ id: 'copy', label: 'Copy the text', disabled: locked || !body.trim(), onSelect: () => { void copy(); } },
    ...(from?.capabilities.compose_link ? [{ id: 'open', label: 'Open in your mail service', disabled: locked || !body.trim(), onSelect: () => { void openInService(); } }] : [])];
  return (
    <section className="mail-compose" aria-label={label} onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canSend && ready && !locked && !checking) { e.preventDefault(); void check(); } }}>
      <header className="mail-compose-head"><h3>{label}</h3>
        {onClose && <button type="button" className="iconbtn small ghost" aria-label="Close the editor" title="Close (the draft is kept)" onClick={onClose}><I.Close width={16} height={16} /></button>}</header>
      <div className="mail-fields">
        <div className="mail-field"><span className="mail-field-label">From</span>
          {accounts.length > 1 && !thread ? <select className="mail-field-input" aria-label="From" value={account} disabled={locked} onChange={e => { void changeAccount(e.target.value); }}>
            {accounts.map(a => <option key={a.id} value={a.id}>{a.identity}</option>)}</select> : <span className="mail-field-fixed" title={fromLabel}>{fromLabel}</span>}</div>
        <div className="mail-field"><span className="mail-field-label">To</span><PeopleField label="To" value={to} disabled={!!sending} autoFocus={autoFocus && !to} onChange={edit(setTo)} />
          {!showCc && <button type="button" className="btn small tertiary" onClick={() => setShowCc(true)}>Cc</button>}</div>
        {showCc && <div className="mail-field"><span className="mail-field-label">Cc</span><PeopleField label="Cc" value={cc} disabled={!!sending} onChange={edit(setCc)} /></div>}
        <div className="mail-field"><span className="mail-field-label">Subject</span>
          <input className="mail-field-input" value={subject} disabled={!!sending} maxLength={500} onChange={e => edit(setSubject)(e.target.value)} aria-label="Subject" /></div>
      </div>
      <textarea ref={area} className="mail-compose-body" value={body} disabled={!!sending} maxLength={40000} onChange={e => edit(setBody)(e.target.value)} aria-label="Message"
        autoFocus={autoFocus && !!to} placeholder="Write your message, or ask your assistant to draft it." />
      {checking && <div className="notice mail-check" role="alertdialog" aria-label="Before you send">
        <ul className="small">{checking.map(n => <li key={n}>{n}</li>)}</ul>
        <div className="row"><button type="button" className="btn small primary" disabled={busy} onClick={send}>Send anyway</button>
          <button type="button" className="btn small tertiary" disabled={busy} onClick={() => setChecking(null)}>Keep editing</button></div></div>}
      {sending && <p className="notice mail-sending" role="status"><span>Sending from {fromLabel} in {left} s.</span> <button type="button" className="btn small" onClick={undoSend}>Undo send</button></p>}
      {needsGrant && from && <AllowChanges account={from} capability="send" />}
      {confirm ? <div className="mail-compose-foot" role="alertdialog" aria-label="Discard this draft?"><span className="small">Discard this draft? It is only in Lumina, so nothing changes in your mailbox.</span>
        <span className="mail-foot-end"><button type="button" className="btn small danger" onClick={discard}>Discard</button><button type="button" className="btn small" onClick={() => setConfirm(false)}>Keep</button></span></div>
        : <footer className="mail-compose-foot">
          {canSend ? <button type="button" className="btn small primary" disabled={locked || !!checking || !ready} title="Send (Ctrl or ⌘ Enter)" onClick={check}><I.Send width={15} height={15} />Send</button>
            : <button type="button" className="btn small primary" disabled={locked || !body.trim()} onClick={from?.capabilities.compose_link ? openInService : copy}>{from?.capabilities.compose_link ? 'Open in your mail service' : 'Copy the text'}</button>}
          <span className="faint small" role="status">{note || status}</span>
          <span className="mail-foot-end">
            {canSend && <Menu label="More ways to use this draft" align="end" side="top" items={more}
              trigger={({ open, props }) => <button type="button" className="iconbtn small ghost" aria-label="More" title="More" aria-expanded={open} {...props}><I.More width={16} height={16} /></button>} />}
            <button type="button" className="iconbtn small ghost" aria-label="Discard this draft" title="Discard" disabled={locked} onClick={() => (worth() || id.current ? setConfirm(true) : void discard())}><I.Trash width={16} height={16} /></button></span>
        </footer>}
      {!canSend && !needsGrant && <p className="faint small">Sending from Lumina is not on for this account yet. Send this from your mail service; it stays here until you discard it.</p>}
      {err && <p className="notice warning" role="alert">{err}</p>}
    </section>);
}
