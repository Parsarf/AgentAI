/** The workspace frame's arithmetic, apart from React so it can be tested on its own: which width class a window is in, how wide each zone may be, and which zones
 *  are docked beside the canvas and which open as sheets. See plans/product/ui-remodel/architecture.md. */

export type WidthClass = 'compact' | 'medium' | 'expanded' | 'large';
export type SideZone = 'context' | 'inspector' | 'assistant';
export type Widths = Record<SideZone, number>;

/** Under 600 px: one zone at a time and a bottom bar. 600-1199: rail, context, canvas. 1200-1499: the inspector docks too. 1500 and up: the assistant docks too. */
export function widthClass(px: number): WidthClass {
  return px < 600 ? 'compact' : px < 1200 ? 'medium' : px < 1500 ? 'expanded' : 'large';
}

export const RAIL = 60;              // the rail's width, px
export const CANVAS_MIN = 440;       // the canvas never gets narrower than this while a zone is docked: that zone becomes a sheet first
export const LIMITS: Record<SideZone, { min: number; max: number; base: number }> = {
  context: { min: 200, max: 420, base: 248 },
  inspector: { min: 300, max: 720, base: 380 },
  assistant: { min: 320, max: 600, base: 360 },
};
export const DEFAULT_WIDTHS: Widths = { context: LIMITS.context.base, inspector: LIMITS.inspector.base, assistant: LIMITS.assistant.base };
export const clampWidth = (zone: SideZone, px: number) => Math.round(Math.min(LIMITS[zone].max, Math.max(LIMITS[zone].min, px)));
/** Keyboard and button steps for resizing a zone. */
export const STEP = 24;

export interface Wanted { context: boolean; inspector: boolean; assistant: boolean }
export interface Placement { docked: Record<SideZone, boolean>; widthClass: WidthClass }

/** Which of the zones the page uses (and the person has open) sit beside the canvas. The width class allows a zone to dock; the canvas minimum then demotes zones to
 *  sheets in this order: the assistant, the inspector, the context column. */
export function place(px: number, wanted: Wanted, widths: Widths): Placement {
  const cls = widthClass(px);
  const allowed: Record<SideZone, boolean> = {
    context: cls !== 'compact',
    inspector: cls === 'expanded' || cls === 'large',
    assistant: cls === 'large',
  };
  const docked: Record<SideZone, boolean> = { context: wanted.context && allowed.context, inspector: wanted.inspector && allowed.inspector, assistant: wanted.assistant && allowed.assistant };
  const room = () => px - (cls === 'compact' ? 0 : RAIL) - (['context', 'inspector', 'assistant'] as SideZone[]).reduce((sum, z) => sum + (docked[z] ? widths[z] : 0), 0);
  for (const zone of ['assistant', 'inspector', 'context'] as SideZone[]) if (room() < CANVAS_MIN && docked[zone]) docked[zone] = false;
  return { docked, widthClass: cls };
}

/** The widest a zone may be made right now without pushing the canvas under its minimum. */
export function roomFor(zone: SideZone, px: number, placement: Placement, widths: Widths): number {
  const others = (['context', 'inspector', 'assistant'] as SideZone[]).filter(z => z !== zone && placement.docked[z]).reduce((sum, z) => sum + widths[z], 0);
  return Math.max(LIMITS[zone].min, Math.min(LIMITS[zone].max, px - RAIL - others - CANVAS_MIN));
}

/** A short, stable, non-reversible tag for a person, so remembered widths are theirs on a shared browser without writing their address into storage. */
export function personTag(email: string): string {
  let h = 2166136261;
  for (let i = 0; i < email.length; i++) { h ^= email.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36);
}
