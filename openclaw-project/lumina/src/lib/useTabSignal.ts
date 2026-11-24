import { useEffect, useRef, useState } from 'react';
import { TAB_NAME, tabIcon, tabSignal, tabTitle } from './tabSignal';
import type { TaskSummary } from './work';

const open = (t: Pick<TaskSummary, 'phase'>) => t.phase !== 'ended';

/** Keeps the tab's title and icon in step with the shared task state: "Needs you" while a task waits for the person, "Done" when a task that was going ended while the tab was
 *  not being looked at (cleared when they look). Leaves the tab as it found it when unmounted. */
export function useTabSignal(tasks: Pick<TaskSummary, 'id' | 'phase' | 'attention'>[]) {
  const [unseen, setUnseen] = useState(false); const going = useRef<Set<string>>(new Set());
  useEffect(() => {
    const ended = tasks.some(t => !open(t) && going.current.has(t.id));
    going.current = new Set(tasks.filter(open).map(t => t.id));
    if (ended && document.hidden) setUnseen(true);
  }, [tasks]);
  useEffect(() => {
    const looked = () => { if (!document.hidden) setUnseen(false); };
    document.addEventListener('visibilitychange', looked); window.addEventListener('focus', looked);
    return () => { document.removeEventListener('visibilitychange', looked); window.removeEventListener('focus', looked); };
  }, []);
  const needs = tasks.filter(t => t.attention).length; const signal = tabSignal(needs, unseen);
  useEffect(() => {
    document.title = tabTitle(signal, needs);
    let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) { link = document.createElement('link'); link.rel = 'icon'; link.type = 'image/svg+xml'; document.head.appendChild(link); }
    link.href = tabIcon(signal);
  }, [signal, needs]);
  useEffect(() => () => { document.title = TAB_NAME; }, []);
}
