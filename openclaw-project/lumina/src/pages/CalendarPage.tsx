import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as I from '../components/Icons';
import Accounts from '../components/hub/Accounts';
import Workspace from '../components/frame/Workspace';
import { EmptyState } from '../components/frame/parts';
import { useSelection, type Action, type Looking } from '../components/frame/Assistant';
import { useCommands } from '../components/frame/CommandBar';
import { usePulse } from '../components/hub/usePulse';
import { AddAccount, ChooseAccess, CONNECT_NOTE } from '../components/hub/Connect';
import AllowChanges from '../components/hub/AllowChanges';
import EventEditor from '../components/hub/EventEditor';
import { addDays, addMonths, ago, browserZone, clock, dayKey, dayTitle, eventDays, eventKey, eventTime, failed, hub, layoutDay, minuteOfDay, personName, rangeTitle, startOfMonth, startOfWeek,
  validZone, zonedEpoch, type HubAccount, type HubAction, type HubCalendar, type HubEvent, type Overview } from '../lib/hub';
import { useData } from '../state/data';
import '../styles/hub.css';

type View = 'day' | 'week' | 'month' | 'agenda';
const VIEWS: { id: View; label: string }[] = [{ id: 'day', label: 'Day' }, { id: 'week', label: 'Week' }, { id: 'month', label: 'Month' }, { id: 'agenda', label: 'Agenda' }];
const RESPONSE: Record<string, string> = { accepted: 'Going', declined: 'Not going', tentative: 'Maybe', needs_action: 'Not answered' };
const ACCESS: Record<string, string> = { busy: 'Shows only when you are busy', read: 'Read only', write: 'Read only here', owner: 'Read only here' };
const HOURS = Array.from({ length: 23 }, (_, i) => i + 1);
const nowSeconds = () => Math.floor(Date.now() / 1000);
const hourLabel = (h: number) => `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? 'AM' : 'PM'}`;
const titleOf = (e: HubEvent) => (e.busy_only ? 'Busy' : e.title || '(no title)');

function range(view: View, anchor: string): { from: string; to: string; days: string[] } {
  const from = view === 'week' ? startOfWeek(anchor) : view === 'month' ? startOfWeek(startOfMonth(anchor)) : anchor;
  const count = view === 'day' ? 1 : view === 'week' ? 7 : view === 'month' ? 42 : 30;
  const days = Array.from({ length: count }, (_, i) => addDays(from, i));
  return { from, to: days[days.length - 1], days };
}

function EventChip({ event, zone, current, onOpen, block, style }: { event: HubEvent; zone: string; current: boolean; onOpen(e: HubEvent): void; block?: boolean; style?: React.CSSProperties }) {
  const when = event.all_day ? 'all day' : clock(event.start_epoch, zone);
  return (
    <button type="button" className={`hub-event cal-${event.colour}${block ? ' block' : ''}${event.my_response === 'declined' ? ' declined' : ''}${event.my_response === 'tentative' ? ' tentative' : ''}`}
      style={style} aria-current={current ? 'true' : undefined} aria-label={`${titleOf(event)}, ${when}`} title={`${titleOf(event)} · ${when}`} onClick={() => onOpen(event)}>
      <b>{titleOf(event)}</b>{!block && !event.all_day && <span>{clock(event.start_epoch, zone)}</span>}
    </button>);
}

/** What the inspector shows for one event: when (in the customer's timezone, and the event's own when that differs), where, who and their answers, the notes, which account
 *  and calendar it is from, and how fresh it is. An event that is only visible as busy shows nothing else. Nothing here changes the event. */
