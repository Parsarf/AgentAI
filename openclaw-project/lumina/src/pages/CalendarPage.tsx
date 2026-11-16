import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as I from '../components/Icons';
import Accounts from '../components/hub/Accounts';
import { AddAccount, ChooseAccess, CONNECT_NOTE } from '../components/hub/Connect';
import { addDays, addMonths, ago, browserZone, clock, dayKey, dayTitle, eventDays, eventKey, eventTime, failed, hub, layoutDay, minuteOfDay, personName, rangeTitle, startOfMonth, startOfWeek,
  validZone, zonedEpoch, type HubAccount, type HubCalendar, type HubEvent, type Overview } from '../lib/hub';
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
function Inspector({ event, zone, account, calendar, now, onClose }: { event: HubEvent; zone: string; account?: HubAccount; calendar?: HubCalendar; now: number; onClose(): void }) {
  return (
    <aside className={`hub-open hub-inspector panel cal-${event.colour}`} aria-label="Event">
      <header style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <h2 style={{ flex: 1 }}>{titleOf(event)}</h2>
        <button type="button" className="iconbtn small ghost" aria-label="Close" onClick={onClose}><I.Plus width={16} height={16} style={{ transform: 'rotate(45deg)' }} /></button>
      </header>
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
      <p className="faint small">{calendar ? ACCESS[calendar.access] : 'Read only'} · Updated {ago(event.synced_epoch, now)}.
        {event.provider_url && account && <> <a href={event.provider_url} target="_blank" rel="noopener noreferrer">Open in {account.provider_label}</a></>}</p>
    </aside>);
}

/** The Calendar: every selected calendar of every connected account together, in the customer's timezone. Left: accounts and calendars. Middle: day, week, month or agenda.
 *  Right: the event that is open. Read-only in this phase: nothing here creates, moves or answers an event. */
