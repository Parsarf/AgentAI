import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { failed, hub, type HubAccount } from '../../lib/hub';

export interface Provider { provider: string; label: string }
interface Resource { kind: string; id: string; name: string }

/** Connect a mail and calendar account. The customer is sent to the provider, which shows what is asked for; nothing is connected until they come back, and then nothing
 *  can be read until they choose what. The providers come from the server as data: this component names none. */
export function AddAccount({ providers, primary }: { providers: Provider[]; primary?: boolean }) {
  const [busy, setBusy] = useState(''); const [err, setErr] = useState('');
  const start = async (provider: string) => {
    setBusy(provider); setErr('');
    try { const r = await api<{ authorize_url: string }>('POST', '/v1/hub/link', { provider }); window.location.assign(r.authorize_url); }
    catch (e) { setErr(failed(e)); setBusy(''); }
  };
  if (!providers.length) return <p className="faint small">No mail or calendar service can be connected yet.</p>;
  return (
    <div className="hub-connect">
      {providers.map(p => <button key={p.provider} type="button" className={`btn small${primary ? ' primary' : ''}`} disabled={!!busy} aria-busy={busy === p.provider} onClick={() => start(p.provider)}>
        {busy === p.provider ? 'Opening…' : `Connect ${p.label}`}</button>)}
      <p className="faint small">Lumina asks only to read. Changing anything needs a separate permission, asked the first time you do it.</p>
      {err && <p className="notice warning" role="alert">{err}</p>}
    </div>);
}

/** After signing in: the customer chooses what Lumina may read. Nothing is chosen for them. Mail: all of it, only some labels or folders, or none. Calendars: each one. */
export function ChooseAccess({ account, onDone, onCancel }: { account: HubAccount; onDone(): void; onCancel(): void }) {
  const [resources, setResources] = useState<Resource[] | null>(null); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const [mail, setMail] = useState<'all' | 'some' | 'none'>('none'); const [labels, setLabels] = useState<Set<string>>(new Set()); const [calendars, setCalendars] = useState<Set<string>>(new Set());
  useEffect(() => {
    let alive = true;
    api<{ resources: Resource[] }>('GET', `/v1/integrations/${account.id}/resources`).then(r => { if (alive) setResources(r.resources); }).catch(e => { if (alive) { setErr(failed(e)); setResources([]); } });
    return () => { alive = false; };
  }, [account.id]);
  const groups = useMemo(() => ({ everything: (resources ?? []).find(r => r.kind === 'mailbox'), labels: (resources ?? []).filter(r => r.kind === 'label'), calendars: (resources ?? []).filter(r => r.kind === 'calendar') }), [resources]);
  const flip = (set: Set<string>, id: string) => { const next = new Set(set); if (next.has(id)) next.delete(id); else next.add(id); return next; };
  const nothing = (mail === 'none' || (mail === 'some' && !labels.size)) && !calendars.size;
  const save = async () => {
    setBusy(true); setErr('');
    const grants = [...(mail === 'all' && groups.everything ? [{ kind: 'mailbox', id: groups.everything.id, name: groups.everything.name }] : []),
      ...(mail === 'some' ? groups.labels.filter(l => labels.has(l.id)).map(l => ({ kind: 'label', id: l.id, name: l.name })) : []),
      ...groups.calendars.filter(c => calendars.has(c.id)).map(c => ({ kind: 'calendar', id: c.id, name: c.name }))];
    try { await api('POST', `/v1/integrations/${account.id}/grants`, { grants }); await hub.refresh(account.id).catch(() => undefined); onDone(); }
    catch (e) { setErr(failed(e)); setBusy(false); }
  };
  const kind = account.capabilities.labels === 'folders' ? 'folders' : 'labels';
  return (
    <div className="hub-choose panel" role="dialog" aria-modal="false" aria-label={`Choose what Lumina may read in ${account.identity}`}>
      <h2>What may Lumina read in {account.identity}?</h2>
      <p className="muted small">Nothing is read until you choose. You can change this at any time in Settings, Access. Lumina cannot send, change or delete anything here.</p>
      {resources === null ? <p className="muted" role="status">Loading…</p> : <>
        {(groups.everything || groups.labels.length > 0) && <fieldset><legend>Mail</legend>
          {groups.everything && <label><input type="radio" name="hub-mail" checked={mail === 'all'} onChange={() => setMail('all')} /> All mail</label>}
          {groups.labels.length > 0 && <label><input type="radio" name="hub-mail" checked={mail === 'some'} onChange={() => setMail('some')} /> Only these {kind}</label>}
          {mail === 'some' && <div className="hub-choose-list">{groups.labels.map(l => <label key={l.id}><input type="checkbox" checked={labels.has(l.id)} onChange={() => setLabels(s => flip(s, l.id))} /> {l.name}</label>)}</div>}
          <label><input type="radio" name="hub-mail" checked={mail === 'none'} onChange={() => setMail('none')} /> No mail</label>
        </fieldset>}
        {groups.calendars.length > 0 && <fieldset><legend>Calendars</legend>
          <div className="hub-choose-list">{groups.calendars.map(c => <label key={c.id}><input type="checkbox" checked={calendars.has(c.id)} onChange={() => setCalendars(s => flip(s, c.id))} /> {c.name}</label>)}</div>
          <button type="button" className="btn small tertiary" onClick={() => setCalendars(new Set(calendars.size === groups.calendars.length ? [] : groups.calendars.map(c => c.id)))}>
            {calendars.size === groups.calendars.length ? 'Clear all' : 'Select all calendars'}</button>
        </fieldset>}
        {!groups.everything && !groups.labels.length && !groups.calendars.length && !err && <p className="notice warning">This account gave Lumina nothing it can read. Connect it again and allow mail or calendars.</p>}
      </>}
      {err && <p className="notice warning" role="alert">{err}</p>}
      <div className="hub-choose-actions">
        <button type="button" className="btn primary" disabled={busy || nothing || resources === null} onClick={save}>{busy ? 'Saving…' : 'Let Lumina read these'}</button>
        <button type="button" className="btn" onClick={onCancel}>Not now</button>
      </div>
    </div>);
}

/** What the page says after coming back from a provider. */
export const CONNECT_NOTE: Record<string, string> = { failed: 'The account could not be connected. Nothing was connected. Please try again.', declined: 'You did not give access, so nothing was connected.' };
