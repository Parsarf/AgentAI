import { useEffect, useRef, useState } from 'react';
import { addresses, failed, hub, type Draft, type HubAction } from '../../lib/hub';
import { ApiError } from '../../lib/api';

/** What a new draft starts from: a reply (to one or all), a forward, or a new message from one account. */
export interface DraftStart { account: string; thread: string | null; to: string[]; cc?: string[]; subject: string; body?: string }

/** A mail draft kept in Lumina (#57), and since Phase 6 sent from here (#66, #D6). The customer edits it freely or asks the assistant beside the page to change it. Send:
 *  the draft is saved, what they should know about its people is shown (people never written to, a large audience, people outside their organization), and their press
 *  sends it from the account shown, after "Undo send" (their setting, 10 seconds by default) in which it can be stopped. Without permission to send, it can still be copied
 *  or opened in the mail service's own compose screen. */
export default function DraftEditor({ draft, start, accountLabel, canOpenInService, canSend = false, onSaved, onDiscarded, onSent, autoFocus }: {
  draft?: Draft; start?: DraftStart; accountLabel: string; canOpenInService: boolean; canSend?: boolean; onSaved(d: Draft): void; onDiscarded(id: string | null): void;
  onSent?(id: string, action: HubAction): void; autoFocus?: boolean;
}) {
  const [to, setTo] = useState((draft?.to ?? start?.to ?? []).join(', ')); const [cc, setCc] = useState((draft?.cc ?? start?.cc ?? []).join(', '));
  const [subject, setSubject] = useState(draft?.subject ?? start?.subject ?? ''); const [body, setBody] = useState(draft?.body ?? start?.body ?? '');
  const [busy, setBusy] = useState(false); const [note, setNote] = useState(''); const [err, setErr] = useState(''); const [confirm, setConfirm] = useState(false);
  const [checking, setChecking] = useState<string[] | null>(null); const [sending, setSending] = useState<{ action: HubAction; until: number } | null>(null); const [left, setLeft] = useState(0);
  const id = useRef<string | null>(draft?.id ?? null);
  const seen = useRef(draft?.updated_epoch ?? 0);
  // The assistant changed this draft ("shorter", "more formal"): show its version unless the customer is in the middle of their own edit.
  const dirty = useRef(false);
  useEffect(() => {
    if (!draft || draft.updated_epoch <= seen.current || dirty.current) return;
    seen.current = draft.updated_epoch; id.current = draft.id;
    setTo(draft.to.join(', ')); setCc(draft.cc.join(', ')); setSubject(draft.subject); setBody(draft.body);
  }, [draft]);
  const edit = <T,>(set: (v: T) => void) => (v: T) => { dirty.current = true; setNote(''); setChecking(null); set(v); };

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

  const save = async (): Promise<Draft | null> => {
    setBusy(true); setErr('');
    try {
      const change = { to: addresses(to), cc: addresses(cc), subject, body };
      const r = await hub.saveDraft(id.current ? { draft: id.current, ...change } : { connection_id: start!.account, thread_id: start!.thread, ...change });
      id.current = r.draft.id; seen.current = r.draft.updated_epoch; dirty.current = false; onSaved(r.draft); setNote(canSend ? 'Saved in Lumina. Not sent yet.' : 'Saved in Lumina. Nothing was sent.');
      return r.draft;
    } catch (e) { setErr(failed(e)); return null; } finally { setBusy(false); }
  };
  const saved = async () => (dirty.current || !id.current ? await save() : true);
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
    setConfirm(false);
    if (!id.current) { onDiscarded(null); return; }
    setBusy(true); setErr('');
    try { await hub.discardDraft(id.current); onDiscarded(id.current); } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };

  const label = draft?.origin === 'assistant' ? 'Draft by your assistant' : 'Your draft';
  const locked = busy || !!sending;
  return (
    <section className="hub-draft" aria-label={label}>
      <header className="hub-draft-head"><b>{label}</b><span className="faint small">From {accountLabel} · kept in Lumina until it is sent</span></header>
      <label className="hub-draft-field"><span>To</span><input className="input" value={to} disabled={!!sending} onChange={e => edit(setTo)(e.target.value)} aria-label="To" autoFocus={autoFocus} /></label>
      <label className="hub-draft-field"><span>Cc</span><input className="input" value={cc} disabled={!!sending} onChange={e => edit(setCc)(e.target.value)} aria-label="Cc" /></label>
      <label className="hub-draft-field"><span>Subject</span><input className="input" value={subject} disabled={!!sending} maxLength={500} onChange={e => edit(setSubject)(e.target.value)} aria-label="Subject" /></label>
      <textarea className="input hub-draft-body" value={body} disabled={!!sending} maxLength={40000} rows={8} onChange={e => edit(setBody)(e.target.value)} aria-label="Message" placeholder="Write here, or ask your assistant to draft it." />
      {checking && <div className="notice" role="alertdialog" aria-label="Before you send">
        <ul className="small">{checking.map(n => <li key={n}>{n}</li>)}</ul>
        <button type="button" className="btn small primary" disabled={busy} onClick={send}>Send</button>
        <button type="button" className="btn small tertiary" disabled={busy} onClick={() => setChecking(null)}>Keep editing</button></div>}
      {sending && <p className="notice" role="status">Sending from {accountLabel} in {left} s. <button type="button" className="btn small" onClick={undoSend}>Undo send</button></p>}
      <div className="hub-draft-actions">
        {canSend && <button type="button" className="btn small primary" disabled={locked || !!checking || !addresses(to + ',' + cc).length || !(subject.trim() || body.trim())} onClick={check}>Send</button>}
        <button type="button" className={`btn small${canSend ? '' : ' primary'}`} disabled={locked} onClick={() => { void save(); }}>Save</button>
        <button type="button" className="btn small" disabled={locked || !body.trim()} onClick={copy}>Copy</button>
        {canOpenInService && <button type="button" className="btn small" disabled={locked || !body.trim()} onClick={openInService}>Open in your mail service</button>}
        <button type="button" className="btn small tertiary" disabled={locked} onClick={() => setConfirm(true)}>Discard</button>
        {!canSend && <span className="faint small">Sending from Lumina is not on for this account: send it from your mail service.</span>}
      </div>
      {confirm && <div className="file-confirm" role="alertdialog" aria-label="Discard this draft?"><span>Discard this draft? It is only in Lumina, so nothing changes in your mailbox.</span>
        <button type="button" className="btn small danger" onClick={discard}>Discard</button><button type="button" className="btn small" onClick={() => setConfirm(false)}>Keep</button></div>}
      {note && <p className="faint small" role="status">{note}</p>}
      {err && <p className="notice warning" role="alert">{err}</p>}
    </section>);
}
