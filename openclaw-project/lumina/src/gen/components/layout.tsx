import { useId, useRef, type ReactNode } from 'react';
import { safeHttpUrl } from '../safety';
import { cx, type P } from './types';
import { useGen, useLocal } from './context';
import { StatusPill } from './cards';

export function Divider() { return <hr className="gen-hr" />; }
export function Section({ block, children }: P<'section'> & { children: ReactNode }) {
  const cols = block.layout?.columns;
  return <section className="gen-section" aria-label={block.props.title}>{block.props.title && <h4>{block.props.title}</h4>}{block.props.description && <p className="faint">{block.props.description}</p>}
    <div className="gen-grid" style={cols ? { ['--cols' as string]: cols } : undefined}>{children}</div></section>;
}
export function Tabs({ block, panels }: P<'tabs'> & { panels: ReactNode[] }) {
  const tabs = block.props.tabs; const uid = useId(); const [l, set] = useLocal(block.id, { selected: block.props.initial ?? tabs[0].id });
  const cur = Math.max(0, tabs.findIndex(t => t.id === l.selected)); const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const key = (e: React.KeyboardEvent, i: number) => {
    const to = e.key === 'ArrowRight' ? (i + 1) % tabs.length : e.key === 'ArrowLeft' ? (i + tabs.length - 1) % tabs.length : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : -1;
    if (to >= 0) { e.preventDefault(); set({ selected: tabs[to].id }); refs.current[to]?.focus(); }
  };
  return <div className={cx('gen-tabs', block.variant)}><div role="tablist" aria-label={block.props.title ?? 'Views'}>{tabs.map((t, i) =>
    <button key={t.id} ref={el => { refs.current[i] = el; }} role="tab" id={`${uid}-t-${t.id}`} aria-selected={i === cur} aria-controls={`${uid}-p-${t.id}`} tabIndex={i === cur ? 0 : -1} onClick={() => set({ selected: t.id })} onKeyDown={e => key(e, i)}>{t.label}</button>)}</div>
    {tabs.map((t, i) => <div key={t.id} role="tabpanel" id={`${uid}-p-${t.id}`} aria-labelledby={`${uid}-t-${t.id}`} hidden={i !== cur} tabIndex={0}>{i === cur && panels[i]}</div>)}</div>;
}
export function Accordion({ block, panels }: P<'accordion'> & { panels: ReactNode[] }) {
  const uid = useId(); const items = block.props.items;
  const [l, set] = useLocal(block.id, { open: items.filter(i => i.open).map(i => i.id) as string[] });
  const open = l.open as string[];
  const toggle = (id: string) => set({ open: open.includes(id) ? open.filter(x => x !== id) : block.props.multiple ? [...open, id] : [id] });
  return <div className="gen-accordion">{items.map((it, i) => { const on = open.includes(it.id);
    return <div key={it.id} className="gen-acc-item"><h4><button id={`${uid}-b-${it.id}`} aria-expanded={on} aria-controls={`${uid}-r-${it.id}`} onClick={() => toggle(it.id)}>{it.title}<span aria-hidden>{on ? '−' : '+'}</span></button></h4>
      <div id={`${uid}-r-${it.id}`} role="region" aria-labelledby={`${uid}-b-${it.id}`} hidden={!on}>{on && panels[i]}</div></div>; })}</div>;
}
export function Timeline({ block }: P<'timeline'>) {
  return <ol className={cx('gen-timeline', block.variant)} aria-label={block.props.title ?? 'Timeline'}>{block.props.events.map((e, n) =>
    <li key={e.id ?? n} className={e.state}><span className="gen-node" aria-hidden />{e.time && <time className="faint">{e.time}</time>}<strong>{e.title}</strong>
      {e.state && <span className="sr"> ({e.state})</span>}{e.detail && <p className="faint">{e.detail}</p>}</li>)}</ol>;
}
function Pic({ refId, alt, fit, thumb }: { refId: string; alt: string; fit: string; thumb?: boolean }) {
  const src = useGen().assetUrl(refId);
  if (!src) return <p className="gen-empty">{alt}</p>;
  return <img className={cx('gen-img', fit, thumb && 'thumb')} src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" />;
}
export function ImageBlock({ block }: P<'image'>) {
  const p = block.props; const ext = p.externalUrl ? safeHttpUrl(p.externalUrl) : null;
  return <figure className={cx('gen-figure', block.variant)}><Pic refId={p.assetRef} alt={p.alt} fit={block.variant === 'cover' ? 'cover' : p.fit} />
    {(p.caption || ext) && <figcaption className="faint">{p.caption}{ext && <> <a href={ext} target="_blank" rel="noopener noreferrer nofollow">Source ↗<span className="sr"> (opens in a new tab)</span></a></>}</figcaption>}</figure>;
}
export function Gallery({ block }: P<'gallery'>) {
  return <ul className="gen-gallery" aria-label={block.props.title ?? 'Images'}>{block.props.images.map((im, n) => <li key={n}><figure><Pic refId={im.assetRef} alt={im.alt} fit="cover" thumb />{im.caption && <figcaption className="faint">{im.caption}</figcaption>}</figure></li>)}</ul>;
}
export { StatusPill };
