import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as I from '../components/Icons';
import Accounts from '../components/hub/Accounts';
import Workspace from '../components/frame/Workspace';
import Menu, { type MenuItem } from '../components/ui/Menu';
import { useSize } from '../lib/useSize';
import { EmptyState } from '../components/frame/parts';
import { useSelection, type Action, type Looking } from '../components/frame/Assistant';
import { useCommands } from '../components/frame/CommandBar';
import { usePulse } from '../components/hub/usePulse';
import { AddAccount, ChooseAccess, connectNote as connectWords } from '../components/hub/Connect';
import AllowChanges from '../components/hub/AllowChanges';
import EventEditor from '../components/hub/EventEditor';
import Field from '../components/ui/Field';
import ChangeEvent from '../components/hub/ChangeEvent';
import SeriesScope from '../components/hub/SeriesScope';
import { addDays, addMonths, ago, browserZone, clock, dayKey, dayTitle, eventDays, eventKey, eventTime, failed, foldDay, hub, layoutDay, minuteOfDay, personName, rangeShort, rangeTitle, startOfMonth, startOfWeek,
  titleParts, validZone, zonedEpoch, localTime, type HubAccount, type HubAction, type HubCalendar, type HubEvent, type MeetingProposal, type Overview, type Scope } from '../lib/hub';
import { useData } from '../state/data';
import { ApiError } from '../lib/api';
import '../styles/hub.css';

type View = 'day' | 'week' | 'month' | 'agenda';
const VIEWS: { id: View; label: string }[] = [{ id: 'day', label: 'Day' }, { id: 'week', label: 'Week' }, { id: 'month', label: 'Month' }, { id: 'agenda', label: 'Agenda' }];
const RESPONSE: Record<string, string> = { accepted: 'Going', declined: 'Not going', tentative: 'Maybe', needs_action: 'Not answered' };
const ACCESS: Record<string, string> = { busy: 'Shows only when you are busy', read: 'Read only', write: 'Read only here', owner: 'Read only here' };
/** What the customer may do with a calendar here (Phase 6): change it (changes are on and the account holds the permission), allow changes first, or only read it. */
const accessWords = (c: HubCalendar, account: HubAccount | undefined, writes: boolean) => {
  const theirs = writes && (c.access === 'owner' || c.access === 'write');
  if (theirs && account?.capabilities.event_write) return 'You can change this calendar';
  if (theirs && account?.capabilities.missing?.event_write) return 'Read only until you allow changes';
  return ACCESS[c.access];
};
const HOURS = Array.from({ length: 23 }, (_, i) => i + 1);
/** The grid's measures, in CSS pixels (styles/hub.css reads the same ones as --hour, --gutter and --day-min). LINE is one line of an event with its padding: no event is
 *  drawn shorter, so every one has a title that can be read. Overlapping events sit side by side down to TIGHT pixels each; a busier stretch than that is drawn in
 *  lanes of at least LANE (wide enough for a name) and the rest fold into a "+N" control FOLD wide. */
const HOUR = 48, GUTTER = 56, DAY_MIN = 112, LINE = 22, TIGHT = 56, LANE = 64, FOLD = 30;
const LABEL = Math.ceil((LINE / HOUR) * 60);
const nowSeconds = () => Math.floor(Date.now() / 1000);
const hourLabel = (h: number) => `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? 'AM' : 'PM'}`;
const titleOf = (e: HubEvent) => (e.busy_only ? 'Busy' : e.title || '(no title)');
/** When an event is, in few words: for a chip's tooltip and for a row of a list. */
const timeOf = (e: HubEvent, zone: string) => (e.all_day ? 'all day' : e.end_epoch <= e.start_epoch ? clock(e.start_epoch, zone) : `${clock(e.start_epoch, zone)} to ${clock(e.end_epoch, zone)}`);

function range(view: View, anchor: string): { from: string; to: string; days: string[] } {
  const from = view === 'week' ? startOfWeek(anchor) : view === 'month' ? startOfWeek(startOfMonth(anchor)) : anchor;
  const count = view === 'day' ? 1 : view === 'week' ? 7 : view === 'month' ? 42 : 30;
  const days = Array.from({ length: count }, (_, i) => addDays(from, i));
  return { from, to: days[days.length - 1], days };
}

type Press = (e: React.PointerEvent, event: HubEvent, resize: boolean) => void;
/** One event on a grid. What it is comes first (a bracketed course or team at the end of the title is shown after it, where there is room); the time follows. A `brief`
 *  one has room for a single line, a `point` one is a deadline: both are drawn at their true time with a label that can be read. The whole title and the time are in the
 *  tooltip and in what a screen reader says; pressing it (mouse, Enter or Space, or a tap) opens the event. */
function EventChip({ event, zone, current, onOpen, block, style, onPress, shift, brief, point, length }: { event: HubEvent; zone: string; current: boolean; onOpen(e: HubEvent): void; block?: boolean;
  style?: React.CSSProperties; onPress?: Press; shift?: { minutes: number; days: number; resize: boolean; width: number }; brief?: boolean; point?: boolean; length?: number }) {
  const when = event.all_day ? 'all day' : clock(event.start_epoch, zone);
  const moved = shift ? (shift.resize ? { height: `calc(${style?.height} + var(--hour) * ${shift.minutes / 60})` }
    : { transform: `translate(${shift.days * shift.width}px, calc(var(--hour) * ${shift.minutes / 60}))`, zIndex: 6 }) : {};
  const { main, tag } = titleParts(titleOf(event)); const timed = !block && !event.all_day;
  const kind = `${block ? ' block' : ''}${brief ? ' brief' : ''}${point ? ' point' : ''}${event.my_response === 'declined' ? ' declined' : ''}${event.my_response === 'tentative' ? ' tentative' : ''}${onPress ? ' movable' : ''}${shift ? ' moving' : ''}`;
  // How much of a short event's box is the event itself: its edge is drawn solid for that long, so ten minutes still read as ten minutes.
  const real = brief && !point && length !== undefined ? { ['--real' as string]: `calc(var(--hour) * ${Math.max(length, 3) / 60})` } : {};
  return (
    <button type="button" className={`hub-event cal-${event.colour}${kind}`} data-layout-allow="calendar-event"
      style={{ ...style, ...real, ...moved }} aria-current={current ? 'true' : undefined} aria-label={`${titleOf(event)}, ${when}`} title={`${titleOf(event)} · ${timeOf(event, zone)}`} onClick={() => onOpen(event)}
      onPointerDown={onPress ? e => onPress(e, event, false) : undefined}>
      <b>{main}</b>
      {timed && <span className="hub-event-when"><span>{when}</span>{!brief && !point && <span> – {clock(event.end_epoch, zone)}</span>}</span>}
      {tag ? <span className="hub-event-tag">{tag}</span> : timed && !brief && event.place ? <span className="hub-event-tag">{event.place}</span> : null}
      {onPress && <span className="hub-resize" aria-hidden="true" onPointerDown={e => { e.stopPropagation(); onPress(e, event, true); }} />}
    </button>);
}
/** The control that stands in for events with no room to be drawn ("+3 more"): it opens the list, and choosing one opens that event. */
function MoreEvents({ events, count, label, heading, zone, onOpen, className = '', style }: { events: HubEvent[]; count: number; label: string; heading: string; zone: string; onOpen(e: HubEvent): void;
  className?: string; style?: React.CSSProperties }) {
  const items: MenuItem[] = events.map(e => ({ id: eventKey(e), label: titleOf(e), hint: timeOf(e, zone), icon: <i className={`hub-dot cal-${e.colour}`} aria-hidden="true" />, onSelect: () => onOpen(e) }));
  return <Menu label={label} heading={heading} items={items} className={`hub-more-wrap ${className}`} style={style}
    trigger={({ props }) => <button type="button" className="hub-more" aria-label={label} title={label} {...props}>+{count}<span> more</span></button>} />;
}

