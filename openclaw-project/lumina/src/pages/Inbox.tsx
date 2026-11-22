import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as I from '../components/Icons';
import { AddAccount, ChooseAccess, connectNote, Reconnect } from '../components/hub/Connect';
import Workspace from '../components/frame/Workspace';
import List from '../components/frame/List';
import MasterDetail from '../components/frame/MasterDetail';
import { EmptyState } from '../components/frame/parts';
import { useSelection, type Action, type Looking } from '../components/frame/Assistant';
import { useSettings } from '../state/settings';
import { useCommands } from '../components/frame/CommandBar';
import DraftEditor, { type DraftStart } from '../components/hub/DraftEditor';
import AllowChanges from '../components/hub/AllowChanges';
import MailSide, { MailSettingsSheet } from '../components/hub/MailSide';
import Reader, { Mark, type ReaderActions } from '../components/hub/Reader';
import { usePulse } from '../components/hub/usePulse';
import { ApiError } from '../lib/api';
import { browserZone, failed, fullTime, hub, LABEL_WORDS, linkWords, listTime, mergeNewest, people, personName, problemWords, quoteOf, threadKey, validZone,
  replySubject, type Draft, type HubAccount, type HubAction, type Message, type OrganizeOp, type Overview, type Thread } from '../lib/hub';
import { useData } from '../state/data';
import '../styles/hub.css';
import '../styles/mail.css';

type Opened = { thread: Thread; messages: Message[]; problem: string | null };
type Older = { connection: string; found: { id: string; thread_id: string; connection_id: string; subject: string; sender: { name: string; address: string }; sent_epoch: number; snippet: string }[];
  complete: boolean; continuation: string | null; problem: string | null };
const nowSeconds = () => Math.floor(Date.now() / 1000);
const EMPTY: Overview = { accounts: [], settings: { timezone: null, image_senders: [] }, counts: { unread: 0, by_account: {} }, calendars: [], labels: [], colours: [], read_only: true };
const blank = (connection_id: string, id: string, subject = '', last_epoch = 0): Thread => ({ connection_id, id, subject, snippet: '', people: [], last_epoch, message_count: 0, unread: false, starred: false,
  has_attachments: false, labels: [], provider_labels: [] });

/** A reply to a thread: to whoever wrote its last message that was not from this account, with "Re:" once, and that message quoted under the customer's own words.
 *  "Reply all" adds everyone else on that message (never this account). The reply is sent from the account that received the thread. */
function replyTo(opened: Opened, own: string | undefined, zone: string, all = false): DraftStart {
  const mine = (own ?? '').toLowerCase();
  const last = [...opened.messages].reverse().find(m => m.sender.address && m.sender.address.toLowerCase() !== mine) ?? opened.messages[opened.messages.length - 1];
  const to = last?.sender.address ? [last.sender.address] : [];
  const others = all && last ? [...last.to, ...last.cc].map(p => p.address).filter(a => a && a.toLowerCase() !== mine && !to.some(t => t.toLowerCase() === a.toLowerCase())) : [];
  return { account: opened.thread.connection_id, thread: opened.thread.id, to, cc: [...new Set(others)], subject: replySubject(opened.thread.subject || last?.subject || ''), body: last ? quoteOf(last, zone) : '' };
}

/** A forward of the thread's last message: to nobody yet, "Fwd:" once, with that message quoted below the customer's own words. A new conversation. */
function forwardOf(opened: Opened, zone: string): DraftStart {
  const last = opened.messages[opened.messages.length - 1];
  const subject = (opened.thread.subject || last?.subject || '').trim();
  const head = last ? [`---------- Forwarded message ----------`, `From: ${personName(last.sender)}${last.sender.name ? ` <${last.sender.address}>` : ''}`, `Date: ${fullTime(last.sent_epoch, zone)}`,
    `Subject: ${last.subject}`, `To: ${last.to.map(p => p.address).join(', ')}`].join('\n') : '';
  const text = last?.body?.text || last?.snippet || '';
  return { account: opened.thread.connection_id, thread: null, to: [], subject: /^fwd?:/i.test(subject) ? subject : `Fwd: ${subject}`, body: `\n\n${head}\n\n${text}`.slice(0, 39000) };
}

const OP_WORDS: Record<string, string> = { archive: 'Archived', inbox: 'Moved to the inbox', star: 'Starred', unstar: 'Star removed', read: 'Marked as read', unread: 'Marked as unread',
  label: 'Labelled', unlabel: 'Label removed', move: 'Moved', trash: 'Moved to the bin', untrash: 'Taken out of the bin' };

/** The Inbox: the mail of every connected account in one place. The side column holds the mailboxes and the accounts; the canvas holds the conversations and, beside
 *  them where there is room, the open one (only the rows in view are drawn, so a mailbox of any size scrolls smoothly). What a customer does here goes through the
 *  action pipeline at once, shows at once, and can be undone; what an account may not do yet is offered as a permission where it would be used, not as a notice on
 *  every screen. */
