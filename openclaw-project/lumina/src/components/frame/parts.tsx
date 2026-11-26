import { useMemo, useState, type ReactNode } from 'react';

/** The canvas's own toolbar: the page title on the left, its controls on the right. It stays at the top while the page scrolls. */
export function Toolbar({ title, tools, leading }: { title: ReactNode; tools?: ReactNode; leading?: ReactNode }) {
  return <header className="wsp-toolbar">
    {leading}
    {typeof title === 'string' ? <h1 className="wsp-title" title={title}>{title}</h1> : title}
    {tools && <div className="wsp-tools">{tools}</div>}
  </header>;
}

/** What a place shows when it has nothing: one plain sentence of what is true, and what the person can do about it. */
export function EmptyState({ title, children, action, role }: { title?: ReactNode; children?: ReactNode; action?: ReactNode; role?: 'status' }) {
  return <div className="empty empty-state" role={role}>
    {title && <p className="empty-title">{title}</p>}
    {children && <div className="empty-text">{children}</div>}
    {action && <div className="empty-action">{action}</div>}
  </div>;
}

/** The body of an inspector zone: a heading for the thing that is open, its actions, then its details. */
export function Inspector({ title, meta, actions, children, label }: { title: ReactNode; meta?: ReactNode; actions?: ReactNode; children: ReactNode; label?: string }) {
  return <section className="inspector" aria-label={label}>
    <header className="inspector-head"><h2 className="inspector-title">{title}</h2>{meta && <div className="inspector-meta">{meta}</div>}{actions && <div className="inspector-actions">{actions}</div>}</header>
    <div className="inspector-body">{children}</div>
  </section>;
}

export interface Column<T> {
  key: string; label: string; render(row: T): ReactNode;
  /** A value to sort by; a column without it cannot be sorted. */
  sort?(row: T): string | number;
  className?: string;
}
/** A table of rows that can be sorted by a column (click or Enter on its heading) and opened (click, or Enter on the focused row). The selected row is marked for
 *  screen readers as well as by colour. */
export function Table<T>({ columns, rows, rowKey, label, selected, onOpen, initialSort, empty }: {
  columns: Column<T>[]; rows: T[]; rowKey(row: T): string; label: string; selected?: string | null; onOpen?(row: T): void;
  initialSort?: { key: string; dir: 'asc' | 'desc' }; empty?: ReactNode;
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const shown = useMemo(() => {
    const col = sort && columns.find(c => c.key === sort.key);
    if (!col?.sort) return rows;
    const by = col.sort; const dir = sort!.dir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => { const x = by(a), y = by(b); return (x < y ? -1 : x > y ? 1 : 0) * dir; });
  }, [rows, sort, columns]);
  if (!rows.length && empty) return <>{empty}</>;
  return <div className="table-wrap"><table className="table" aria-label={label}>
    <thead><tr>{columns.map(c => <th key={c.key} scope="col" className={c.className} aria-sort={sort?.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}>
      {c.sort ? <button type="button" className="table-sort" onClick={() => setSort(s => ({ key: c.key, dir: s?.key === c.key && s.dir === 'desc' ? 'asc' : 'desc' }))}>{c.label}</button> : c.label}</th>)}</tr></thead>
    <tbody>{shown.map(row => { const k = rowKey(row); return <tr key={k} aria-selected={selected === k} tabIndex={onOpen ? 0 : undefined} className={onOpen ? 'clickable' : undefined}
      onClick={onOpen ? () => onOpen(row) : undefined} onKeyDown={onOpen ? e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); onOpen(row); } } : undefined}>
      {columns.map(c => <td key={c.key} className={c.className}>{c.render(row)}</td>)}</tr>; })}</tbody>
  </table></div>;
}
