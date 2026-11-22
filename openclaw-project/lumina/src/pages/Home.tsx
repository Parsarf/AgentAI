import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import * as I from '../components/Icons';
import Composer, { TEMPLATES } from '../components/Composer';
import Orb from '../components/Orb';
import Workspace from '../components/frame/Workspace';
import { useSelection } from '../components/frame/Assistant';
import { Status } from '../components/work/parts';
import { api } from '../lib/api';
import { ago, displayName, greeting } from '../lib/format';
import { humanSize, type Catalogue } from '../lib/files';
import { browserZone, clock, dayKey, dayTitle, failed, hub, people, type HubEvent, type Thread } from '../lib/hub';
import { isOpen, type TaskSummary } from '../lib/work';
import { useData } from '../state/data';
import { useWork } from '../state/work';

const STARTERS = [
  { key: 'Web', name: 'Search the web' }, { key: 'Code', name: 'Build and code' }, { key: 'Data', name: 'Analyze data' }, { key: 'Automate', name: 'Automate' },
];

/** A tile of Today: a fact from one source with a count and a time, opening its place. It loads on its own, so a slow source never holds up the others. */
type Load<T> = { state: 'loading' } | { state: 'off'; words: ReactNode } | { state: 'error'; words: string } | { state: 'ready'; data: T };
function useSource<T>(enabled: boolean | null, off: ReactNode, fetcher: () => Promise<T>): [Load<T>, () => void] {
  const [load, setLoad] = useState<Load<T>>({ state: 'loading' }); const [n, setN] = useState(0);
  useEffect(() => {
    if (enabled === null) return;                                   // not known yet (the account is still loading)
    if (!enabled) { setLoad({ state: 'off', words: off }); return; }
    let stop = false; setLoad({ state: 'loading' });
    fetcher().then(data => { if (!stop) setLoad({ state: 'ready', data }); }).catch(e => { if (!stop) setLoad({ state: 'error', words: failed(e) === 'Mail and Calendar are not switched on.' ? 'This is not switched on.' : 'This could not be loaded just now.' }); });
    return () => { stop = true; };
  }, [enabled, n]);   // eslint-disable-line react-hooks/exhaustive-deps
  return [load, useCallback(() => setN(x => x + 1), [])];
}

function Tile<T>({ id, title, to, count, load, retry, empty, children }: { id: string; title: string; to: string; count?: (data: T) => number | null; load: Load<T>; retry(): void;
  empty(data: T): boolean; children(data: T): ReactNode }) {
  const n = load.state === 'ready' && count ? count(load.data) : null;
  return <section className="panel card tile-today" aria-labelledby={`tile-${id}`} aria-busy={load.state === 'loading'}>
    <header className="tile-head"><h2 id={`tile-${id}`}><Link to={to}>{title}</Link></h2>{n !== null && n > 0 && <span className="badge">{n}</span>}<Link to={to} className="iconbtn small ghost" aria-label={`Open ${title.toLowerCase()}`}><I.Chevron width={14} height={14} /></Link></header>
    {load.state === 'loading' ? <div className="tile-body" role="status"><div className="skeleton" style={{ height: 14, width: '80%' }} /><div className="skeleton" style={{ height: 14, width: '60%' }} /><span className="sr">Loading…</span></div>
      : load.state === 'off' ? <p className="tile-body muted small">{load.words}</p>
      : load.state === 'error' ? <p className="tile-body muted small">{load.words} <button type="button" className="linkish" onClick={retry}>Try again</button></p>
      : empty(load.data) ? <p className="tile-body muted small">Nothing today.</p>
      : <div className="tile-body">{children(load.data)}</div>}
  </section>;
}

/** Home is Today: the prompt first, with the greeting and a smaller orb; then what the day holds, each tile from live data and each opening its place. No tile invents
 *  urgency: what it shows is a fact with a count and a time. */
