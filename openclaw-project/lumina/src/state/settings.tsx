import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type Theme = 'obsidian' | 'parchment';
interface Settings { reducedMotion: boolean; compact: boolean; sidebarOpen: boolean; theme: Theme; setTheme(v: Theme): void; setReducedMotion(v: boolean): void; setCompact(v: boolean): void; setSidebarOpen(v: boolean): void }
const Ctx = createContext<Settings>(null as any);

function read(key: string, fallback: boolean): boolean {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v === '1'; } catch { return fallback; }
}
function write(key: string, v: boolean) { try { localStorage.setItem(key, v ? '1' : '0'); } catch { /* private mode */ } }

/** The dark world is the default; parchment is the owner's alternative. Read before first paint (main.tsx) so nothing flashes. */
export function storedTheme(): Theme {
  try { return localStorage.getItem('lumina.theme') === 'parchment' ? 'parchment' : 'obsidian'; } catch { return 'obsidian'; }
}
export function applyTheme(t: Theme) { document.documentElement.dataset.theme = t; }

export function SettingsProvider({ children }: { children: ReactNode }) {
  const system = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const [reducedMotion, setRM] = useState(() => read('lumina.reducedMotion', system));
  const [compact, setC] = useState(() => read('lumina.compact', false));
  const [theme, setT] = useState<Theme>(storedTheme);
  const [sidebarOpen, setSO] = useState(() => read('lumina.sidebar', true));
  useEffect(() => { applyTheme(theme); }, [theme]);
  useEffect(() => {
    document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full';
    document.documentElement.dataset.compact = String(compact);
  }, [reducedMotion, compact]);
  const value = useMemo<Settings>(() => ({
    reducedMotion, compact, sidebarOpen, theme,
    setTheme: v => { try { localStorage.setItem('lumina.theme', v); } catch { /* private mode */ } setT(v); },
    setReducedMotion: v => { write('lumina.reducedMotion', v); setRM(v); },
    setCompact: v => { write('lumina.compact', v); setC(v); },
    setSidebarOpen: v => { write('lumina.sidebar', v); setSO(v); },
  }), [reducedMotion, compact, sidebarOpen, theme]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export const useSettings = () => useContext(Ctx);
