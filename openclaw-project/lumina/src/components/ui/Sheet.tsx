import { useEffect, useRef, type ReactNode } from 'react';
import { Plus } from '../Icons';

/** A side sheet for one focused task. Esc and the scrim close it, Tab stays inside, and focus returns to what opened it. */
export default function Sheet({ title, onClose, children, footer }: { title: ReactNode; onClose(): void; children: ReactNode; footer?: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = root.current!;
    const focusable = () => Array.from(node.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')).filter(el => !el.hasAttribute('disabled'));
    focusable()[0]?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return; }
      if (e.key !== 'Tab') return;
      const items = focusable(); if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    node.addEventListener('keydown', key);
    return () => { node.removeEventListener('keydown', key); opener?.focus?.(); };
  }, [onClose]);
  return <div className="sheet-scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="sheet" role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined} ref={root}>
      <div className="sheet-head"><div className="sheet-title">{title}</div>
        <button type="button" className="iconbtn" aria-label="Close" onClick={onClose}><Plus className="rot45" /></button></div>
      <div className="sheet-body">{children}</div>
      {footer && <div className="sheet-foot">{footer}</div>}
    </div>
  </div>;
}
