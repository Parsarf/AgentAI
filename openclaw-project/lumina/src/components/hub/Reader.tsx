import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import * as I from '../Icons';
import Menu, { type MenuItem } from '../ui/Menu';
import MessageBody from './MessageBody';
import { failed, fileSize, fileUrl, fullTime, hub, initials, isPicture, listTime, personName, problemWords, recipients, tint,
  type Attachment, type HubAccount, type Message, type OrganizeOp, type Person, type Thread } from '../../lib/hub';

/** A person's mark: two letters on one of six quiet tints, always the same tint for the same address. Decoration: the name is beside it. */
export function Mark({ person, size = 'md' }: { person: Person; size?: 'sm' | 'md' }) {
  return <span className={`mail-mark mail-mark-${size} tint-${tint(person.address || person.name)}`} aria-hidden="true">{initials(person)}</span>;
}

const KIND_WORDS: [RegExp, string][] = [[/pdf$/i, 'PDF'], [/^image\//i, 'Picture'], [/spreadsheet|excel|csv/i, 'Spreadsheet'], [/wordprocessing|msword|opendocument\.text/i, 'Document'],
  [/presentation|powerpoint/i, 'Slides'], [/zip|compressed|tar/i, 'Archive'], [/^audio\//i, 'Audio'], [/^video\//i, 'Video'], [/calendar/i, 'Invitation'], [/^text\//i, 'Text']];
const kindWords = (a: Attachment) => KIND_WORDS.find(([test]) => test.test(a.type))?.[1] ?? 'File';

/** A message's files. A picture opens here, large, with the rest of the page behind a scrim; anything else is downloaded. Each is read from the mail service when it is
 *  asked for and is not kept by Lumina. */
export function Attachments({ connection, message, files }: { connection: string; message: string; files: Attachment[] }) {
  const [shown, setShown] = useState<Attachment | null>(null); const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!shown) return;
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setShown(null); } };
    window.addEventListener('keydown', key, true);
    return () => { window.removeEventListener('keydown', key, true); opener.current?.focus?.(); };
  }, [shown]);
  if (!files.length) return null;
  return <>
    <ul className="mail-files" aria-label={`${files.length} attachment${files.length === 1 ? '' : 's'}`}>{files.map(a => { const picture = isPicture(a); const at = fileUrl(connection, message, a.id); return (
      <li key={a.id} className="mail-file">
        {picture ? <button type="button" className="mail-file-open" title={`Show ${a.name}`} onClick={e => { opener.current = e.currentTarget; setShown(a); }}>
          <img className="mail-file-thumb" src={fileUrl(connection, message, a.id, true)} alt="" loading="lazy" />
          <span className="mail-file-text"><b>{a.name}</b><span className="faint">{kindWords(a)} · {fileSize(a.size)}</span></span></button>
          : <a className="mail-file-open" href={at} download={a.name} title={`Download ${a.name}`}>
            <span className="mail-file-icon" aria-hidden="true"><I.Doc width={18} height={18} /></span>
            <span className="mail-file-text"><b>{a.name}</b><span className="faint">{kindWords(a)} · {fileSize(a.size)}</span></span></a>}
        <a className="iconbtn small ghost" href={at} download={a.name} aria-label={`Download ${a.name}`} title="Download"><I.Download width={16} height={16} /></a>
      </li>); })}</ul>
    {shown && <div className="scrim mail-preview" role="dialog" aria-modal="true" aria-label={shown.name} onClick={() => setShown(null)}>
      <header className="mail-preview-bar" onClick={e => e.stopPropagation()}><b title={shown.name}>{shown.name}</b>
        <a className="btn small" href={fileUrl(connection, message, shown.id)} download={shown.name}><I.Download width={16} height={16} />Download</a>
        <button type="button" className="iconbtn small" aria-label="Close" autoFocus onClick={() => setShown(null)}><I.Close width={16} height={16} /></button></header>
      <img src={fileUrl(connection, message, shown.id, true)} alt={shown.name} onClick={e => e.stopPropagation()} />
    </div>}
  </>;
}

/** One message of an open conversation. Closed, it is one line (who, the first words, when). Open, it has its header (who wrote it, to whom, when: the full list of
 *  people on demand), its content in a frame that can run nothing, and its files. Remote pictures stay out until the customer asks for them, for this message or for
 *  this sender. */
