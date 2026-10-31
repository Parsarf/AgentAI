// Draws every on-screen orb from the shared frame clock (lib/frameClock.ts): one clock at 15 fps for the whole page, not one 60 fps loop per orb.
//  - one IntersectionObserver: orbs that are off screen are not drawn, and with none visible this stops listening to the clock.
//  - the clock itself skips scrolling and hidden tabs.
// The drawing itself is the thinking-orbs engine, unchanged.
import { onFrame } from './frameClock';

export interface OrbEntry { draw(nowSeconds: number): void }

const entries = new Map<Element, { entry: OrbEntry; visible: boolean }>();
let observer: IntersectionObserver | null = null;
let unsubscribe: (() => void) | null = null;

const anyVisible = () => { for (const e of entries.values()) if (e.visible) return true; return false; };

function drawAll() {
  const t = performance.now() / 1000;
  for (const e of entries.values()) if (e.visible) e.entry.draw(t);
}
function sync() {                                              // listen to the clock only while at least one orb can be seen
  if (anyVisible() && !unsubscribe) unsubscribe = onFrame(drawAll);
  else if (!anyVisible() && unsubscribe) { unsubscribe(); unsubscribe = null; }
}

/** Start drawing `entry` on `el` whenever it is on screen. Returns the function that stops it. */
export function addOrb(el: Element, entry: OrbEntry): () => void {
  if (typeof IntersectionObserver === 'undefined') entries.set(el, { entry, visible: true });
  else {
    observer ??= new IntersectionObserver(list => {
      for (const c of list) { const e = entries.get(c.target); if (e) e.visible = c.isIntersecting; }
      sync();
    });
    entries.set(el, { entry, visible: false }); observer.observe(el);
  }
  sync();
  return () => { observer?.unobserve(el); entries.delete(el); sync(); };
}
