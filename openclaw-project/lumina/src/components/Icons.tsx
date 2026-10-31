import type { ReactNode, SVGProps } from 'react';

const base = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const;
const make = (d: ReactNode) => (p: SVGProps<SVGSVGElement>) => <svg {...base} {...p}>{d}</svg>;

export const Home = make(<><path d="M3 11l9-7 9 7" /><path d="M5 10v10h5v-6h4v6h5V10" /></>);
export const Chat = make(<path d="M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z" />);
export const Tasks = make(<><path d="M9 6h12M9 12h12M9 18h12" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></>);
export const OwnBrowser = make(<><rect x="3" y="4.5" width="18" height="14" rx="3" /><path d="M3 9h18" /><path d="M13 12.2l5.6 2.2-2.4 1-1 2.4z" fill="currentColor" /></>);
export const Browser = make(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18" /></>);
export const Files = make(<><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z" /><path d="M14 3v5h5" /></>);
export const Calendar = make(<><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M8 3v4M16 3v4M4 10h16" /></>);
export const Bolt = make(<path d="M13 2L5 14h6l-1 8 8-12h-6z" />);
export const Cube = make(<><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" /><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5" /></>);
export const Gear = make(<><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 00-2-1.2L14.2 3h-4l-.4 2.6a7 7 0 00-2 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 005 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-.9a7 7 0 002 1.2l.4 2.6h4l.4-2.6a7 7 0 002-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z" /></>);
export const Search = make(<><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>);
export const Bell = make(<><path d="M6 9a6 6 0 1112 0c0 6 2.5 7 2.5 7h-17S6 15 6 9z" /><path d="M10 20a2 2 0 004 0" /></>);
export const Motion = make(<><path d="M4 12c3-6 5-6 8 0s5 6 8 0" /></>);
export const Mic = make(<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" /></>);
export const Up = make(<path d="M12 19V5M5 12l7-7 7 7" />);
export const Plus = make(<path d="M12 5v14M5 12h14" />);
export const Code = make(<path d="M8 8l-5 4 5 4M16 8l5 4-5 4M14 5l-4 14" />);
export const Chart = make(<path d="M5 20V11M12 20V5M19 20v-6" strokeWidth="2.4" />);
export const Clip = make(<path d="M20 11l-8.5 8.5a5 5 0 01-7-7L13 4a3.5 3.5 0 015 5l-8.5 8.5a2 2 0 01-3-3L14 7" />);
export const Chevron = make(<path d="M9 6l6 6-6 6" />);
export const Check = make(<path d="M5 12.5l4.5 4.5L19 7.5" strokeWidth="2.4" />);
export const Out = make(<path d="M15 4h5v5M20 4l-9 9M10 6H5v13h13v-5" />);
export const Spark = (p: SVGProps<SVGSVGElement>) => (
  <svg width="30" height="30" viewBox="0 0 32 32" fill="currentColor" aria-hidden {...p}><path d="M16 1c1 8 3 12 15 15-12 3-14 7-15 15-1-8-3-12-15-15C13 13 15 9 16 1z" /></svg>);
export const Panel = make(<><rect x="3.5" y="4.5" width="17" height="15" rx="3" /><path d="M9.5 4.5v15" /></>);
export const Edit = make(<><path d="M4 20h4L19 9a2.8 2.8 0 00-4-4L4 16v4z" /></>);
export const ChevronDown = make(<path d="M6 9l6 6 6-6" />);
export const Grid = make(<><rect x="4" y="4" width="6.5" height="6.5" rx="1.8" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8" /></>);
export const More = make(<><circle cx="5.5" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="18.5" cy="12" r="1.2" /></>);