export default function Home() {
  const { app } = useData(); const { tasks, loaded } = useWork(); const nav = useNavigate();
  const [seed, setSeed] = useState<{ text: string; n: number } | null>(null);
  const name = displayName(app?.user.email ?? ''); const zone = browserZone(); const now = Math.floor(Date.now() / 1000);
  const known = app ? true : null; const dashboard = app ? !!app.features.dashboard : null; const files = app ? !!app.features.files : null;
  useSelection({ looking: { kind: 'page', page: 'home' }, words: 'Today', actions: dashboard ? [{ label: 'Plan my day', message: 'Look at my calendar and mail for today and suggest how to plan my day.' }] : [] });

  const [meetings, retryMeetings] = useSource<{ events: HubEvent[]; connected: boolean }>(dashboard, 'Your calendars are not available on your account yet.', async () => {
    const o = await hub.overview(); const connected = o.accounts.some(a => a.capabilities.calendar);
    if (!connected) return { events: [], connected };
    const r = await hub.events(now, now + 7 * 86400);
    return { events: r.events.filter(e => !e.cancelled && e.end_epoch > now).sort((a, b) => a.start_epoch - b.start_epoch).slice(0, 4), connected };
  });
  const [mail, retryMail] = useSource<{ threads: Thread[]; unread: number; connected: boolean }>(dashboard, 'Your mail is not available on your account yet.', async () => {
    const o = await hub.overview(); const connected = o.accounts.some(a => a.capabilities.mail);
    if (!connected) return { threads: [], unread: 0, connected };
    const r = await hub.threads({ label: 'inbox', unread: true, limit: 4 });
    return { threads: r.threads, unread: o.counts.unread, connected };
  });
  const [recent, retryFiles] = useSource<Catalogue>(files, 'Saved files are switched off for now.', () => api<Catalogue>('GET', '/v1/catalogue'));
  const [spend, retrySpend] = useSource<{ reported_microusd: number; period_limit_microusd?: number | null; period_remaining_microusd?: number | null }>(known && app?.features.usage !== false, 'Spending is not shown for your account.', () => api('GET', '/v1/costs'));
  const waiting = tasks.filter(t => t.attention); const running = tasks.filter(t => isOpen(t) && !t.attention);
  const work: Load<TaskSummary[]> = loaded ? { state: 'ready', data: [...waiting, ...running].slice(0, 5) } : { state: 'loading' };
  // The day an event is on. An all-day event is on its own dates (a date has no timezone: reading its start as an instant put it a day early west of Greenwich);
  // one that began before today and is still going counts as today.
  const today = dayKey(now, zone);
  const dayOf = (e: HubEvent) => { const d = e.all_day && e.start_date ? e.start_date : dayKey(e.start_epoch, zone); return d < today ? today : d; };
  const when = (e: HubEvent) => `${dayOf(e) === today ? 'Today' : dayTitle(dayOf(e), 'short')}, ${e.all_day ? 'all day' : clock(e.start_epoch, zone)}`;
  const money = (micro: number) => `$${(micro / 1e6).toFixed(2)}`;

  return (
    <Workspace title={<span className="wsp-title">Home</span>} backdrop className="today-page">
      <div className="today">
        <header className="today-hero">
          <Orb state="breathing" size={48} />
          <div><h1>{greeting(new Date())}, {name}</h1><p>What would you like to do today?</p></div>
          <time className="hero-date" dateTime={new Date().toISOString().slice(0, 10)}>{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</time>
        </header>
        <Composer seed={seed} onSent={r => nav(`/chat/${r.conversation_id}`)} />
        <div className="today-starters" role="group" aria-label="Start with">{STARTERS.map(s => <button key={s.key} type="button" className="chip small" onClick={() => setSeed({ text: TEMPLATES[s.key], n: Date.now() })}>{s.name}</button>)}</div>
        <div className="today-tiles">
          <Tile id="meetings" title="Next meetings" to="/calendar" load={meetings} retry={retryMeetings} empty={d => d.connected && !d.events.length}
            count={d => d.events.filter(e => dayOf(e) === today).length}>
            {d => !d.connected ? <p className="muted small">No calendar is connected. <Link to="/calendar">Connect one</Link></p>
              : <ul className="tile-list">{d.events.map(e => <li key={e.connection_id + e.calendar_id + e.id}><Link to={`/calendar?connection=${encodeURIComponent(e.connection_id)}&calendar=${encodeURIComponent(e.calendar_id)}&event=${encodeURIComponent(e.id)}`}>
                <b>{e.busy_only ? 'Busy' : e.title || '(no title)'}</b><span className="faint small">{when(e)}{e.place ? ` · ${e.place}` : ''}</span></Link></li>)}</ul>}
          </Tile>
          <Tile id="mail" title="Mail that needs you" to="/inbox" load={mail} retry={retryMail} empty={d => d.connected && !d.threads.length} count={d => d.unread}>
            {d => !d.connected ? <p className="muted small">No mail account is connected. <Link to="/inbox">Connect one</Link></p>
              : <><p className="faint small">{d.unread === 1 ? '1 unread in your inbox, newest first.' : `${d.unread} unread in your inbox, newest first.`}</p>
                <ul className="tile-list">{d.threads.map(t => <li key={t.connection_id + t.id}><Link to={`/inbox?connection=${encodeURIComponent(t.connection_id)}&thread=${encodeURIComponent(t.id)}`}>
                  <b>{t.subject || '(no subject)'}</b><span className="faint small">{people(t.people)} · {ago(t.last_epoch)}</span></Link></li>)}</ul></>}
          </Tile>
          <Tile id="work" title="Work running and waiting on you" to="/activity" load={work} retry={() => undefined} empty={d => !d.length} count={() => waiting.length || null}>
            {d => <ul className="tile-list">{d.map(t => <li key={t.id}><Link to={t.attention ? `/activity/${t.id}` : t.conversation_id ? `/chat/${t.conversation_id}` : `/activity/${t.id}`}>
              <b>{t.title}</b><span className="tile-meta"><Status task={t} size="sm" /><span className="faint small">{ago(t.created_epoch)}</span></span></Link></li>)}</ul>}
          </Tile>
          <Tile id="files" title="Recent files" to="/files" load={recent} retry={retryFiles} empty={d => !d.files.length}>
            {d => <ul className="tile-list">{[...d.files].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4).map(f => <li key={f.kind + f.id}><Link to={`/files?open=${encodeURIComponent(`${f.kind}:${f.id}`)}`}>
              <b>{f.name}</b><span className="faint small">{humanSize(f.size_bytes)} · {f.source === 'uploaded' ? 'you uploaded it' : 'made by your assistant'}</span></Link></li>)}</ul>}
          </Tile>
          <Tile id="spend" title="This period's spending" to="/settings/usage" load={spend} retry={retrySpend} empty={() => false}>
            {d => <><p className="tile-figure">{money(d.reported_microusd)}{d.period_limit_microusd ? <span className="faint small"> of {money(d.period_limit_microusd)}</span> : null}</p>
              {d.period_limit_microusd ? <div className="files-meter-bar" aria-hidden="true"><span style={{ width: `${Math.min(100, Math.round((d.reported_microusd / d.period_limit_microusd) * 100))}%` }} /></div> : null}
              <p className="faint small">{d.period_remaining_microusd != null ? `${money(d.period_remaining_microusd)} left this period.` : 'Used so far this period.'}</p></>}
          </Tile>
        </div>
      </div>
    </Workspace>);
}