/** What the inspector shows for one event: when (in the customer's timezone, and the event's own when that differs), where, who and their answers, the notes, which account
 *  and calendar it is from, and how fresh it is. An event that is only visible as busy shows nothing else. With changes on (Phase 6): Change and Cancel for an event the
 *  customer organizes, the answers for an invitation from someone else; a repeating event always asks how much of the series (#62). */
function Inspector({ event, zone, account, calendar, now, writes, onCancel, onRespond, onChanged }: { event: HubEvent; zone: string; account?: HubAccount; calendar?: HubCalendar; now: number;
  writes: boolean; onCancel(e: HubEvent, notify: boolean, scope?: Scope): Promise<void>; onRespond(e: HubEvent, response: 'accepted' | 'tentative' | 'declined', scope?: 'this' | 'all'): Promise<void>;
  onChanged(action: HubAction, words: string): void }) {
  const [asking, setAsking] = useState(false); const [busy, setBusy] = useState(false); const [editing, setEditing] = useState(false);
  const [scope, setScope] = useState<Scope | null>(null); const [answerScope, setAnswerScope] = useState<Scope | null>(null);
  useEffect(() => { setAsking(false); setEditing(false); setScope(null); setAnswerScope(null); }, [event.id]);
  // An event the customer organizes, in a calendar this account may change, when changes are allowed for it. A repeating event needs the series permission too.
  const mine = !!account && (!event.organizer || event.organizer.address === account.identity || !!event.attendees?.find(a => a.self && a.address === event.organizer?.address));
  const writable = writes && (calendar?.access === 'owner' || calendar?.access === 'write') && !event.busy_only && !event.cancelled && mine;
  const series = !!event.series_id; const seriesOk = !series || !!account?.capabilities.event_series;
  const changeable = writable && !!account?.capabilities.event_write && seriesOk;
  const editable = writable && !!account?.capabilities.event_change && seriesOk;
  const others = (event.attendees ?? []).filter(a => !a.self).length;
  // An invitation from someone else is answered, never cancelled (#63, #64): Going, Maybe, Not going. The organizer is told.
  const invited = writes && !!account?.capabilities.respond && !mine && !!event.attendees?.some(a => a.self) && !event.cancelled && !event.busy_only;
  const askAnswerScope = invited && series && !!account?.capabilities.event_series;
  if (editing && account) return (
    <section className={`hub-inspector cal-${event.colour}`} aria-label="Event details">
      <header><h2>Change “{titleOf(event)}”</h2></header>
      <ChangeEvent event={event} account={account} zone={zone} onDone={(a, words) => { setEditing(false); onChanged(a, words); }} onCancel={() => setEditing(false)} />
    </section>);
  return (
    <section className={`hub-inspector cal-${event.colour}`} aria-label="Event details">
      <header><h2>{titleParts(titleOf(event)).main}</h2>{titleParts(titleOf(event)).tag && <p className="hub-inspector-tag">{titleParts(titleOf(event)).tag}</p>}</header>
      {event.cancelled && <p className="notice warning">This occurrence was cancelled.</p>}
      <dl>
        <dt>When</dt><dd>{eventTime(event, zone)}{event.series_id && <span className="faint"> · {event.exception ? 'A changed occurrence of a repeating event' : 'Repeats'}</span>}</dd>
        {event.place && <><dt>Where</dt><dd>{event.place}</dd></>}
        {event.conference_url && <><dt>Call</dt><dd><a href={event.conference_url} target="_blank" rel="noopener noreferrer">Join the call</a></dd></>}
        <dt>Calendar</dt><dd>{calendar?.name ?? 'Calendar'}{account ? ` · ${account.identity}` : ''}</dd>
        {event.my_response && <><dt>You</dt><dd>{RESPONSE[event.my_response]}</dd></>}
        {event.organizer && <><dt>Organizer</dt><dd>{personName(event.organizer)}</dd></>}
      </dl>
      {event.busy_only && <p className="muted small">This calendar only shares when you are busy, so there is nothing more to show.</p>}
      {!!event.attendees?.length && <section aria-label="People"><h3 className="hub-side-title">People ({event.attendees.length})</h3>
        <ul>{event.attendees.map((a, i) => <li key={a.address || i} className="small">{personName(a)}{a.self ? ' (you)' : ''} <span className="faint">· {RESPONSE[a.response] ?? a.response}{a.optional ? ' · optional' : ''}</span></li>)}</ul></section>}
      {event.description && <section aria-label="Notes"><h3 className="hub-side-title">Notes</h3><p className="hub-notes">{event.description}</p></section>}
      {(editable || changeable) && !asking && <p className="hub-inspector-acts">
        {editable && <button type="button" className="btn small" onClick={() => setEditing(true)}>Change</button>}
        {changeable && <button type="button" className="btn small tertiary" onClick={() => setAsking(true)}>Cancel event</button>}</p>}
      {changeable && asking && <div className="notice" role="alertdialog" aria-label="Cancel this event?">
        {series && <SeriesScope name={`cancel-${event.id}`} value={scope} onChange={setScope} legend="This event repeats. Which events should be cancelled?" />}
        <p className="small">{others ? `${others} ${others === 1 ? 'person is' : 'people are'} told it is cancelled.` : 'Nobody else is invited.'} You can undo it afterwards.</p>
        <button type="button" className="btn small" disabled={busy || (series && !scope)} onClick={async () => { setBusy(true); try { await onCancel(event, true, scope ?? undefined); } finally { setBusy(false); setAsking(false); } }}>Cancel it</button>
        <button type="button" className="btn small tertiary" disabled={busy} onClick={() => setAsking(false)}>Keep it</button></div>}
      {askAnswerScope && <SeriesScope name={`answer-${event.id}`} value={answerScope} onChange={setAnswerScope} legend="This event repeats. Answer for" choices={['this', 'all']} />}
      {invited && <div className="seg" role="group" aria-label="Your answer">{(['accepted', 'tentative', 'declined'] as const).map(r =>
        <button key={r} type="button" className="seg-item" aria-pressed={event.my_response === r} disabled={busy || (askAnswerScope && !answerScope)}
          onClick={async () => { setBusy(true); try { await onRespond(event, r, askAnswerScope ? (answerScope as 'this' | 'all') : undefined); } finally { setBusy(false); } }}>{RESPONSE[r]}</button>)}</div>}
      {writes && account && !account.capabilities.event_write && <AllowChanges account={account} capability="event_write" />}
      <p className="faint small">{calendar ? (changeable || (writes && account?.capabilities.event_write && (calendar.access === 'owner' || calendar.access === 'write')) ? 'You can change this calendar' : ACCESS[calendar.access]) : 'Read only'} · Updated {ago(event.synced_epoch, now)}.
        {event.provider_url && account && <> <a href={event.provider_url} target="_blank" rel="noopener noreferrer">Open in {account.provider_label}</a></>}</p>
    </section>);
}

