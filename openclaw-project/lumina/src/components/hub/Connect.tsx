import { useEffect, useMemo, useState, type ReactNode } from 'react';
import * as I from '../Icons';
import Menu, { type MenuItem } from '../ui/Menu';
import { api } from '../../lib/api';
import { failed, hub, linkWords, type HubAccount, type Provider } from '../../lib/hub';

export type { Provider };
interface Resource { kind: string; id: string; name: string }

/** Connect a mail and calendar account. The customer is sent to the provider, which shows what is asked for; nothing is connected until they come back, and then nothing
 *  can be read until they choose what. Where a provider signs in different kinds of account separately (a personal or a work account) the customer picks one first: each
 *  has its own sign-in page. The providers and their kinds come from the server as data: this component names none. */
export function AddAccount({ providers, primary, label = 'Add account', trigger }: { providers: Provider[]; primary?: boolean; label?: string;
  trigger?(p: { open: boolean; props: Record<string, unknown>; busy: boolean }): ReactNode }) {
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const start = async (provider: string, kind?: string) => {
    setBusy(true); setErr('');
    try { const r = await hub.connect(provider, kind); window.location.assign(r.authorize_url); }
    catch (e) { setErr(failed(e)); setBusy(false); }
  };
  const items: MenuItem[] = providers.flatMap(p => (p.kinds?.length
    ? p.kinds.map((k, n) => ({ id: `${p.provider}:${k.id}`, label: k.label, section: n === 0 ? p.label : undefined, onSelect: () => { void start(p.provider, k.id); } }))
    : [{ id: p.provider, label: p.label, onSelect: () => { void start(p.provider); } }]));
  if (!providers.length) return <p className="faint small">No mail or calendar service can be connected yet.</p>;
  return (
    <span className="hub-connect">
      <Menu label="Choose a mail service" heading="Lumina asks only to read. Changing anything is a separate permission, asked the first time you use it." items={items}
        trigger={({ open, props }) => trigger ? trigger({ open, props, busy }) : <button type="button" className={`btn small${primary ? ' primary' : ''}`} disabled={busy} aria-busy={busy} aria-expanded={open} {...props}>
          <I.Plus width={16} height={16} />{busy ? 'Opening…' : label}</button>} />
      {err && <span className="hub-connect-error small" role="alert">{err}</span>}
    </span>);
}

/** Sign in again to an account whose access ended. The same connection: its mail and what it was allowed stay. */
export function Reconnect({ account, small = true, className = '' }: { account: HubAccount; small?: boolean; className?: string }) {
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const go = async () => {
    setBusy(true); setErr('');
    try { const r = await hub.reconnect(account); window.location.assign(r.authorize_url); } catch (e) { setErr(failed(e)); setBusy(false); }
  };
  return <>
    <button type="button" className={`btn${small ? ' small' : ''} ${className}`} disabled={busy} aria-busy={busy} onClick={go}>{busy ? 'Opening…' : 'Reconnect'}</button>
    {err && <span className="small" role="alert">{err}</span>}
  </>;
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
    <div className="hub-choose" role="dialog" aria-modal="false" aria-label={`Choose what Lumina may read in ${account.identity}`}>
      <header><h2>{account.identity} is connected</h2>
        <p className="muted small">Choose what Lumina may read. Nothing is read until you do, and you can change it at any time in Settings, Access. This does not let Lumina send, change or delete anything.</p></header>
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

/** What the page says after coming back from a provider without a connection: the reason the server gave, as a sentence that says what to do. */
export const connectNote = (reason: string | null, reference?: string | null) => (reason ? linkWords(reason, reference) : '');