function MessageItem({ connection, message, zone, own, now, initiallyOpen, alone, onSender }: { connection: string; message: Message; zone: string; own?: string; now: number;
  initiallyOpen: boolean; alone: boolean; onSender(address: string): void }) {
  const [open, setOpen] = useState(initiallyOpen); const [shown, setShown] = useState(message); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const [images, setImages] = useState(false); const [details, setDetails] = useState(false);
  useEffect(() => { setShown(message); }, [message]);
  const load = useCallback(async (withImages: boolean) => {
    setBusy(true); setErr('');
    try { const r = await hub.message(connection, message.id, withImages); setShown(r.message); setErr(problemWords(r.problem)); if (withImages) setImages(true); }
    catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  }, [connection, message.id]);
  useEffect(() => { if (initiallyOpen && !message.body) void load(false); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = () => { if (alone) return; const next = !open; setOpen(next); if (next && !shown.body && !busy) void load(false); };
  const body = shown.body; const who = personName(shown.sender);
  const everyone = [...shown.to, ...shown.cc];
  return (
    <article className={`mail-message${open ? ' open' : ''}`} aria-label={`Message from ${who}`}>
      <header className="mail-message-head">
        <Mark person={shown.sender} />
        <div className="mail-message-who">
          <div className="mail-message-line"><button type="button" className="mail-message-toggle" aria-expanded={open} disabled={alone} onClick={toggle}><b>{who}</b>
            {open && shown.sender.name && shown.sender.address && <span className="mail-message-address faint">{shown.sender.address}</span>}</button>
            <time className="faint small" dateTime={new Date(shown.sent_epoch * 1000).toISOString()} title={fullTime(shown.sent_epoch, zone)}>{open ? fullTime(shown.sent_epoch, zone) : listTime(shown.sent_epoch, zone, now)}</time></div>
          {open ? <button type="button" className="mail-message-to faint small" aria-expanded={details} disabled={!everyone.length} onClick={() => setDetails(d => !d)}>
            to {recipients(shown.to, shown.cc, own)}{everyone.length > 0 && <I.ChevronDown width={12} height={12} className={details ? 'flip' : undefined} />}</button>
            : <button type="button" className="mail-message-snippet faint small" tabIndex={-1} aria-hidden="true" onClick={toggle}>{shown.snippet}</button>}
        </div>
      </header>
      {open && <div className="mail-message-body">
        {details && <dl className="mail-people-list small">
          <dt>From</dt><dd>{shown.sender.name ? `${shown.sender.name} <${shown.sender.address}>` : shown.sender.address}</dd>
          {shown.to.length > 0 && <><dt>To</dt><dd>{shown.to.map(p => (p.name ? `${p.name} <${p.address}>` : p.address)).join(', ')}</dd></>}
          {shown.cc.length > 0 && <><dt>Cc</dt><dd>{shown.cc.map(p => (p.name ? `${p.name} <${p.address}>` : p.address)).join(', ')}</dd></>}
          <dt>Sent</dt><dd>{fullTime(shown.sent_epoch, zone)}</dd></dl>}
        {busy && !body && <div className="mail-opening" role="status"><div className="skeleton" /><div className="skeleton" /><div className="skeleton short" /><span className="sr">Opening…</span></div>}
        {err && <p className="notice warning" role="alert">{err} <button type="button" className="btn small tertiary" onClick={() => load(false)}>Try again</button></p>}
        {body && body.blocked_images > 0 && <p className="mail-pictures small" role="note">
          <I.Picture width={16} height={16} /><span>{body.blocked_images === 1 ? 'A picture is' : `${body.blocked_images} pictures are`} hidden, so the sender cannot tell that you opened this.</span>
          <button type="button" className="btn small" disabled={busy} onClick={() => load(true)}>Show pictures</button>
          {shown.sender.address && <button type="button" className="btn small tertiary" disabled={busy} onClick={() => { onSender(shown.sender.address); void load(true); }}>Always from this sender</button>}</p>}
        {body && <MessageBody connection={connection} id={shown.id} images={images || body.images_shown} designed={!!body.designed} title={`Message from ${who}`} />}
        {body && <Attachments connection={connection} message={shown.id} files={body.attachments} />}
      </div>}
    </article>);
}

export interface ReaderActions {
  organize(op: OrganizeOp, label?: string): void;
  can(op: OrganizeOp): boolean;
  reply(): void; replyAll(): void; forward(): void;
  close(): void; next?(): void; previous?(): void;
}

/** The open conversation: its subject and what can be done with it at the top, its messages below (the newest open, the earlier ones one line each), and room to
 *  answer at the end. What may not be done in this account is not drawn disabled: it is not drawn, and where a permission would make it possible that is offered once. */
export default function Reader({ thread, summary, messages, problem, error, account, accountsShown, zone, now, labels, actions, onSender, children, footer }: {
  thread: Thread | null; summary?: Thread; messages: Message[] | null; problem: string | null; error: string; account?: HubAccount; accountsShown: number; zone: string; now: number;
  labels: { id: string; name: string }[]; actions: ReaderActions; onSender(address: string): void; children?: ReactNode; footer?: ReactNode;
}) {
  const head = thread ?? summary; const subject = head?.subject || '(no subject)';
  const end = useRef<HTMLDivElement>(null);
  const tool = (label: string, icon: ReactNode, run: () => void, key?: string) =>
    <button type="button" className="iconbtn small ghost" aria-label={label} title={key ? `${label} (${key})` : label} onClick={run}>{icon}</button>;
  const inInbox = !!thread?.labels.includes('inbox'), inBin = !!thread?.labels.includes('trash');
  const more: MenuItem[] = thread ? [
    ...(actions.can('unread') ? [{ id: 'unread', label: 'Mark as unread', hint: 'U', onSelect: () => actions.organize('unread') }] : []),
    ...(actions.can('label') ? labels.map((l, n) => ({ id: 'label:' + l.id, label: l.name, section: n === 0 ? (account?.capabilities.labels === 'folders' ? 'Move to folder' : 'Add label') : undefined,
      checked: thread.provider_labels.some(p => p.id === l.id), onSelect: () => actions.organize(thread.provider_labels.some(p => p.id === l.id) ? 'unlabel' : 'label', l.id) })) : []),
  ] : [];
  return <div className="mail-reader">
    <header className="mail-reader-head">
      <div className="mail-reader-bar">
        <button type="button" className="iconbtn small ghost md-back" aria-label="Back to the list" title="Back (Esc)" onClick={actions.close}><I.Back width={18} height={18} /></button>
        {thread && <div className="mail-tools" role="toolbar" aria-label="This conversation">
          {actions.can('archive') && (inInbox ? tool('Archive', <I.Archive width={18} height={18} />, () => actions.organize('archive'), 'E')
            : !inBin && tool('Move to the inbox', <I.Inbox width={18} height={18} />, () => actions.organize('inbox')))}
          {actions.can('trash') && (inBin ? tool('Take out of the bin', <I.Inbox width={18} height={18} />, () => actions.organize('untrash')) : tool('Move to the bin', <I.Trash width={18} height={18} />, () => actions.organize('trash'), '#'))}
          {actions.can('star') && tool(thread.starred ? 'Remove the star' : 'Star', thread.starred ? <I.StarFilled width={18} height={18} className="mail-starred" /> : <I.Star width={18} height={18} />, () => actions.organize(thread.starred ? 'unstar' : 'star'), 'S')}
          {more.length > 0 && <Menu label="More for this conversation" align="end" items={more}
            trigger={({ open, props }) => <button type="button" className="iconbtn small ghost" aria-label="More" title="More" aria-expanded={open} {...props}><I.More width={18} height={18} /></button>} />}
        </div>}
        <span className="mail-reader-nav">
          {actions.previous && tool('Newer conversation', <I.Chevron width={18} height={18} className="up" />, actions.previous, 'K')}
          {actions.next && tool('Older conversation', <I.Chevron width={18} height={18} className="down" />, actions.next, 'J')}
          <button type="button" className="iconbtn small ghost mail-reader-close" aria-label="Close the conversation" title="Close (Esc)" onClick={actions.close}><I.Close width={18} height={18} /></button>
        </span>
      </div>
      <h2 className="mail-subject" dir="auto">{subject}</h2>
      <p className="mail-reader-meta small">
        {accountsShown > 1 && account && <span className="mail-chip" title={`In ${account.identity} (${account.provider_label})`}><I.Person width={12} height={12} />{account.identity}</span>}
        {thread?.provider_labels.map(l => <span key={l.id} className="mail-chip">{l.name}</span>)}
        {thread && thread.message_count > 1 && <span className="faint">{thread.message_count} messages</span>}
      </p>
    </header>
    <div className="mail-reader-scroll">
      {error ? <p className="notice warning mail-pad" role="alert">{error}</p>
        : !messages ? <div className="mail-opening mail-pad" role="status">{summary && <p><b>{summary.people.map(personName).slice(0, 2).join(', ')}</b> <span className="faint small">{listTime(summary.last_epoch, zone, now)}</span></p>}
          <div className="skeleton" /><div className="skeleton" /><div className="skeleton short" /><span className="sr">Opening…</span></div>
        : <>
          {problem && <p className="notice warning mail-pad" role="alert">{problemWords(problem)}</p>}
          <div className="mail-messages">{messages.map((m, i) => <MessageItem key={m.id} connection={thread!.connection_id} message={m} zone={zone} own={account?.identity} now={now}
            initiallyOpen={i === messages.length - 1} alone={messages.length === 1} onSender={onSender} />)}</div>
          <div className="mail-answer" ref={end}>
            {children}
            {footer ?? <div className="mail-answer-actions">
              <button type="button" className="btn" onClick={actions.reply} title="Reply (R)"><I.Reply width={16} height={16} />Reply</button>
              {messages.some(m => m.to.length + m.cc.length > 1) && <button type="button" className="btn" onClick={actions.replyAll} title="Reply to everyone (A)"><I.ReplyAll width={16} height={16} />Reply all</button>}
              <button type="button" className="btn" onClick={actions.forward} title="Forward (F)"><I.Forward width={16} height={16} />Forward</button></div>}
          </div>
        </>}
    </div>
  </div>;
}