/** A calendar feed by its address (#D9): a school's, a team's or a booking system's. Read only. The address is checked to be a calendar, then kept like a password and
 *  never shown again in full. */
function FeedForm({ onAdded }: { onAdded(): void }) {
  const [open, setOpen] = useState(false); const [address, setAddress] = useState(''); const [name, setName] = useState(''); const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(''); const [err, setErr] = useState('');
  if (!open) return <button type="button" className="btn small tertiary hub-feed-open" onClick={() => { setOpen(true); setNote(''); }}><I.Plus width={14} height={14} />Add a calendar feed</button>;
  const add = async () => {
    setBusy(true); setErr('');
    try { await hub.addFeed(address.trim(), name.trim() || undefined); setOpen(false); setAddress(''); setName(''); setNote('Added. Its events appear in a moment.'); onAdded(); }
    catch (e) { setErr(e instanceof ApiError && e.detail ? e.detail : failed(e)); } finally { setBusy(false); }
  };
  return (
    <form className="form hub-feed" aria-label="Add a calendar feed" onSubmit={e => { e.preventDefault(); if (address.trim()) void add(); }}>
      <Field label="Feed address" error={err} hint="Read only. Lumina keeps the address private and does not show it again.">{p =>
        <input {...p} className="input" value={address} onChange={e => setAddress(e.target.value)} placeholder="https://… or webcal://…" required autoFocus />}</Field>
      <Field label="Name (optional)">{p => <input {...p} className="input" value={name} onChange={e => setName(e.target.value)} maxLength={200} />}</Field>
      {note && <p className="faint small" role="status">{note}</p>}
      <div className="form-actions"><button type="button" className="btn small tertiary" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
        <button type="submit" className="btn small primary" disabled={busy || !address.trim()}>Add</button></div>
    </form>);
}

/** A small month for jumping to a day. The days of the current view are marked. */
function MiniMonth({ day, today, from, to, onPick }: { day: string; today: string; from: string; to: string; onPick(d: string): void }) {
  const [month, setMonth] = useState(day.slice(0, 7) + '-01');
  useEffect(() => { setMonth(day.slice(0, 7) + '-01'); }, [day]);
  const first = startOfWeek(month); const days = Array.from({ length: 42 }, (_, i) => addDays(first, i));
  return <section className="mini-month" aria-label="Jump to a day">
    <header><b>{dayTitle(month, 'month')}</b>
      <button type="button" className="iconbtn small ghost" aria-label="Previous month" onClick={() => setMonth(addMonths(month, -1))}><I.Chevron width={14} height={14} style={{ transform: 'rotate(180deg)' }} /></button>
      <button type="button" className="iconbtn small ghost" aria-label="Next month" onClick={() => setMonth(addMonths(month, 1))}><I.Chevron width={14} height={14} /></button></header>
    <div className="mini-grid">{days.slice(0, 7).map(d => <span key={'h' + d} className="mini-head" aria-hidden="true">{dayTitle(d, 'weekday').slice(0, 2)}</span>)}
      {days.map(d => <button key={d} type="button" className={`mini-day${d.slice(0, 7) !== month.slice(0, 7) ? ' other' : ''}${d === today ? ' today' : ''}${d >= from && d <= to ? ' shown' : ''}`}
        aria-label={`Go to ${dayTitle(d)}`} aria-current={d === day ? 'date' : undefined} onClick={() => onPick(d)}>{Number(d.slice(8))}</button>)}</div>
  </section>;
}

/** The Calendar: every selected calendar of every connected account together, in the customer's timezone. Left: accounts and calendars. Middle: day, week, month or agenda.
 *  Right: the event that is open. Read-only in this phase: nothing here creates, moves or answers an event. */
