import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';

export interface OwnBrowser {
  /** The browser service answered and the feature is on for everyone. Until then nothing about it is shown. */
  available: boolean;
  /** The customer's switch: run browser tasks in my own Chrome. */
  use: boolean;
  /** The Lumina extension in one of their browsers is on and connected right now. */
  connected: boolean;
  /** At least one browser has been paired. */
  paired: boolean;
  ready: boolean;
}

const POLL_MS = 20_000;
const NONE: OwnBrowser = { available: false, use: false, connected: false, paired: false, ready: false };

/** The state behind the browser icon at the top of every chat, kept fresh while the tab is visible. `setUse` flips the switch at once and puts it back if the server says no. */
export function useOwnBrowser() {
  const [state, setState] = useState<OwnBrowser>(NONE);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const refresh = useCallback(async () => {
    try {
      const r = await api<{ available: boolean; use: boolean; connected: boolean; devices: unknown[] }>('GET', '/v1/devices');
      if (alive.current) setState({ available: !!r.available, use: !!r.use, connected: !!r.connected, paired: (r.devices ?? []).length > 0, ready: true });
    } catch { if (alive.current) setState({ ...NONE, ready: true }); }
  }, []);

  useEffect(() => {
    void refresh();
    const tick = () => { if (document.visibilityState === 'visible') void refresh(); };
    const timer = setInterval(tick, POLL_MS);
    document.addEventListener('visibilitychange', tick);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
  }, [refresh]);

  const setUse = useCallback(async (on: boolean) => {
    setState(s => ({ ...s, use: on }));
    try { await api('POST', '/v1/devices/use', { on }); await refresh(); return true; }
    catch { if (alive.current) setState(s => ({ ...s, use: !on })); return false; }
  }, [refresh]);

  return { ...state, setUse, refresh };
}

/** What the icon's tooltip and screen-reader label say. The colour dot is never the only signal. */
export function describeOwnBrowser(s: Pick<OwnBrowser, 'use' | 'connected' | 'paired'>): { state: 'off' | 'setup' | 'waiting' | 'live'; label: string } {
  if (!s.use) return { state: 'off', label: 'Use my own browser: off. Lumina uses its own browser. Click to turn on.' };
  if (!s.paired) return { state: 'setup', label: 'Use my own browser: on, but no browser is connected yet. Click to turn off; open Settings to connect one.' };
  if (!s.connected) return { state: 'waiting', label: 'Use my own browser: on, waiting for the Lumina extension in Chrome. Until it is on, tasks use Lumina’s browser. Click to turn off.' };
  return { state: 'live', label: 'Use my own browser: on. Browser tasks run in your Chrome. Click to turn off.' };
}
