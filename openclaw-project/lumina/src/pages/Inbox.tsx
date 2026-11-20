import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as I from '../components/Icons';
import Accounts from '../components/hub/Accounts';
import { AddAccount, ChooseAccess, CONNECT_NOTE } from '../components/hub/Connect';
import Workspace from '../components/frame/Workspace';
import List from '../components/frame/List';
import { EmptyState } from '../components/frame/parts';
import { useSelection, type Action, type Looking } from '../components/frame/Assistant';
import { useSettings } from '../state/settings';
import { useCommands } from '../components/frame/CommandBar';
import MessageBody from '../components/hub/MessageBody';
import DraftEditor, { type DraftStart } from '../components/hub/DraftEditor';
import AllowChanges from '../components/hub/AllowChanges';
import { usePulse } from '../components/hub/usePulse';
import { api } from '../lib/api';
import { browserZone, failed, fileSize, fullTime, hub, LABEL_WORDS, LIST_ORDER, listTime, people, personName, problemWords, threadKey, validZone,
  replySubject, type Draft, type HubAccount, type HubAction, type Message, type OrganizeOp, type Overview, type Thread } from '../lib/hub';
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

/** A reply to a thread: to whoever wrote its last message that was not from this account, with "Re:" once. "Reply all" adds everyone else on that message (never this
 *  account). The reply is sent from the account that received the thread. */
function replyTo(opened: Opened, own: string | undefined, all = false): DraftStart {
  const mine = (own ?? '').toLowerCase();
  const last = [...opened.messages].reverse().find(m => m.sender.address && m.sender.address.toLowerCase() !== mine) ?? opened.messages[opened.messages.length - 1];
  const to = last?.sender.address ? [last.sender.address] : [];
  const others = all && last ? [...last.to, ...last.cc].map(p => p.address).filter(a => a && a.toLowerCase() !== mine && !to.some(t => t.toLowerCase() === a.toLowerCase())) : [];
  return { account: opened.thread.connection_id, thread: opened.thread.id, to, cc: [...new Set(others)], subject: replySubject(opened.thread.subject || last?.subject || '') };
}

/** A forward of the thread's last message: to nobody yet, "Fwd:" once, with that message quoted below the customer's own words. A new conversation. */
function forwardOf(opened: Opened, zone: string): DraftStart {
  const last = opened.messages[opened.messages.length - 1];
  const subject = (opened.thread.subject || last?.subject || '').trim();
  const head = last ? [`---------- Forwarded message ----------`, `From: ${personName(last.sender)}${last.sender.name ? ` <${last.sender.address}>` : ''}`, `Date: ${fullTime(last.sent_epoch, zone)}`,
    `Subject: ${last.subject}`, `To: ${last.to.map(p => p.address).join(', ')}`].join('\n') : '';
  const text = last?.body?.text || last?.snippet || '';
  return { account: opened.thread.connection_id, thread: null, to: [], subject: /^fwd?:/i.test(subject) ? subject : `Fwd: ${subject}`, body: `\n\n${head}\n\n${text}` };
}

/** The Inbox: the mail of every connected account in one list. Context: accounts, mailboxes and filters. Canvas: the threads, newest first (only the rows in view are drawn,
 *  so a mailbox of any size scrolls smoothly). Inspector: the open thread, or the thread in place of the list in the full reading view. Read-only in this phase: nothing here
 *  sends, archives, labels or marks anything as read in the customer's mailbox, and the page says so where those controls would be. */
const READING_KEY = 'lumina.inbox.reading';
const LUMINA = 'lumina';                 // the "Written in Lumina" list: drafts kept in Lumina, across accounts
const readReading = (): 'split' | 'full' => { try { return localStorage.getItem(READING_KEY) === 'full' ? 'full' : 'split'; } catch { return 'split'; } };

