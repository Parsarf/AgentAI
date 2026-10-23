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
 * them on everywhere); at most MAX_ANIMATED_ORBS animate at once. The palette follows the theme: dark ink on parchment.
 * Decorative by default: put the meaning in the text beside it, or pass `label` to make it an image with a name.
 */
export default function Orb({ state = 'breathing', size = 20, label, still = false }: { state?: OrbState; size?: 20 | 48 | 64; label?: string; still?: boolean }) {
  const id = useId(); const { reducedMotion } = useSettings();
  const order = useSyncExternalStore(subscribe, snapshot);
  useEffect(() => register(id), [id]);
  const rank = order.indexOf(id);
  const animate = !reducedMotion && !still && rank >= 0 && rank < MAX_ANIMATED_ORBS;
  const ref = useRef<HTMLCanvasElement>(null);
  const previousState = useRef<OrbState | null>(null);
  const motionTime = useRef(0.6);
  const transitionMs = 600;
  const motionSpeed = 0.55; // calmer motion, independent of the shared frame rate


  useEffect(() => {
    const canvas = ref.current; if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    // Preserve the displayed frame, including any interrupted blend. The new
    // state fades in from exactly what the person was seeing, without a flash.
    let previous: HTMLCanvasElement | null = null;
    if (animate && previousState.current !== null && previousState.current !== state) {
      previous = document.createElement('canvas');
      previous.width = canvas.width; previous.height = canvas.height;
      previous.getContext('2d')?.drawImage(canvas, 0, 0);
    }
    previousState.current = state;
    canvas.width = canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    // Keep the library's purpose-tuned avatar preset; render it at 48px instead
    // of changing its dot geometry or pretending 48 is a shipped preset.
    const presetSize = size === 48 ? 64 : size;
    const { mode, speed, opts } = resolvePreset(state, presetSize);
    const draw = MODE_DRAWS[mode];
    const started = performance.now() / 1000;
    let last = started;
    const paint = (seconds: number) => {
      // Clamp resume deltas so hidden tabs and typing pauses never cause a jump.
      motionTime.current += Math.min(0.1, Math.max(0, seconds - last)) * motionSpeed;
      last = seconds;
      const fraction = Math.min(1, Math.max(0, (seconds - started) * 1000 / transitionMs));
      const blend = fraction * fraction * (3 - 2 * fraction);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (previous) {
        ctx.globalAlpha = 1 - blend;
        ctx.drawImage(previous, 0, 0, canvas.width, canvas.height);
      }
      const scale = dpr * size / presetSize;
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.globalAlpha = previous ? blend : 1;
      draw(ctx, presetSize, motionTime.current * speed, document.documentElement.dataset.theme === 'obsidian', opts);   // dark ink on the parchment, light ink on the old dark world
      ctx.globalAlpha = 1;
      if (fraction === 1) previous = null;
    };
    paint(started); // reduced motion swaps states immediately to a still frame
    return animate ? addOrb(canvas, { draw: paint }) : undefined;
  }, [state, size, animate]);

  return <canvas ref={ref} className="orb" style={{ width: size, height: size, display: 'block' }}
    {...(label ? { role: 'img', 'aria-label': label } : { role: 'presentation', 'aria-hidden': true })} />;
}
