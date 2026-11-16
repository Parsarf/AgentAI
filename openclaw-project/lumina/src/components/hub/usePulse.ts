import { useEffect, useRef } from 'react';
import { api } from '../../lib/api';

/** Keeps an open Inbox or Calendar live. Every few seconds, while the tab is visible, it asks the server one cheap question: has anything changed? Only when the answer's
 *  mark differs from the last one does it call `onChange`, which reloads what is on screen. A hidden tab asks nothing, and asks at once when it is shown again. */
export function usePulse(on: boolean, onChange: () => void, seconds = 8) {
  const mark = useRef<string | null>(null); const change = useRef(onChange); change.current = onChange;
  useEffect(() => {
    if (!on) return;
    let alive = true;
    const ask = async () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      try {
        const r = await api<{ mark: string }>('GET', '/v1/hub/pulse');
        if (!alive) return;
        if (mark.current !== null && r.mark !== mark.current) change.current();
        mark.current = r.mark;
      } catch { /* a missed beat is not an error to show: the next one tries again */ }
    };
    void ask();
    const timer = window.setInterval(ask, seconds * 1000);
    const shown = () => { if (document.visibilityState === 'visible') void ask(); };
    document.addEventListener('visibilitychange', shown);
    return () => { alive = false; window.clearInterval(timer); document.removeEventListener('visibilitychange', shown); };
  }, [on, seconds]);
}
