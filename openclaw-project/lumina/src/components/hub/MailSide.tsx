import type { ReactNode } from 'react';
import * as I from '../Icons';
import Sheet from '../ui/Sheet';
import { AddAccount, Reconnect, type Provider } from './Connect';
import { ago, hub, LABEL_WORDS, LIST_ORDER, type HubAccount, type MailSettings, type Overview } from '../../lib/hub';

const ICONS: Record<string, ReactNode> = { inbox: <I.Inbox width={17} height={17} />, starred: <I.Star width={17} height={17} />, sent: <I.Send width={17} height={17} />, drafts: <I.Edit width={17} height={17} />,
  archive: <I.Archive width={17} height={17} />, all: <I.Mail width={17} height={17} />, spam: <I.Alert width={17} height={17} />, trash: <I.Trash width={17} height={17} /> };

/** An address that, where it must wrap, wraps before its "@" (never in the middle of a word, never cut short). */
/** An address breaks only where a reader expects it to: before the "@" and before each dot of the domain (at 150% text "example.com" was split as "co|m"). */
const address = (text: string) => { const at = text.lastIndexOf('@'); if (at <= 0) return text;
  const domain = text.slice(at).split(/(?=\.)/); return <>{text.slice(0, at)}{domain.map((part, i) => <span key={i}><wbr />{part}</span>)}</>; };

/** What one account is doing, when that is worth a line: nothing is said about an account that simply works. */
export function accountNote(a: HubAccount, now: number): string {
  if (a.state === 'needs_you') return 'Its access ended.';
  if (!a.granted.mail) return 'Nothing chosen to read yet.';
  if (!a.mail) return 'Getting ready…';
  if (!a.mail.filled) return a.mail.items ? `Loading mail: ${a.mail.items.toLocaleString()} so far` : 'Loading mail for the first time…';
  if (a.mail.error) return `Could not update. Last updated ${ago(a.mail.synced_epoch, now)}.`;
  return '';
}

/** The Inbox's side column: the mailboxes, the accounts (all of them together, or one), and each account's own labels or folders. Nothing here explains itself at
 *  length: what an account needs is said on its own row, and connecting another one is one button. */
export default function MailSide({ accounts, providers, counts, drafts, label, providerLabel, only, own, now, tags, onLabel, onProviderLabel, onOnly, onChoose }: {
  accounts: HubAccount[]; providers: Provider[]; counts?: Overview['counts']; drafts: number; label: string; providerLabel: { account: string; id: string } | null; only: string | null;
  /** The shortest name that tells each account from the others (account id -> name), for where a whole address has no room. */
  tags?: Record<string, string>;
  own: { connection_id: string; labels: { id: string; name: string; threads: number }[] }[]; now: number;
  onLabel(l: string): void; onProviderLabel(account: string, id: string, name: string): void; onOnly(id: string | null): void; onChoose(a: HubAccount): void;
}) {
  const unread = only ? counts?.by_account[only] ?? 0 : counts?.unread ?? 0;
  return <div className="mail-side" aria-label="Mailboxes and accounts">
    <nav className="mail-nav" aria-label="Mailboxes">
      {LIST_ORDER.map(l => <button key={l} type="button" className="mail-nav-item" aria-current={!providerLabel && label === l ? 'page' : undefined} onClick={() => onLabel(l)}>
        {ICONS[l]}<span className="mail-nav-name">{LABEL_WORDS[l]}</span>
        {l === 'inbox' && unread > 0 && <span className="mail-count" aria-label={`${unread} unread`}>{unread > 999 ? '999+' : unread}</span>}
        {l === 'drafts' && drafts > 0 && <span className="mail-count quiet" aria-label={`${drafts} written in Lumina`}>{drafts}</span>}</button>)}
    </nav>
    <section className="mail-accounts" aria-label="Accounts">
      <header className="mail-side-head"><h2>Accounts</h2>
        <AddAccount providers={providers} trigger={({ open, props, busy }) => <button type="button" className="iconbtn small ghost" aria-label="Add an account" title="Add an account" aria-expanded={open} disabled={busy} {...props}><I.Plus width={16} height={16} /></button>} /></header>
      {accounts.length > 1 && <button type="button" className="mail-account" aria-pressed={only === null} onClick={() => onOnly(null)}>
        <span className="mail-account-mark all" aria-hidden="true"><I.Mail width={14} height={14} /></span><span className="mail-account-text"><b>All accounts</b></span></button>}
      {accounts.map(a => { const note = accountNote(a, now); const n = counts?.by_account[a.id] ?? 0; return (
        <div key={a.id} className={`mail-account-row${a.state === 'needs_you' ? ' needs' : ''}`}>
          <button type="button" className="mail-account" aria-pressed={accounts.length > 1 ? only === a.id : undefined} title={`${a.identity} (${a.provider_label})`} onClick={() => onOnly(accounts.length > 1 && only !== a.id ? a.id : null)}>
            <span className="mail-account-mark" aria-hidden="true">{(a.identity[0] ?? '?').toUpperCase()}</span>
            <span className="mail-account-text"><b>{address(a.identity)}</b><span className="faint">{a.provider_label}{note ? ` · ${note}` : ''}</span></span>
            {n > 0 && <span className="mail-count quiet" aria-label={`${n} unread`}>{n > 999 ? '999+' : n}</span>}</button>
          {a.state === 'needs_you' && <div className="mail-account-act"><Reconnect account={a} /></div>}
          {a.state === 'working' && !a.granted.mail && <div className="mail-account-act"><button type="button" className="btn small" onClick={() => onChoose(a)}>Choose what to read</button></div>}
        </div>); })}
    </section>
    {own.filter(o => (!only || only === o.connection_id) && o.labels.length).map(o => { const account = accounts.find(a => a.id === o.connection_id); const folders = account?.capabilities.labels === 'folders'; return (
      <details key={o.connection_id} className="mail-own" open={!!providerLabel && providerLabel.account === o.connection_id ? true : undefined}>
        <summary title={account?.identity}><I.Chevron width={14} height={14} /><span>{folders ? 'Folders' : 'Labels'}{accounts.length > 1 && account ? ` · ${tags?.[account.id] ?? account.identity}` : ''}</span></summary>
        {o.labels.map(l => <button key={l.id} type="button" className="mail-nav-item" aria-current={providerLabel?.account === o.connection_id && providerLabel.id === l.id ? 'page' : undefined}
          onClick={() => onProviderLabel(o.connection_id, l.id, l.name)}>{folders ? <I.Folder width={16} height={16} /> : <I.Tag width={16} height={16} />}<span className="mail-nav-name">{l.name}</span>
          <span className="mail-count quiet">{l.threads}</span></button>)}
      </details>); })}
  </div>;
}

