import type { ComponentType, SVGProps } from 'react';
import { Link, useLocation } from 'react-router-dom';
import * as I from '../Icons';
import Menu from '../ui/Menu';
import SafetyButton from '../safety/SafetyButton';
import Sheet from '../ui/Sheet';
import type { AppInfo } from '../../lib/api';
import { displayName } from '../../lib/format';
import { useData } from '../../state/data';
import { useSettings } from '../../state/settings';
import { useWork } from '../../state/work';
import { useFrame } from './FrameProvider';
import { keyWords, shortcut } from '../../lib/shortcuts';

type Feature = 'dashboard' | 'files';
export interface Place { to: string; label: string; icon: ComponentType<SVGProps<SVGSVGElement>>; group: 'main' | 'work' | 'activity' | 'bottom'; feature?: Feature; also?: string[]; key: string }
/** Every place of the app, in rail order. `also` lists the addresses that belong to the place (Chat history is part of Chat, Integrations part of Settings). `key` is the
 *  letter after `g` that goes there. */
export const PLACES: Place[] = [
  { to: '/home', label: 'Home', icon: I.Home, group: 'main', key: 'h' },
  { to: '/chat', label: 'Chat', icon: I.Chat, group: 'main', also: ['/history'], key: 'c' },
  { to: '/inbox', label: 'Inbox', icon: I.Mail, group: 'work', feature: 'dashboard', key: 'i' },
  { to: '/calendar', label: 'Calendar', icon: I.Calendar, group: 'work', feature: 'dashboard', key: 'l' },
  { to: '/files', label: 'Files', icon: I.Files, group: 'work', feature: 'files', also: ['/knowledge'], key: 'f' },
  { to: '/activity', label: 'Activity', icon: I.Tasks, group: 'activity', also: ['/tasks', '/live', '/automations'], key: 'a' },
  { to: '/settings', label: 'Settings', icon: I.Gear, group: 'bottom', also: ['/integrations'], key: 's' },
];
export const available = (app: AppInfo | null) => PLACES.filter(p => !p.feature || !!app?.features[p.feature]);
const belongs = (p: Place, path: string) => [p.to, ...(p.also ?? [])].some(to => path === to || path.startsWith(to + '/')) || (p.to === '/chat' && path === '/');
export const placeFor = (path: string) => PLACES.find(p => belongs(p, path));

function Entry({ place, count, onPick }: { place: Place; count?: number; onPick?(): void }) {
  const { pathname } = useLocation(); const here = belongs(place, pathname);
  const words = count ? `${place.label}, ${count} waiting for you` : place.label;
  return <Link to={place.to} className="rail-item" aria-current={here ? 'page' : undefined} aria-label={words} onClick={onPick}>
    <place.icon width={20} height={20} aria-hidden="true" /><span className="rail-tip" aria-hidden="true">{place.label}{count ? ` · ${count} waiting` : ''}{shortcut(`go-${place.to.slice(1)}`) && <kbd className="kbd">{keyWords(shortcut(`go-${place.to.slice(1)}`)!.keys)}</kbd>}</span>
    {count ? <span className="rail-count" aria-hidden="true" data-layout-allow="count-badge">{count > 99 ? '99+' : count}</span> : null}
  </Link>;
}

function Account({ side = 'top' }: { side?: 'top' | 'bottom' }) {
  const { app, signOut } = useData(); const { reducedMotion, setReducedMotion } = useSettings(); const name = displayName(app?.user.email ?? '');
  const plan = app?.features.billing_mode === 'paid_required' ? 'Subscriber' : app?.features.billing_mode === 'open' ? 'Free access' : 'Private beta';
  return <Menu label="Account" heading={`${name} · ${plan}`} side={side} items={[
    { id: 'motion', label: reducedMotion ? 'Turn animations on' : 'Reduce motion', onSelect: () => setReducedMotion(!reducedMotion) },
    { id: 'out', label: 'Sign out', icon: <I.Out width={18} height={18} />, separatorBefore: true, onSelect: () => { void signOut(); } },
  ]} trigger={({ open, props }) => <button type="button" className="rail-item rail-avatar" aria-label={`Account: ${name}`} aria-expanded={open} {...props}>
    <span className="avatar" aria-hidden="true">{name[0]}</span><span className="rail-tip" aria-hidden="true">{name}</span></button>} />;
}

