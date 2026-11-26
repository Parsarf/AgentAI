import type { ReactNode } from 'react';

/** A list and the thing opened from it, inside a canvas (the Inbox: conversations and the open one). Where the canvas is wide enough the two sit side by side, the list
 *  in a column of its own and the opened thing in the rest; where it is not, one is shown at a time: the list, or what was opened from it, which then has a way back.
 *  Which it is follows the canvas's own width (a container query in frame.css), so it is right whatever zones are docked beside the canvas. Both stay mounted, so the
 *  list keeps its place while something is open.
 *
 *  - `open`: something is opened (decides which one a narrow canvas shows).
 *  - `empty`: what the detail side shows while nothing is open (wide canvases only). */
export default function MasterDetail({ list, detail, open, empty, listLabel, detailLabel, className = '' }: {
  list: ReactNode; detail: ReactNode; open: boolean; empty?: ReactNode; listLabel: string; detailLabel: string; className?: string;
}) {
  return <div className={`master-detail${open ? ' md-open' : ''} ${className}`}>
    <section className="md-list" aria-label={listLabel}>{list}</section>
    <section className="md-detail" aria-label={detailLabel}>{open ? detail : <div className="md-empty">{empty}</div>}</section>
  </div>;
}