export default function Inbox() {
  const { app } = useData(); const on = !!app?.features.dashboard; const { compact } = useSettings();
  const [view, setView] = useState<Overview | null>(null); const [err, setErr] = useState(''); const [now, setNow] = useState(nowSeconds);
  const [chosen, setChosen] = useState<Set<string> | null>(null); const [label, setLabel] = useState('inbox'); const [providerLabel, setProviderLabel] = useState<{ account: string; id: string; name: string } | null>(null);
  const [unread, setUnread] = useState(false); const [attachments, setAttachments] = useState(false); const [typed, setTyped] = useState(''); const [query, setQuery] = useState('');
  const [threads, setThreads] = useState<Thread[] | null>(null); const [next, setNext] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const [own, setOwn] = useState<{ connection_id: string; labels: { id: string; name: string; threads: number }[] }[]>([]);
  const [selected, setSelected] = useState<string | null>(null); const [opened, setOpened] = useState<Opened | null>(null); const [openErr, setOpenErr] = useState('');
  const [older, setOlder] = useState<Older | null>(null);
  // Drafts kept in Lumina (#57): those of the open thread, the "Written in Lumina" list, and one opened on its own (a new message, not a reply).
  const [threadDrafts, setThreadDrafts] = useState<Draft[]>([]); const [replying, setReplying] = useState<DraftStart | null>(null);
  const [replyingId, setReplyingId] = useState<string | null>(null);     // the reply being written, once saved: it stays in its editor (not listed twice) until sent or discarded
  const [luminaDrafts, setLuminaDrafts] = useState<Draft[] | null>(null); const [openDraft, setOpenDraft] = useState<Draft | DraftStart | null>(null);
  const wantedDraft = useRef<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(() => new Set()); const anchor = useRef<number | null>(null);
  const [reading, setReadingState] = useState<'split' | 'full'>(readReading);
  const setReading = (r: 'split' | 'full') => { setReadingState(r); try { localStorage.setItem(READING_KEY, r); } catch { /* private mode */ } };
  const search = useRef<HTMLInputElement>(null); const request = useRef(0); const cache = useRef(new Map<string, Opened>());
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

  // Until the customer narrows the accounts, the list asks for every account's mail: it then does not wait for the accounts overview (one round trip fewer).
  const filters = useMemo(() => ({ label, accounts: providerLabel ? [providerLabel.account] : chosen ? shownAccounts : undefined, provider_label: providerLabel?.id, unread: unread || undefined,
    attachments: attachments || undefined, q: query || undefined, limit: 50 }), [label, providerLabel, chosen, shownAccounts, unread, attachments, query]);
  const filterKey = JSON.stringify(filters);
  const further = useRef(false); const [fresh, setFresh] = useState(false);
  const loadDrafts = useCallback(async () => {
    try { const r = await hub.drafts(); setLuminaDrafts(r.drafts); } catch (e) { setErr(failed(e)); setLuminaDrafts(prev => prev ?? []); }
  }, []);
  const load = useCallback(async (cursor?: string) => {
    if (label === LUMINA) { setThreads([]); setNext(null); void loadDrafts(); return; }
    if (filters.accounts && !filters.accounts.length) { setThreads([]); setNext(null); return; }
    const mine = ++request.current; setLoading(true);
    try {
      const r = await hub.threads({ ...filters, cursor });
      if (mine !== request.current) return;                              // a newer filter was chosen while this one was on its way
      setThreads(prev => (cursor && prev ? [...prev, ...r.threads.filter(t => !prev.some(p => threadKey(p) === threadKey(t)))] : r.threads)); setNext(r.next); setErr(''); further.current = !!cursor; if (!cursor) setFresh(false);
    } catch (e) { if (mine === request.current) { setErr(failed(e)); setThreads(prev => prev ?? []); } }
    finally { if (mine === request.current) setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, loadDrafts]);
  useEffect(() => { if (on) { setOlder(null); setPicked(new Set()); void load(); } }, [load, on]);
  // Live: when anything changed at the server, the accounts and the first page of the list are loaded again, quietly. New mail joins at the top while the rows the reader
  // is looking at stay where they are. If the customer has paged further down, the list is left as it is and a line offers the new mail instead.
  usePulse(on, () => { void loadOverview(); if (further.current) setFresh(true); else void load(); void loadThreadDrafts(); });

  const fetchThread = useCallback(async (t: Thread) => {
    const k = threadKey(t); const known = cache.current.get(k); if (known) return known;
    const r = await hub.thread(t.connection_id, t.id); cache.current.set(k, r); if (cache.current.size > 40) cache.current.delete(cache.current.keys().next().value!);
    return r;
  }, []);
  const shownThread = useRef<string | null>(null); const listRef = useRef<Thread[] | null>(null); listRef.current = threads;
  const loadThreadDrafts = useCallback(async () => {
    const k = shownThread.current; if (!k) { setThreadDrafts([]); return; }
    const cut = k.indexOf('\u0000'); const [connection, id] = [k.slice(0, cut), k.slice(cut + 1)];      // a thread's key: its account and its id (threadKey)
    try { const r = await hub.drafts(id); if (shownThread.current === k) setThreadDrafts(r.drafts.filter(d => d.account === connection)); } catch { /* the thread still shows */ }
  }, []);
  const open = useCallback(async (t: Thread) => {
    const k = threadKey(t); shownThread.current = k; setSelected(k); setOpenErr(''); setOpenDraft(null); setReplying(null); setReplyingId(null); setThreadDrafts([]); void loadThreadDrafts();
    setOpened(cache.current.get(k) ?? null);                             // known already (fetched ahead): shown at once, from its headers if nothing else
    let r: Opened;
    try { r = await fetchThread(t); } catch (e) { if (shownThread.current === k) setOpenErr(failed(e)); return; }
    if (shownThread.current !== k) return;                               // the reader moved on while this was on its way
    setOpened(r);
    // The next thread down is fetched ahead, so moving on with j shows it at once.
    const list = listRef.current ?? []; const at = list.findIndex(x => threadKey(x) === k);
    if (at > -1 && list[at + 1]) void fetchThread(list[at + 1]).catch(() => undefined);
  }, [fetchThread, loadThreadDrafts]);
  const close = () => { shownThread.current = null; setSelected(null); setOpened(null); setOpenErr(''); setOpenDraft(null); setReplying(null); setReplyingId(null); setThreadDrafts([]); };

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
  // Select threads (it only selects in this phase: managing mail comes later). Shift extends from the last one chosen.
  const pick = (index: number, extend: boolean) => {
    if (!threads) return;
    setPicked(prev => {
      const next = new Set(prev); const k = threadKey(threads[index]);
      if (extend && anchor.current !== null) { const [a, b] = [Math.min(anchor.current, index), Math.max(anchor.current, index)]; for (let i = a; i <= b; i++) next.add(threadKey(threads[i])); }
      else if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
    anchor.current = index;
  };

  // Phase 6 (#67, #D6): the customer's own changes to their mail. Each goes through the action pipeline at once, shows at once (pending), is final when the provider
  // confirms it, goes back with a sentence when it fails, and can be undone in one step.
  const writes = !!view && !view.read_only;
  const canOrganize = (connection: string, op: OrganizeOp) => writes && !!byId[connection]?.capabilities[op === 'read' || op === 'unread' ? 'mark_read' : 'organize'];
  const [changed, setChanged] = useState<{ actions: HubAction[]; words: string } | null>(null);
  const OP_WORDS: Record<string, string> = { archive: 'Archived', inbox: 'Moved back to the inbox', star: 'Starred', unstar: 'Took the star off', read: 'Marked as read', unread: 'Marked as unread',
    label: 'Labelled', unlabel: 'Took the label off', move: 'Moved', trash: 'Moved to the bin', untrash: 'Took out of the bin' };
  const organize = async (items: Thread[], op: OrganizeOp, labelId?: string) => {
    const chosen = items.filter(t => canOrganize(t.connection_id, op)); if (!chosen.length) return;
    const keys = new Set(chosen.map(threadKey)); const before = threads;
    const leaves = op === 'trash' || (op === 'archive' && label === 'inbox') || (op === 'move' && label === 'inbox');
    setThreads(list => list && (leaves ? list.filter(t => !keys.has(threadKey(t))) : list.map(t => !keys.has(threadKey(t)) ? t
      : { ...t, unread: op === 'read' ? false : op === 'unread' ? true : t.unread, starred: op === 'star' ? true : op === 'unstar' ? false : t.starred })));
    setPicked(new Set()); setErr(''); setChanged(null);
    if (leaves && selected && keys.has(selected)) close();
    const groups = new Map<string, string[]>(); for (const t of chosen) groups.set(t.connection_id, [...(groups.get(t.connection_id) ?? []), t.id]);
    const done: HubAction[] = []; let problem = '';
    for (const [connection, ids] of groups) {
      try { const r = await hub.organize(connection, ids, op, labelId); if (r.action.state === 'done') done.push(r.action); else problem = r.action.ended_words || 'That could not be done in your mailbox.'; }
      catch (e) { problem = failed(e); }
    }
    if (problem) { setThreads(before); setErr(`${problem} Nothing was left half done in the list: it shows your mailbox as it is.`); }
    if (done.length) setChanged({ actions: done, words: `${OP_WORDS[op]} ${chosen.length} ${chosen.length === 1 ? 'conversation' : 'conversations'}.` });
    window.setTimeout(() => { void load(); }, 1500);
  };
  const undoChange = async () => {
    if (!changed) return;
    try { for (const a of changed.actions) await hub.undo(a.id, 'inbox'); setChanged({ actions: [], words: 'Undone.' }); } catch (e) { setErr(failed(e)); }
    window.setTimeout(() => { void load(); }, 1200);
  };
  const pickedThreads = (threads ?? []).filter(t => picked.has(threadKey(t)));
  const mail = view?.settings.mail;
  const saveMail = async (change: Parameters<typeof hub.setSettings>[0]['mail']) => {
    try { const r = await hub.setSettings({ mail: change }); setView(v => (v ? { ...v, settings: r.settings } : v)); } catch (e) { setErr(failed(e)); }
  };
  // Opening a message marks it read in the mailbox only when the customer turned that on (default off: reading in Lumina does not change the mailbox silently).
  const marked = useRef('');
  useEffect(() => {
    const t = opened?.thread; if (!t || !t.unread || !mail?.mark_read_on_open || !canOrganize(t.connection_id, 'read') || marked.current === threadKey(t)) return;
    marked.current = threadKey(t);
    hub.organize(t.connection_id, [t.id], 'read').then(() => setThreads(list => list && list.map(x => (threadKey(x) === threadKey(t) ? { ...x, unread: false } : x)))).catch(() => undefined);
  }, [opened?.thread.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  const sent = (where: 'thread' | 'draft') => (draftId: string) => {
    if (where === 'thread') setThreadDrafts(list => list.filter(x => x.id !== draftId)); else { close(); void loadDrafts(); }
    setChanged({ actions: [], words: 'Sent.' }); window.setTimeout(() => { void load(); }, 2000);
  };

  // Keyboard: j and k move through the list, Enter opens, Escape closes, x selects, "/" goes to search.
  const active = threads ? threads.findIndex(t => threadKey(t) === selected) : -1;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) { if (e.key === 'Escape') target.blur(); return; }
      if (e.metaKey || e.ctrlKey || e.altKey || document.querySelector('[role="dialog"][aria-modal="true"]:not(.zone-sheet)')) return;
      if (e.key === '/') { e.preventDefault(); search.current?.focus(); return; }
      if (e.key === 'Escape' && selected) { close(); return; }
      if (e.key === 'x' && active > -1) { e.preventDefault(); pick(active, e.shiftKey); return; }
      if (!threads?.length || (e.key !== 'j' && e.key !== 'k')) return;
      const to = threads[Math.min(threads.length - 1, Math.max(0, active + (e.key === 'j' ? 1 : -1)))];
      if (to) { e.preventDefault(); void open(to); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });   // eslint-disable-line react-hooks/exhaustive-deps

  const title = providerLabel ? providerLabel.name : label === LUMINA ? 'Written in Lumina' : LABEL_WORDS[label] ?? label;
  const openThread = opened && selected === threadKey(opened.thread) ? opened : null;
  const looking: Looking = openThread ? { kind: 'thread', connection: openThread.thread.connection_id, thread: openThread.thread.id } : { kind: 'mail', label, ...(query ? { query } : {}) };
  const lookingWords = openThread ? `the thread “${openThread.thread.subject || '(no subject)'}”` : `${title}${query ? `, searching “${query}”` : ''}`;
  const actions: Action[] = openThread ? [{ label: 'Summarize', message: 'Summarize this thread.' }, { label: 'What do they need from me?', message: 'What do they need from me in this thread, and by when?' },
    { label: 'Draft a reply', message: 'Draft a reply to this thread for me to review. Do not send anything.', draft: true }]
    : [{ label: 'What needs my attention?', message: 'Which threads in my mail need my attention most? List them with why.' }, { label: 'Unread, in short', message: 'Summarize my unread mail in a few lines.' }];
  useSelection(on ? { looking, words: lookingWords, actions } : null);
  useCommands(on ? [{ id: 'mail-refresh', label: 'Refresh mail', run: () => { void refresh(); } },
    { id: 'mail-reading', label: reading === 'full' ? 'Read threads beside the list' : 'Read threads in place of the list', run: () => setReading(reading === 'full' ? 'split' : 'full') },
    { id: 'mail-unread', label: unread ? 'Show all mail, read and unread' : 'Show unread mail only', run: () => setUnread(!unread) },
    { id: 'mail-search', label: 'Search mail', shortcut: 'mail-search', run: () => window.setTimeout(() => search.current?.focus(), 0) }] : []);
  // Opened from the command bar or from a link in an answer: ?connection=&thread= opens that thread (its headers come with it), &draft= also opens that Lumina draft;
  // ?connection=&draft= alone opens a draft that is not a reply. A new link while the page is open selects the new thread in place.
  const linked = useRef('');
  useEffect(() => {
    const id = params.get('thread'), connection = params.get('connection'), draft = params.get('draft');
    const key = `${connection}|${id}|${draft}`;
    if (!on || linked.current === key || !connection || (!id && !draft)) return;
    linked.current = key; wantedDraft.current = draft;
    if (id) { void open({ connection_id: connection, id, subject: '', snippet: '', people: [], last_epoch: 0, message_count: 0, unread: false, starred: false, has_attachments: false, labels: [], provider_labels: [] }); return; }
    hub.drafts().then(r => { const found = r.drafts.find(d => d.id === draft); if (found) { close(); setOpenDraft(found); setSelected('draft:' + found.id); } }).catch(e => setErr(failed(e)));
  }, [on, params, open]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!on) return (
    <Workspace title="Inbox"><EmptyState title="Not available yet" action={<Link className="btn" to="/home">Back to Home</Link>}>The mail of your connected accounts in one place, with your assistant beside it.</EmptyState></Workspace>);

  const needing = accounts.filter(a => a.state === 'needs_you');
  const choosingAccount = (view?.accounts ?? []).find(a => a.id === choosing);
  const filling = accounts.filter(a => a.mail && !a.mail.filled && a.state === 'working');
  const searchable = query ? accounts.filter(a => shownAccounts.includes(a.id) && a.capabilities.mail_search) : [];
  const rowHeight = compact ? 64 : 100;
  const summaryOf = selected ? threads?.find(t => threadKey(t) === selected) : undefined;

  const context = <div className="hub-side" aria-label="Mail filters">
    <Accounts accounts={accounts} part="mail" chosen={new Set(shownAccounts)} onToggle={toggle} counts={view?.counts.by_account} now={now} providers={view?.providers} onChoose={a => setChoosing(a.id)} />
    <nav className="hub-labels" aria-label="Mailboxes">
      {LIST_ORDER.map(l => <button key={l} type="button" className="hub-label" aria-current={!providerLabel && label === l ? 'page' : undefined} onClick={() => { setProviderLabel(null); setLabel(l); }}>
        <span>{LABEL_WORDS[l]}</span>{l === 'inbox' && !!view?.counts.unread && <span className="badge accent" aria-label={`${view.counts.unread} unread`}>{view.counts.unread}</span>}</button>)}
      <button type="button" className="hub-label" aria-current={!providerLabel && label === LUMINA ? 'page' : undefined} onClick={() => { setProviderLabel(null); setLabel(LUMINA); }}>
        <span>Written in Lumina</span>{!!luminaDrafts?.length && <span className="faint small">{luminaDrafts.length}</span>}</button>
    </nav>
    <div className="hub-toggles">
      <label><input type="checkbox" checked={unread} onChange={e => setUnread(e.target.checked)} /> Unread only</label>
      <label><input type="checkbox" checked={attachments} onChange={e => setAttachments(e.target.checked)} /> Has an attachment</label>
    </div>
    {writes && mail && accounts.some(a => a.capabilities.send || a.capabilities.mark_read) && <details className="hub-own" aria-label="Mail settings">
      <summary>Mail settings</summary>
      <label className="small">Undo send waits <select className="input" value={mail.undo_send_seconds} onChange={e => saveMail({ undo_send_seconds: Number(e.target.value) })}>
        {[0, 5, 10, 20, 30].map(n => <option key={n} value={n}>{n ? `${n} seconds` : 'no wait'}</option>)}</select></label>
      <label className="small"><input type="checkbox" checked={mail.mark_read_on_open} onChange={e => saveMail({ mark_read_on_open: e.target.checked })} /> Opening a message marks it read in my mailbox</label>
      <label className="small">At most <input className="input" type="number" min={1} max={mail.platform.recipients} value={mail.limits.recipients ?? mail.allowed.recipients}
        onChange={e => saveMail({ limits: { ...mail.limits, recipients: Number(e.target.value) } })} aria-label="People a message may go to" /> people a message</label>
      <label className="small">At most <input className="input" type="number" min={1} max={mail.platform.per_hour} value={mail.limits.per_hour ?? mail.allowed.per_hour}
        onChange={e => saveMail({ limits: { ...mail.limits, per_hour: Number(e.target.value) } })} aria-label="Messages an hour" /> messages an hour</label>
    </details>}
    {own.filter(o => shownAccounts.includes(o.connection_id) && o.labels.length).map(o => (
      <details key={o.connection_id} className="hub-own">
        <summary>{byId[o.connection_id]?.capabilities.labels === 'folders' ? 'Folders' : 'Labels'} in {byId[o.connection_id]?.identity ?? 'this account'}</summary>
        {o.labels.map(l => <button key={l.id} type="button" className="hub-label" aria-current={providerLabel?.account === o.connection_id && providerLabel.id === l.id ? 'page' : undefined}
          onClick={() => { setLabel('all'); setProviderLabel({ account: o.connection_id, id: l.id, name: l.name }); }}><span>{l.name}</span><span className="faint small">{l.threads}</span></button>)}
      </details>))}
  </div>;

  const threadView = !selected || selected.startsWith('draft:') ? null : <section className="hub-open" aria-label="Open thread">
    <header className="hub-open-head">
      <button type="button" className="iconbtn small ghost hub-back" aria-label="Back to the list" onClick={close}><I.Chevron width={16} height={16} /></button>
      <div><h2>{(openThread?.thread ?? summaryOf)?.subject || '(no subject)'}</h2>
        <p className="faint small">{byId[(openThread?.thread ?? summaryOf)?.connection_id ?? '']?.identity}{openThread?.thread.provider_labels.length ? ` · ${openThread.thread.provider_labels.map(l => l.name).join(', ')}` : ''}</p></div>
      {openThread && canOrganize(openThread.thread.connection_id, 'archive') && <div className="hub-organize" role="group" aria-label="Organize this conversation">
        {openThread.thread.labels.includes('inbox') && <button type="button" className="btn small" onClick={() => organize([openThread.thread], 'archive')}>Archive</button>}
        <button type="button" className="btn small" onClick={() => organize([openThread.thread], openThread.thread.starred ? 'unstar' : 'star')}>{openThread.thread.starred ? 'Unstar' : 'Star'}</button>
        {canOrganize(openThread.thread.connection_id, 'unread') && <button type="button" className="btn small" onClick={() => organize([openThread.thread], 'unread')}>Mark unread</button>}
        <button type="button" className="btn small" onClick={() => organize([openThread.thread], 'trash')}>Bin</button></div>}
    </header>
    {openErr ? <p className="notice warning" role="alert">{openErr}</p>
      : !openThread ? <div className="hub-opening" role="status">{summaryOf && <p className="hub-opening-who"><b>{people(summaryOf.people, byId[summaryOf.connection_id]?.identity)}</b> <span className="faint small">{listTime(summaryOf.last_epoch, zone, now)}</span></p>}
          <div className="skeleton" style={{ height: 14, width: '70%' }} /><div className="skeleton" style={{ height: 14, width: '90%' }} /><div className="skeleton" style={{ height: 14, width: '55%' }} /><span className="sr">Opening…</span></div>
      : <>
        {openThread.problem && <p className="notice warning" role="alert">{problemWords(openThread.problem)}</p>}
        <div className="hub-messages">{openThread.messages.map((m, i) => <MessageItem key={m.id} connection={openThread.thread.connection_id} message={m} zone={zone}
          initiallyOpen={i === openThread.messages.length - 1} onSender={allowSender} />)}</div>
        <div className="hub-drafts" aria-label="Drafts for this thread">
          {threadDrafts.filter(d => d.id !== replyingId).map(d => <DraftEditor key={d.id} draft={d} accountLabel={byId[d.account]?.identity ?? 'this account'} canOpenInService={!!byId[d.account]?.capabilities.compose_link}
            canSend={writes && !!byId[d.account]?.capabilities.send} onSent={sent('thread')}
            autoFocus={wantedDraft.current === d.id} onSaved={saved => setThreadDrafts(list => list.map(x => (x.id === saved.id ? saved : x)))}
            onDiscarded={gone => setThreadDrafts(list => list.filter(x => x.id !== gone))} />)}
          {replying && <DraftEditor start={replying} accountLabel={byId[replying.account]?.identity ?? 'this account'} canOpenInService={!!byId[replying.account]?.capabilities.compose_link} autoFocus
            canSend={writes && !!byId[replying.account]?.capabilities.send} onSent={id => { setReplying(null); setReplyingId(null); sent('thread')(id); }}
            onSaved={saved => setReplyingId(saved.id)} onDiscarded={() => { setReplying(null); setReplyingId(null); }} />}
          {!replying && <div className="row">
            <button type="button" className="btn small" onClick={() => setReplying(replyTo(openThread, byId[openThread.thread.connection_id]?.identity))}>Reply</button>
            <button type="button" className="btn small" onClick={() => setReplying(replyTo(openThread, byId[openThread.thread.connection_id]?.identity, true))}>Reply all</button>
            <button type="button" className="btn small" onClick={() => setReplying(forwardOf(openThread, zone))}>Forward</button></div>}
          {writes && byId[openThread.thread.connection_id]?.capabilities.missing?.send && <AllowChanges account={byId[openThread.thread.connection_id]} capability="send" />}
        </div>
      </>}
  </section>;

  const draftView = openDraft && <section className="hub-open" aria-label="Draft">
    <header className="hub-open-head">
      <button type="button" className="iconbtn small ghost hub-back" aria-label="Back to the list" onClick={close}><I.Chevron width={16} height={16} /></button>
      <div><h2>{('subject' in openDraft && openDraft.subject) || 'New message'}</h2><p className="faint small">{byId[openDraft.account]?.identity}</p></div>
    </header>
    <DraftEditor key={'id' in openDraft ? openDraft.id : 'new'} draft={'id' in openDraft ? openDraft : undefined} start={'id' in openDraft ? undefined : openDraft}
      accountLabel={byId[openDraft.account]?.identity ?? 'this account'} canOpenInService={!!byId[openDraft.account]?.capabilities.compose_link} autoFocus
      canSend={writes && !!byId[openDraft.account]?.capabilities.send} onSent={sent('draft')}
      onSaved={saved => { setOpenDraft(saved); setSelected('draft:' + saved.id); void loadDrafts(); }} onDiscarded={() => { close(); void loadDrafts(); }} />
  </section>;
  const draftList = label === LUMINA && <div className="hub-pad">
    <p className="faint small">Drafts you or your assistant wrote in Lumina. They are not in your mailbox until they are sent: open one to edit it, send it, copy it or open it in your mail service.</p>
    {accounts.length > 0 && <button type="button" className="btn small" onClick={() => { close(); setOpenDraft({ account: accounts[0].id, thread: null, to: [], subject: '' }); setSelected('draft:new'); }}>New message</button>}
    {luminaDrafts === null ? <div className="skeleton" style={{ height: 48 }} /> : !luminaDrafts.length ? <EmptyState>No drafts yet. Ask your assistant to draft a reply, or write one here.</EmptyState>
      : <ul className="hub-threads" aria-label="Drafts">{luminaDrafts.map(d => <li key={d.id}>
        <button type="button" className="hub-thread" aria-current={selected === 'draft:' + d.id ? 'true' : undefined} onClick={() => {
          if (d.thread) { wantedDraft.current = d.id; void open({ connection_id: d.account, id: d.thread, subject: d.subject, snippet: '', people: [], last_epoch: d.updated_epoch, message_count: 0, unread: false, starred: false, has_attachments: false, labels: [], provider_labels: [] }); }
          else { close(); setOpenDraft(d); setSelected('draft:' + d.id); } }}>
          <span className="hub-thread-top"><span className="hub-thread-who">{d.to.join(', ') || 'No one yet'}</span><time className="faint small">{listTime(d.updated_epoch, zone, now)}</time></span>
          <span className="hub-thread-subject">{d.subject || '(no subject)'}</span>
          <span className="hub-thread-snippet faint">{d.origin === 'assistant' ? 'By your assistant · ' : ''}{d.body.slice(0, 140)}</span>
          {accounts.length > 1 && <span className="hub-thread-marks faint small"><span className="hub-thread-account">{byId[d.account]?.identity}</span></span>}
        </button></li>)}</ul>}
  </div>;

  const notices = <div className="hub-notices">
    {!accounts.some(a => writes && (a.capabilities.send || a.capabilities.organize)) && <p className="hub-readonly faint small">Read only for now: nothing here changes your mailbox, and opening a message does not mark it as read there.</p>}
    {err && <p className="notice warning" role="alert">{err}</p>}
    {changed && <p className="notice" role="status">{changed.words}{changed.actions.length > 0 && changed.actions.every(a => a.can_undo) && <> <button type="button" className="btn small tertiary" onClick={undoChange}>Undo</button></>}</p>}
    {(linkNote || connectNote) && <p className={`notice${linkNote.endsWith('…') ? '' : ' warning'}`} role="status">{linkNote || connectNote}</p>}
    {choosingAccount && <ChooseAccess account={choosingAccount} onDone={doneChoosing} onCancel={() => { setChoosing(null); setParams({}, { replace: true }); }} />}
    {needing.map(a => <p key={a.id} className="notice warning" role="status">{a.identity} needs you. What was loaded before is still shown. <Link to="/settings?tab=access">Open Access</Link></p>)}
    {filling.length > 0 && <p className="notice" role="status">Loading all mail from {filling.map(a => `${a.identity} (${a.mail?.items ?? 0} so far)`).join(', ')}. Newest first; this list fills in as it arrives.</p>}
    {fresh && <p className="notice" role="status">There is new mail. <button type="button" className="btn small" onClick={() => { void load(); }}>Show it</button></p>}
    {picked.size > 0 && <div className="hub-picked" role="status"><b>{picked.size} selected</b>
      {pickedThreads.some(t => canOrganize(t.connection_id, 'archive')) ? <span className="hub-organize" role="group" aria-label="Organize the selected conversations">
        {label === 'inbox' && <button type="button" className="btn small" onClick={() => organize(pickedThreads, 'archive')}>Archive</button>}
        {label === 'archive' && <button type="button" className="btn small" onClick={() => organize(pickedThreads, 'inbox')}>Move to the inbox</button>}
        <button type="button" className="btn small" onClick={() => organize(pickedThreads, 'read')}>Mark read</button>
        <button type="button" className="btn small" onClick={() => organize(pickedThreads, 'unread')}>Mark unread</button>
        <button type="button" className="btn small" onClick={() => organize(pickedThreads, 'star')}>Star</button>
        {label === 'trash' ? <button type="button" className="btn small" onClick={() => organize(pickedThreads, 'untrash')}>Take out of the bin</button>
          : <button type="button" className="btn small" onClick={() => organize(pickedThreads, 'trash')}>Bin</button>}
        {new Set(pickedThreads.map(t => t.connection_id)).size === 1 && (own.find(o => o.connection_id === pickedThreads[0]?.connection_id)?.labels.length ?? 0) > 0 &&
          <select className="input" aria-label="Add a label" value="" onChange={e => { if (e.target.value) void organize(pickedThreads, 'label', e.target.value); }}>
            <option value="">Add a label…</option>{own.find(o => o.connection_id === pickedThreads[0].connection_id)!.labels.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}</select>}
      </span> : <span className="faint small">You can ask your assistant about them.</span>}
      {writes && accounts.filter(a => a.capabilities.missing?.organize && pickedThreads.some(t => t.connection_id === a.id)).map(a => <AllowChanges key={a.id} account={a} capability="organize" />)}
      <button type="button" className="btn small tertiary" onClick={() => setPicked(new Set())}>Clear</button></div>}
  </div>;

  const olderPart = query && threads && !next && searchable.length > 0 && <div className="hub-older">
    <p className="faint small">{filling.length ? 'Some of your mail is still loading, so older messages may be missing above. ' : ''}You can also search in your mail service itself:</p>
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
  </div>;

  const list = label === LUMINA ? draftList : view && !accounts.length ? (
    <EmptyState title="No mail account is connected" action={<AddAccount providers={view.providers ?? []} primary />}>Connect an account and choose what Lumina may read. It shows up here.</EmptyState>
  ) : threads === null ? <div className="hub-loading" role="status">{[0, 1, 2, 3, 4].map(n => <div key={n} className="skeleton" style={{ height: rowHeight - 16 }} />)}<span className="sr">Loading…</span></div>
    : !threads.length && !loading ? (
    <EmptyState>{query ? <>Nothing matches “{query}”{filling.length ? ' in what has loaded so far' : ''}.</> : accounts.some(a => !a.granted.mail) && !accounts.some(a => a.granted.mail)
      ? <>Nothing has been chosen to show yet. Use “Choose what Lumina may read” beside the account.</> : <>Nothing here.</>}</EmptyState>
  ) : null;
  const shownList = list ?? <List label="Threads" className="hub-vlist" items={threads ?? []} rowHeight={rowHeight} rowKey={t => threadKey(t)} active={active} onEnd={next ? () => { if (!loading) void load(next); } : undefined}
      footer={<>{loading && next && <p className="hub-pad faint small" role="status">Loading more…</p>}{olderPart}</>}
      renderRow={(t, index) => { const k = threadKey(t); const account = byId[t.connection_id]; const who = people(t.people, account?.identity); return (
        <div className={`hub-row${picked.has(k) ? ' picked' : ''}`}>
          <label className="hub-pick-area"><input type="checkbox" className="hub-pick" checked={picked.has(k)} aria-label={`Select the thread from ${who}`} onChange={() => undefined}
            onClick={e => pick(index, (e as React.MouseEvent).shiftKey)} /></label>
          <button type="button" className={`hub-thread${t.unread ? ' unread' : ''}`} aria-current={selected === k ? 'true' : undefined} onClick={e => { if (e.shiftKey) { pick(index, true); return; } void open(t); }}>
            <span className="hub-thread-top"><span className="hub-thread-who">{who}{t.message_count > 1 && <span className="faint"> {t.message_count}</span>}</span>
              <time className="faint small">{listTime(t.last_epoch, zone, now)}</time></span>
            <span className="hub-thread-subject">{t.unread && <i className="hub-dot" role="img" aria-label="Unread" />}{t.subject || '(no subject)'}</span>
            {!compact && <span className="hub-thread-snippet faint">{t.snippet}</span>}
            <span className="hub-thread-marks faint small">{accounts.length > 1 && <span className="hub-thread-account" title={account?.provider_label}>{account?.identity}</span>}
              {t.starred && <span>Starred</span>}{t.has_attachments && <span><I.Clip width={12} height={12} /> Attachment</span>}</span>
          </button>
        </div>); }} />;

  const full = reading === 'full' && !!selected;
  const tools = <>
    <form className="hub-search" role="search" onSubmit={e => { e.preventDefault(); setQuery(typed.trim()); }}>
      <I.Search width={16} height={16} />
      <input ref={search} className="input" type="search" placeholder="Search mail" aria-label="Search mail" value={typed} onChange={e => { setTyped(e.target.value); if (!e.target.value) setQuery(''); }} />
    </form>
    <button type="button" className="iconbtn small ghost" aria-label={reading === 'full' ? 'Read beside the list' : 'Read in place of the list'} aria-pressed={reading === 'full'}
      title={reading === 'full' ? 'Reading view: full. Switch to beside the list' : 'Reading view: beside the list. Switch to full'} onClick={() => setReading(reading === 'full' ? 'split' : 'full')}><I.Page width={16} height={16} /></button>
    <button type="button" className="iconbtn small ghost" aria-label="Refresh" title="Refresh" onClick={refresh}><I.Retry width={16} height={16} /></button>
  </>;
  return (
    <Workspace title={title} fill tools={tools} context={context} contextLabel="Mail" inspector={reading === 'split' ? (draftView || threadView) : null} inspectorLabel={draftView ? 'Draft' : 'Open thread'}
      onInspectorClose={close} className="hub-inbox">
      <div className="wsp-body">{notices}{full ? <div className="hub-full">{draftView || threadView}</div> : <>{shownList}{list && label !== LUMINA && olderPart}</>}</div>
    </Workspace>);
}