/** The rail: every main place one click away, dimmer than the canvas (it is chrome, not content). Home and Chat; Inbox, Calendar and Files as one group; Activity with
 *  the count of what waits for the person (the old bell); Settings and the account at the bottom. A place whose feature is off has no entry. */
export function NavRail({ onSearch }: { onSearch(): void }) {
  const { app } = useData(); const { attention } = useWork(); const frame = useFrame();
  const places = available(app);
  const group = (g: Place['group']) => places.filter(p => p.group === g).map(p => <Entry key={p.to} place={p} count={p.to === '/activity' ? attention : 0} />);
  return <nav className="rail-nav" aria-label="Primary">
    <div className="rail-brand" aria-hidden="true"><I.Spark /></div>
    <div className="rail-group">{group('main')}</div>
    {places.some(p => p.group === 'work') && <div className="rail-group">{group('work')}</div>}
    <div className="rail-group">{group('activity')}</div>
    <div className="rail-end">
      <button type="button" className="rail-item" aria-label="Search and commands" onClick={onSearch}><I.Search width={20} height={20} aria-hidden="true" /><span className="rail-tip" aria-hidden="true">Search and commands <kbd className="kbd">{keyWords('mod+k')}</kbd></span></button>
      {frame?.declared.assistant && <button type="button" className="rail-item" aria-label="Assistant" aria-pressed={frame.placement.docked.assistant || frame.sheet === 'assistant'}
        onClick={() => frame.toggle('assistant')}><I.Spark width={20} height={20} aria-hidden="true" /><span className="rail-tip" aria-hidden="true">Assistant <kbd className="kbd">{keyWords('mod+j')}</kbd></span></button>}
      <SafetyButton />
      {group('bottom')}
      <Account />
    </div>
  </nav>;
}

/** Under 600 px: a bar at the bottom with five entries (hidden menus are used less). Home, Chat, Inbox, Calendar and More; without mail and calendar, Files and
 *  Activity take their places. More holds everything else. */
export function BottomBar({ onSearch }: { onSearch(): void }) {
  const { app } = useData(); const { attention } = useWork(); const frame = useFrame(); const { pathname } = useLocation();
  const places = available(app); const first = places.filter(p => p.group !== 'bottom').slice(0, 4); const rest = places.filter(p => !first.includes(p));
  const moreHere = rest.some(p => belongs(p, pathname));
  return <>
    <nav className="bottom-bar" aria-label="Primary">
      {first.map(p => <Entry key={p.to} place={p} count={p.to === '/activity' ? attention : 0} />)}
      <button type="button" className="rail-item" aria-label={attention && !first.some(p => p.to === '/activity') ? `More, ${attention} waiting for you` : 'More'} aria-expanded={frame?.sheet === 'more'}
        aria-current={moreHere ? 'page' : undefined} onClick={() => frame?.setSheet(frame.sheet === 'more' ? null : 'more')}><I.More width={20} height={20} aria-hidden="true" /><span className="rail-tip" aria-hidden="true">More</span></button>
    </nav>
    {frame?.sheet === 'more' && <Sheet side="bottom" title="More" onClose={() => frame.setSheet(null)}>
      <div className="more-list">
        {rest.map(p => <Entry key={p.to} place={p} count={p.to === '/activity' ? attention : 0} onPick={() => frame.setSheet(null)} />)}
        <button type="button" className="rail-item" onClick={() => { frame.setSheet(null); onSearch(); }}><I.Search width={20} height={20} aria-hidden="true" /><span className="rail-tip">Search</span></button>
        {frame.declared.assistant && <button type="button" className="rail-item" onClick={() => frame.reveal('assistant')}><I.Spark width={20} height={20} aria-hidden="true" /><span className="rail-tip">Assistant</span></button>}
        <SafetyButton />
        <Account side="top" />
      </div>
    </Sheet>}
  </>;
}
