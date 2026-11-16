import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';

/** A long list that renders only the rows in view (plus a few either side), so 100,000 rows scroll as smoothly as 50. Rows have one fixed height per density.
 *  The list owns its scrolling box: give it a parent with a height (a `fill` workspace). Hand-written on purpose (plans/product/ui-remodel/architecture.md).
 *
 *  - `active`: the index the keyboard is on; the list scrolls it into view.
 *  - `onEnd`: asked for more when the reader is within a few screens of the end (paged loading).
 *  - `keepTop`: when rows are added above (new mail), the rows the reader is looking at stay where they are. */
export default function List<T>({ items, rowHeight, rowKey, renderRow, label, active, onEnd, overscan = 8, className = '', header, footer }: {
  items: T[]; rowHeight: number; rowKey(item: T, index: number): string; renderRow(item: T, index: number): ReactNode; label: string;
  active?: number; onEnd?(): void; overscan?: number; className?: string; header?: ReactNode; footer?: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null); const [top, setTop] = useState(0); const [height, setHeight] = useState(0);
  const headerRef = useRef<HTMLDivElement>(null); const [headerHeight, setHeaderHeight] = useState(0);
  useLayoutEffect(() => {
    const el = box.current; if (!el) return;
    const measure = () => { setHeight(el.clientHeight); setHeaderHeight(headerRef.current?.offsetHeight ?? 0); };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure); ro.observe(el); if (headerRef.current) ro.observe(headerRef.current); return () => ro.disconnect();
  }, []);
  // Rows added above the first one: keep the reader's place (the first visible row's key stays at the same spot).
  const firstKey = useRef<string | null>(null); const firstIndex = Math.floor(Math.max(0, top - headerHeight) / rowHeight);
  useLayoutEffect(() => {
    const el = box.current; if (!el || !items.length) return;
    const key = firstKey.current;
    if (key !== null && top > headerHeight) {
      const now = items.findIndex((it, i) => rowKey(it, i) === key);
      if (now > -1 && now !== firstIndex) el.scrollTop += (now - firstIndex) * rowHeight;
    }
  }, [items]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { firstKey.current = items[firstIndex] ? rowKey(items[firstIndex], firstIndex) : null; });

  const view = height || 900;                                          // before layout (and in tests) show a screenful
  const start = Math.max(0, firstIndex - overscan);
  const end = Math.min(items.length, Math.ceil((Math.max(0, top - headerHeight) + view) / rowHeight) + overscan);
  const asked = useRef(-1);
  useEffect(() => { if (onEnd && items.length && end >= items.length - overscan * 3 && asked.current !== items.length) { asked.current = items.length; onEnd(); } }, [end, items.length, onEnd, overscan]);
  useEffect(() => {
    const el = box.current; if (active === undefined || active < 0 || !el) return;
    const y = headerHeight + active * rowHeight;
    if (y < el.scrollTop) el.scrollTop = y; else if (y + rowHeight > el.scrollTop + el.clientHeight) el.scrollTop = y + rowHeight - el.clientHeight;
  }, [active, rowHeight, headerHeight]);
  const onScroll = useCallback(() => { const el = box.current; if (el) setTop(el.scrollTop); }, []);

  return <div ref={box} className={`vlist ${className}`} onScroll={onScroll} style={{ ['--row' as string]: `${rowHeight}px` }}>
    {header && <div ref={headerRef}>{header}</div>}
    <ul aria-label={label} className="vlist-rows" style={{ height: items.length * rowHeight, paddingTop: start * rowHeight }}>
      {items.slice(start, end).map((item, n) => { const i = start + n; return <li key={rowKey(item, i)} aria-setsize={items.length} aria-posinset={i + 1} style={{ height: rowHeight }}>{renderRow(item, i)}</li>; })}
    </ul>
    {footer}
  </div>;
}