export default function Inbox() {
  const { app } = useData(); const on = !!app?.features.dashboard; const { compact } = useSettings();
  const [view, setView] = useState<Overview | null>(null); const [err, setErr] = useState(''); const [now, setNow] = useState(nowSeconds);
  const [only, setOnly] = useState<string | null>(null); const [label, setLabel] = useState('inbox'); const [providerLabel, setProviderLabel] = useState<{ account: string; id: string; name: string } | null>(null);
  const [unread, setUnread] = useState(false); const [attachments, setAttachments] = useState(false); const [typed, setTyped] = useState(''); const [query, setQuery] = useState('');
  const [threads, setThreads] = useState<Thread[] | null>(null); const [next, setNext] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  const [own, setOwn] = useState<{ connection_id: string; labels: { id: string; name: string; threads: number }[] }[]>([]);
  const [selected, setSelected] = useState<string | null>(null); const [opened, setOpened] = useState<Opened | null>(null); const [openErr, setOpenErr] = useState('');
  const [older, setOlder] = useState<Older | null>(null);
  // Drafts kept in Lumina (#57): those of the open thread, the list under Drafts, and one opened on its own (a new message, not a reply).
  const [replying, setReplying] = useState<DraftStart | null>(null);
  const [replyingId, setReplyingId] = useState<string | null>(null);     // the reply being written, once saved: it stays in its editor (not listed twice) until sent or discarded
  const [luminaDrafts, setLuminaDrafts] = useState<Draft[] | null>(null); const [openDraft, setOpenDraft] = useState<Draft | DraftStart | null>(null);
  const wantedDraft = useRef<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(() => new Set()); const anchor = useRef<number | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [composing, setComposing] = useState(0);                         // one editor for one piece of writing: it is not started again when its draft is first saved (mid-sentence)
  const search = useRef<HTMLInputElement>(null); const request = useRef(0); const cache = useRef(new Map<string, Opened>());
  const [params, setParams] = useSearchParams(); const [choosing, setChoosing] = useState<string | null>(params.get('connected'));
  const [linkNote, setLinkNote] = useState<{ words: string; busy?: boolean } | null>(() => { const words = connectNote(params.get('connect'), params.get('ref')); return words ? { words } : null; });
  const doneChoosing = () => { setChoosing(null); setParams({}, { replace: true }); reloadSoon(1200); };

  const zone = useMemo(() => (view?.settings.timezone && validZone(view.settings.timezone) ? view.settings.timezone : browserZone()), [view?.settings.timezone]);
  const accounts = useMemo(() => (view?.accounts ?? []).filter(a => a.capabilities.mail), [view]);
  const byId = useMemo(() => Object.fromEntries(accounts.map(a => [a.id, a])) as Record<string, HubAccount>, [accounts]);
  useEffect(() => { if (only && view && !byId[only]) setOnly(null); }, [only, view, byId]);
  // The shortest name that tells one connected account from the others, for where a whole address has no room: what follows the "@" when that differs between them,
  // else what precedes it, else the address.
  const tags = useMemo(() => { const part = (a: HubAccount, n: 0 | 1) => a.identity.split('@')[n] ?? a.identity; const alone = (n: 0 | 1, a: HubAccount) => accounts.filter(b => part(b, n) === part(a, n)).length === 1;
    return Object.fromEntries(accounts.map(a => [a.id, alone(1, a) ? part(a, 1) : alone(0, a) ? part(a, 0) : a.identity])) as Record<string, string>; }, [accounts]);

  const loadOverview = useCallback(async () => {
    try { const r = await hub.overview(); setView(r); setNow(nowSeconds()); hub.labels().then(l => setOwn(l.labels)).catch(() => undefined); }
    catch (e) { setErr(failed(e)); setView(v => v ?? EMPTY); }
  }, []);
  useEffect(() => { if (on) void loadOverview(); }, [on, loadOverview]);
  // Coming back from a provider: its return cannot carry the session (it arrives from another site), so the server handed the two values to this page in the address
  // fragment. The page finishes the sign-in itself, from inside Lumina, and takes them out of the address at once. A sign-in that connects nothing says why.
  const finishing = useRef(false);
  useEffect(() => {
    if (!on || finishing.current || !window.location.hash.includes('link-state=')) return;
    const given = new URLSearchParams(window.location.hash.slice(1)); const state = given.get('link-state'), code = given.get('link-code');
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    if (!state || !code) return;
    finishing.current = true; setLinkNote({ words: 'Connecting your account…', busy: true });
    hub.finishLink(state, code)
      .then(async r => { setLinkNote(null); await loadOverview(); setChoosing(r.connection_id); })
      .catch(e => { const said = e instanceof ApiError ? (e.data as { reason?: string; reference?: string } | undefined) : undefined; setLinkNote({ words: linkWords(said?.reason ?? 'failed', said?.reference) }); void loadOverview(); });
  }, [on, loadOverview]);

  // Until the customer narrows the accounts, the list asks for every account's mail: it then does not wait for the accounts overview (one round trip fewer).
  const filters = useMemo(() => ({ label, accounts: providerLabel ? [providerLabel.account] : only ? [only] : undefined, provider_label: providerLabel?.id, unread: unread || undefined,
    attachments: attachments || undefined, q: query || undefined, limit: 50 }), [label, providerLabel, only, unread, attachments, query]);
  const filterKey = JSON.stringify(filters);
  const further = useRef(false);
  const shownThread = useRef<string | null>(null); const listRef = useRef<Thread[] | null>(null); listRef.current = threads;
  const loadDrafts = useCallback(async () => {
    try { const r = await hub.drafts(); setLuminaDrafts(r.drafts); } catch { setLuminaDrafts(prev => prev ?? []); }
  }, []);
  const load = useCallback(async (cursor?: string) => {
    const mine = ++request.current; setLoading(true);
    try {
      const r = await hub.threads({ ...filters, cursor });
      if (mine !== request.current) return;                              // a newer filter was chosen while this one was on its way
      setThreads(prev => (cursor && prev ? [...prev, ...r.threads.filter(t => !prev.some(p => threadKey(p) === threadKey(t)))] : r.threads)); setNext(r.next); further.current = !!cursor;
    } catch (e) { if (mine === request.current) { setErr(failed(e)); setThreads(prev => prev ?? []); } }
    finally { if (mine === request.current) setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);
  useEffect(() => { if (on) { setOlder(null); setPicked(new Set()); setThreads(null); void load(); } }, [load, on]);
  // Keeping the list current, as a mail program does: the newest page is read again and laid over what is on screen. New mail joins at the top by itself, whatever
  // the reader has scrolled to (the list keeps their place when rows are added above), and what they had loaded further down stays. Nothing is asked, nothing jumps.
  // The open conversation is read again when it got a new message, so an answer that arrives while it is open shows in it.
  const shown = useRef<Opened | null>(null);
  const catchUp = useCallback(async () => {
    const mine = request.current; if (listRef.current === null) return;  // the list itself is still on its way
    let r: Awaited<ReturnType<typeof hub.threads>>;
    try { r = await hub.threads({ ...filters }); } catch { return; }      // a missed beat: the next one tries again
    if (mine !== request.current) return;                                // another mailbox or a search was chosen meanwhile, or a further page arrived
    setThreads(prev => (prev && further.current ? mergeNewest(prev, r.threads, !r.next) : r.threads));
    if (!further.current || !r.next) { setNext(r.next); if (!r.next) further.current = false; }
    const open = shown.current; const now = open && r.threads.find(t => threadKey(t) === threadKey(open.thread));
    if (!open || !now) return;
    const k = threadKey(now);
    if (now.message_count === open.thread.message_count && now.last_epoch === open.thread.last_epoch) { setOpened(o => (o && threadKey(o.thread) === k ? { ...o, thread: now } : o)); return; }
    cache.current.delete(k);
    hub.thread(now.connection_id, now.id).then(again => { cache.current.set(k, again); if (shownThread.current === k) setOpened(again); }).catch(() => undefined);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);
  // Anything that reads the list again a moment later reads it for the mailbox and filters shown THEN, not for the ones that were shown when it was asked to (a list
  // read late for the mailbox the customer had just left was drawn under the new mailbox's name).
  const latestLoad = useRef(catchUp); latestLoad.current = catchUp;
  useEffect(() => { if (on) void loadDrafts(); }, [on, loadDrafts]);

  const fetchThread = useCallback(async (t: Thread) => {
    const k = threadKey(t); const known = cache.current.get(k); if (known) return known;
    const r = await hub.thread(t.connection_id, t.id); cache.current.set(k, r); if (cache.current.size > 40) cache.current.delete(cache.current.keys().next().value!);
    return r;
  }, []);
  // Live: when anything changed at the server, the accounts and the list are brought up to date, quietly (catchUp above).
  usePulse(on, () => { void loadOverview(); void latestLoad.current(); void loadDrafts(); });

  const reset = () => { setOpenErr(''); setOpenDraft(null); setReplying(null); setReplyingId(null); };
  const open = useCallback(async (t: Thread) => {
    const k = threadKey(t); shownThread.current = k; setSelected(k); reset();
    setOpened(cache.current.get(k) ?? null);                             // known already (fetched ahead): shown at once, from its headers if nothing else
    let r: Opened;
    try { r = await fetchThread(t); } catch (e) { if (shownThread.current === k) setOpenErr(failed(e)); return; }
    if (shownThread.current !== k) return;                               // the reader moved on while this was on its way
    setOpened(r);
    // The next thread down is fetched ahead, so moving on with j shows it at once.
    const list = listRef.current ?? []; const at = list.findIndex(x => threadKey(x) === k);
    if (at > -1 && list[at + 1]) void fetchThread(list[at + 1]).catch(() => undefined);
  }, [fetchThread]);   // eslint-disable-line react-hooks/exhaustive-deps
  // The drafts of the open conversation are those of the list already here (every draft kept in Lumina): no question to the server for each conversation opened.
  const threadDrafts = useMemo(() => { const k = selected; if (!k || k.startsWith('draft:')) return [];
    const cut = k.indexOf('\u0000'); const connection = k.slice(0, cut), id = k.slice(cut + 1);      // a thread's key: its account and its id (threadKey)
    return (luminaDrafts ?? []).filter(d => d.thread === id && d.account === connection); }, [selected, luminaDrafts]);
  const keepDraft = (saved: Draft) => setLuminaDrafts(list => { const all = list ?? []; return all.some(x => x.id === saved.id) ? all.map(x => (x.id === saved.id ? saved : x)) : [saved, ...all]; });
  const dropDraft = (gone: string | null) => setLuminaDrafts(list => (list ?? []).filter(x => x.id !== gone));
  const close = () => { shownThread.current = null; setSelected(null); setOpened(null); reset(); };
  const compose = (start?: DraftStart) => {
    const from = only ?? accounts.find(a => a.state === 'working')?.id ?? accounts[0]?.id; if (!from) return;
    shownThread.current = null; setOpened(null); reset(); setComposing(n => n + 1); setOpenDraft(start ?? { account: from, thread: null, to: [], subject: '' }); setSelected('draft:new');
  };

  const refresh = async () => { try { await hub.refresh(); } catch (e) { setErr(failed(e)); } reloadSoon(1500); };
  const allowSender = (address: string) => { hub.setSettings({ allow_images_from: address }).then(r => setView(v => (v ? { ...v, settings: r.settings } : v))).catch(() => undefined); };
  const searchOlder = async (connection: string, continuation?: string | null) => {
    try {
      const r = await hub.searchOlder(connection, query, continuation);
      setOlder(prev => ({ connection, found: [...(continuation && prev?.connection === connection ? prev.found : []), ...r.messages], complete: r.page?.complete ?? true,
        continuation: r.page?.continuation ?? null, problem: r.problem }));
    } catch (e) { setOlder({ connection, found: [], complete: true, continuation: null, problem: null }); setErr(failed(e)); }
  };
  // Select conversations. Shift extends from the last one chosen.
  const pick = (index: number, extend: boolean) => {
    if (!threads) return;
    setPicked(prev => {
      const out = new Set(prev); const k = threadKey(threads[index]);
      if (extend && anchor.current !== null) { const [a, b] = [Math.min(anchor.current, index), Math.max(anchor.current, index)]; for (let i = a; i <= b; i++) out.add(threadKey(threads[i])); }
      else if (out.has(k)) out.delete(k); else out.add(k);
      return out;
    });
    anchor.current = index;
  };

  // Phase 6 (#67, #D6): the customer's own changes to their mail. Each goes through the action pipeline at once, shows at once (pending), is final when the provider
  // confirms it, goes back with a sentence when it fails, and can be undone in one step.
  const writes = !!view && !view.read_only;
  const canOrganize = useCallback((connection: string, op: OrganizeOp) => writes && !!byId[connection]?.capabilities[op === 'read' || op === 'unread' ? 'mark_read' : 'organize'], [writes, byId]);
  const [changed, setChanged] = useState<{ actions: HubAction[]; words: string; before?: Thread[] | null } | null>(null);
  // After a change the list already shows it. The copy on the server catches up a moment later (the mail service is asked again at once); the list is read again then,
  // not sooner, so what was just done does not flicker back.
  const settle = useRef(0);
  const here = useRef(true);                                             // false once the page is left: a change that finishes after that reads nothing again
  const reloadSoon = (ms = 2600) => { if (!here.current) return; window.clearTimeout(settle.current); settle.current = window.setTimeout(() => { void latestLoad.current(); void loadOverview(); }, ms); };
  useEffect(() => { here.current = true; return () => { here.current = false; window.clearTimeout(settle.current); }; }, []);
  useEffect(() => { if (!changed) return; const t = window.setTimeout(() => setChanged(null), 12000); return () => window.clearTimeout(t); }, [changed]);
  const organize = async (items: Thread[], op: OrganizeOp, labelId?: string) => {
    const chosen = items.filter(t => canOrganize(t.connection_id, op)); if (!chosen.length) return;
    const keys = new Set(chosen.map(threadKey)); const before = threads;
    const leaves = op === 'trash' || (op === 'untrash' && label === 'trash') || (op === 'archive' && label === 'inbox') || (op === 'inbox' && label === 'archive') || (op === 'move' && label === 'inbox');
    const patch = (t: Thread): Thread => ({ ...t, unread: op === 'read' ? false : op === 'unread' ? true : t.unread, starred: op === 'star' ? true : op === 'unstar' ? false : t.starred,
      labels: op === 'archive' ? t.labels.filter(l => l !== 'inbox') : op === 'inbox' && !t.labels.includes('inbox') ? [...t.labels, 'inbox'] : t.labels });
    setThreads(list => list && (leaves ? list.filter(t => !keys.has(threadKey(t))) : list.map(t => (keys.has(threadKey(t)) ? patch(t) : t))));
    setOpened(o => (o && keys.has(threadKey(o.thread)) ? { ...o, thread: patch(o.thread) } : o));
    for (const k of keys) cache.current.delete(k);
    setPicked(new Set()); setErr(''); setChanged(null);
    if (selected && keys.has(selected) && (leaves || op === 'unread')) {  // what was open left the list: the next one is shown, as a mail program does
      const list = before ?? []; const at = list.findIndex(t => threadKey(t) === selected);
      const following = leaves ? list.slice(at + 1).find(t => !keys.has(threadKey(t))) ?? [...list.slice(0, at)].reverse().find(t => !keys.has(threadKey(t))) : undefined;
      if (following) void open(following); else close();
    }
    const groups = new Map<string, string[]>(); for (const t of chosen) groups.set(t.connection_id, [...(groups.get(t.connection_id) ?? []), t.id]);
    const done: HubAction[] = []; let problem = '';
    for (const [connection, ids] of groups) {
      try { const r = await hub.organize(connection, ids, op, labelId); if (r.action.state === 'done') done.push(r.action); else problem = r.action.ended_words || 'That could not be done in your mailbox.'; }
      catch (e) { problem = failed(e); }
    }
    if (problem) { setThreads(before); setErr(`${problem} The list shows your mailbox as it is.`); }
    if (done.length) setChanged({ actions: done, words: `${OP_WORDS[op]}${chosen.length > 1 ? ` ${chosen.length} conversations` : ''}.`, before: problem ? null : before });
    reloadSoon(problem ? 400 : undefined);
  };
  const undoChange = async () => {
    if (!changed) return;
    try {
      for (const a of changed.actions) await hub.undo(a.id, 'inbox');
      if (changed.before) setThreads(changed.before);                    // back as it was, at once
      for (const t of changed.before ?? []) cache.current.delete(threadKey(t));
      setChanged({ actions: [], words: 'Undone.' });
    } catch (e) { setErr(failed(e)); }
    reloadSoon();
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
    hub.organize(t.connection_id, [t.id], 'read').then(() => { setThreads(list => list && list.map(x => (threadKey(x) === threadKey(t) ? { ...x, unread: false } : x))); void loadOverview(); }).catch(() => undefined);
  }, [opened?.thread.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  const sent = (where: 'thread' | 'draft') => (draftId: string) => {
    dropDraft(draftId);
    if (where === 'thread') { if (selected) cache.current.delete(selected); } else close();
    setChanged({ actions: [], words: 'Sent.' });
    hub.refresh().catch(() => undefined).finally(() => reloadSoon());    // the mail service is asked again now, so the message is under Sent (and in its conversation) without a wait
  };

  const openThread = opened && selected === threadKey(opened.thread) ? opened : null;
  shown.current = openThread;
  const openAccount = byId[(openThread?.thread ?? threads?.find(t => threadKey(t) === selected))?.connection_id ?? ''];
  const startReply = (all = false) => { if (openThread) setReplying(replyTo(openThread, byId[openThread.thread.connection_id]?.identity, zone, all)); };
  const startForward = () => { if (openThread) compose(forwardOf(openThread, zone)); };

  // Keyboard: j and k move through the list, Enter opens, Escape closes, x selects, "/" goes to search; e archives, # bins, s stars, u marks unread; r, a and f answer; c writes.
  const active = threads ? threads.findIndex(t => threadKey(t) === selected) : -1; const wentAt = useRef(0);
  const step = (by: number) => { if (!threads?.length) return; const to = threads[Math.min(threads.length - 1, Math.max(0, active + by))]; if (to && threadKey(to) !== selected) void open(to); };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) { if (e.key === 'Escape') target.blur(); return; }
      if (e.metaKey || e.ctrlKey || e.altKey || document.querySelector('[role="dialog"][aria-modal="true"]:not(.zone-sheet), [role="menu"]')) return;
      // "G then a letter" goes somewhere else in the app (the frame's own shortcut): the letter after G is not one of the mail keys.
      if (e.key === 'g') { wentAt.current = Date.now(); return; }
      if (Date.now() - wentAt.current < 1200) { wentAt.current = 0; return; }
      const current = openThread?.thread ?? (active > -1 ? threads![active] : undefined);
      if (e.key === '/') { e.preventDefault(); search.current?.focus(); return; }
      if (e.key === 'c') { e.preventDefault(); compose(); return; }
      if (e.key === 'Escape' && selected) { close(); return; }
      if (e.key === 'j' || e.key === 'k') { e.preventDefault(); step(e.key === 'j' ? 1 : -1); return; }
      if (e.key === 'x' && active > -1) { e.preventDefault(); pick(active, e.shiftKey); return; }
      if (!current) return;
      const act: Record<string, () => void> = { e: () => organize([current], current.labels.includes('inbox') ? 'archive' : 'inbox'), '#': () => organize([current], 'trash'),
        s: () => organize([current], current.starred ? 'unstar' : 'star'), u: () => organize([current], 'unread'), r: () => startReply(), a: () => startReply(true), f: () => startForward() };
      if (act[e.key]) { e.preventDefault(); act[e.key](); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });   // eslint-disable-line react-hooks/exhaustive-deps

  const title = providerLabel ? providerLabel.name : LABEL_WORDS[label] ?? label;
  const looking: Looking = openThread ? { kind: 'thread', connection: openThread.thread.connection_id, thread: openThread.thread.id } : { kind: 'mail', label, ...(query ? { query } : {}) };
  const lookingWords = openThread ? `the thread “${openThread.thread.subject || '(no subject)'}”` : `${title}${query ? `, searching “${query}”` : ''}`;
  const actions: Action[] = openThread ? [{ label: 'Summarize', message: 'Summarize this thread.' }, { label: 'What do they need from me?', message: 'What do they need from me in this thread, and by when?' },
    { label: 'Draft a reply', message: 'Draft a reply to this thread for me to review. Do not send anything.', draft: true }]
    : [{ label: 'What needs my attention?', message: 'Which threads in my mail need my attention most? List them with why.' }, { label: 'Unread, in short', message: 'Summarize my unread mail in a few lines.' }];
  useSelection(on ? { looking, words: lookingWords, actions } : null);
  useCommands(on ? [{ id: 'mail-compose', label: 'Write a new message', run: () => compose() }, { id: 'mail-refresh', label: 'Refresh mail', run: () => { void refresh(); } },
    { id: 'mail-unread', label: unread ? 'Show all mail, read and unread' : 'Show unread mail only', run: () => setUnread(!unread) },
    { id: 'mail-settings', label: 'Mail settings', run: () => setSettingsOpen(true) },
    { id: 'mail-search', label: 'Search mail', shortcut: 'mail-search', run: () => window.setTimeout(() => search.current?.focus(), 0) }] : []);
  // Opened from the command bar or from a link in an answer: ?connection=&thread= opens that thread (its headers come with it), &draft= also opens that Lumina draft;
  // ?connection=&draft= alone opens a draft that is not a reply. A new link while the page is open selects the new thread in place.
  const linked = useRef('');
  useEffect(() => {
    const id = params.get('thread'), connection = params.get('connection'), draft = params.get('draft');
    const key = `${connection}|${id}|${draft}`;
    if (!on || linked.current === key || !connection || (!id && !draft)) return;
    linked.current = key; wantedDraft.current = draft;
    if (id) { void open(blank(connection, id)); return; }
    hub.drafts().then(r => { const found = r.drafts.find(d => d.id === draft); if (found) { close(); setComposing(n => n + 1); setOpenDraft(found); setSelected('draft:' + found.id); } }).catch(e => setErr(failed(e)));
  }, [on, params, open]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!on) return (
    <Workspace title="Inbox"><EmptyState title="Not available yet" action={<Link className="btn" to="/home">Back to Home</Link>}>The mail of your connected accounts in one place, with your assistant beside it.</EmptyState></Workspace>);

  const needing = accounts.filter(a => a.state === 'needs_you');
  const choosingAccount = (view?.accounts ?? []).find(a => a.id === choosing);
  const filling = accounts.filter(a => (!only || only === a.id) && a.mail && !a.mail.filled && a.state === 'working');
  const searchable = query ? accounts.filter(a => (!only || only === a.id) && a.capabilities.mail_search) : [];
  const rowHeight = compact ? 60 : 84;
  const summaryOf = selected ? threads?.find(t => threadKey(t) === selected) : undefined;
  const several = accounts.length > 1 && !only && !providerLabel;
  const draftsHere = label === 'drafts' && !providerLabel ? (luminaDrafts ?? []).filter(d => !only || d.account === only) : [];

  const side = <MailSide accounts={accounts} providers={view?.providers ?? []} counts={view?.counts} drafts={(luminaDrafts ?? []).length} label={label} providerLabel={providerLabel} only={only} own={own} now={now} tags={tags}
    onLabel={l => { setProviderLabel(null); setLabel(l); }} onProviderLabel={(account, id, name) => { setLabel('all'); setProviderLabel({ account, id, name }); }}
    onOnly={id => { setProviderLabel(null); setOnly(id); }} onChoose={a => setChoosing(a.id)} />;

  const readerActions: ReaderActions = {
    organize: (op, l) => { if (openThread) void organize([openThread.thread], op, l); },
    can: op => !!openThread && canOrganize(openThread.thread.connection_id, op),
    reply: () => startReply(), replyAll: () => startReply(true), forward: startForward, close,
    next: active > -1 && threads && active < threads.length - 1 ? () => step(1) : undefined, previous: active > 0 ? () => step(-1) : undefined,
  };
  const missingOrganize = writes && openAccount && openThread && !canOrganize(openThread.thread.connection_id, 'archive') && openAccount.capabilities.missing?.organize;
  const threadView = selected && !selected.startsWith('draft:') ? <Reader thread={openThread?.thread ?? null} summary={summaryOf} messages={openThread?.messages ?? null} problem={openThread?.problem ?? null} error={openErr}
    account={openAccount} accountsShown={accounts.length} zone={zone} now={now} labels={own.find(o => o.connection_id === openThread?.thread.connection_id)?.labels ?? []} actions={readerActions} onSender={allowSender}
    footer={replying ? <></> : undefined}>
    {threadDrafts.filter(d => d.id !== replyingId).map(d => <DraftEditor key={d.id} draft={d} accounts={accounts} writes={writes} onSent={sent('thread')}
      autoFocus={wantedDraft.current === d.id} onSaved={keepDraft} onDiscarded={dropDraft} />)}
    {replying && <DraftEditor start={replying} accounts={accounts} writes={writes} autoFocus
      onSent={id => { setReplying(null); setReplyingId(null); sent('thread')(id); }}
      onSaved={saved => { setReplyingId(saved.id); keepDraft(saved); }} onDiscarded={gone => { setReplying(null); setReplyingId(null); dropDraft(gone); }} />}
    {missingOrganize && openAccount && <AllowChanges account={openAccount} capability="organize" />}
  </Reader> : null;

  const draftView = openDraft && <div className="mail-reader">
    <header className="mail-reader-head bare"><div className="mail-reader-bar">
      <button type="button" className="iconbtn small ghost md-back" aria-label="Back to the list" title="Back (Esc)" onClick={close}><I.Back width={18} height={18} /></button></div></header>
    <div className="mail-reader-scroll"><div className="mail-answer alone">
      <DraftEditor key={composing} onClose={close} draft={'id' in openDraft ? openDraft : undefined} start={'id' in openDraft ? undefined : openDraft} accounts={accounts} writes={writes} autoFocus
        title={'id' in openDraft && openDraft.origin === 'assistant' ? undefined : 'subject' in openDraft && /^fwd?:/i.test(openDraft.subject) ? 'Forward' : 'New message'} onSent={sent('draft')}
        onSaved={saved => { setOpenDraft(d => (d && 'id' in d && d.id !== saved.id ? d : saved)); setSelected(k => (k?.startsWith('draft:') ? 'draft:' + saved.id : k)); keepDraft(saved); }} onDiscarded={gone => { close(); dropDraft(gone); }} /></div></div>
  </div>;

  const olderPart = query && threads && !next && searchable.length > 0 && <div className="mail-older">
    <p className="faint small">{filling.length ? 'Some of your mail is still loading, so older messages may be missing above. ' : ''}Not here? Search the mail service itself:</p>
    <div className="row">{searchable.map(a => <button key={a.id} type="button" className="btn small" onClick={() => searchOlder(a.id)}>Search {a.identity}</button>)}</div>
    {older && <div role="status">
      {older.problem ? <p className="notice warning">{problemWords(older.problem)}</p> : <p className="small">{older.complete
        ? `${older.found.length} older message${older.found.length === 1 ? '' : 's'} found. That is all of them.`
        : `The first ${older.found.length} older messages are shown. There are more.`}</p>}
      <ul className="mail-older-list">{older.found.map(m => <li key={m.id}><span className="mail-row-top"><b>{personName(m.sender)}</b><time className="faint small">{listTime(m.sent_epoch, zone, now)}</time></span>
        <span className="mail-row-subject">{m.subject || '(no subject)'}</span><span className="mail-row-snippet faint">{m.snippet}</span></li>)}</ul>
      {!older.complete && older.continuation && <button type="button" className="btn small" onClick={() => searchOlder(older.connection, older.continuation)}>Show more older mail</button>}
    </div>}
  </div>;

  const draftRows = draftsHere.length > 0 && <div className="mail-drafts" aria-label="Written in Lumina">
    <p className="mail-group small">Written in Lumina <span className="faint">· not in your mailbox until sent</span></p>
    {draftsHere.map(d => <button key={d.id} type="button" className="mail-row-open draft" aria-current={selected === 'draft:' + d.id ? 'true' : undefined} onClick={() => {
      if (d.thread) { wantedDraft.current = d.id; void open(blank(d.account, d.thread, d.subject, d.updated_epoch)); } else { shownThread.current = null; setOpened(null); reset(); setComposing(n => n + 1); setOpenDraft(d); setSelected('draft:' + d.id); } }}>
      <span className="mail-row-top"><span className="mail-row-who">{d.to.join(', ') || 'No recipient yet'}</span><time className="faint small">{listTime(d.updated_epoch, zone, now)}</time></span>
      <span className="mail-row-subject">{d.subject || '(no subject)'}</span>
      <span className="mail-row-snippet faint">{d.origin === 'assistant' ? 'By your assistant · ' : ''}{d.body.trim().slice(0, 140) || 'Nothing written yet'}</span></button>)}
    {(threads?.length ?? 0) > 0 && <p className="mail-group small">In your mailbox</p>}
  </div>;

  const organizable = pickedThreads.some(t => canOrganize(t.connection_id, 'archive'));
  const listHead = picked.size > 0 ? <div className="mail-bulk" role="toolbar" aria-label="Selected conversations">
    <button type="button" className="iconbtn small ghost" aria-label="Clear the selection" title="Clear" onClick={() => setPicked(new Set())}><I.Close width={16} height={16} /></button>
    <b role="status">{picked.size} selected</b>
    {organizable ? <span className="mail-bulk-tools">
      {label === 'archive' ? <button type="button" className="iconbtn small ghost" aria-label="Move to the inbox" title="Move to the inbox" onClick={() => organize(pickedThreads, 'inbox')}><I.Inbox width={17} height={17} /></button>
        : label !== 'trash' && <button type="button" className="iconbtn small ghost" aria-label="Archive" title="Archive" onClick={() => organize(pickedThreads, 'archive')}><I.Archive width={17} height={17} /></button>}
      {label === 'trash' ? <button type="button" className="iconbtn small ghost" aria-label="Take out of the bin" title="Take out of the bin" onClick={() => organize(pickedThreads, 'untrash')}><I.Inbox width={17} height={17} /></button>
        : <button type="button" className="iconbtn small ghost" aria-label="Move to the bin" title="Move to the bin" onClick={() => organize(pickedThreads, 'trash')}><I.Trash width={17} height={17} /></button>}
      <button type="button" className="iconbtn small ghost" aria-label="Mark as read" title="Mark as read" onClick={() => organize(pickedThreads, 'read')}><I.MailOpen width={17} height={17} /></button>
      <button type="button" className="iconbtn small ghost" aria-label="Mark as unread" title="Mark as unread" onClick={() => organize(pickedThreads, 'unread')}><I.MailUnread width={17} height={17} /></button>
      <button type="button" className="iconbtn small ghost" aria-label="Star" title="Star" onClick={() => organize(pickedThreads, 'star')}><I.Star width={17} height={17} /></button>
      {new Set(pickedThreads.map(t => t.connection_id)).size === 1 && (own.find(o => o.connection_id === pickedThreads[0]?.connection_id)?.labels.length ?? 0) > 0 &&
        <select className="input mail-bulk-label" aria-label="Add a label" value="" onChange={e => { if (e.target.value) void organize(pickedThreads, 'label', e.target.value); }}>
          <option value="">Label…</option>{own.find(o => o.connection_id === pickedThreads[0].connection_id)!.labels.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}</select>}
    </span> : <span className="faint small">These accounts are read only here. You can ask your assistant about them.</span>}
  </div> : <div className="mail-filters">
    <button type="button" className="chip small" aria-pressed={unread} onClick={() => setUnread(!unread)}>Unread</button>
    <button type="button" className="chip small" aria-pressed={attachments} onClick={() => setAttachments(!attachments)}><I.Clip width={14} height={14} />Attachments</button>
    {query && <span className="mail-searching small"><span className="faint">Results for</span> <b>{query}</b>
      <button type="button" className="iconbtn small ghost" aria-label="Clear the search" title="Clear the search" onClick={() => { setTyped(''); setQuery(''); }}><I.Close width={14} height={14} /></button></span>}
    {filling.length > 0 && <span className="mail-filling faint small" role="status">Still loading older mail…</span>}
  </div>;

  const status = <>
    {err && <p className="mail-status warning" role="alert"><span>{err}</span><button type="button" className="iconbtn small ghost" aria-label="Dismiss" onClick={() => setErr('')}><I.Close width={14} height={14} /></button></p>}
    {changed && <p className="mail-status" role="status"><span>{changed.words}</span>{changed.actions.length > 0 && changed.actions.every(a => a.can_undo) && <button type="button" className="btn small" onClick={undoChange}>Undo</button>}</p>}
  </>;

  const nothing = view && !accounts.length ? (
    <EmptyState title="Bring your mail into Lumina" action={<AddAccount providers={view.providers ?? []} primary label="Connect an account" />}>Connect an account and choose what Lumina may read. Your mail shows up here, with your assistant beside it.</EmptyState>
  ) : threads === null ? <div className="mail-loading" role="status">{[0, 1, 2, 3, 4, 5].map(n => <div key={n} className="skeleton" style={{ height: rowHeight - 20 }} />)}<span className="sr">Loading…</span></div>
    : !threads.length && !loading && !draftsHere.length ? (
    <EmptyState>{query ? <>Nothing matches “{query}”{filling.length ? ' in what has loaded so far' : ''}.</> : accounts.some(a => !a.granted.mail) && !accounts.some(a => a.granted.mail)
      ? <>Nothing has been chosen to read yet. Use “Choose what to read” on the account.</> : unread ? <>No unread mail here.</> : <>Nothing in {title}.</>}</EmptyState>
  ) : null;

  const rows = nothing ?? <List label="Conversations" className="mail-list" items={threads ?? []} rowHeight={rowHeight} rowKey={t => threadKey(t)} active={active} onEnd={next ? () => { if (!loading) void load(next); } : undefined}
    header={draftRows || undefined} footer={<>{loading && next && <p className="mail-pad faint small" role="status">Loading more…</p>}{olderPart}</>}
    renderRow={(t, index) => { const k = threadKey(t); const account = byId[t.connection_id]; const who = people(t.people, account?.identity); const first = t.people.find(p => p.address !== account?.identity.toLowerCase()) ?? t.people[0];
      const can = canOrganize(t.connection_id, 'archive'); return (
      <div className={`mail-row${picked.has(k) ? ' picked' : ''}${t.unread ? ' unread' : ''}${selected === k ? ' current' : ''}${picked.size ? ' picking' : ''}`}>
        <label className="mail-row-lead"><input type="checkbox" className="mail-pick" checked={picked.has(k)} aria-label={`Select the conversation with ${who}`} onChange={() => undefined}
          onClick={e => pick(index, (e as React.MouseEvent).shiftKey)} />{first && <Mark person={first} />}</label>
        <button type="button" className="mail-row-open" aria-current={selected === k ? 'true' : undefined} onClick={e => { if (e.shiftKey) { pick(index, true); return; } void open(t); }}>
          <span className="mail-row-top"><span className="mail-row-who">{t.unread && <i className="mail-dot" role="img" aria-label="Unread" />}<span dir="auto">{who}</span>{t.message_count > 1 && <span className="mail-row-count faint">{t.message_count}</span>}</span>
            <span className="mail-row-marks">{t.has_attachments && <I.Clip width={13} height={13} role="img" aria-label="Has an attachment" aria-hidden={undefined} />}{t.starred && <I.StarFilled width={13} height={13} className="mail-starred" role="img" aria-label="Starred" aria-hidden={undefined} />}
              <time className="faint small">{listTime(t.last_epoch, zone, now)}</time></span></span>
          <span className="mail-row-subject" dir="auto">{t.subject || '(no subject)'}</span>
          {!compact && <span className="mail-row-bottom"><span className="mail-row-snippet faint" dir="auto">{t.snippet}</span>
            {several && account && <span className="mail-row-account" title={`In ${account.identity}`}>{tags[account.id]}</span>}</span>}
        </button>
        {can && <span className="mail-row-quick" role="group" aria-label={`Quick actions for the conversation with ${who}`}>
          {t.labels.includes('inbox') && <button type="button" className="iconbtn small" aria-label="Archive" title="Archive" tabIndex={-1} onClick={() => organize([t], 'archive')}><I.Archive width={16} height={16} /></button>}
          <button type="button" className="iconbtn small" aria-label="Move to the bin" title="Move to the bin" tabIndex={-1} onClick={() => organize([t], 'trash')}><I.Trash width={16} height={16} /></button>
          {canOrganize(t.connection_id, 'read') && <button type="button" className="iconbtn small" aria-label={t.unread ? 'Mark as read' : 'Mark as unread'} title={t.unread ? 'Mark as read' : 'Mark as unread'} tabIndex={-1}
            onClick={() => organize([t], t.unread ? 'read' : 'unread')}>{t.unread ? <I.MailOpen width={16} height={16} /> : <I.MailUnread width={16} height={16} />}</button>}
        </span>}
      </div>); }} />;

  const tools = <>
    <form className="hub-search mail-search" role="search" onSubmit={e => { e.preventDefault(); setQuery(typed.trim()); }}>
      <I.Search width={16} height={16} />
      <input ref={search} className="input" type="search" placeholder="Search mail" aria-label="Search mail" value={typed} onChange={e => { setTyped(e.target.value); if (!e.target.value) setQuery(''); }} />
    </form>
    {accounts.length > 0 && <button type="button" className="btn small primary mail-compose-button" onClick={() => compose()} title="Write a new message (C)"><I.Compose width={16} height={16} /><span>Compose</span></button>}
    <button type="button" className="iconbtn small ghost" aria-label="Mail settings" title="Mail settings" onClick={() => setSettingsOpen(true)}><I.Sliders width={16} height={16} /></button>
    <button type="button" className="iconbtn small ghost" aria-label="Refresh" title="Refresh" onClick={refresh}><I.Retry width={16} height={16} /></button>
  </>;
  const banners = (linkNote || choosingAccount || needing.length > 0) && <div className="mail-banners">
    {linkNote && <p className={`notice${linkNote.busy ? '' : ' warning'}`} role={linkNote.busy ? 'status' : 'alert'}><span>{linkNote.words}</span>
      {!linkNote.busy && <button type="button" className="iconbtn small ghost" aria-label="Dismiss" onClick={() => { setLinkNote(null); setParams({}, { replace: true }); }}><I.Close width={14} height={14} /></button>}</p>}
    {choosingAccount && <ChooseAccess account={choosingAccount} onDone={doneChoosing} onCancel={() => { setChoosing(null); setParams({}, { replace: true }); }} />}
    {needing.map(a => <p key={a.id} className="notice warning" role="status"><span><b>{a.identity}</b> is no longer connected: its access ended at {a.provider_label}. The mail already here is still shown, but nothing new arrives.</span> <Reconnect account={a} /></p>)}
  </div>;
  return (
    <Workspace title={title} fill tools={tools} context={side} contextLabel="Mail" className="hub-inbox mail-page">
      <div className="wsp-body">
        {banners}
        <MasterDetail listLabel="Conversations" detailLabel={draftView ? 'Draft' : 'Open conversation'} open={!!selected} className="mail-md"
          list={<>{listHead}{status}{rows}{nothing && label !== 'drafts' && olderPart}</>}
          detail={draftView || threadView}
          empty={accounts.length > 0 ? <div className="mail-nothing-open"><I.Mail width={28} height={28} /><p>Select a conversation to read it here.</p>
            <p className="faint small"><span className="kbd">J</span> <span className="kbd">K</span> move through the list · <span className="kbd">C</span> writes a new message · <span className="kbd">?</span> shows every shortcut</p></div> : null} />
      </div>
      {settingsOpen && <MailSettingsSheet mail={mail} canChange={writes && accounts.some(a => a.capabilities.send || a.capabilities.mark_read)} onSave={saveMail} onClose={() => setSettingsOpen(false)} />}
    </Workspace>);
}
