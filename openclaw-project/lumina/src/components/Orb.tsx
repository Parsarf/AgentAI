import { useEffect, useId, useRef, useSyncExternalStore } from 'react';
import { MODE_DRAWS, resolvePreset, type OrbState } from '../vendor/thinking-orbs';
import { addOrb } from '../lib/orbLoop';
import { MAX_ANIMATED_ORBS } from '../lib/orbs';
import { useSettings } from '../state/settings';

// Orbs currently on screen, in the order they appeared. Only the first few animate (see MAX_ANIMATED_ORBS).
let mounted: string[] = [];
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
const snapshot = () => mounted;
function register(id: string) {
  mounted = [...mounted, id]; listeners.forEach(f => f());
  return () => { mounted = mounted.filter(x => x !== id); listeners.forEach(f => f()); };
}

/**
 * Lumina's "thinking" indicator: the thinking-orbs drawing engine, driven by one shared 15 fps clock (lib/frameClock.ts) instead of a 60 fps loop
 * per orb. Drawn only while on screen and never while the page scrolls or you type; a still frame when Lumina's Reduce motion setting is on
 * (that setting starts from the system's and is the one switch for the planet and the orbs alike, so turning animations on in Lumina turns
 * them on everywhere); at most MAX_ANIMATED_ORBS animate at once. Lumina is always dark, so the light-ink palette is fixed.
 * Decorative by default: put the meaning in the text beside it, or pass `label` to make it an image with a name.
 */
export default function Orb({ state = 'breathing', size = 20, label, still = false }: { state?: OrbState; size?: 20 | 64; label?: string; still?: boolean }) {
  const id = useId(); const { reducedMotion } = useSettings();
  const order = useSyncExternalStore(subscribe, snapshot);
  useEffect(() => register(id), [id]);
  const rank = order.indexOf(id);
  const animate = !reducedMotion && !still && rank >= 0 && rank < MAX_ANIMATED_ORBS;
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current; if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    const { mode, speed, opts } = resolvePreset(state, size);
    const draw = MODE_DRAWS[mode];
    const paint = (seconds: number) => { ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, size, size); draw(ctx, size, seconds * speed, true, opts); };
    paint(0.6);                                                 // always one good frame: the whole picture when it is not animating
    return animate ? addOrb(canvas, { draw: paint }) : undefined;
  }, [state, size, animate]);

  return <canvas ref={ref} className="orb" style={{ width: size, height: size, display: 'block' }}
    {...(label ? { role: 'img', 'aria-label': label } : { role: 'presentation', 'aria-hidden': true })} />;
}
