// The one clock for Lumina's decorative animation (the planet and the thinking orbs).
//  - Both tick together, 15 times a second, so the browser paints ONE frame per tick instead of two interleaved ones.
//  - It does not tick while the page is scrolling, while you type, or while the tab is hidden: those get the whole frame budget.
//  - It only runs while something is subscribed.

export const FRAME_FPS = 15;
export const SCROLL_QUIET_MS = 200;

const subscribers = new Set<() => void>();
let timer: ReturnType<typeof setTimeout> | undefined;
let quietAt = 0;
let listening = false;

function tick() {
  timer = undefined;
  if (!subscribers.size || document.visibilityState !== 'visible') return;     // nothing wants frames, or a hidden tab: stop until woken
  if (performance.now() >= quietAt) for (const fn of [...subscribers]) fn();
  timer = setTimeout(tick, 1000 / FRAME_FPS);
}
const wake = () => { if (timer === undefined && subscribers.size) timer = setTimeout(tick, 0); };

function listen() {
  if (listening) return; listening = true;
  const quiet = () => { quietAt = performance.now() + SCROLL_QUIET_MS; };
  document.addEventListener('scroll', quiet, { capture: true, passive: true });
  document.addEventListener('wheel', quiet, { capture: true, passive: true });
  document.addEventListener('touchmove', quiet, { capture: true, passive: true });
  document.addEventListener('keydown', quiet, { capture: true, passive: true });      // typing is the other thing that must feel instant
  document.addEventListener('visibilitychange', wake);
}

/** Call `fn` on every tick until the returned function is called. */
export function onFrame(fn: () => void): () => void {
  listen(); subscribers.add(fn); wake();
  return () => { subscribers.delete(fn); };
}