function Inspector({ event, zone, account, calendar, now, writes, onCancel }: { event: HubEvent; zone: string; account?: HubAccount; calendar?: HubCalendar; now: number;
  writes: boolean; onCancel(e: HubEvent, notify: boolean): Promise<void> }) {
  const [asking, setAsking] = useState(false); const [busy, setBusy] = useState(false);
  // Cancelling (#63) is offered for an event the customer organizes, in a calendar this account may change, when changes are allowed for it. Others are told how many.
  const mine = !!account && (!event.organizer || event.organizer.address === account.identity || !!event.attendees?.find(a => a.self && a.address === event.organizer?.address));
  const changeable = writes && !!account?.capabilities.event_write && (calendar?.access === 'owner' || calendar?.access === 'write') && !event.busy_only && !event.cancelled && !event.series_id && mine;
  const others = (event.attendees ?? []).filter(a => !a.self).length;
  return (
    <section className={`hub-inspector cal-${event.colour}`} aria-label="Event details">
      <header><h2>{titleOf(event)}</h2></header>
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
      {changeable && (!asking ? <p><button type="button" className="btn small" onClick={() => setAsking(true)}>Cancel event</button></p>
        : <div className="notice" role="alertdialog" aria-label="Cancel this event?"><p className="small">{others ? `${others} ${others === 1 ? 'person is' : 'people are'} told it is cancelled.` : 'Nobody else is invited.'} You can undo it afterwards.</p>
          <button type="button" className="btn small" disabled={busy} onClick={async () => { setBusy(true); try { await onCancel(event, true); } finally { setBusy(false); setAsking(false); } }}>Cancel it</button>
          <button type="button" className="btn small tertiary" disabled={busy} onClick={() => setAsking(false)}>Keep it</button></div>)}
      {writes && account && !account.capabilities.event_write && <AllowChanges account={account} capability="event_write" />}
      <p className="faint small">{calendar ? (changeable || (writes && account?.capabilities.event_write && (calendar.access === 'owner' || calendar.access === 'write')) ? 'You can change this calendar' : ACCESS[calendar.access]) : 'Read only'} · Updated {ago(event.synced_epoch, now)}.
        {event.provider_url && account && <> <a href={event.provider_url} target="_blank" rel="noopener noreferrer">Open in {account.provider_label}</a></>}</p>
    </section>);
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
  const [typed, setTyped] = useState(''); const [found, setFound] = useState<{ query: string; events: HubEvent[]; complete: boolean } | null>(null);
  const [zoneEdit, setZoneEdit] = useState<string | null>(null); const [colouring, setColouring] = useState<string | null>(null);
  const request = useRef(0); const grid = useRef<HTMLDivElement>(null);
  // A range of days chosen by dragging across the day headings, or from the keyboard (Shift with the arrows). It only tells the assistant "these days" in this phase.
  const [days, setDays] = useState<{ start: string; end: string } | null>(null); const drag = useRef<{ from: string; moved: boolean } | null>(null);
  useEffect(() => { const up = () => { drag.current = drag.current && { ...drag.current, from: '' }; }; window.addEventListener('pointerup', up); return () => window.removeEventListener('pointerup', up); }, []);
  useEffect(() => { const t = window.setInterval(() => { if (document.visibilityState === 'visible') setNow(nowSeconds()); }, 60000); return () => window.clearInterval(t); }, []);   // the current time line moves
  const [params, setParams] = useSearchParams(); const [choosing, setChoosing] = useState<string | null>(params.get('connected'));
  const connectNote = CONNECT_NOTE[params.get('connect') ?? ''];
  const doneChoosing = () => { setChoosing(null); setParams({}, { replace: true }); window.setTimeout(() => { void loadInfo(); void load(); }, 1200); };

  const zone = useMemo(() => (info?.settings.timezone && validZone(info.settings.timezone) ? info.settings.timezone : browserZone()), [info?.settings.timezone]);
  const today = dayKey(now, zone); const day = anchor ?? today;
  const accounts = useMemo(() => (info?.accounts ?? []).filter(a => a.capabilities.calendar), [info]);
  const byAccount = useMemo(() => Object.fromEntries(accounts.map(a => [a.id, a])) as Record<string, HubAccount>, [accounts]);
  const calendars = info?.calendars ?? [];
  const calendarOf = useCallback((e: HubEvent) => calendars.find(c => c.connection_id === e.connection_id && c.id === e.calendar_id), [calendars]);
  const shownAccounts = useMemo(() => accounts.filter(a => !chosen || chosen.has(a.id)).map(a => a.id), [accounts, chosen]);
  const span = useMemo(() => range(view, day), [view, day]);

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
    } catch (e) { if (mine === request.current) { setErr(failed(e)); setEvents(prev => prev ?? []); } }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!info, span.from, span.to, zone, shownAccounts.join(','), selection]);
  useEffect(() => { void load(); }, [load]);
  usePulse(on, () => { void loadInfo(); void load(); });      // live: when anything changed at the server, the calendars and the events on screen are loaded again, quietly
  // The grid opens at the current hour when today is on screen (an hour above it, for context), at 7 in the morning otherwise.
  useEffect(() => {
    if ((view !== 'week' && view !== 'day') || !grid.current || typeof grid.current.scrollTo !== 'function') return;
    const hour = span.days.includes(today) ? Math.max(0, Math.floor(minuteOfDay(nowSeconds(), zone) / 60) - 1) : 7;
    grid.current.scrollTo({ top: hour * 44 });
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
  const cancelEvent = async (e: HubEvent, notify: boolean) => {
    try { const r = await hub.cancelEvent(e.connection_id, e.calendar_id, e.id, notify); if (r.action.state === 'done') { changed(r.action, `"${titleOf(e)}" was cancelled.`); close(); } else setErr(r.action.ended_words || 'The event was not cancelled.'); }
    catch (error) { setErr(failed(error)); }
  };
  const undo = async () => {
    if (!done) return;
    try { const r = await hub.undo(done.action.id); setDone(r.action.state === 'done' ? { action: r.action, words: 'Undone.' } : null); if (r.action.state !== 'done') setErr(r.action.ended_words || 'It could not be undone.'); void refresh(); }
    catch (error) { setErr(failed(error)); }
  };
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
    {accounts.filter(a => shownAccounts.includes(a.id)).map(a => { const mine = calendars.filter(c => c.connection_id === a.id); return !mine.length ? null : (
      <section key={a.id} className="hub-calendars" aria-label={`Calendars of ${a.identity}`}>
        <h2 className="hub-side-title" title={a.identity}>{a.identity}</h2>
        {mine.map(c => { const k = c.connection_id + c.id; return (
          <div key={k} className={`cal-${c.colour}`}>
            <label className="hub-calendar-row"><input type="checkbox" checked={c.selected} onChange={e => setCalendar(c, { selected: e.target.checked })} />
              <span title={`${c.name} · ${ACCESS[c.access]}`}>{c.name}</span>
              <button type="button" className="hub-swatch" aria-label={`Colour of ${c.name}`} aria-expanded={colouring === k} onClick={e => { e.preventDefault(); setColouring(colouring === k ? null : k); }} /></label>
            {colouring === k && <div className="hub-swatches" role="group" aria-label={`Choose a colour for ${c.name}`}>{(info?.colours ?? []).map(colour => (
              <button key={colour} type="button" className={`hub-swatch cal-${colour}`} aria-label={colour} aria-pressed={c.colour === colour} onClick={() => { setColouring(null); void setCalendar(c, { colour }); }} />))}</div>}
          </div>); })}
      </section>); })}
  </div>;

  const tools = <>
    <button type="button" className="btn small" onClick={() => { setFound(null); setAnchor(null); }}>Today</button>
    <button type="button" className="iconbtn small ghost" aria-label="Earlier" onClick={() => step(-1)}><I.Chevron width={16} height={16} style={{ transform: 'rotate(180deg)' }} /></button>
    <button type="button" className="iconbtn small ghost" aria-label="Later" onClick={() => step(1)}><I.Chevron width={16} height={16} /></button>
    <div className="seg hub-views" role="group" aria-label="View">{VIEWS.map(v => <button key={v.id} type="button" className="seg-item" aria-pressed={view === v.id && !found} onClick={() => { setFound(null); setView(v.id); }}>{v.label}</button>)}</div>
    <form className="hub-search" role="search" onSubmit={e => { e.preventDefault(); void search(); }}>
      <I.Search width={16} height={16} /><input className="input" type="search" placeholder="Search events" aria-label="Search events" value={typed} onChange={e => { setTyped(e.target.value); if (!e.target.value) setFound(null); }} /></form>
    <button type="button" className="iconbtn small ghost" aria-label="Refresh" title="Refresh" onClick={refresh}><I.Retry width={16} height={16} /></button>
    {writes && accounts.some(a => a.capabilities.event_write || a.capabilities.missing?.event_write) && <button type="button" className="btn small" onClick={() => { setDone(null); setCreating(true); }}>New event</button>}
  </>;

  return (
    <Workspace title={<h1 className="wsp-title" aria-live="polite">{found ? `Events matching “${found.query}”` : heading}</h1>} tools={tools} fill context={context} contextLabel="Calendars"
      inspector={detail ? <Inspector event={detail} zone={zone} account={byAccount[detail.connection_id]} calendar={calendarOf(detail)} now={now} writes={writes} onCancel={cancelEvent} /> : null} inspectorLabel="Event" onInspectorClose={close} className="hub-calendar">
      <div className="wsp-body">
        <div className="hub-cal-zone faint small">
          {zoneEdit === null ? <><span>Times are shown in {zone.replace(/_/g, ' ')}{info?.settings.timezone ? '' : " (this device's timezone)"}.{writes ? '' : ' Read only for now.'}</span>
            <button type="button" className="btn small tertiary" onClick={() => setZoneEdit(zone)}>Change timezone</button></>
            : <><input className="input" list="hub-zones" aria-label="Timezone" value={zoneEdit} onChange={e => setZoneEdit(e.target.value)} />
              <datalist id="hub-zones">{((Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? []).map(z => <option key={z} value={z} />)}</datalist>
              <button type="button" className="btn small primary" onClick={() => saveZone(zoneEdit.trim())}>Save</button>
              <button type="button" className="btn small" onClick={() => saveZone(null)}>Use this device's</button>
              <button type="button" className="btn small tertiary" onClick={() => setZoneEdit(null)}>Cancel</button></>}
          {days && <span className="hub-range" role="status">Chosen: {rangeWords(days)} <button type="button" className="btn small tertiary" onClick={() => setDays(null)}>Clear</button></span>}
        </div>
        {err && <p className="notice warning" role="alert">{err}</p>}
        {done && <p className="notice" role="status">{done.words}{done.action.can_undo && done.words !== 'Undone.' && <> <button type="button" className="btn small tertiary" onClick={undo}>Undo</button></>}</p>}
        {creating && (accounts.some(a => a.capabilities.event_write)
          ? <EventEditor accounts={accounts} calendars={calendars} day={day} onDone={a => changed(a, 'The event was created.')} onCancel={() => setCreating(false)} />
          : accounts.filter(a => a.capabilities.missing?.event_write).map(a => <AllowChanges key={a.id} account={a} capability="event_write" />))}
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
          <div className="hub-week" ref={grid} style={{ ['--days' as string]: span.days.length, ['--hour' as string]: '44px' }}>
            <div className="hub-week-corner" />
            {span.days.map(d => <div key={'d' + d} className={`hub-week-day${d === today ? ' today' : ''}${days && d >= days.start && d <= days.end ? ' chosen' : ''}`}><button type="button" aria-label={dayTitle(d)} {...dayProps(d, () => { setAnchor(d); setView('day'); })}>{dayTitle(d, 'short')}</button></div>)}
            <div className="hub-week-allday gutter">all day</div>
            {span.days.map(d => <div key={'a' + d} className="hub-week-allday" aria-label={`All day, ${dayTitle(d)}`}>
              {byDay[d].allDay.map(e => <EventChip key={eventKey(e)} event={e} zone={zone} current={selected === eventKey(e)} onOpen={open} block />)}</div>)}
            <div className="hub-hours" aria-hidden="true">{HOURS.map(h => <span key={h} style={{ top: `calc(var(--hour) * ${h})` }}>{hourLabel(h)}</span>)}</div>
            {span.days.map(d => <div key={'c' + d} className={`hub-day-col${days && d >= days.start && d <= days.end ? ' chosen' : ''}`} aria-label={dayTitle(d)}>
              {d === today && <i className="hub-now" style={{ top: `calc(var(--hour) * ${minuteOfDay(now, zone) / 60})` }} aria-label="Now" role="img" />}
              {layoutDay(byDay[d].timed, d, zone).map(p => <EventChip key={eventKey(p.event)} event={p.event} zone={zone} current={selected === eventKey(p.event)} onOpen={open}
                style={{ top: `calc(var(--hour) * ${p.top / 60})`, height: `calc(var(--hour) * ${p.height / 60} - 2px)`, left: `calc(${(p.column / p.columns) * 100}% + 2px)`, width: `calc(${100 / p.columns}% - 4px)` }} />)}
            </div>)}
          </div>)}
      </div>
    </Workspace>);
}