/** The customer's own mail settings, in a sheet: out of the way until wanted. Each is saved as it is changed. */
export function MailSettingsSheet({ mail, canChange, onSave, onClose }: { mail: MailSettings | undefined; canChange: boolean;
  onSave(change: NonNullable<Parameters<typeof hub.setSettings>[0]['mail']>): void; onClose(): void }) {
  return <Sheet title="Mail settings" onClose={onClose} className="zone-sheet">
    <div className="mail-settings">
      {!mail || !canChange ? <p className="muted small">These settings apply once an account may send or organize mail from Lumina. Open a conversation and use “Allow changes” to give that permission.</p> : <>
        <label className="mail-setting"><span><b>Undo send</b><span className="faint small">How long a message waits after you press Send, so you can take it back.</span></span>
          <select className="input" value={mail.undo_send_seconds} onChange={e => onSave({ undo_send_seconds: Number(e.target.value) })}>
            {[0, 5, 10, 20, 30].map(n => <option key={n} value={n}>{n ? `${n} seconds` : 'Send at once'}</option>)}</select></label>
        <label className="mail-setting check"><input type="checkbox" checked={mail.mark_read_on_open} onChange={e => onSave({ mark_read_on_open: e.target.checked })} />
          <span><b>Opening a message marks it read in my mailbox</b><span className="faint small">Off: reading here leaves it unread in your mail service until you mark it.</span></span></label>
        <label className="mail-setting"><span><b>People per message</b><span className="faint small">The most people one message may go to (up to {mail.platform.recipients}).</span></span>
          <input className="input" type="number" min={1} max={mail.platform.recipients} value={mail.limits.recipients ?? mail.allowed.recipients}
            onChange={e => onSave({ limits: { ...mail.limits, recipients: Number(e.target.value) } })} aria-label="People a message may go to" /></label>
        <label className="mail-setting"><span><b>Messages an hour</b><span className="faint small">The most messages sent from Lumina in an hour (up to {mail.platform.per_hour}).</span></span>
          <input className="input" type="number" min={1} max={mail.platform.per_hour} value={mail.limits.per_hour ?? mail.allowed.per_hour}
            onChange={e => onSave({ limits: { ...mail.limits, per_hour: Number(e.target.value) } })} aria-label="Messages an hour" /></label>
      </>}
      <p className="faint small">Remote pictures stay hidden until you show them, for one message or always for a sender. Row height follows the app's density (Shift+D).</p>
    </div>
  </Sheet>;
}