export default function CalendarPage() {
  const { app } = useData(); const on = !!app?.features.dashboard;
  const [info, setInfo] = useState<Overview | null>(null); const [err, setErr] = useState(''); const [now, setNow] = useState(nowSeconds);
  const [view, setView] = useState<View>(() => (typeof window !== 'undefined' && window.innerWidth < 600 ? 'day' : 'week')); const [anchor, setAnchor] = useState<string | null>(null);   // a phone opens on one day
  const [chosen, setChosen] = useState<Set<string> | null>(null); const [events, setEvents] = useState<HubEvent[] | null>(null); const [partial, setPartial] = useState(false);
  const [selected, setSelected] = useState<string | null>(null); const [detail, setDetail] = useState<HubEvent | null>(null);
  const [creating, setCreating] = useState(false); const [done, setDone] = useState<{ action: HubAction; words: string } | null>(null);
  // Times the assistant found for a meeting (#65): drawn as suggestions; picking one fills in the new event (the customer still presses Create).
  const [proposals, setProposals] = useState<MeetingProposal[]>([]); const [picking, setPicking] = useState<{ proposal: MeetingProposal; option: MeetingProposal['options'][number] } | null>(null);
  const [typed, setTyped] = useState(''); const [found, setFound] = useState<{ query: string; events: HubEvent[]; complete: boolean } | null>(null);
  const [zoneEdit, setZoneEdit] = useState<string | null>(null); const [colouring, setColouring] = useState<string | null>(null);
  const request = useRef(0); const grid = useRef<HTMLDivElement | null>(null);
  // The room the calendar itself has (not the window's: the side column is dragged and hidden, the assistant docks). The toolbar, the all-day section and how many
  // events sit side by side all follow it. Unknown (0) counts as roomy.
  const [bodyRef, body] = useSize<HTMLDivElement>(); const [gridSize, sized] = useSize<HTMLDivElement>();
  const room = !body.width || body.width >= 1000 ? 'wide' : body.width >= 860 ? 'medium' : body.width >= 460 ? 'narrow' : 'tiny';
  const stacked = room === 'narrow' || room === 'tiny';
  const [searching, setSearching] = useState(false);
  // Where the customer had the grid. It is put back when the grid comes back (after a search, a dialog, a reload), so nothing but their own scrolling moves it.
  const kept = useRef<{ key: string; top: number; left: number } | null>(null); const showing = useRef('');
  const gridRef = useCallback((node: HTMLDivElement | null) => {
    grid.current = node; gridSize(node);
    if (node && kept.current && kept.current.key === showing.current && typeof node.scrollTo === 'function') node.scrollTo({ top: kept.current.top, left: kept.current.left });
  }, [gridSize]);
  // A range of days chosen by dragging across the day headings, or from the keyboard (Shift with the arrows). It only tells the assistant "these days" in this phase.
  const [days, setDays] = useState<{ start: string; end: string } | null>(null); const drag = useRef<{ from: string; moved: boolean } | null>(null);
  useEffect(() => { const up = () => { drag.current = drag.current && { ...drag.current, from: '' }; }; window.addEventListener('pointerup', up); return () => window.removeEventListener('pointerup', up); }, []);
  useEffect(() => { const t = window.setInterval(() => { if (document.visibilityState === 'visible') setNow(nowSeconds()); }, 60000); return () => window.clearInterval(t); }, []);   // the current time line moves
  const [params, setParams] = useSearchParams(); const [choosing, setChoosing] = useState<string | null>(params.get('connected'));
  const connectNote = connectWords(params.get('connect'), params.get('ref'));
  const doneChoosing = () => { setChoosing(null); setParams({}, { replace: true }); window.setTimeout(() => { void loadInfo(); void load(); }, 1200); };

  const zone = useMemo(() => (info?.settings.timezone && validZone(info.settings.timezone) ? info.settings.timezone : browserZone()), [info?.settings.timezone]);
  const today = dayKey(now, zone); const day = anchor ?? today;
  const accounts = useMemo(() => (info?.accounts ?? []).filter(a => a.capabilities.calendar), [info]);
  const byAccount = useMemo(() => Object.fromEntries(accounts.map(a => [a.id, a])) as Record<string, HubAccount>, [accounts]);
  const calendars = info?.calendars ?? [];
  const calendarOf = useCallback((e: HubEvent) => calendars.find(c => c.connection_id === e.connection_id && c.id === e.calendar_id), [calendars]);
  const shownAccounts = useMemo(() => accounts.filter(a => !chosen || chosen.has(a.id)).map(a => a.id), [accounts, chosen]);
  const span = useMemo(() => range(view, day), [view, day]);
  showing.current = `${view}|${span.from}`;

  const loadInfo = useCallback(async () => {
    try { const r = await hub.overview(); setInfo(r); setErr(''); setNow(nowSeconds()); }
    catch (e) { setErr(failed(e)); setInfo(v => v ?? { accounts: [], settings: { timezone: null, image_senders: [] }, counts: { unread: 0, by_account: {} }, calendars: [], labels: [], colours: [], read_only: true }); }
  }, []);
  useEffect(() => { if (on) void loadInfo(); }, [on, loadInfo]);

  const selection = calendars.filter(c => c.selected).map(c => c.connection_id + c.id + c.colour).join('|');
  const load = useCallback(async () => {
    if (!info) return;
    if (!shownAccounts.length) { setEvents([]); return; }
    const mine = ++request.current;
    try {
      // A day either side, so an all-day event (whose dates carry no timezone) is never missed at the edge.
      const r = await hub.events(zonedEpoch(addDays(span.from, -1), 0, zone), zonedEpoch(addDays(span.to, 2), 0, zone), shownAccounts);
      if (mine !== request.current) return;
      setEvents(r.events); setPartial(!r.complete); setErr('');
      hub.proposals(zonedEpoch(span.from, 0, zone), zonedEpoch(addDays(span.to, 1), 0, zone)).then(p => { if (mine === request.current) setProposals(p.proposals); }).catch(() => setProposals([]));
    } catch (e) { if (mine === request.current) { setErr(failed(e)); setEvents(prev => prev ?? []); } }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!info, span.from, span.to, zone, shownAccounts.join(','), selection]);
  useEffect(() => { void load(); }, [load]);
  usePulse(on, () => { void loadInfo(); void load(); });      // live: when anything changed at the server, the calendars and the events on screen are loaded again, quietly
  // The grid opens at the current hour when today is on screen (an hour above it, for context), at 7 in the morning otherwise.
  useEffect(() => {
    if ((view !== 'week' && view !== 'day') || !grid.current || typeof grid.current.scrollTo !== 'function') return;
    const hour = span.days.includes(today) ? Math.max(0, Math.floor(minuteOfDay(nowSeconds(), zone) / 60) - 1) : 7;
    // Where the week is wider than its box (a narrow window), it opens on the day that is shown in the side column, not on Monday.
    const column = grid.current.querySelector<HTMLElement>(`[data-col="${day}"]`);
    grid.current.scrollTo({ top: hour * HOUR, left: column ? Math.max(0, column.offsetLeft - GUTTER) : 0 });
  }, [view, events === null, span.from]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setDays(null); }, [view, span.from]);

  const open = useCallback(async (e: HubEvent) => {
    setSelected(eventKey(e)); setDetail(e);
    try { const r = await hub.event(e.connection_id, e.calendar_id, e.id); setDetail(d => (d && eventKey(d) === eventKey(e) ? { ...e, ...r.event } : d)); }
    catch (error) { setErr(failed(error)); }
  }, []);
  const close = () => { setSelected(null); setDetail(null); };
  const step = (n: number) => setAnchor(view === 'month' ? addMonths(day, n) : addDays(day, n * (view === 'week' ? 7 : view === 'agenda' ? 30 : 1)));
  const refresh = async () => { try { await hub.refresh(); } catch (e) { setErr(failed(e)); } window.setTimeout(() => { void loadInfo(); void load(); }, 1500); };
  // Phase 6: the customer's own changes. Each is one action through the pipeline; the result says so, with Undo, and the calendar is read again.
  const writes = !!info && !info.read_only;
  const changed = (action: HubAction, words: string) => { setDone({ action, words }); setCreating(false); void refresh(); };
  const cancelEvent = async (e: HubEvent, notify: boolean, scope?: Scope) => {
    try { const r = await hub.cancelEvent(e.connection_id, e.calendar_id, e.id, notify, scope, e.series_id); if (r.action.state === 'done') { changed(r.action, `"${titleOf(e)}" was cancelled.`); close(); } else setErr(r.action.ended_words || 'The event was not cancelled.'); }
    catch (error) { setErr(failed(error)); }
  };
  const respond = async (e: HubEvent, response: 'accepted' | 'tentative' | 'declined', scope?: 'this' | 'all') => {
    try { const r = await hub.respondEvent(e.connection_id, e.calendar_id, e.id, response, scope, e.series_id); if (r.action.state === 'done') { changed(r.action, `You answered "${RESPONSE[response]}" to "${titleOf(e)}".`); setDetail(d => d && eventKey(d) === eventKey(e) ? { ...d, my_response: response } : d); } else setErr(r.action.ended_words || 'Your answer was not sent.'); }
    catch (error) { setErr(failed(error)); }
  };
  const undo = async () => {
    if (!done) return;
    try { const r = await hub.undo(done.action.id); setDone(r.action.state === 'done' ? { action: r.action, words: 'Undone.' } : null); if (r.action.state !== 'done') setErr(r.action.ended_words || 'It could not be undone.'); void refresh(); }
    catch (error) { setErr(failed(error)); }
  };
  // Moving or resizing an event on the grid (#D7). A drop is the customer's own change; when other people are invited or the event repeats, it asks first and says who is told.
  const press = useRef<{ event: HubEvent; x: number; y: number; resize: boolean; width: number; hour: number; moved: boolean } | null>(null);
  const swallowClick = useRef(false);
  const [moving, setMoving] = useState<{ key: string; minutes: number; days: number; resize: boolean; width: number } | null>(null);
  const [pendingMove, setPendingMove] = useState<{ event: HubEvent; start: number; end: number; others: number } | null>(null);
  const [moveScope, setMoveScope] = useState<Scope | null>(null);
  const movable = (e: HubEvent) => {
    const account = byAccount[e.connection_id]; const cal = calendarOf(e);
    return writes && !!account?.capabilities.event_change && (cal?.access === 'owner' || cal?.access === 'write') && !e.busy_only && !e.cancelled && !e.all_day
      && (!e.series_id || !!account.capabilities.event_series);
  };
  const applyMove = async (e: HubEvent, start: number, end: number, scope?: Scope) => {
    try {
      const r = await hub.changeEvent({ connection: e.connection_id, calendar: e.calendar_id, event: e.id, series: e.series_id, scope, start: localTime(start, zone), end: localTime(end, zone), timezone: zone, notify: true });
      if (r.action.state === 'done') changed(r.action, `"${titleOf(e)}" was moved to ${dayTitle(dayKey(start, zone), 'short')}, ${clock(start, zone)} to ${clock(end, zone)}.`);
      else setErr(r.action.ended_words || 'The event was not moved.');
    } catch (error) { setErr(failed(error)); }
    setPendingMove(null); setMoveScope(null);
  };
  const dropped = async (e: HubEvent, start: number, end: number) => {
    let full: HubEvent = e;
    try { full = { ...e, ...(await hub.event(e.connection_id, e.calendar_id, e.id)).event }; } catch (error) { setErr(failed(error)); return; }
    const account = byAccount[e.connection_id];
    const mine = !full.organizer || full.organizer.address === account?.identity || !!full.attendees?.find(a => a.self && a.address === full.organizer?.address);
    if (!mine) { setErr(`Only the organizer can move “${titleOf(e)}”. You can answer the invitation instead.`); return; }
    const others = (full.attendees ?? []).filter(a => !a.self).length;
    if (others || full.series_id) { setMoveScope(null); setPendingMove({ event: full, start, end, others }); return; }
    await applyMove(full, start, end);
  };
  const onPress: Press = (e, event, resize) => {
    if (e.button !== 0) return;
    const col = (e.currentTarget as HTMLElement).closest('.hub-day-col');
    const hour = parseFloat(getComputedStyle(grid.current ?? document.body).getPropertyValue('--hour')) || HOUR;
    press.current = { event, x: e.clientX, y: e.clientY, resize, width: col?.getBoundingClientRect().width || 100, hour, moved: false };
  };
  useEffect(() => {
    const step = (p: NonNullable<typeof press.current>, x: number, y: number) => ({
      minutes: Math.round(((y - p.y) / p.hour) * 4) * 15, days: p.resize || view !== 'week' ? 0 : Math.round((x - p.x) / p.width) });
    const move = (ev: PointerEvent) => {
      const p = press.current; if (!p) return;
      if (!p.moved && Math.abs(ev.clientX - p.x) < 5 && Math.abs(ev.clientY - p.y) < 5) return;
      p.moved = true;
      setMoving({ key: eventKey(p.event), ...step(p, ev.clientX, ev.clientY), resize: p.resize, width: p.width });
    };
    const up = (ev: PointerEvent) => {
      const p = press.current; press.current = null; setMoving(null);
      if (!p?.moved) return;
      swallowClick.current = true; window.setTimeout(() => { swallowClick.current = false; }, 0);
      const { minutes, days } = step(p, ev.clientX, ev.clientY);
      if (!minutes && !days) return;
      const e = p.event; const length = e.end_epoch - e.start_epoch;
      const startMinute = minuteOfDay(e.start_epoch, zone);
      if (p.resize) { const end = Math.max(e.start_epoch + 900, e.end_epoch + minutes * 60); void dropped(e, e.start_epoch, end); return; }
      const minute = Math.min(24 * 60 - 15, Math.max(0, startMinute + minutes));
      const start = zonedEpoch(addDays(dayKey(e.start_epoch, zone), days), minute, zone);
      void dropped(e, start, start + length);
    };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zone, view, byAccount, calendars]);
  const openUnlessDragged = (e: HubEvent) => { if (swallowClick.current) return; void open(e); };
  const toggleAccount = (id: string) => setChosen(prev => { const base = new Set(prev ?? accounts.map(a => a.id)); if (base.has(id)) base.delete(id); else base.add(id); return base; });
  const setCalendar = async (c: HubCalendar, change: { selected?: boolean; colour?: string }) => {
    try { const r = await hub.setCalendar(c.connection_id, c.id, change); setInfo(v => (v ? { ...v, calendars: r.calendars } : v)); }
    catch (e) { setErr(failed(e)); }
  };
  const saveZone = async (value: string | null) => {
    if (value !== null && !validZone(value)) { setErr('That timezone is not known. Choose one from the list.'); return; }
    try { const r = await hub.setSettings({ timezone: value }); setInfo(v => (v ? { ...v, settings: r.settings } : v)); setZoneEdit(null); setErr(''); }
    catch (e) { setErr(failed(e)); }
  };
  const search = async () => {
    const q = typed.trim();
    if (!q) { setFound(null); return; }
    try { const r = await hub.searchEvents(q); setFound({ query: q, ...r }); } catch (e) { setErr(failed(e)); }
  };
  const endSearch = () => { setSearching(false); setTyped(''); setFound(null); };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT')) return;
      if (e.metaKey || e.ctrlKey || e.altKey || target?.closest?.('[data-day]') || document.querySelector('[role="dialog"][aria-modal="true"]:not(.zone-sheet)')) return;   // a focused day heading handles its own arrows
      if (e.key === 'Escape' && selected) close();
      else if (e.key === 'Escape' && days) setDays(null);
      else if (e.key === 't') setAnchor(null);
      else if (e.key === 'ArrowLeft') step(-1);
      else if (e.key === 'ArrowRight') step(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, view, day, days]);

  const ordered = (a: string, b: string) => (a <= b ? { start: a, end: b } : { start: b, end: a });
  const rangeWords = (r: { start: string; end: string }) => (r.start === r.end ? dayTitle(r.start) : rangeTitle(r.start, r.end));
  const looking: Looking = detail ? { kind: 'event', connection: detail.connection_id, calendar: detail.calendar_id, event: detail.id } : days ? { kind: 'days', ...days } : { kind: 'days', start: span.from, end: span.to };
  const lookingWords = detail ? `the event “${titleOf(detail)}”` : days ? `these days: ${rangeWords(days)}` : view === 'day' ? dayTitle(day) : rangeTitle(span.from, span.to);
  const actions: Action[] = detail ? [{ label: 'Prepare me for this', message: 'Prepare me for this meeting: who is in it, what we last discussed, and what I should have ready.' },
    { label: 'Who are these people?', message: 'Who are the people in this event, from my mail and calendar?' }]
    : [{ label: 'What matters here?', message: 'What matters most in my calendar for these days? Point out conflicts and anything I should prepare for.' },
      { label: 'When am I free?', message: 'When am I free in these days? List the open stretches of an hour or more during the working day.' }];
  useSelection(on ? { looking, words: lookingWords, actions } : null);
  const unit = view === 'month' ? 'month' : view === 'week' ? 'week' : view === 'agenda' ? '30 days' : 'day';
  useCommands(on ? [{ id: 'cal-later', label: `Go to the next ${unit}`, shortcut: 'cal-later', run: () => step(1) }, { id: 'cal-earlier', label: `Go to the previous ${unit}`, shortcut: 'cal-earlier', run: () => step(-1) },
    { id: 'cal-today', label: 'Go to today', shortcut: 'cal-today', run: () => { setFound(null); setAnchor(null); } },
    ...VIEWS.filter(v => v.id !== view).map(v => ({ id: `cal-${v.id}`, label: `Show the ${v.label.toLowerCase()} view`, run: () => { setFound(null); setView(v.id); } }))] : []);
  // Opened from the command bar or from a link in an answer: ?connection=&calendar=&event= opens that event and shows its day. A new link while the page is open selects
  // the new event in place.
  const linked = useRef('');
  useEffect(() => {
    const id = params.get('event'), connection = params.get('connection'), cal = params.get('calendar');
    const key = `${connection}|${cal}|${id}`;
    if (!on || linked.current === key || !id || !connection || !cal || !info) return;
    linked.current = key;
    hub.event(connection, cal, id).then(r => { setAnchor(dayKey(r.event.start_epoch, zone)); setSelected(eventKey(r.event)); setDetail(r.event); }).catch(e => setErr(failed(e)));
  }, [on, params, info, zone]);
  /** A day heading: click to open the day; drag across headings, or Shift with the arrow keys, to choose a range; the arrows alone move between headings. */
  const dayProps = (d: string, goes: () => void) => ({
    'data-day': d, 'aria-pressed': days ? d >= days.start && d <= days.end : undefined,
    onPointerDown: (e: React.PointerEvent) => { if (e.button === 0) drag.current = { from: d, moved: false }; },
    onPointerEnter: () => { const g = drag.current; if (g?.from && g.from !== d) { g.moved = true; setDays(ordered(g.from, d)); } },
    onClick: () => { if (drag.current?.moved) { drag.current = null; return; } drag.current = null; goes(); },
    onKeyDown: (e: React.KeyboardEvent) => {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowDown' && view === 'month' ? 7 : e.key === 'ArrowUp' && view === 'month' ? -7 : 0;
      if (e.key === 'Escape' && days) { e.preventDefault(); e.stopPropagation(); setDays(null); return; }
      if (!step) return;
      e.preventDefault();
      const to = addDays(d, step);
      const target = (e.currentTarget.closest('.wsp-body') ?? document).querySelector<HTMLElement>(`[data-day="${to}"]`);
      if (!target) return;
      target.focus();
      if (e.shiftKey) setDays(prev => { const pivot = prev ? (prev.start === d ? prev.end : prev.start) : d; return ordered(pivot, to); });
    },
  });

  const byDay = useMemo(() => {
    const out: Record<string, { allDay: HubEvent[]; timed: HubEvent[] }> = Object.fromEntries(span.days.map(d => [d, { allDay: [], timed: [] }]));
    for (const e of events ?? []) for (const d of eventDays(e, zone, span.from, span.to)) (e.all_day ? out[d].allDay : out[d].timed).push(e);
    return out;
  }, [events, span, zone]);

  const heading = view === 'day' ? dayTitle(day) : view === 'month' ? dayTitle(day, 'month')
    : rangeTitle(span.from, span.to);
  // The same heading in fewer words, where the toolbar is tight: "Sat, Nov 21", "Nov 16 – 22, 2026".
  const brief = view === 'day' ? new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(day + 'T12:00:00Z'))
    : view === 'month' ? heading : rangeShort(span.from, span.to);
  // The grid's own room: how many all-day events a day shows before "+N more" (more in a tall window), and how many timed events fit side by side in one day's column.
  const allDayRows = !sized.height ? 3 : sized.height >= 640 ? 4 : sized.height >= 440 ? 3 : 2;
  const columnWidth = sized.width ? Math.max(view === 'week' ? DAY_MIN : 0, (sized.width - GUTTER) / span.days.length) : 0;
  const fit = columnWidth ? Math.max(1, Math.floor((columnWidth - 4) / TIGHT)) : 99, lanes = columnWidth ? Math.max(1, Math.floor((columnWidth - 4 - FOLD) / LANE)) : 99;
  const needing = accounts.filter(a => a.state === 'needs_you');
  const choosingAccount = (info?.accounts ?? []).find(a => a.id === choosing);
  const filling = calendars.filter(c => !c.filled && shownAccounts.includes(c.connection_id));
  const list = (items: HubEvent[], days: string[]) => days.map(d => ({ day: d, items: items.filter(e => eventDays(e, zone, d, d).length).sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start_epoch - b.start_epoch) })).filter(g => g.items.length);
  const agendaRows = (groups: { day: string; items: HubEvent[] }[]) => groups.map(g => (
    <section key={g.day} aria-label={dayTitle(g.day)}><h2>{g.day === today ? 'Today · ' : ''}{dayTitle(g.day)}</h2>
      <ul>{g.items.map(e => <li key={eventKey(e) + g.day}><button type="button" className={`hub-agenda-row cal-${e.colour}`} aria-current={selected === eventKey(e) ? 'true' : undefined} onClick={() => open(e)}>
        <span className="faint">{e.all_day ? 'All day' : `${clock(e.start_epoch, zone)} to ${clock(e.end_epoch, zone)}`}</span>
        <span><b>{titleOf(e)}</b>{e.place && <span className="faint"> · {e.place}</span>}{accounts.length > 1 && <span className="faint"> · {byAccount[e.connection_id]?.identity}</span>}</span></button></li>)}</ul>
    </section>));

  if (!on) return (
    <Workspace title="Calendar"><EmptyState title="Not available yet" action={<Link className="btn" to="/home">Back to Home</Link>}>The calendars of your connected accounts in one place, with your assistant beside them.</EmptyState></Workspace>);

  const context = <div className="hub-side" aria-label="Calendars">
    <MiniMonth day={day} today={today} from={span.from} to={span.to} onPick={d => { setFound(null); setAnchor(d); }} />
    <Accounts accounts={accounts} part="calendar" chosen={new Set(shownAccounts)} onToggle={toggleAccount} now={now} providers={info?.providers} onChoose={a => setChoosing(a.id)} />
    {info?.feeds && <FeedForm onAdded={() => window.setTimeout(() => { void loadInfo(); void load(); }, 1500)} />}
    {accounts.filter(a => shownAccounts.includes(a.id)).map(a => { const mine = calendars.filter(c => c.connection_id === a.id); return !mine.length ? null : (
      <section key={a.id} className="hub-calendars" aria-label={`Calendars of ${a.identity}`}>
        <h2 className="hub-side-title" title={a.identity}>{a.identity}</h2>
        {mine.map(c => { const k = c.connection_id + c.id; return (
          <div key={k} className={`cal-${c.colour}`}>
            <label className="hub-calendar-row"><input type="checkbox" checked={c.selected} onChange={e => setCalendar(c, { selected: e.target.checked })} />
              <span title={`${c.name} · ${accessWords(c, a, writes)}`}>{c.name}</span>
              <button type="button" className="hub-swatch" aria-label={`Colour of ${c.name}`} aria-expanded={colouring === k} onClick={e => { e.preventDefault(); setColouring(colouring === k ? null : k); }} /></label>
            {colouring === k && <div className="hub-swatches" role="group" aria-label={`Choose a colour for ${c.name}`}>{(info?.colours ?? []).map(colour => (
              <button key={colour} type="button" className={`hub-swatch cal-${colour}`} aria-label={colour} aria-pressed={c.colour === colour} onClick={() => { setColouring(null); void setCalendar(c, { colour }); }} />))}</div>}
          </div>); })}
      </section>); })}
  </div>;

  const canCreate = writes && accounts.some(a => a.capabilities.event_write || a.capabilities.missing?.event_write);
  const searchForm = (own: boolean) => <form className={`hub-search${own ? ' hub-search-row' : ''}`} role="search" onSubmit={e => { e.preventDefault(); void search(); }}>
    <I.Search width={16} height={16} /><input className="input" type="search" placeholder="Search events" aria-label="Search events" value={typed} autoFocus={own}
      onChange={e => { setTyped(e.target.value); if (!e.target.value) setFound(null); }} onKeyDown={own ? e => { if (e.key === 'Escape') { e.stopPropagation(); endSearch(); } } : undefined} />
    {own && <button type="button" className="iconbtn small ghost" aria-label="Close search" onClick={endSearch}><I.Plus width={16} height={16} className="rot45" /></button>}</form>;
  // What a tight toolbar puts away: refreshing and the timezone. Moving through time, the views and New event always stay in reach.
  const more: MenuItem[] = [{ id: 'refresh', label: 'Refresh', icon: <I.Retry width={16} height={16} />, onSelect: () => { void refresh(); } },
    { id: 'zone', label: 'Change timezone', hint: zone.replace(/_/g, ' '), icon: <I.Clock width={16} height={16} />, onSelect: () => setZoneEdit(zone) }];
  // Three groups, so the toolbar can put them on two rows where one is too short: moving through time, the views, and the rest.
  const tools = <>
    <div className="cal-nav">
      <button type="button" className="btn small" onClick={() => { setFound(null); setAnchor(null); }}>Today</button>
      <button type="button" className="iconbtn small ghost" aria-label="Earlier" title={`Previous ${unit}`} onClick={() => step(-1)}><I.Chevron width={16} height={16} style={{ transform: 'rotate(180deg)' }} /></button>
      <button type="button" className="iconbtn small ghost" aria-label="Later" title={`Next ${unit}`} onClick={() => step(1)}><I.Chevron width={16} height={16} /></button>
    </div>
    <div className="seg hub-views" role="group" aria-label="View">{VIEWS.map(v => <button key={v.id} type="button" className="seg-item" aria-pressed={view === v.id && !found} onClick={() => { setFound(null); setView(v.id); }}>{v.label}</button>)}</div>
    <div className="cal-acts">
      {room === 'wide' ? searchForm(false)
        : <button type="button" className="iconbtn small ghost" aria-label="Search events" title="Search events" aria-expanded={searching} onClick={() => (searching ? endSearch() : setSearching(true))}><I.Search width={16} height={16} /></button>}
      {stacked ? <Menu label="More" align="end" items={more} trigger={({ open, props }) => <button type="button" className="iconbtn small ghost" aria-label="More" title="More" aria-expanded={open} {...props}><I.More width={16} height={16} /></button>} />
        : <button type="button" className="iconbtn small ghost" aria-label="Refresh" title="Refresh" onClick={refresh}><I.Retry width={16} height={16} /></button>}
      {canCreate && <button type="button" className="btn small primary cal-new" aria-label="New event" title={room === 'tiny' ? 'New event' : undefined} onClick={() => { setDone(null); setCreating(true); }}>
        <I.Plus width={15} height={15} />{room !== 'tiny' && <span>New event</span>}</button>}
    </div>
  </>;

  return (
    <Workspace title={<h1 className="wsp-title" aria-live="polite" title={heading}>{found ? `Events matching “${found.query}”` : stacked || room === 'medium' ? brief : heading}</h1>} tools={tools} fill context={context} contextLabel="Calendars"
      inspector={detail ? <Inspector event={detail} zone={zone} account={byAccount[detail.connection_id]} calendar={calendarOf(detail)} now={now} writes={writes} onCancel={cancelEvent} onRespond={respond}
        onChanged={(a, words) => { changed(a, words); if (detail) void open(detail); }} /> : null} inspectorLabel="Event" onInspectorClose={close} className={`hub-calendar cal-${room}${stacked ? ' cal-stacked' : ''}`}>
      <div className="wsp-body" ref={bodyRef}>
        {room !== 'wide' && (searching || !!found) && searchForm(true)}
        {(!stacked || zoneEdit !== null || !!days) && <div className="hub-cal-zone faint small">
          {zoneEdit === null ? stacked ? null : <><span>Times are shown in {zone.replace(/_/g, ' ')}{info?.settings.timezone ? '' : " (this device's timezone)"}.{writes ? '' : ' Read only for now.'}</span>
            <button type="button" className="btn small tertiary" onClick={() => setZoneEdit(zone)}>Change timezone</button></>
            : <><input className="input" list="hub-zones" aria-label="Timezone" value={zoneEdit} onChange={e => setZoneEdit(e.target.value)} />
              <datalist id="hub-zones">{((Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? []).map(z => <option key={z} value={z} />)}</datalist>
              <button type="button" className="btn small primary" onClick={() => saveZone(zoneEdit.trim())}>Save</button>
              <button type="button" className="btn small" onClick={() => saveZone(null)}>Use this device's</button>
              <button type="button" className="btn small tertiary" onClick={() => setZoneEdit(null)}>Cancel</button></>}
          {days && <span className="hub-range" role="status">Chosen: {rangeWords(days)} <button type="button" className="btn small tertiary" onClick={() => setDays(null)}>Clear</button></span>}
        </div>}
        {err && <p className="notice warning" role="alert">{err}</p>}
        {pendingMove && <div className="notice" role="alertdialog" aria-label="Move this event?">
          <p className="small">Move “{titleOf(pendingMove.event)}” to {dayTitle(dayKey(pendingMove.start, zone), 'short')}, {clock(pendingMove.start, zone)} to {clock(pendingMove.end, zone)}?
            {pendingMove.others ? ` ${pendingMove.others} ${pendingMove.others === 1 ? 'person is' : 'people are'} told.` : ''}</p>
          {pendingMove.event.series_id && <SeriesScope name="move-scope" value={moveScope} onChange={setMoveScope} legend="This event repeats. Which events should move?" />}
          <button type="button" className="btn small" disabled={!!pendingMove.event.series_id && !moveScope} onClick={() => applyMove(pendingMove.event, pendingMove.start, pendingMove.end, moveScope ?? undefined)}>Move it</button>
          <button type="button" className="btn small tertiary" onClick={() => { setPendingMove(null); setMoveScope(null); }}>Keep it</button></div>}
        {done && <p className="notice" role="status">{done.words}{done.action.can_undo && done.words !== 'Undone.' && <> <button type="button" className="btn small tertiary" onClick={undo}>Undo</button></>}</p>}
        {proposals.map(p => <p key={p.id} className="notice" role="status">Suggested times for “{p.title || 'a meeting'}” with {p.attendees.join(', ')}: {p.options.map((o, i) =>
          <button key={o.start} type="button" className="btn small tertiary" onClick={() => { setDone(null); setPicking({ proposal: p, option: o }); }}>{i ? ', ' : ''}{dayTitle(o.start.slice(0, 10), 'short')} {clock(o.start_epoch, zone)}</button>)}
          {p.waiting && <span className="faint"> · Waiting for {p.external.join(', ')} to answer</span>}
          {' '}<button type="button" className="btn small tertiary" onClick={async () => { try { await hub.closeProposal(p.id, 'dismissed'); setProposals(v => v.filter(x => x.id !== p.id)); } catch (e) { setErr(failed(e)); } }}>Dismiss</button></p>)}
        {picking && <EventEditor accounts={accounts} calendars={calendars} day={day} initial={{ connection: picking.proposal.connection_id, title: picking.proposal.title, start: picking.option.start, end: picking.option.end, attendees: picking.proposal.attendees }}
          onDone={async a => { const id = picking.proposal.id; setPicking(null); setProposals(v => v.filter(x => x.id !== id)); try { await hub.closeProposal(id, 'picked'); } catch { /* the event exists; the suggestion is only drawn */ } changed(a, 'The event was created.'); }}
          onCancel={() => setPicking(null)} />}
        {creating && <EventEditor accounts={accounts} calendars={calendars} day={day} onDone={a => changed(a, 'The event was created.')} onCancel={() => setCreating(false)} />}
        {connectNote && <p className="notice warning" role="status">{connectNote}</p>}
        {choosingAccount && <ChooseAccess account={choosingAccount} onDone={doneChoosing} onCancel={() => { setChoosing(null); setParams({}, { replace: true }); }} />}
        {needing.map(a => <p key={a.id} className="notice warning" role="status">{a.identity} needs you. What was loaded before is still shown. <Link to="/settings?tab=access">Open Access</Link></p>)}
        {filling.length > 0 && <p className="notice" role="status">Loading {filling.map(c => c.name).join(', ')} for the first time.</p>}
        {partial && <p className="notice" role="status">There are more events in this range than can be shown at once. Choose a shorter range.</p>}

        {info && !accounts.length ? (
          <EmptyState title="No calendar is connected" action={<AddAccount providers={info.providers ?? []} primary />}>Connect an account and choose which calendars Lumina may read. They show up here.</EmptyState>
        ) : events === null ? <div className="hub-loading" role="status"><div className="skeleton" style={{ height: 320 }} /><span className="sr">Loading…</span></div>
        : found ? <div className="hub-agenda">{found.events.length ? agendaRows(list(found.events, [...new Set(found.events.flatMap(e => eventDays(e, zone, '0000-01-01', '9999-12-31').slice(0, 1)))].sort()))
            : <div className="empty">No event matches “{found.query}”.</div>}
            {!found.complete && <p className="faint small">These are the closest matches. There are more.</p>}</div>
        : view === 'agenda' ? <div className="hub-agenda">{agendaRows(list(events, span.days)).length ? agendaRows(list(events, span.days)) : <div className="empty">Nothing in these 30 days.</div>}</div>
        : view === 'month' ? (
          <div className="hub-month" role="grid" aria-label={heading}>
            {span.days.slice(0, 7).map(d => <div key={'h' + d} className="hub-month-head" role="columnheader">{dayTitle(d, 'weekday')}</div>)}
            {span.days.map(d => { const items = [...byDay[d].allDay, ...byDay[d].timed.sort((a, b) => a.start_epoch - b.start_epoch)]; return (
              <div key={d} role="gridcell" className={`hub-month-cell${d === today ? ' today' : ''}${d.slice(0, 7) !== day.slice(0, 7) ? ' other' : ''}${days && d >= days.start && d <= days.end ? ' chosen' : ''}`}>
                <button type="button" aria-label={dayTitle(d)} {...dayProps(d, () => { setAnchor(d); setView('day'); })}>{Number(d.slice(8))}</button>
                {items.slice(0, 3).map(e => <EventChip key={eventKey(e)} event={e} zone={zone} current={selected === eventKey(e)} onOpen={open} block />)}
                {items.length > 3 && <button type="button" className="hub-more" onClick={() => { setAnchor(d); setView('day'); }}>{items.length - 3} more</button>}
              </div>); })}
          </div>
        ) : (
          <div className={`hub-week ${view}`} ref={gridRef} onScroll={e => { kept.current = { key: showing.current, top: e.currentTarget.scrollTop, left: e.currentTarget.scrollLeft }; }}
            style={{ ['--days' as string]: span.days.length, ['--hour' as string]: `${HOUR}px`, ['--gutter' as string]: `${GUTTER}px`, ['--day-min' as string]: `${view === 'week' ? DAY_MIN : 0}px` }}>
            <div className="hub-week-corner" />
            {span.days.map(d => <div key={'d' + d} data-col={d} className={`hub-week-day${d === today ? ' today' : ''}${days && d >= days.start && d <= days.end ? ' chosen' : ''}`}>
              <button type="button" aria-label={dayTitle(d)} {...dayProps(d, () => { setAnchor(d); setView('day'); })}><span>{dayTitle(d, 'weekday')}</span><b>{Number(d.slice(8))}</b></button></div>)}
            <div className="hub-week-allday gutter">all day</div>
            {span.days.map(d => { const all = byDay[d].allDay; const fits = all.length <= allDayRows ? all : all.slice(0, allDayRows - 1); return (
              <div key={'a' + d} className="hub-week-allday" aria-label={`All day, ${dayTitle(d)}`}>
                {fits.map(e => <EventChip key={eventKey(e)} event={e} zone={zone} current={selected === eventKey(e)} onOpen={open} block />)}
                {all.length > fits.length && <MoreEvents events={all} count={all.length - fits.length} zone={zone} onOpen={open} label={`${all.length - fits.length} more all day on ${dayTitle(d)}. Show all ${all.length}`}
                  heading={`All day · ${dayTitle(d)}`} />}</div>); })}
            <div className="hub-hours" aria-hidden="true">{HOURS.map(h => <span key={h} style={{ top: `calc(var(--hour) * ${h})` }}>{hourLabel(h)}</span>)}</div>
            {span.days.map(d => { const { shown, more: folded } = foldDay(layoutDay(byDay[d].timed, d, zone, LABEL), fit, lanes); return (
              <div key={'c' + d} className={`hub-day-col${days && d >= days.start && d <= days.end ? ' chosen' : ''}`} aria-label={dayTitle(d)}>
                {d === today && <i className="hub-now" style={{ top: `calc(var(--hour) * ${minuteOfDay(now, zone) / 60})` }} aria-label="Now" role="img" />}
                {proposals.flatMap(p => p.options.filter(o => dayKey(o.start_epoch, zone) === d).map(o => <button key={p.id + o.start} type="button" className="hub-suggestion"
                  aria-label={`Suggested time for ${p.title || 'a meeting'}, ${clock(o.start_epoch, zone)}`} onClick={() => { setDone(null); setPicking({ proposal: p, option: o }); }}
                  style={{ top: `calc(var(--hour) * ${minuteOfDay(o.start_epoch, zone) / 60})`, height: `calc(var(--hour) * ${(o.end_epoch - o.start_epoch) / 3600} - 2px)` }}>
                  <b>{p.title || 'Suggested time'}</b><span>{clock(o.start_epoch, zone)}</span></button>))}
                {shown.map(p => <EventChip key={eventKey(p.event)} event={p.event} zone={zone} current={selected === eventKey(p.event)} onOpen={openUnlessDragged}
                  onPress={movable(p.event) ? onPress : undefined} shift={moving?.key === eventKey(p.event) ? moving : undefined}
                  brief={(p.height * HOUR) / 60 < 2 * LINE - 4} point={p.point} length={p.length}
                  style={{ top: `min(calc(var(--hour) * ${p.top / 60}), calc(100% - max(1lh + 4px, ${LINE}px)))`, height: `calc(var(--hour) * ${p.height / 60} - 2px)`,
                    ...(p.folded ? { left: `calc((100% - ${FOLD}px) * ${p.column / p.columns} + 2px)`, width: `calc((100% - ${FOLD}px) * ${p.span / p.columns} - 4px)` }
                      : { left: `calc(${(p.column / p.columns) * 100}% + 2px)`, width: `calc(${(p.span / p.columns) * 100}% - 4px)` }) }} />)}
                {folded.map(f => <MoreEvents key={f.key} events={f.events} count={f.events.length} zone={zone} onOpen={open} className="timed"
                  label={`${f.events.length} more ${f.events.length === 1 ? 'event' : 'events'} on ${dayTitle(d)} from ${clock(f.events[0].start_epoch, zone)}`} heading={`${dayTitle(d, 'short')} · from ${clock(f.events[0].start_epoch, zone)}`}
                  style={{ top: `calc(var(--hour) * ${f.top / 60})`, height: `calc(var(--hour) * ${f.height / 60} - 2px)`, left: `calc(100% - ${FOLD}px)`, width: `${FOLD - 2}px` }} />)}
              </div>); })}
          </div>)}
      </div>
    </Workspace>);
}
