import { useContext, useMemo, useState } from 'react';
import { ChatActionsContext } from '../../lib/chatActions';
import type { AnswerSpec, CalloutSpec, ChoiceSpec, PlacesSpec, ProductsSpec, SourcesSpec, StepsSpec, TimelineSpec } from '../../lib/genui/data';
import { em, FollowUps, link, OptionPicture } from './Cards';

// The cards below draw what the assistant chose to show. Everything interactive here either happens in the browser (filter, sort, tick off) or sends
// exactly the words on a button as the person's next message: nothing hidden is ever sent, and nothing reaches another site until the person clicks a link.

const stars = (r: number) => `★ ${r.toFixed(1)}`;
const compactCount = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));
const joinNames = (names: string[]) => (names.length <= 2 ? names.join(' and ') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);

/** A map search for a place: opened only when the person clicks it. */
export const mapLink = (name: string, where?: string) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([name, where].filter(Boolean).join(' '))}`;

function Chip({ on, onClick, children }: { on: boolean; onClick(): void; children: React.ReactNode }) {
  return <button type="button" className="gchip" aria-pressed={on} onClick={onClick}>{children}</button>;
}

// ---------------------------------------------------------------- places
export function PlacesCard({ spec }: { spec: PlacesSpec }) {
  const [openOnly, setOpenOnly] = useState(false);
  const [price, setPrice] = useState<string | null>(null);
  const [sort, setSort] = useState<'best' | 'rating' | 'distance'>('best');
  const hasOpen = spec.items.some(p => p.open !== undefined);
  const prices = useMemo(() => [...new Set(spec.items.map(p => p.price).filter((x): x is string => !!x && /^\${1,4}$/.test(x)))].sort((a, b) => a.length - b.length), [spec]);
  const canRate = spec.items.filter(p => p.rating !== undefined).length >= 2;
  const canNear = spec.items.filter(p => p.distance_km !== undefined).length >= 2;
  const shown = spec.items
    .filter(p => !openOnly || p.open === true)
    .filter(p => !price || p.price === price)
    .sort((a, b) => sort === 'rating' ? (b.rating ?? -1) - (a.rating ?? -1) : sort === 'distance' ? (a.distance_km ?? 1e9) - (b.distance_km ?? 1e9) : 0);
  const filtered = shown.length !== spec.items.length;
  return (
    <section className="gcard gplaces" aria-label={spec.title}>
      <header className="gcard-h"><h3>{em(spec.title)}</h3><span className="gcompare-count">{filtered ? `${shown.length} of ${spec.items.length}` : `${spec.items.length} places`}</span></header>
      {(hasOpen || prices.length > 1 || canRate || canNear) && (
        <div className="gtools" role="toolbar" aria-label="Filter and sort">
          {hasOpen && <Chip on={openOnly} onClick={() => setOpenOnly(!openOnly)}>Open now</Chip>}
          {prices.length > 1 && prices.map(p => <Chip key={p} on={price === p} onClick={() => setPrice(price === p ? null : p)}>{p}</Chip>)}
          {(canRate || canNear) && (
            <label className="gsort">Sort
              <select value={sort} onChange={e => setSort(e.target.value as typeof sort)}>
                <option value="best">Best match</option>{canRate && <option value="rating">Highest rated</option>}{canNear && <option value="distance">Closest</option>}
              </select>
            </label>)}
        </div>)}
      <div className="gplace-list">
        {shown.map(p => (
          <article key={p.name} className="gplace">
            {p.image && <OptionPicture image={p.image} name={p.name} />}
            <div className="gplace-body">
              <h4>{p.link ? link(p.link, p.name) : em(p.name)}</h4>
              <p className="gmeta">
                {p.rating !== undefined && <span className="grating">{stars(p.rating)}{p.reviews !== undefined && <span className="muted"> ({compactCount(p.reviews)})</span>}</span>}
                {p.price && <span>{p.price}</span>}
                {p.distance && <span>{p.distance}</span>}
                {p.open !== undefined && <span className={p.open ? 'gopen' : 'gclosed'}>{p.open ? 'Open now' : 'Closed'}</span>}
              </p>
              {(p.address || p.area) && <p className="gaddr">{em(p.address ?? p.area ?? '')}</p>}
              {p.hours && <p className="small muted">{em(p.hours)}</p>}
              {p.tags.length > 0 && <ul className="gtags">{p.tags.map(t => <li key={t}>{em(t)}</li>)}</ul>}
              {p.note && <p className="gnote">{em(p.note)}</p>}
              <p className="gplace-links">{link(mapLink(p.name, p.address ?? p.area), 'Map')}</p>
              <FollowUps items={p.actions} scope="option" />
            </div>
          </article>))}
        {shown.length === 0 && <p className="muted">No places match these filters. <button type="button" className="linkish" onClick={() => { setOpenOnly(false); setPrice(null); }}>Show all</button></p>}
      </div>
      <FollowUps items={spec.actions} scope="card" />
      {spec.caption && <p className="gcard-cap">{spec.caption}</p>}
    </section>);
}

// ---------------------------------------------------------------- products
export function ProductsCard({ spec }: { spec: ProductsSpec }) {
  const chat = useContext(ChatActionsContext);
  const [sort, setSort] = useState<'best' | 'low' | 'high' | 'rating'>('best');
  const [store, setStore] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [sent, setSent] = useState(false); const [failed, setFailed] = useState(false);
  const stores = useMemo(() => [...new Set(spec.items.map(p => p.store).filter((x): x is string => !!x))], [spec]);
  const canPrice = spec.items.filter(p => p.price_value !== undefined).length >= 2;
  const canRate = spec.items.filter(p => p.rating !== undefined).length >= 2;
  const shown = spec.items
    .filter(p => !store || p.store === store)
    .sort((a, b) => sort === 'low' ? (a.price_value ?? 1e12) - (b.price_value ?? 1e12) : sort === 'high' ? (b.price_value ?? -1) - (a.price_value ?? -1) : sort === 'rating' ? (b.rating ?? -1) - (a.rating ?? -1) : 0);
  const toggle = (name: string) => setPicked(p => p.includes(name) ? p.filter(x => x !== name) : p.length >= 3 ? p : [...p, name]);
  const compareText = `Compare ${joinNames(picked)}`;
  const compare = async () => {
    if (!chat || sent) return;
    setSent(true); setFailed(false);
    try { await chat.send(compareText); } catch { setSent(false); setFailed(true); }
  };
  return (
    <section className="gcard gproducts" aria-label={spec.title}>
      <header className="gcard-h"><h3>{em(spec.title)}</h3><span className="gcompare-count">{shown.length === spec.items.length ? `${spec.items.length} products` : `${shown.length} of ${spec.items.length}`}</span></header>
      {(stores.length > 1 || canPrice || canRate) && (
        <div className="gtools" role="toolbar" aria-label="Filter and sort">
          {stores.length > 1 && stores.map(s => <Chip key={s} on={store === s} onClick={() => setStore(store === s ? null : s)}>{s}</Chip>)}
          {(canPrice || canRate) && (
            <label className="gsort">Sort
              <select value={sort} onChange={e => setSort(e.target.value as typeof sort)}>
                <option value="best">Best match</option>
                {canPrice && <><option value="low">Price: low to high</option><option value="high">Price: high to low</option></>}
                {canRate && <option value="rating">Highest rated</option>}
              </select>
            </label>)}
        </div>)}
      <div className="gproduct-grid" data-count={shown.length}>
        {shown.map(p => (
          <article key={p.name} className={`gproduct${picked.includes(p.name) ? ' on' : ''}`}>
            {p.image && <OptionPicture image={p.image} name={p.name} />}
            {p.badge && <span className="gbadge">{em(p.badge)}</span>}
            <h4>{p.link ? link(p.link, p.name) : em(p.name)}</h4>
            <p className="gmeta">
              {p.price && <span className="gprice">{em(p.price)}</span>}
              {p.store && <span>{em(p.store)}</span>}
              {p.rating !== undefined && <span className="grating">{stars(p.rating)}{p.reviews !== undefined && <span className="muted"> ({compactCount(p.reviews)})</span>}</span>}
            </p>
            {p.specs.length > 0 && <dl>{p.specs.map(f => <div key={f.label}><dt>{em(f.label)}</dt><dd>{em(f.value)}</dd></div>)}</dl>}
            {p.note && <p className="gnote">{em(p.note)}</p>}
            {chat && spec.items.length > 1 && (
              <label className="gpick"><input type="checkbox" checked={picked.includes(p.name)} disabled={sent || (!picked.includes(p.name) && picked.length >= 3)} onChange={() => toggle(p.name)} /> Compare</label>)}
            <FollowUps items={p.actions} scope="option" />
          </article>))}
        {shown.length === 0 && <p className="muted">Nothing matches. <button type="button" className="linkish" onClick={() => setStore(null)}>Show all</button></p>}
      </div>
      {chat && picked.length >= 2 && (
        <div className="gfollow gfollow-card">
          <button type="button" className="gfollow-b" disabled={sent} onClick={compare}>{sent ? '✓ ' : ''}{compareText}</button>
          {failed && <p className="err small" role="alert">That did not go through. Try again.</p>}
        </div>)}
      <FollowUps items={spec.actions} scope="card" />
      {spec.caption && <p className="gcard-cap">{spec.caption}</p>}
    </section>);
}

// ---------------------------------------------------------------- steps: a checklist that remembers what was ticked (in this browser only)
const keyOf = (spec: StepsSpec) => {
  let h = 0; const text = spec.title + spec.items.map(i => i.title).join('|');
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
  return `lumina-steps-${(h >>> 0).toString(36)}`;
};
function readTicks(key: string): number[] {
  try { const v = JSON.parse(localStorage.getItem(key) ?? '[]'); return Array.isArray(v) ? v.filter(n => Number.isInteger(n)) : []; } catch { return []; }
}
export function StepsCard({ spec }: { spec: StepsSpec }) {
  const key = keyOf(spec);
  const [done, setDone] = useState<number[]>(() => readTicks(key));
  const toggle = (i: number) => setDone(d => {
    const next = d.includes(i) ? d.filter(x => x !== i) : [...d, i];
    try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* private window: ticks just are not remembered */ }
    return next;
  });
  const n = done.filter(i => i < spec.items.length).length;
  return (
    <section className="gcard gsteps" aria-label={spec.title}>
      <header className="gcard-h"><h3>{em(spec.title)}</h3><span className="gcompare-count">{n} of {spec.items.length} done</span></header>
      <div className="gprogress" role="progressbar" aria-valuemin={0} aria-valuemax={spec.items.length} aria-valuenow={n}><span style={{ width: `${(100 * n) / spec.items.length}%` }} /></div>
      <ol className="gstep-list">
        {spec.items.map((s, i) => (
          <li key={i} className={done.includes(i) ? 'done' : undefined}>
            <label><input type="checkbox" checked={done.includes(i)} onChange={() => toggle(i)} /> <span className="gstep-title">{em(s.title)}</span></label>
            {s.detail && <p className="small muted">{em(s.detail)}</p>}
          </li>))}
      </ol>
      <FollowUps items={spec.actions} scope="card" />
      {spec.caption && <p className="gcard-cap">{spec.caption}</p>}
    </section>);
}

// ---------------------------------------------------------------- answer: the result first, then how sure, then where it came from
const CONFIDENCE = { confirmed: 'Confirmed', likely: 'Likely', uncertain: 'Not certain' } as const;
export function AnswerCard({ spec }: { spec: AnswerSpec }) {
  return (
    <section className="gcard ganswer" aria-label={spec.title ?? 'Answer'}>
      {spec.title && <p className="glabel">{em(spec.title)}</p>}
      {spec.value && <p className="gvalue">{em(spec.value)}</p>}
      <p className="gheadline">{em(spec.headline)}</p>
      {spec.confidence && <span className={`gconf gconf-${spec.confidence}`}>{CONFIDENCE[spec.confidence]}</span>}
      {spec.detail && <p className="gdetail">{em(spec.detail)}</p>}
      {spec.sources.length > 0 && <p className="gsources">{spec.sources.map(s => <span key={s.link}>{link(s.link, s.site ?? s.title)}</span>)}</p>}
      <FollowUps items={spec.actions} scope="card" />
    </section>);
}

// ---------------------------------------------------------------- choice: quick replies; what is on the button is what is sent
export function ChoiceCard({ spec }: { spec: ChoiceSpec }) {
  const chat = useContext(ChatActionsContext);
  const [picked, setPicked] = useState<string[]>([]);
  const [sent, setSent] = useState<string | null>(null); const [failed, setFailed] = useState(false);
  const send = async (text: string) => {
    if (!chat || sent) return;
    setSent(text); setFailed(false);
    try { await chat.send(text); } catch { setSent(null); setFailed(true); }
  };
  const many = !!spec.multiple;
  const together = joinNames(picked);
  return (
    <section className="gcard gchoice" aria-label={spec.question}>
      <p className="gquestion">{em(spec.question)}</p>
      <div className="gchoice-options" role="group" aria-label="Options">
        {spec.options.map(o => many
          ? <Chip key={o} on={picked.includes(o)} onClick={() => !sent && setPicked(p => p.includes(o) ? p.filter(x => x !== o) : [...p, o])}>{em(o)}</Chip>
          : <button key={o} type="button" className={`gfollow-b${sent === o ? ' chosen' : ''}`} disabled={!chat || !!sent} onClick={() => send(o)}>{sent === o ? '✓ ' : ''}{em(o)}</button>)}
      </div>
      {many && chat && picked.length > 0 && (
        <div className="gfollow"><button type="button" className="gfollow-b" disabled={!!sent} onClick={() => send(together)}>{sent ? '✓ ' : ''}Send: {together}</button></div>)}
      {failed && <p className="err small" role="alert">That did not go through. Try again.</p>}
    </section>);
}

// ---------------------------------------------------------------- callout
const TONE_ICON = { info: 'ℹ️', tip: '💡', warning: '⚠️', success: '✅' } as const;
export function CalloutCard({ spec }: { spec: CalloutSpec }) {
  return (
    <aside className={`gcallout gcallout-${spec.tone}`} role={spec.tone === 'warning' ? 'alert' : 'note'}>
      <span className="gcallout-icon" aria-hidden="true">{em(TONE_ICON[spec.tone])}</span>
      <div>{spec.title && <strong>{em(spec.title)}</strong>}<p>{em(spec.text)}</p></div>
    </aside>);
}

// ---------------------------------------------------------------- timeline
export function TimelineCard({ spec }: { spec: TimelineSpec }) {
  return (
    <section className="gcard gtimeline" aria-label={spec.title}>
      <header className="gcard-h"><h3>{em(spec.title)}</h3></header>
      <ol className="gtime-list">
        {spec.items.map((m, i) => (
          <li key={i}><span className="gwhen">{em(m.when)}</span><div><p className="gtime-title">{em(m.title)}</p>{m.detail && <p className="small muted">{em(m.detail)}</p>}</div></li>))}
      </ol>
      <FollowUps items={spec.actions} scope="card" />
      {spec.caption && <p className="gcard-cap">{spec.caption}</p>}
    </section>);
}

// ---------------------------------------------------------------- sources
export function SourcesCard({ spec }: { spec: SourcesSpec }) {
  return (
    <section className="gcard gsources-card" aria-label={spec.title}>
      <header className="gcard-h"><h3>{em(spec.title)}</h3></header>
      <ul className="gsource-list">
        {spec.items.map(s => (
          <li key={s.link}>{link(s.link, s.title)}{s.site && <span className="muted small"> · {s.site}</span>}{s.note && <p className="small muted">{em(s.note)}</p>}</li>))}
      </ul>
    </section>);
}
