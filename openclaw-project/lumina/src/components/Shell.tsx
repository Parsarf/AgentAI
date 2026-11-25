import { useTabSignal } from '../lib/useTabSignal';
import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import LocationRequest from './LocationRequest';
import { FrameProvider, useFrame } from './frame/FrameProvider';
import { BottomBar, NavRail } from './frame/Nav';
import { CommandBar, CommandsProvider, HelpSheet, useCommandBar, useFrameKeys } from './frame/CommandBar';
import { AssistantProvider, AssistantZone } from './frame/Assistant';
import { useData } from '../state/data';
import { useWork } from '../state/work';

function Body() {
  const frame = useFrame()!; const { pathname } = useLocation();
  useEffect(() => { frame.setSheet(null); }, [pathname]);   // eslint-disable-line react-hooks/exhaustive-deps -- a sheet belongs to the page it was opened on
  const { app } = useData(); const { tasks } = useWork();
  useTabSignal(tasks);
  const c = useCommandBar()!; useFrameKeys();
  const compact = frame.placement.widthClass === 'compact';
  // The width class is on the document root too: sheets, dialogs and menus are portalled outside .frame, and the phone rules (44px targets) must reach them.
  const width = frame.placement.widthClass;
  useEffect(() => { const root = document.documentElement; root.classList.add(`w-${width}`); return () => root.classList.remove(`w-${width}`); }, [width]);
  return (
    <div className={`frame w-${frame.placement.widthClass}`}>
      <a className="skip" href="#canvas" data-layout-allow="skip-link">Skip to content</a>
      {compact ? <BottomBar onSearch={() => c.setOpen(true)} /> : <NavRail onSearch={() => c.setOpen(true)} />}
      <div className="frame-work">
        {tasks.some(t => t.phase === 'working' || t.phase === 'needs_you' || t.phase === 'starting') && <LocationRequest key={app?.user.email} />}
        <Outlet />
      </div>
      <AssistantZone />
      {c.open && <CommandBar onClose={() => c.setOpen(false)} />}
      {c.help && <HelpSheet onClose={() => c.setHelp(false)} />}
    </div>);
}

/** The workspace frame around every page: the rail (a bottom bar on a phone), the page's own zones, and the shared assistant panel. */
export default function Shell() {
  const { app } = useData();
  return <FrameProvider person={app?.user.email ?? ''}><AssistantProvider><CommandsProvider><Body /></CommandsProvider></AssistantProvider></FrameProvider>;
}
