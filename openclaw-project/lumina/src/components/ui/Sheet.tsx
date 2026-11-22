import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Plus } from '../Icons';

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** A sheet for one focused thing: a zone of the workspace that has no room to sit docked, or a task of its own. Esc and the scrim close it, Tab stays inside, focus
 *  returns to what opened it, and because it lies over the page (it is drawn in the document's top layer) it never hides the element that has focus behind it.
 *  `side` is where it slides in from; on a phone every sheet takes the whole width. `side="center"` is the dialog: a compact panel in the middle of the window for a
 *  short task (a new event), with the page still visible around it; where the window is narrow or short it fills the width, its body scrolls and its footer stays.
 *  `onSubmit` makes the body and the footer one form, so Enter in a field and a submit button in the footer both send it. */
export default function Sheet({ title, onClose, children, footer, side = 'right', className = '', label, onSubmit }: {
  title: ReactNode; onClose(): void; children: ReactNode; footer?: ReactNode; side?: 'right' | 'left' | 'bottom' | 'center'; className?: string; label?: string; onSubmit?(): void;
}) {
  const root = useRef<HTMLDivElement>(null); const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = root.current!;
    const focusable = () => Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(el => !el.hasAttribute('disabled'));
    // Focus the first thing in the body when there is one (the sheet's own content), else the close button.
    (node.querySelector<HTMLElement>(`.sheet-body :is(${FOCUSABLE})`) ?? focusable()[0])?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); close.current(); return; }
      if (e.key !== 'Tab') return;
      const items = focusable(); if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    node.addEventListener('keydown', key);
    return () => { node.removeEventListener('keydown', key); if (opener && document.contains(opener)) opener.focus?.(); };
  }, []);
  const inner = <><div className="sheet-body">{children}</div>{footer && <div className="sheet-foot">{footer}</div>}</>;
  return createPortal(<div className={`sheet-scrim side-${side}`} onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className={`sheet ${className}`} role="dialog" aria-modal="true" aria-label={label ?? (typeof title === 'string' ? title : undefined)} ref={root}>
      <div className="sheet-head"><div className="sheet-title">{title}</div>
        <button type="button" className="iconbtn" aria-label="Close" onClick={onClose}><Plus className="rot45" /></button></div>
      {onSubmit ? <form className="sheet-form" noValidate aria-label={label ?? (typeof title === 'string' ? title : undefined)} onSubmit={e => { e.preventDefault(); onSubmit(); }}>{inner}</form> : inner}
    </div>
  </div>, document.body);
}