export default function CalendarPage() {
  const { app } = useData(); const on = !!app?.features.dashboard;
  const [info, setInfo] = useState<Overview | null>(null); const [err, setErr] = useState(''); const [now, setNow] = useState(nowSeconds);
  const [view, setView] = useState<View>('week'); const [anchor, setAnchor] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Set<string> | null>(null); const [events, setEvents] = useState<HubEvent[] | null>(null); const [partial, setPartial] = useState(false);
  const [selected, setSelected] = useState<string | null>(null); const [detail, setDetail] = useState<HubEvent | null>(null);
  const [typed, setTyped] = useState(''); const [found, setFound] = useState<{ query: string; events: HubEvent[]; complete: boolean } | null>(null);
  const [zoneEdit, setZoneEdit] = useState<string | null>(null); const [colouring, setColouring] = useState<string | null>(null);
  const request = useRef(0); const grid = useRef<HTMLDivElement>(null);
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
  useEffect(() => { if ((view === 'week' || view === 'day') && grid.current && typeof grid.current.scrollTo === 'function') grid.current.scrollTo({ top: 7 * 44 }); }, [view, events === null]);

  const open = useCallback(async (e: HubEvent) => {
    setSelected(eventKey(e)); setDetail(e);
    try { const r = await hub.event(e.connection_id, e.calendar_id, e.id); setDetail(d => (d && eventKey(d) === eventKey(e) ? { ...e, ...r.event } : d)); }
    catch (error) { setErr(failed(error)); }
  }, []);
  const close = () => { setSelected(null); setDetail(null); };
  const step = (n: number) => setAnchor(view === 'month' ? addMonths(day, n) : addDays(day, n * (view === 'week' ? 7 : view === 'agenda' ? 30 : 1)));
  const refresh = async () => { try { await hub.refresh(); } catch (e) { setErr(failed(e)); } window.setTimeout(() => { void loadInfo(); void load(); }, 1500); };
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
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'Escape' && selected) close();
      else if (e.key === 't') setAnchor(null);
      else if (e.key === 'ArrowLeft') step(-1);
      else if (e.key === 'ArrowRight') step(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, view, day]);

  const byDay = useMemo(() => {
    const out: Record<string, { allDay: HubEvent[]; timed: HubEvent[] }> = Object.fromEntries(span.days.map(d => [d, { allDay: [], timed: [] }]));
    for (const e of events ?? []) for (const d of eventDays(e, zone, span.from, span.to)) (e.all_day ? out[d].allDay : out[d].timed).push(e);
    return out;
  }, [events, span, zone]);

  if (!on) return (
    <div className="center"><h1 className="page-title">Calendar</h1><section className="panel card"><h2>Not available yet</h2>
      <p className="muted" style={{ marginTop: 8 }}>The calendars of your connected accounts in one place, with your assistant beside them.</p>
      <p style={{ marginTop: 16 }}><Link className="btn" to="/">Back to Home</Link></p></section></div>);

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

  return (
    <div className={`hub hub-calendar${detail ? ' has-open' : ''}`}>
      <aside className="hub-side panel" aria-label="Calendars">
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
      </aside>

      <section className="hub-cal panel" aria-label="Calendar">
        <header className="hub-cal-bar">
          <button type="button" className="btn small" onClick={() => setAnchor(null)}>Today</button>
          <button type="button" className="iconbtn small ghost" aria-label="Earlier" onClick={() => step(-1)}><I.Chevron width={16} height={16} style={{ transform: 'rotate(180deg)' }} /></button>
          <button type="button" className="iconbtn small ghost" aria-label="Later" onClick={() => step(1)}><I.Chevron width={16} height={16} /></button>
          <h1 aria-live="polite">{found ? `Events matching “${found.query}”` : heading}</h1>
          <div className="seg" role="group" aria-label="View">{VIEWS.map(v => <button key={v.id} type="button" className="seg-item" aria-pressed={view === v.id && !found} onClick={() => { setFound(null); setView(v.id); }}>{v.label}</button>)}</div>
          <form className="hub-search" role="search" onSubmit={e => { e.preventDefault(); void search(); }}>
            <I.Search width={16} height={16} /><input className="input" type="search" placeholder="Search events" aria-label="Search events" value={typed} onChange={e => { setTyped(e.target.value); if (!e.target.value) setFound(null); }} /></form>
          <button type="button" className="iconbtn small ghost" aria-label="Refresh" title="Refresh" onClick={refresh}><I.Retry width={16} height={16} /></button>
        </header>
        <div className="hub-cal-zone faint small">
          {zoneEdit === null ? <><span>Times are shown in {zone.replace(/_/g, ' ')}{info?.settings.timezone ? '' : " (this device's timezone)"}. Read only for now.</span>
            <button type="button" className="btn small tertiary" onClick={() => setZoneEdit(zone)}>Change timezone</button></>
            : <><input className="input" list="hub-zones" aria-label="Timezone" value={zoneEdit} onChange={e => setZoneEdit(e.target.value)} />
              <datalist id="hub-zones">{((Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? []).map(z => <option key={z} value={z} />)}</datalist>
              <button type="button" className="btn small primary" onClick={() => saveZone(zoneEdit.trim())}>Save</button>
              <button type="button" className="btn small" onClick={() => saveZone(null)}>Use this device's</button>
              <button type="button" className="btn small tertiary" onClick={() => setZoneEdit(null)}>Cancel</button></>}
        </div>
        {err && <p className="notice warning" role="alert">{err}</p>}
        {connectNote && <p className="notice warning" role="status">{connectNote}</p>}
        {choosingAccount && <ChooseAccess account={choosingAccount} onDone={doneChoosing} onCancel={() => { setChoosing(null); setParams({}, { replace: true }); }} />}
        {needing.map(a => <p key={a.id} className="notice warning" role="status">{a.identity} needs you. What was loaded before is still shown. <Link to="/settings?tab=access">Open Access</Link></p>)}
        {filling.length > 0 && <p className="notice" role="status">Loading {filling.map(c => c.name).join(', ')} for the first time.</p>}
        {partial && <p className="notice" role="status">There are more events in this range than can be shown at once. Choose a shorter range.</p>}

        {info && !accounts.length ? (
          <div className="empty"><b>No calendar is connected</b><p className="muted">Connect an account and choose which calendars Lumina may read. They show up here.</p>
            <AddAccount providers={info.providers ?? []} primary /></div>
        ) : events === null ? <p className="muted hub-pad" role="status">Loading…</p>
        : found ? <div className="hub-agenda">{found.events.length ? agendaRows(list(found.events, [...new Set(found.events.flatMap(e => eventDays(e, zone, '0000-01-01', '9999-12-31').slice(0, 1)))].sort()))
            : <div className="empty">No event from last month to a year ahead matches “{found.query}”.</div>}
            {!found.complete && <p className="faint small">These are the closest matches. There are more.</p>}</div>
        : view === 'agenda' ? <div className="hub-agenda">{agendaRows(list(events, span.days)).length ? agendaRows(list(events, span.days)) : <div className="empty">Nothing in these 30 days.</div>}</div>
        : view === 'month' ? (
          <div className="hub-month" role="grid" aria-label={heading}>
            {span.days.slice(0, 7).map(d => <div key={'h' + d} className="hub-month-head" role="columnheader">{dayTitle(d, 'weekday')}</div>)}
            {span.days.map(d => { const items = [...byDay[d].allDay, ...byDay[d].timed.sort((a, b) => a.start_epoch - b.start_epoch)]; return (
              <div key={d} role="gridcell" className={`hub-month-cell${d === today ? ' today' : ''}${d.slice(0, 7) !== day.slice(0, 7) ? ' other' : ''}`}>
                <button type="button" aria-label={dayTitle(d)} onClick={() => { setAnchor(d); setView('day'); }}>{Number(d.slice(8))}</button>
                {items.slice(0, 3).map(e => <EventChip key={eventKey(e)} event={e} zone={zone} current={selected === eventKey(e)} onOpen={open} block />)}
                {items.length > 3 && <button type="button" className="hub-more" onClick={() => { setAnchor(d); setView('day'); }}>{items.length - 3} more</button>}
              </div>); })}
          </div>
        ) : (
          <div className="hub-week" ref={grid} style={{ ['--days' as string]: span.days.length, ['--hour' as string]: '44px' }}>
            <div className="hub-week-corner" />
            {span.days.map(d => <div key={'d' + d} className={`hub-week-day${d === today ? ' today' : ''}`}><button type="button" aria-label={dayTitle(d)} onClick={() => { setAnchor(d); setView('day'); }}>{dayTitle(d, 'short')}</button></div>)}
            <div className="hub-week-allday gutter">all day</div>
            {span.days.map(d => <div key={'a' + d} className="hub-week-allday" aria-label={`All day, ${dayTitle(d)}`}>
              {byDay[d].allDay.map(e => <EventChip key={eventKey(e)} event={e} zone={zone} current={selected === eventKey(e)} onOpen={open} block />)}</div>)}
            <div className="hub-hours" aria-hidden="true">{HOURS.map(h => <span key={h} style={{ top: `calc(var(--hour) * ${h})` }}>{hourLabel(h)}</span>)}</div>
            {span.days.map(d => <div key={'c' + d} className="hub-day-col" aria-label={dayTitle(d)}>
              {d === today && <i className="hub-now" style={{ top: `calc(var(--hour) * ${minuteOfDay(now, zone) / 60})` }} aria-label="Now" role="img" />}
              {layoutDay(byDay[d].timed, d, zone).map(p => <EventChip key={eventKey(p.event)} event={p.event} zone={zone} current={selected === eventKey(p.event)} onOpen={open}
                style={{ top: `calc(var(--hour) * ${p.top / 60})`, height: `calc(var(--hour) * ${p.height / 60} - 2px)`, left: `calc(${(p.column / p.columns) * 100}% + 2px)`, width: `calc(${100 / p.columns}% - 4px)` }} />)}
            </div>)}
          </div>)}
      </section>

      {detail && <Inspector event={detail} zone={zone} account={byAccount[detail.connection_id]} calendar={calendarOf(detail)} now={now} onClose={close} />}
    </div>);
}
