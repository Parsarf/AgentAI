import { useRef } from 'react';
import { useFrame } from './FrameProvider';
import { LIMITS, roomFor, STEP, type SideZone } from './layout';

const NAMES: Record<SideZone, string> = { context: 'the side column', inspector: 'the details panel', assistant: 'the assistant panel' };

/** The edge between a zone and the canvas. Drag it, or focus it and use the arrow keys (Home and End for the narrowest and widest); the zone's own menu has
 *  "Narrower" and "Wider" for anyone who does neither (WCAG 2.2, 2.5.7). `edge` says which side of the zone the handle is on. */
export default function Split({ zone, edge }: { zone: SideZone; edge: 'start' | 'end' }) {
  const frame = useFrame(); const drag = useRef<{ x: number; w: number } | null>(null);
  if (!frame) return null;
  const now = frame.widths[zone]; const most = roomFor(zone, frame.width, frame.placement, frame.widths);
  const set = (px: number) => frame.setWidth(zone, Math.min(px, most));
  const grow = edge === 'end' ? 1 : -1;               // dragging right widens a zone on the left and narrows one on the right
  return <div role="separator" aria-orientation="vertical" tabIndex={0} data-layout-allow="resize-edge" className={`split split-${edge}`} aria-label={`Resize ${NAMES[zone]}`}
    aria-valuemin={LIMITS[zone].min} aria-valuemax={most} aria-valuenow={now} title="Drag, or use the arrow keys, to resize"
    onPointerDown={e => { if (e.button !== 0) return; e.preventDefault(); (e.target as HTMLElement).setPointerCapture?.(e.pointerId); drag.current = { x: e.clientX, w: now }; document.documentElement.dataset.resizing = 'true'; }}
    onPointerMove={e => { if (drag.current) set(drag.current.w + (e.clientX - drag.current.x) * grow); }}
    onPointerUp={() => { drag.current = null; delete document.documentElement.dataset.resizing; }}
    onPointerCancel={() => { drag.current = null; delete document.documentElement.dataset.resizing; }}
    onKeyDown={e => {
      const by = e.shiftKey ? STEP * 4 : STEP;
      if (e.key === 'ArrowRight') { e.preventDefault(); set(now + by * grow); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); set(now - by * grow); }
      else if (e.key === 'Home') { e.preventDefault(); set(LIMITS[zone].min); }
      else if (e.key === 'End') { e.preventDefault(); set(most); }
    }} />;
}

/** "Narrower" and "Wider" for a zone, as menu items (the pointer alternative to dragging). */
export function sizeItems(frame: NonNullable<ReturnType<typeof useFrame>>, zone: SideZone) {
  const now = frame.widths[zone]; const most = roomFor(zone, frame.width, frame.placement, frame.widths);
  return [
    { id: `${zone}-narrower`, label: 'Narrower', disabled: now <= LIMITS[zone].min, onSelect: () => frame.setWidth(zone, now - STEP * 3) },
    { id: `${zone}-wider`, label: 'Wider', disabled: now >= most, onSelect: () => frame.setWidth(zone, Math.min(most, now + STEP * 3)) },
  ];
}
