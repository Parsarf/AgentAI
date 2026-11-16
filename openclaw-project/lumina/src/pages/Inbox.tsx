import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as I from '../components/Icons';
import Accounts from '../components/hub/Accounts';
import { AddAccount, ChooseAccess, CONNECT_NOTE } from '../components/hub/Connect';
import Dock, { type Looking, type Suggestion } from '../components/hub/Dock';
import MessageBody from '../components/hub/MessageBody';
import { api } from '../lib/api';
import { browserZone, failed, fileSize, fullTime, hub, LABEL_WORDS, LIST_ORDER, listTime, people, personName, problemWords, threadKey, validZone,
  type HubAccount, type Message, type Overview, type Thread } from '../lib/hub';
import { useData } from '../state/data';
import '../styles/hub.css';

type Opened = { thread: Thread; messages: Message[]; problem: string | null };
type Older = { connection: string; found: { id: string; thread_id: string; connection_id: string; subject: string; sender: { name: string; address: string }; sent_epoch: number; snippet: string }[];
  complete: boolean; continuation: string | null; problem: string | null };
const nowSeconds = () => Math.floor(Date.now() / 1000);

/** One message of an open thread. Its header is always there; its content is fetched when it is opened, and shown inside a frame that can run nothing. Remote pictures stay
 *  out until the customer asks for them, for this message or for this sender. */
function MessageItem({ connection, message, zone, initiallyOpen, onSender }: { connection: string; message: Message; zone: string; initiallyOpen: boolean; onSender(address: string): void }) {
  const [open, setOpen] = useState(initiallyOpen); const [shown, setShown] = useState(message); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  useEffect(() => { setShown(message); }, [message]);
  const load = useCallback(async (images: boolean) => {
    setBusy(true); setErr('');
    try { const r = await hub.message(connection, message.id, images); setShown(r.message); setErr(problemWords(r.problem)); }
    catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  }, [connection, message.id]);
  const toggle = () => { const next = !open; setOpen(next); if (next && !shown.body && !busy) void load(false); };
  const body = shown.body;
  return (
    <article className={`hub-message${open ? ' open' : ''}`} aria-label={`Message from ${personName(shown.sender)}`}>
      <button type="button" className="hub-message-head" aria-expanded={open} onClick={toggle}>
        <span className="hub-avatar" aria-hidden="true">{(personName(shown.sender)[0] ?? '?').toUpperCase()}</span>
        <span className="hub-message-who"><b>{personName(shown.sender)}</b>
          <span className="faint small">{open ? `to ${shown.to.map(personName).join(', ') || 'no one'}${shown.cc.length ? `, copy to ${shown.cc.map(personName).join(', ')}` : ''}` : shown.snippet}</span></span>
        <time className="faint small" dateTime={new Date(shown.sent_epoch * 1000).toISOString()}>{fullTime(shown.sent_epoch, zone)}</time>
      </button>
      {open && <div className="hub-message-body">
        {busy && !body && <p className="muted" role="status">Opening…</p>}
        {err && <p className="notice warning" role="alert">{err} <button type="button" className="btn small tertiary" onClick={() => load(false)}>Try again</button></p>}
        {body && body.blocked_images > 0 && <p className="hub-images small">
          {body.blocked_images === 1 ? '1 picture is' : `${body.blocked_images} pictures are`} not shown, so the sender cannot tell that you opened this.{' '}
          <button type="button" className="btn small tertiary" disabled={busy} onClick={() => load(true)}>Show pictures</button>
          {shown.sender.address && <button type="button" className="btn small tertiary" disabled={busy} onClick={() => { onSender(shown.sender.address); void load(true); }}>Always show from {shown.sender.address}</button>}</p>}
        {body && <MessageBody html={body.html} title={`Message from ${personName(shown.sender)}`} />}
        {body && body.attachments.length > 0 && <ul className="hub-attachments" aria-label="Attachments">{body.attachments.map(a => (
          <li key={a.id}><I.Clip width={16} height={16} /><span title={a.name}>{a.name}</span><span className="faint small">{fileSize(a.size)}</span></li>))}</ul>}
      </div>}
    </article>);
}

