import type { SVGProps } from 'react';

export type ServiceKind = 'asana' | 'gmail' | 'calendar' | 'drive' | 'github' | 'custom';
/** Which logo to draw for a connection: the known presets by host or name, anything else gets its initial. */
export function kindOf(name: string, url = ''): ServiceKind {
  const hay = `${name} ${url}`.toLowerCase();
  if (hay.includes('asana')) return 'asana';
  if (hay.includes('gmail')) return 'gmail';
  if (hay.includes('calendar')) return 'calendar';
  if (hay.includes('drive')) return 'drive';
  if (hay.includes('github')) return 'github';
  return 'custom';
}
const base = { viewBox: '0 0 24 24', width: 24, height: 24, 'aria-hidden': true, focusable: false } as const;
/** A service's mark inside a rounded tile. Colours come from the brand tokens through the `.svc-*` classes. */
export default function ServiceIcon({ name, url, kind, size = 'md' }: { name: string; url?: string; kind?: ServiceKind; size?: 'md' | 'lg' }) {
  const k = kind ?? kindOf(name, url);
  const svg = (props: SVGProps<SVGSVGElement> & { children: React.ReactNode }) => <svg {...base} {...props} />;
  return <span className={`svc svc-${size}`} aria-hidden="true">{
    k === 'asana' ? svg({ children: <><circle className="f-asana" cx="12" cy="7.2" r="4" /><circle className="f-asana" cx="6.4" cy="16.4" r="4" /><circle className="f-asana" cx="17.6" cy="16.4" r="4" /></> })
    : k === 'gmail' ? svg({ children: <><rect className="s-red" x="3" y="5.5" width="18" height="13" rx="2.6" fill="none" strokeWidth="2" /><path className="s-red" d="M3.6 8l8.4 6.2L20.4 8" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></> })
    : k === 'calendar' ? svg({ children: <><rect className="s-blue" x="3.5" y="4.5" width="17" height="16" rx="3" fill="none" strokeWidth="2" /><path className="s-blue" d="M3.5 9.5h17M8 3v3M16 3v3" fill="none" strokeWidth="2" strokeLinecap="round" /><circle className="f-green" cx="12" cy="14.6" r="2" /></> })
    : k === 'drive' ? svg({ children: <><path className="f-green" d="M8.5 3L2 14.2l3.2 5.6 6.5-11.2z" /><path className="f-yellow" d="M8.5 3h7l6.5 11.2h-7z" /><path className="f-blue" d="M5.2 19.8h13.6l3.2-5.6H8.4z" /></> })
    : k === 'github' ? svg({ children: <path className="f-ink" d="M12 .3a12 12 0 00-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.7-.3-5.500-1.300-5.500-5.900 0-1.300.5-2.400 1.200-3.200-.1-.3-.5-1.500.1-3.200 0 0 1-.3 3.300 1.200a11.500 11.500 0 016 0C17.300 4.800 18.300 5.100 18.300 5.100c.7 1.700.2 2.900.1 3.200.8.800 1.200 1.900 1.200 3.200 0 4.600-2.800 5.600-5.500 5.900.4.400.8 1.100.8 2.200v3.300c0 .3.2.7.8.6A12 12 0 0012 .3" /> })
    : <span className="svc-letter">{(name.trim()[0] ?? '?').toUpperCase()}</span>}</span>;
}
