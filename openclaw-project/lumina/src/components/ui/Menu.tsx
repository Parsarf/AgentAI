import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export interface MenuItem {
  id: string; label: string; hint?: string; icon?: ReactNode; checked?: boolean; danger?: boolean; disabled?: boolean; separatorBefore?: boolean; onSelect(): void;
}

/** The shared dropdown: an opaque elevated menu with roving focus, Escape to close and focus returned to the trigger.
 *  `checkable` makes it a choice list (menuitemradio with a check); otherwise rows are plain menuitems. It renders in a portal with fixed coordinates so no scrolling or overflow-hidden parent can clip it; tokens live on :root, so it stays themed. */
export default function Menu({ label, heading, items, trigger, side = 'bottom', align = 'start', checkable = false, className = '' }: {
  label: string; heading?: string; items: MenuItem[]; side?: 'top' | 'bottom'; align?: 'start' | 'end'; checkable?: boolean; className?: string;
  trigger(p: { open: boolean; props: Record<string, unknown> }): ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null); const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const close = (restore = true) => { setOpen(false); if (restore) wrap.current?.querySelector<HTMLElement>('[data-menu-trigger]')?.focus(); };
  const rows = () => Array.from(list.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([disabled])') ?? []);
  useEffect(() => {
    if (!open) return;
    const first = rows().find(r => r.getAttribute('aria-checked') === 'true') ?? rows()[0]; first?.focus();
    const down = (e: MouseEvent) => { const n = e.target as Node; if (!wrap.current?.contains(n) && !list.current?.contains(n)) close(false); };
    document.addEventListener('mousedown', down); return () => document.removeEventListener('mousedown', down);
  }, [open]);
  // Place under (or over) the trigger, flip when it would leave the viewport, and clamp horizontally.
  const [pos, setPos] = useState<{ style: CSSProperties; side: 'top' | 'bottom' } | null>(null);
  useLayoutEffect(() => {
    if (!open) { setPos(null); return; }
    const place = () => {
      const t = wrap.current?.querySelector<HTMLElement>('[data-menu-trigger]')?.getBoundingClientRect(); const m = list.current?.getBoundingClientRect(); if (!t || !m) return;
      const room = { top: t.top, bottom: window.innerHeight - t.bottom };
      const want = side; const use: 'top' | 'bottom' = room[want] >= m.height + 12 || room[want] >= room[want === 'top' ? 'bottom' : 'top'] ? want : (want === 'top' ? 'bottom' : 'top');
      let left = align === 'end' ? t.right - m.width : t.left; left = Math.max(8, Math.min(left, window.innerWidth - m.width - 8));
      setPos({ side: use, style: { left, top: use === 'bottom' ? t.bottom + 8 : undefined, bottom: use === 'top' ? window.innerHeight - t.top + 8 : undefined, maxHeight: Math.max(160, room[use] - 16) } });
    };
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [open, side, align]);
  const onKey = (e: React.KeyboardEvent) => {
    const r = rows(); const i = r.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); r[(i + 1) % r.length]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); r[(i - 1 + r.length) % r.length]?.focus(); }
    else if (e.key === 'Home') { e.preventDefault(); r[0]?.focus(); }
    else if (e.key === 'End') { e.preventDefault(); r.at(-1)?.focus(); }
    else if (e.key === 'Tab') close(false);
  };
  return (
    <div className={`menu-wrap ${className}`} ref={wrap}>
      {trigger({ open, props: { 'data-menu-trigger': '', 'aria-haspopup': 'menu', 'aria-expanded': open, 'aria-controls': open ? id : undefined, onClick: () => setOpen(o => !o),
        onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'ArrowDown' && !open) { e.preventDefault(); setOpen(true); } } } })}
      {open && createPortal(
        <div className="menu" id={id} role="menu" aria-label={label} data-side={pos?.side ?? side} style={pos?.style ?? { visibility: 'hidden', left: 0, top: 0 }} ref={list} onKeyDown={onKey}>
          {heading && <div className="menu-label" aria-hidden>{heading}</div>}
          {items.map(it => (
            <div key={it.id} style={{ display: 'contents' }}>
              {it.separatorBefore && <hr className="menu-sep" />}
              <button type="button" role={checkable ? 'menuitemradio' : 'menuitem'} aria-checked={checkable ? !!it.checked : undefined} disabled={it.disabled}
                className={`menu-item${it.danger ? ' danger' : ''}`} onClick={() => { it.onSelect(); close(); }}>
                {it.icon}<span className="menu-text">{it.label}{it.hint && <small className="menu-hint">{it.hint}</small>}</span>
                {checkable && it.checked && <svg className="menu-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>}
              </button>
            </div>))}
        </div>, document.body)}
    </div>);
}
