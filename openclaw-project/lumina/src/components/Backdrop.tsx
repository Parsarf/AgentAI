import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import { useSettings } from '../state/settings';

const Globe = lazy(() => import('./Globe'));

class Guard extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function webglAvailable(): boolean {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch { return false; }
}
const lowPowerDevice = () => (navigator as any).deviceMemory ? (navigator as any).deviceMemory < 4 : (navigator.hardwareConcurrency || 4) <= 4 && window.innerWidth < 900;

/** Decorative only: never blocks the interface. Static fallback when WebGL fails, is unavailable, or motion is reduced. */
export default function Backdrop() {
  const { reducedMotion } = useSettings();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const idle = (window as any).requestIdleCallback || ((fn: () => void) => setTimeout(fn, 400));
    idle(() => setReady(webglAvailable()));
  }, []);
  const fallback = <div className="globe-fallback" />;
  return (
    <div className="globe" aria-hidden>
      {ready && !reducedMotion ? (
        <Guard fallback={fallback}>
          <Suspense fallback={fallback}><Globe animate lowPower={lowPowerDevice()} /></Suspense>
        </Guard>
      ) : fallback}
    </div>
  );
}
