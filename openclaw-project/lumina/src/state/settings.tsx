import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type Contrast = 'system' | 'normal' | 'more';
interface Settings { reducedMotion: boolean; compact: boolean; contrast: Contrast; setReducedMotion(v: boolean): void; setCompact(v: boolean): void; setContrast(v: Contrast): void }
const Ctx = createContext<Settings>(null as any);

function read(key: string, fallback: boolean): boolean {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v === '1'; } catch { return fallback; }
}
function write(key: string, v: boolean) { try { localStorage.setItem(key, v ? '1' : '0'); } catch { /* private mode */ } }

export function SettingsProvider({ children }: { children: ReactNode }) {
  const system = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const [reducedMotion, setRM] = useState(() => read('lumina.reducedMotion', system));
  const [compact, setC] = useState(() => read('lumina.compact', false));
  const [contrast, setCt] = useState<Contrast>(() => { try { const v = localStorage.getItem('lumina.contrast'); return v === 'more' || v === 'normal' ? v : 'system'; } catch { return 'system'; } });
  useEffect(() => {
    document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full';
    document.documentElement.dataset.compact = String(compact);
    // No attribute means "like this device": the theme follows prefers-contrast (styles/theme.css).
    if (contrast === 'system') delete document.documentElement.dataset.contrast; else document.documentElement.dataset.contrast = contrast;
  }, [reducedMotion, compact, contrast]);
  const value = useMemo<Settings>(() => ({
    reducedMotion, compact, contrast,
    setReducedMotion: v => { write('lumina.reducedMotion', v); setRM(v); },
    setCompact: v => { write('lumina.compact', v); setC(v); },
    setContrast: v => { try { localStorage.setItem('lumina.contrast', v); } catch { /* private mode */ } setCt(v); },
  }), [reducedMotion, compact, contrast]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
const NONE: Settings = { reducedMotion: false, compact: false, contrast: 'system', setReducedMotion: () => {}, setCompact: () => {}, setContrast: () => {} };
/** The person's display settings; defaults where no provider is above (tests, the component gallery). */
export const useSettings = () => useContext(Ctx) ?? NONE;
