import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { clampWidth, DEFAULT_WIDTHS, personTag, place, type Placement, type SideZone, type Wanted, type Widths } from './layout';

/** What the open page uses. A page says it through <Workspace>; the frame decides where each zone is shown. */
export interface Declared { context: boolean; inspector: boolean; assistant: boolean }
/** Which zone is showing as a sheet (only one at a time), or the phone's "More" sheet. */
export type SheetName = SideZone | 'more' | null;

export interface Frame {
  width: number;
  placement: Placement;
  widths: Widths;
  setWidth(zone: SideZone, px: number): void;
  contextOpen: boolean; setContextOpen(open: boolean): void;
  inspectorOpen: boolean; setInspectorOpen(open: boolean): void;      // a docked inspector the person folded away (pages whose inspector is always available)
  assistantOpen: boolean; setAssistantOpen(open: boolean): void;
  sheet: SheetName; setSheet(name: SheetName): void;
  declared: Declared; declare(d: Declared): void;
  /** Show a zone wherever it is: docked zones open in place, the others open as a sheet. */
  reveal(zone: SideZone): void;
  /** Close or fold a zone wherever it is. */
  toggle(zone: SideZone): void;
}
const Ctx = createContext<Frame | null>(null);

const read = (key: string) => { try { return window.localStorage.getItem(key); } catch { return null; } };
const write = (key: string, value: string) => { try { window.localStorage.setItem(key, value); } catch { /* private mode: remembered for this visit only */ } };
const NONE: Declared = { context: false, inspector: false, assistant: false };

export function FrameProvider({ children, person }: { children: ReactNode; person: string }) {
  const tag = useMemo(() => personTag(person), [person]); const key = (name: string) => `lumina.frame.${tag}.${name}`;
  const [width, setW] = useState(() => (typeof window === 'undefined' ? 1600 : window.innerWidth));
  useEffect(() => { const on = () => setW(window.innerWidth); window.addEventListener('resize', on); return () => window.removeEventListener('resize', on); }, []);
  const [widths, setWidths] = useState<Widths>(() => { try { return { ...DEFAULT_WIDTHS, ...JSON.parse(read(key('widths')) ?? '{}') }; } catch { return DEFAULT_WIDTHS; } });
  const [contextOpen, setCO] = useState(() => read(key('context')) !== 'closed');
  const [assistantOpen, setAO] = useState(() => read(key('assistant')) === 'open');
  const [inspectorOpen, setIO] = useState(() => read(key('inspector')) !== 'closed');
  const [sheet, setSheet] = useState<SheetName>(null);
  const [declared, setDeclared] = useState<Declared>(NONE);

  // The page says whether its inspector wants room (it knows whether something is open, and whether the person folded an always-available one away).
  const wanted: Wanted = { context: declared.context && contextOpen, inspector: declared.inspector, assistant: declared.assistant && assistantOpen };
  const placement = useMemo(() => place(width, wanted, widths), [width, wanted.context, wanted.inspector, wanted.assistant, widths]);   // eslint-disable-line react-hooks/exhaustive-deps
  // A zone that just found room to dock closes its sheet; the phone's sheets close when the window grows past the phone width.
  useEffect(() => { if (sheet && sheet !== 'more' && placement.docked[sheet]) setSheet(null); if (sheet === 'more' && placement.widthClass !== 'compact') setSheet(null); }, [placement, sheet]);

  const setWidth = useCallback((zone: SideZone, px: number) => setWidths(prev => { const next = { ...prev, [zone]: clampWidth(zone, px) }; write(key('widths'), JSON.stringify(next)); return next; }), [tag]);   // eslint-disable-line react-hooks/exhaustive-deps
  const setContextOpen = useCallback((open: boolean) => { setCO(open); write(key('context'), open ? 'open' : 'closed'); }, [tag]);   // eslint-disable-line react-hooks/exhaustive-deps
  const setAssistantOpen = useCallback((open: boolean) => { setAO(open); write(key('assistant'), open ? 'open' : 'closed'); if (!open) setSheet(s => (s === 'assistant' ? null : s)); }, [tag]);   // eslint-disable-line react-hooks/exhaustive-deps
  const setInspectorOpen = useCallback((open: boolean) => { setIO(open); write(key('inspector'), open ? 'open' : 'closed'); }, [tag]);   // eslint-disable-line react-hooks/exhaustive-deps
  const declare = useCallback((d: Declared) => setDeclared(prev => (prev.context === d.context && prev.inspector === d.inspector && prev.assistant === d.assistant ? prev : d)), []);

  const value = useMemo<Frame>(() => {
    // Could this zone dock if it were open? (Same rule as `place`, asked with the zone switched on.)
    const couldDock = (zone: SideZone) => place(width, { ...wanted, [zone]: true }, widths).docked[zone];
    const isShowing = (zone: SideZone) => (placement.docked[zone] ? true : sheet === zone);
    return {
      width, placement, widths, setWidth, contextOpen, setContextOpen, inspectorOpen, setInspectorOpen, assistantOpen, setAssistantOpen, sheet, setSheet, declared, declare,
      reveal: zone => {
        if (zone === 'context') setContextOpen(true); else if (zone === 'assistant') setAssistantOpen(true); else setInspectorOpen(true);
        setSheet(couldDock(zone) ? null : zone);
      },
      toggle: zone => {
        if (isShowing(zone)) {
          if (sheet === zone) setSheet(null);
          else if (zone === 'context') setContextOpen(false); else if (zone === 'assistant') setAssistantOpen(false); else setInspectorOpen(false);
        } else {
          if (zone === 'context') setContextOpen(true); else if (zone === 'assistant') setAssistantOpen(true); else setInspectorOpen(true);
          setSheet(couldDock(zone) ? null : zone);
        }
      },
    };
  }, [width, placement, widths, setWidth, contextOpen, setContextOpen, inspectorOpen, setInspectorOpen, assistantOpen, setAssistantOpen, sheet, declared, declare]);   // eslint-disable-line react-hooks/exhaustive-deps
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** The frame, or null where a page renders without one (tests, the component gallery): pages then show every zone in place. */
export const useFrame = () => useContext(Ctx);
