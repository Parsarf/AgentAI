import { useEffect, useRef, useState } from 'react';
import { addresses, failed, hub, type Draft } from '../../lib/hub';

/** What a new draft starts from: a reply to a thread, or a new message from one account. */
export interface DraftStart { account: string; thread: string | null; to: string[]; cc?: string[]; subject: string }

/** A mail draft kept in Lumina (#57). The customer edits it freely, asks the assistant beside the page to change it, copies it, or opens it in their mail service's own compose
 *  screen to send it there. NOTHING is sent or created in the mailbox from here: the page says so where a Send button would be. */
export default function DraftEditor({ draft, start, accountLabel, canOpenInService, onSaved, onDiscarded, autoFocus }: {
  draft?: Draft; start?: DraftStart; accountLabel: string; canOpenInService: boolean; onSaved(d: Draft): void; onDiscarded(id: string | null): void; autoFocus?: boolean;
}) {
  const [to, setTo] = useState((draft?.to ?? start?.to ?? []).join(', ')); const [cc, setCc] = useState((draft?.cc ?? start?.cc ?? []).join(', '));
  const [subject, setSubject] = useState(draft?.subject ?? start?.subject ?? ''); const [body, setBody] = useState(draft?.body ?? '');
  const [busy, setBusy] = useState(false); const [note, setNote] = useState(''); const [err, setErr] = useState(''); const [confirm, setConfirm] = useState(false);
  const id = useRef<string | null>(draft?.id ?? null);
  const seen = useRef(draft?.updated_epoch ?? 0);
  // The assistant changed this draft ("shorter", "more formal"): show its version unless the customer is in the middle of their own edit.
  const dirty = useRef(false);
  useEffect(() => {
    if (!draft || draft.updated_epoch <= seen.current || dirty.current) return;
    seen.current = draft.updated_epoch; id.current = draft.id;
    setTo(draft.to.join(', ')); setCc(draft.cc.join(', ')); setSubject(draft.subject); setBody(draft.body);
  }, [draft]);
  const edit = <T,>(set: (v: T) => void) => (v: T) => { dirty.current = true; setNote(''); set(v); };

  const save = async (): Promise<Draft | null> => {
    setBusy(true); setErr('');
    try {
      const change = { to: addresses(to), cc: addresses(cc), subject, body };
      const r = await hub.saveDraft(id.current ? { draft: id.current, ...change } : { connection_id: start!.account, thread_id: start!.thread, ...change });
      id.current = r.draft.id; seen.current = r.draft.updated_epoch; dirty.current = false; onSaved(r.draft); setNote('Saved in Lumina. Nothing was sent.');
      return r.draft;
    } catch (e) { setErr(failed(e)); return null; } finally { setBusy(false); }
  };
  const copy = async () => {
    const head = [to.trim() ? `To: ${addresses(to).join(', ')}` : '', cc.trim() ? `Cc: ${addresses(cc).join(', ')}` : '', subject.trim() ? `Subject: ${subject}` : ''].filter(Boolean);
    const text = head.length ? `${head.join('\n')}\n\n${body}` : body;
    try { await navigator.clipboard.writeText(text); setNote('Copied. Paste it into your mail service to send it.'); } catch { setErr('Copying did not work here. Select the text and copy it.'); }
  };
  const openInService = async () => {
    const saved = dirty.current || !id.current ? await save() : null;
    if ((dirty.current || !id.current) && !saved) return;
    setBusy(true); setErr('');
    try {
      const r = await hub.composeLink(id.current!);
      if (r.link) { window.open(r.link, '_blank', 'noopener,noreferrer'); setNote('Opened in your mail service. Send it from there.'); }
      else setErr('This account has no compose screen to open. Copy the draft instead.');
    } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };
  const discard = async () => {
    setConfirm(false);
    if (!id.current) { onDiscarded(null); return; }
    setBusy(true); setErr('');
    try { await hub.discardDraft(id.current); onDiscarded(id.current); } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };

  const label = draft?.origin === 'assistant' ? 'Draft by your assistant' : 'Your draft';
  return (
    <section className="hub-draft" aria-label={label}>
      <header className="hub-draft-head"><b>{label}</b><span className="faint small">From {accountLabel} · kept in Lumina, not in your mailbox</span></header>
      <label className="hub-draft-field"><span>To</span><input className="input" value={to} onChange={e => edit(setTo)(e.target.value)} aria-label="To" autoFocus={autoFocus} /></label>
      <label className="hub-draft-field"><span>Cc</span><input className="input" value={cc} onChange={e => edit(setCc)(e.target.value)} aria-label="Cc" /></label>
      <label className="hub-draft-field"><span>Subject</span><input className="input" value={subject} maxLength={500} onChange={e => edit(setSubject)(e.target.value)} aria-label="Subject" /></label>
      <textarea className="input hub-draft-body" value={body} maxLength={40000} rows={8} onChange={e => edit(setBody)(e.target.value)} aria-label="Message" placeholder="Write here, or ask your assistant to draft it." />
      <div className="hub-draft-actions">
        <button type="button" className="btn small primary" disabled={busy} onClick={() => { void save(); }}>Save</button>
        <button type="button" className="btn small" disabled={busy || !body.trim()} onClick={copy}>Copy</button>
        {canOpenInService && <button type="button" className="btn small" disabled={busy || !body.trim()} onClick={openInService}>Open in your mail service</button>}
        <button type="button" className="btn small tertiary" disabled={busy} onClick={() => setConfirm(true)}>Discard</button>
        <span className="faint small">Lumina does not send mail yet: send it from your mail service.</span>
      </div>
      {confirm && <div className="file-confirm" role="alertdialog" aria-label="Discard this draft?"><span>Discard this draft? It is only in Lumina, so nothing changes in your mailbox.</span>
        <button type="button" className="btn small danger" onClick={discard}>Discard</button><button type="button" className="btn small" onClick={() => setConfirm(false)}>Keep</button></div>}
      {note && <p className="faint small" role="status">{note}</p>}
      {err && <p className="notice warning" role="alert">{err}</p>}
    </section>);
}
