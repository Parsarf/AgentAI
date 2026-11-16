import { useLayoutEffect, type ReactNode } from 'react';
import * as I from '../Icons';
import Menu from '../ui/Menu';
import Sheet from '../ui/Sheet';
import Backdrop from '../Backdrop';
import { useFrame } from './FrameProvider';
import Split, { sizeItems } from './Split';
import { Toolbar } from './parts';

export interface WorkspaceProps {
  /** The page's name, shown in the canvas's own toolbar. */
  title: ReactNode;
  /** Controls for the toolbar, right of the title. */
  tools?: ReactNode;
  /** What belongs to the current place (a list of chats, folders, mailboxes). Docked left of the canvas where there is room, a sheet where there is not. */
  context?: ReactNode;
  contextLabel?: string;
  /** Details of what is open. `selection`: shown while something is selected, closed by `onInspectorClose`. `panel`: always available, folded away by the person. */
  inspector?: ReactNode;
  inspectorLabel?: string;
  inspectorKind?: 'selection' | 'panel';
  onInspectorClose?(): void;
  /** The canvas is the height of the window and its content scrolls inside it (lists and grids with their own scrolling). Otherwise the page scrolls. */
  fill?: boolean;
  /** False on the page that IS the assistant (Chat): the shared assistant panel does not open beside it. */
  assistant?: boolean;
  /** The decorative globe behind the canvas (Home). Never on a conversation. */
  backdrop?: boolean;
  className?: string;
  children: ReactNode;
}

/** A page's place in the workspace frame. A page fills the zones; the frame decides where they go (docked, a sheet, or one at a time on a phone). No page writes a
 *  grid of its own. Without a frame above it (tests, the component gallery) every zone is shown in place. */
export default function Workspace({ title, tools, context, contextLabel = 'Side column', inspector, inspectorLabel = 'Details', inspectorKind = 'selection', onInspectorClose,
  fill = false, assistant = true, backdrop = false, className = '', children }: WorkspaceProps) {
  const frame = useFrame();
  const hasContext = context !== undefined && context !== null && context !== false;
  const hasInspector = inspector !== undefined && inspector !== null && inspector !== false;
  const inspectorWants = hasInspector && (inspectorKind === 'selection' || !!frame?.inspectorOpen);
  useLayoutEffect(() => { frame?.declare({ context: hasContext, inspector: inspectorWants, assistant }); }, [frame?.declare, hasContext, inspectorWants, assistant]);   // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => () => frame?.declare({ context: false, inspector: false, assistant: true }), [frame?.declare]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!frame) return <div className={`wsp wsp-plain${fill ? ' wsp-fill' : ''} ${className}`}>
    {hasContext && <aside className="zone zone-context" aria-label={contextLabel}>{context}</aside>}
    <main className="zone zone-canvas"><Toolbar title={title} tools={tools} />{children}</main>
    {hasInspector && <aside className="zone zone-inspector" aria-label={inspectorLabel}>{inspector}</aside>}
  </div>;

  const { placement, widths } = frame;
  const contextDocked = hasContext && placement.docked.context;
  const inspectorDocked = hasInspector && placement.docked.inspector;
  const contextShowing = contextDocked || (hasContext && frame.sheet === 'context');
  const inspectorShowing = inspectorDocked || (hasInspector && (inspectorKind === 'selection' || frame.sheet === 'inspector'));
  const zoneTools = <>
    {hasContext && <button type="button" className="iconbtn small ghost wsp-zone-toggle" aria-label={contextShowing ? `Hide ${contextLabel.toLowerCase()}` : `Show ${contextLabel.toLowerCase()}`}
      aria-expanded={contextShowing} title={`${contextShowing ? 'Hide' : 'Show'} ${contextLabel.toLowerCase()} (Ctrl+B)`} onClick={() => frame.toggle('context')}><I.Panel width={18} height={18} /></button>}
  </>;
  const inspectorTool = hasInspector && inspectorKind === 'panel' && <button type="button" className="iconbtn small ghost wsp-zone-toggle" aria-label={inspectorShowing ? `Hide ${inspectorLabel.toLowerCase()}` : `Show ${inspectorLabel.toLowerCase()}`}
    aria-expanded={inspectorShowing} title={`${inspectorShowing ? 'Hide' : 'Show'} ${inspectorLabel.toLowerCase()}`} onClick={() => frame.toggle('inspector')}><I.Panel width={18} height={18} style={{ transform: 'scaleX(-1)' }} /></button>;
  const closeInspector = () => { if (inspectorKind === 'selection') onInspectorClose?.(); else frame.toggle('inspector'); };

  return <div className={`wsp${fill ? ' wsp-fill' : ''}${contextDocked ? ' has-context' : ''}${inspectorDocked ? ' has-inspector' : ''} ${className}`}
    style={{ ['--wsp-context' as string]: `${widths.context}px`, ['--wsp-inspector' as string]: `${widths.inspector}px` }}>
    {contextDocked && <>
      <aside className="zone zone-context" aria-label={contextLabel}>
        <div className="zone-head"><span className="zone-label">{contextLabel}</span>
          <Menu label={`${contextLabel} options`} align="end" items={[...sizeItems(frame, 'context'), { id: 'hide', label: `Hide ${contextLabel.toLowerCase()}`, separatorBefore: true, onSelect: () => frame.setContextOpen(false) }]}
            trigger={({ open, props }) => <button type="button" className="iconbtn small ghost" aria-label={`${contextLabel} options`} aria-expanded={open} {...props}><I.More width={16} height={16} /></button>} /></div>
        <div className="zone-body">{context}</div>
      </aside>
      <Split zone="context" edge="end" />
    </>}
    <main className="zone zone-canvas" id="canvas" tabIndex={-1}>
      {backdrop && <Backdrop />}
      <Toolbar title={title} leading={zoneTools} tools={<>{tools}{inspectorTool}</>} />
      {children}
    </main>
    {inspectorDocked && <>
      <Split zone="inspector" edge="start" />
      <aside className="zone zone-inspector" aria-label={inspectorLabel}>
        <div className="zone-head"><span className="zone-label">{inspectorLabel}</span>
          <Menu label={`${inspectorLabel} options`} align="end" items={sizeItems(frame, 'inspector')}
            trigger={({ open, props }) => <button type="button" className="iconbtn small ghost" aria-label={`${inspectorLabel} options`} aria-expanded={open} {...props}><I.More width={16} height={16} /></button>} />
          <button type="button" className="iconbtn small ghost" aria-label={`Close ${inspectorLabel.toLowerCase()}`} onClick={closeInspector}><I.Plus width={16} height={16} className="rot45" /></button></div>
        <div className="zone-body">{inspector}</div>
      </aside>
    </>}
    {hasContext && !contextDocked && frame.sheet === 'context' && <Sheet side="left" title={contextLabel} className="zone-sheet" onClose={() => frame.setSheet(null)}>{context}</Sheet>}
    {hasInspector && !inspectorDocked && inspectorShowing && <Sheet side="right" title={inspectorLabel} className="zone-sheet zone-sheet-wide" onClose={() => (inspectorKind === 'selection' ? onInspectorClose?.() : frame.setSheet(null))}>{inspector}</Sheet>}
  </div>;
}