/** The Inbox: the mail of every connected account in one list. Left: accounts and filters. Middle: threads, newest first. Right: the open thread. Read-only in this phase:
 *  nothing here sends, archives, labels or marks anything as read in the customer's mailbox, and the page says so where those controls would be. */
export default function Inbox() {
  const { app } = useData(); const on = !!app?.features.dashboard;
  const [view, setView] = useState<Overview | null>(null); const [err, setErr] = useState(''); const [now, setNow] = useState(nowSeconds);
  const [chosen, setChosen] = useState<Set<string> | null>(null); const [label, setLabel] = useState('inbox'); const [providerLabel, setProviderLabel] = useState<{ account: string; id: string; name: string } | null>(null);
  const [unread, setUnread] = useState(false); const [attachments, setAttachments] = useState(false); const [typed, setTyped] = useState(''); const [query, setQuery] = useState('');
  const [threads, setThreads] = useState<Thread[] | null>(null); const [next, setNext] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const [own, setOwn] = useState<{ connection_id: string; labels: { id: string; name: string; threads: number }[] }[]>([]);
  const [selected, setSelected] = useState<string | null>(null); const [opened, setOpened] = useState<Opened | null>(null); const [openErr, setOpenErr] = useState('');
  const [older, setOlder] = useState<Older | null>(null);
  const search = useRef<HTMLInputElement>(null); const request = useRef(0);
  const [params, setParams] = useSearchParams(); const [choosing, setChoosing] = useState<string | null>(params.get('connected'));
  const connectNote = CONNECT_NOTE[params.get('connect') ?? ''];
  const doneChoosing = () => { setChoosing(null); setParams({}, { replace: true }); window.setTimeout(() => { void loadOverview(); void load(); }, 1200); };

  const zone = useMemo(() => (view?.settings.timezone && validZone(view.settings.timezone) ? view.settings.timezone : browserZone()), [view?.settings.timezone]);
  const accounts = useMemo(() => (view?.accounts ?? []).filter(a => a.capabilities.mail), [view]);
  const byId = useMemo(() => Object.fromEntries(accounts.map(a => [a.id, a])) as Record<string, HubAccount>, [accounts]);
  const shownAccounts = useMemo(() => accounts.filter(a => !chosen || chosen.has(a.id)).map(a => a.id), [accounts, chosen]);

  const loadOverview = useCallback(async () => {
    try { const r = await hub.overview(); setView(r); setErr(''); setNow(nowSeconds()); hub.labels().then(l => setOwn(l.labels)).catch(() => undefined); }
    catch (e) { setErr(failed(e)); setView(v => v ?? { accounts: [], settings: { timezone: null, image_senders: [] }, counts: { unread: 0, by_account: {} }, calendars: [], labels: [], colours: [], read_only: true }); }
  }, []);
  useEffect(() => { if (on) void loadOverview(); }, [on, loadOverview]);
  // Coming back from a provider: its return cannot carry the session (it arrives from another site), so the server handed the two values to this page in the address
  // fragment. The page finishes the sign-in itself, from inside Lumina, and takes them out of the address at once.
  const [linkNote, setLinkNote] = useState('');
  const finishing = useRef(false);
  useEffect(() => {
    if (!on || finishing.current || !window.location.hash.includes('link-state=')) return;
    const given = new URLSearchParams(window.location.hash.slice(1)); const state = given.get('link-state'), code = given.get('link-code');
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    if (!state || !code) return;
    finishing.current = true; setLinkNote('Connecting your account…');
    api<{ connection_id: string }>('POST', '/v1/hub/link/finish', { state, code })
      .then(async r => { setLinkNote(''); await loadOverview(); setChoosing(r.connection_id); })
      .catch(() => setLinkNote(CONNECT_NOTE.failed));
  }, [on, loadOverview]);

  const filters = useMemo(() => ({ label, accounts: providerLabel ? [providerLabel.account] : shownAccounts, provider_label: providerLabel?.id, unread: unread || undefined,
    attachments: attachments || undefined, q: query || undefined, limit: 50 }), [label, providerLabel, shownAccounts, unread, attachments, query]);
  const filterKey = JSON.stringify(filters);
  const load = useCallback(async (cursor?: string) => {
    if (!view) return;
    if (!filters.accounts.length) { setThreads([]); setNext(null); return; }
    const mine = ++request.current; setLoading(true);
    try {
      const r = await hub.threads({ ...filters, cursor });
      if (mine !== request.current) return;                              // a newer filter was chosen while this one was on its way
      setThreads(prev => (cursor && prev ? [...prev, ...r.threads] : r.threads)); setNext(r.next); setErr('');
    } catch (e) { if (mine === request.current) { setErr(failed(e)); setThreads(prev => prev ?? []); } }
    finally { if (mine === request.current) setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, !!view]);
  useEffect(() => { setOlder(null); void load(); }, [load]);

  const open = useCallback(async (t: Thread) => {
    setSelected(threadKey(t)); setOpened(null); setOpenErr('');
    try { const r = await hub.thread(t.connection_id, t.id); setOpened(r); }
    catch (e) { setOpenErr(failed(e)); }
  }, []);
  const close = () => { setSelected(null); setOpened(null); setOpenErr(''); };

  const refresh = async () => { try { await hub.refresh(); } catch (e) { setErr(failed(e)); } window.setTimeout(() => { void loadOverview(); void load(); }, 1500); };
  const toggle = (id: string) => setChosen(prev => { const base = new Set(prev ?? accounts.map(a => a.id)); if (base.has(id)) base.delete(id); else base.add(id); return base; });
  const allowSender = (address: string) => { hub.setSettings({ allow_images_from: address }).then(r => setView(v => (v ? { ...v, settings: r.settings } : v))).catch(() => undefined); };
  const searchOlder = async (connection: string, continuation?: string | null) => {
    try {
      const r = await hub.searchOlder(connection, query, continuation);
      setOlder(prev => ({ connection, found: [...(continuation && prev?.connection === connection ? prev.found : []), ...r.messages], complete: r.page?.complete ?? true,
        continuation: r.page?.continuation ?? null, problem: r.problem }));
    } catch (e) { setOlder({ connection, found: [], complete: true, continuation: null, problem: null }); setErr(failed(e)); }
  };

  // Keyboard: j and k move through the list, Enter opens, Escape closes, "/" goes to search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) { if (e.key === 'Escape') target.blur(); return; }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === '/') { e.preventDefault(); search.current?.focus(); return; }
      if (e.key === 'Escape' && selected) { close(); return; }
      if (!threads?.length || (e.key !== 'j' && e.key !== 'k')) return;
      const at = threads.findIndex(t => threadKey(t) === selected);
      const to = threads[Math.min(threads.length - 1, Math.max(0, at + (e.key === 'j' ? 1 : -1)))];
      if (to) { e.preventDefault(); void open(to); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [threads, selected, open]);

  if (!on) return (
    <div className="center"><h1 className="page-title">Inbox</h1><section className="panel card"><h2>Not available yet</h2>
      <p className="muted" style={{ marginTop: 8 }}>The mail of your connected accounts in one place, with your assistant beside it.</p>
      <p style={{ marginTop: 16 }}><Link className="btn" to="/">Back to Home</Link></p></section></div>);

  const needing = accounts.filter(a => a.state === 'needs_you');
  const choosingAccount = (view?.accounts ?? []).find(a => a.id === choosing);
  const filling = accounts.filter(a => a.mail && !a.mail.filled && a.state === 'working');
  const searchable = query ? accounts.filter(a => shownAccounts.includes(a.id) && a.capabilities.mail_search) : [];
  const title = providerLabel ? providerLabel.name : LABEL_WORDS[label] ?? label;
  const looking: Looking = opened ? { kind: 'thread', connection: opened.thread.connection_id, thread: opened.thread.id } : { kind: 'mail', label, ...(query ? { query } : {}) };
  const lookingWords = opened ? `the thread “${opened.thread.subject || '(no subject)'}”` : `${title}${query ? `, searching “${query}”` : ''}`;
  const suggestions: Suggestion[] = opened ? [{ label: 'Summarize', message: 'Summarize this thread.' }, { label: 'What do they need from me?', message: 'What do they need from me in this thread, and by when?' },
    { label: 'Draft a reply', message: 'Draft a reply to this thread for me to review. Do not send anything.' }]
    : [{ label: 'What needs my attention?', message: 'Which threads in my mail need my attention most? List them with why.' }, { label: 'Unread, in short', message: 'Summarize my unread mail in a few lines.' }];
  return (
    <div className={`hub hub-inbox has-dock${selected ? ' has-open' : ''}`}>
      <aside className="hub-side panel" aria-label="Mail filters">
        <Accounts accounts={accounts} part="mail" chosen={new Set(shownAccounts)} onToggle={toggle} counts={view?.counts.by_account} now={now} providers={view?.providers} onChoose={a => setChoosing(a.id)} />
        <nav className="hub-labels" aria-label="Mailboxes">
          {LIST_ORDER.map(l => <button key={l} type="button" className="hub-label" aria-current={!providerLabel && label === l ? 'page' : undefined} onClick={() => { setProviderLabel(null); setLabel(l); }}>
            <span>{LABEL_WORDS[l]}</span>{l === 'inbox' && !!view?.counts.unread && <span className="badge accent" aria-label={`${view.counts.unread} unread`}>{view.counts.unread}</span>}</button>)}
        </nav>
        <div className="hub-toggles">
          <label><input type="checkbox" checked={unread} onChange={e => setUnread(e.target.checked)} /> Unread only</label>
          <label><input type="checkbox" checked={attachments} onChange={e => setAttachments(e.target.checked)} /> Has an attachment</label>
        </div>
        {own.filter(o => shownAccounts.includes(o.connection_id) && o.labels.length).map(o => (
          <details key={o.connection_id} className="hub-own">
            <summary>{byId[o.connection_id]?.capabilities.labels === 'folders' ? 'Folders' : 'Labels'} in {byId[o.connection_id]?.identity ?? 'this account'}</summary>
            {o.labels.map(l => <button key={l.id} type="button" className="hub-label" aria-current={providerLabel?.account === o.connection_id && providerLabel.id === l.id ? 'page' : undefined}
              onClick={() => { setLabel('all'); setProviderLabel({ account: o.connection_id, id: l.id, name: l.name }); }}><span>{l.name}</span><span className="faint small">{l.threads}</span></button>)}
          </details>))}
      </aside>

      <section className="hub-list panel" aria-label={`${title}: threads`}>
        <header className="hub-list-head">
          <h1>{title}</h1>
          <form className="hub-search" role="search" onSubmit={e => { e.preventDefault(); setQuery(typed.trim()); }}>
            <I.Search width={16} height={16} />
            <input ref={search} className="input" type="search" placeholder="Search mail" aria-label="Search mail" value={typed} onChange={e => { setTyped(e.target.value); if (!e.target.value) setQuery(''); }} />
          </form>
          <button type="button" className="iconbtn small ghost" aria-label="Refresh" title="Refresh" onClick={refresh}><I.Retry width={16} height={16} /></button>
        </header>
        <p className="hub-readonly faint small">Read only for now: nothing here changes your mailbox, and opening a message does not mark it as read there.</p>
        {err && <p className="notice warning" role="alert">{err}</p>}
        {(linkNote || connectNote) && <p className={`notice${linkNote.endsWith('…') ? '' : ' warning'}`} role="status">{linkNote || connectNote}</p>}
        {choosingAccount && <ChooseAccess account={choosingAccount} onDone={doneChoosing} onCancel={() => { setChoosing(null); setParams({}, { replace: true }); }} />}
        {needing.map(a => <p key={a.id} className="notice warning" role="status">{a.identity} needs you. What was loaded before is still shown. <Link to="/settings?tab=access">Open Access</Link></p>)}
        {filling.length > 0 && <p className="notice" role="status">Loading mail from {filling.map(a => a.identity).join(', ')} for the first time. This list fills in as it arrives.</p>}
        {view && !accounts.length ? (
          <div className="empty"><b>No mail account is connected</b><p className="muted">Connect an account and choose what Lumina may read. It shows up here.</p>
            <AddAccount providers={view.providers ?? []} primary /></div>
        ) : threads === null ? <p className="muted hub-pad" role="status">Loading…</p> : !threads.length && !loading ? (
          <div className="empty">{query ? <>Nothing in the last 90 days matches “{query}”.</> : accounts.some(a => !a.granted.mail) && !accounts.some(a => a.granted.mail)
            ? <>Nothing has been chosen to show yet. Use “Choose what Lumina may read” beside the account.</> : <>Nothing here.</>}</div>
        ) : (
          <ul className="hub-threads" aria-label="Threads">
            {threads.map(t => { const k = threadKey(t); const account = byId[t.connection_id]; return (
              <li key={k}><button type="button" className={`hub-thread${t.unread ? ' unread' : ''}`} aria-current={selected === k ? 'true' : undefined} onClick={() => open(t)}>
                <span className="hub-thread-top"><span className="hub-thread-who">{people(t.people, account?.identity)}{t.message_count > 1 && <span className="faint"> {t.message_count}</span>}</span>
                  <time className="faint small">{listTime(t.last_epoch, zone, now)}</time></span>
                <span className="hub-thread-subject">{t.unread && <i className="hub-dot" role="img" aria-label="Unread" />}{t.subject || '(no subject)'}</span>
                <span className="hub-thread-snippet faint">{t.snippet}</span>
                <span className="hub-thread-marks faint small">{accounts.length > 1 && <span className="hub-thread-account" title={account?.provider_label}>{account?.identity}</span>}
                  {t.starred && <span>Starred</span>}{t.has_attachments && <span><I.Clip width={12} height={12} /> Attachment</span>}</span>
              </button></li>); })}
          </ul>)}
        {next && <p className="hub-pad"><button type="button" className="btn small" disabled={loading} onClick={() => load(next)}>{loading ? 'Loading…' : 'Show more'}</button></p>}
        {query && threads && !next && searchable.length > 0 && <div className="hub-older">
          <p className="faint small">That was the last 90 days, which Lumina keeps a copy of. Older mail can be searched in your mail service:</p>
          {searchable.map(a => <button key={a.id} type="button" className="btn small" onClick={() => searchOlder(a.id)}>Search older mail in {a.identity}</button>)}
          {older && <div className="hub-older-found" role="status">
            {older.problem ? <p className="notice warning">{problemWords(older.problem)}</p> : <p className="small">{older.complete
              ? `${older.found.length} older message${older.found.length === 1 ? '' : 's'} found. That is all of them.`
              : `The first ${older.found.length} older messages are shown. There are more.`}</p>}
            <ul className="hub-threads">{older.found.map(m => <li key={m.id}><div className="hub-thread static">
              <span className="hub-thread-top"><span className="hub-thread-who">{personName(m.sender)}</span><time className="faint small">{listTime(m.sent_epoch, zone, now)}</time></span>
              <span className="hub-thread-subject">{m.subject || '(no subject)'}</span><span className="hub-thread-snippet faint">{m.snippet}</span></div></li>)}</ul>
            {!older.complete && older.continuation && <button type="button" className="btn small" onClick={() => searchOlder(older.connection, older.continuation)}>Show more older mail</button>}
          </div>}
        </div>}
      </section>

      <section className="hub-open panel" aria-label="Open thread">
        {!selected ? <div className="hub-nothing muted"><p>Select a thread to read it.</p><p className="small faint"><span className="kbd">J</span> <span className="kbd">K</span> move · <span className="kbd">/</span> search · <span className="kbd">Esc</span> close</p></div>
          : openErr ? <p className="notice warning hub-pad" role="alert">{openErr}</p>
          : !opened ? <p className="muted hub-pad" role="status">Opening…</p> : (
            <>
              <header className="hub-open-head">
                <button type="button" className="iconbtn small ghost hub-back" aria-label="Back to the list" onClick={close}><I.Chevron width={16} height={16} /></button>
                <div><h2>{opened.thread.subject || '(no subject)'}</h2>
                  <p className="faint small">{byId[opened.thread.connection_id]?.identity}{opened.thread.provider_labels.length ? ` · ${opened.thread.provider_labels.map(l => l.name).join(', ')}` : ''}</p></div>
              </header>
              {opened.problem && <p className="notice warning" role="alert">{problemWords(opened.problem)}</p>}
              <div className="hub-messages">{opened.messages.map((m, i) => <MessageItem key={m.id} connection={opened.thread.connection_id} message={m} zone={zone}
                initiallyOpen={i === opened.messages.length - 1} onSender={allowSender} />)}</div>
            </>)}
      </section>
      <Dock looking={looking} lookingWords={lookingWords} suggestions={suggestions} />
    </div>);
}
