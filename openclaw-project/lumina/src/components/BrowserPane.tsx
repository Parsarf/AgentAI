import { useEffect, useRef, useState, type ReactNode } from 'react';
import * as I from './Icons';

const KEY = 'lumina.chat.browser-pane.width';
/** The pane is never narrower than this, and never leaves the conversation less than CHAT_MIN beside it. Under ROOM_FOR_BOTH the canvas shows one of the two at a time. */
export const PANE_MIN = 340, CHAT_MIN = 360, EDGE = 12, PANE_BASE = 560, ROOM_FOR_BOTH = PANE_MIN + CHAT_MIN + EDGE, STEP = 24;
export const clampPane = (px: number, room: number) => Math.round(Math.max(PANE_MIN, Math.min(px, Math.max(PANE_MIN, room - CHAT_MIN - EDGE))));
const remembered = () => { try { const n = Number(localStorage.getItem(KEY)); return Number.isFinite(n) && n >= PANE_MIN ? n : PANE_BASE; } catch { return PANE_BASE; } };

/** How wide the browser pane is: the width the person last gave it (kept on this device), held inside what the canvas has room for. */
export function usePaneWidth(room: number): [number, (px: number) => void] {
  const [wanted, setWanted] = useState(remembered);
  const set = (px: number) => { const next = clampPane(px, room || 99999); setWanted(next); try { localStorage.setItem(KEY, String(next)); } catch { /* private mode: the width lasts for this visit */ } };
  return [room ? clampPane(wanted, room) : wanted, set];
}

/** The edge between the conversation and the browser. Drag it, or focus it and use the arrow keys (Shift for bigger steps; Home and End for the narrowest and widest). */
export function PaneSplit({ width, room, onWidth }: { width: number; room: number; onWidth(px: number): void }) {
  const drag = useRef<{ x: number; w: number } | null>(null);
  const most = clampPane(99999, room || 99999);
  useEffect(() => () => { delete document.documentElement.dataset.resizing; }, []);
  return <div role="separator" aria-orientation="vertical" tabIndex={0} className="chat-pane-split" aria-label="Resize the browser" aria-valuemin={PANE_MIN} aria-valuemax={most} aria-valuenow={width}
    title="Drag, or use the arrow keys, to resize"
    onPointerDown={e => { if (e.button !== 0) return; e.preventDefault(); (e.target as HTMLElement).setPointerCapture?.(e.pointerId); drag.current = { x: e.clientX, w: width }; document.documentElement.dataset.resizing = 'true'; }}
    onPointerMove={e => { if (drag.current) onWidth(drag.current.w - (e.clientX - drag.current.x)); }}                      // the pane is on the right: dragging left widens it
    onPointerUp={() => { drag.current = null; delete document.documentElement.dataset.resizing; }}
    onPointerCancel={() => { drag.current = null; delete document.documentElement.dataset.resizing; }}
    onKeyDown={e => {
      const by = e.shiftKey ? STEP * 4 : STEP;
      if (e.key === 'ArrowLeft') { e.preventDefault(); onWidth(width + by); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); onWidth(width - by); }
      else if (e.key === 'Home') { e.preventDefault(); onWidth(PANE_MIN); }
      else if (e.key === 'End') { e.preventDefault(); onWidth(most); }
    }} />;
}

/** Lumina's browser beside the conversation: the page it is working on, live, with the controls for stepping in. The person sizes it against the chat, hides the chat to
 *  give it the whole canvas, and closes it when they have seen enough; it opens again from the chat's toolbar. `alone` is a canvas too narrow for both: the pane then has
 *  the canvas to itself and "Back to the chat" closes it. */
export default function BrowserPane({ host, live, chatHidden, alone, onToggleChat, onClose, children }: {
  host?: string; live: boolean; chatHidden: boolean; alone: boolean; onToggleChat(): void; onClose(): void; children: ReactNode;
}) {
  return (
    <aside className="chat-pane" aria-label="Lumina’s browser">
      <header className="chat-pane-head">
        <I.Browser width={16} height={16} aria-hidden="true" />
        <h2>Lumina’s browser</h2>
        {host && <span className="chat-pane-host faint" title={host}>{host}</span>}
        {live && <span className="badge success chat-pane-live">Live</span>}
        <span className="chat-pane-acts">
          {!alone && <button type="button" className="btn small tertiary" aria-pressed={chatHidden} onClick={onToggleChat} title={chatHidden ? 'Show the chat beside the browser' : 'Give the browser the whole view'}>
            <I.Panel width={15} height={15} />{chatHidden ? 'Show chat' : 'Hide chat'}</button>}
          <button type="button" className={alone ? 'btn small' : 'iconbtn small ghost'} aria-label={alone ? undefined : 'Close the browser'} title="Close the browser. It keeps working, and opens again from the top of the chat." onClick={onClose}>
            {alone ? 'Back to the chat' : <I.Plus width={16} height={16} className="rot45" />}</button>
        </span>
      </header>
      <div className="chat-pane-body">{children}</div>
    </aside>);
}
