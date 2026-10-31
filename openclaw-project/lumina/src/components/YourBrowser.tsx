import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';

interface Device { device_id: string; label: string; created: number; last_seen: number; connected: boolean }
interface Pairing { display: string; code: string; expires_at: number; handed: boolean }

/** The Lumina extension's id, built in once the extension is published; without it the customer types the code into the extension's popup instead. */
const EXTENSION_ID = (import.meta.env?.VITE_LUMINA_EXTENSION_ID as string | undefined) || '';
const POLL_MS = 2000;

/** Give the pairing code to the extension, if it is installed and its id is known. Resolves true only when the extension said it took it. Carries nothing but the code. */
export function handOver(code: string, id: string = EXTENSION_ID): Promise<boolean> {
  const runtime = (globalThis as any).chrome?.runtime;
  if (!id || typeof runtime?.sendMessage !== 'function') return Promise.resolve(false);
  return new Promise(resolve => {
    try { runtime.sendMessage(id, { type: 'pair', code }, (reply: any) => { void runtime.lastError; resolve(!!reply?.ok); }); } catch { resolve(false); }
  });
}

const seen = (d: Device) => (d.connected ? 'Connected now' : d.last_seen ? `Last seen ${new Date(d.last_seen * 1000).toLocaleDateString()}` : 'Not seen yet');

/** Settings card: pair the Lumina extension in your own Chrome and manage the browsers. The on/off switch itself is the icon at the top of every chat. Shown only while the browser service says the feature is available. */
export default function YourBrowser() {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [available, setAvailable] = useState(false);
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const load = useCallback(async () => {
    try {
      const r = await api<{ available: boolean; devices: Device[] }>('GET', '/v1/devices');
      if (!mounted.current) return [];
      setAvailable(!!r.available); setDevices(r.devices ?? []);
      return r.devices ?? [];
    } catch { if (mounted.current) { setAvailable(false); setDevices([]); } return []; }
  }, []);
  useEffect(() => { void load(); }, [load]);

  // While a code is on screen, watch for the browser to come up; stop when it does or the code runs out.
  useEffect(() => {
    if (!pairing) return;
    const timer = setInterval(async () => {
      const list = await load();
      if (list.some(d => d.connected) || Date.now() >= pairing.expires_at) { if (mounted.current) setPairing(null); }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [pairing, load]);

  async function connect() {
    setBusy(true); setProblem('');
    try {
      const r = await api<{ code: string; display: string; expires_in: number }>('POST', '/v1/devices/pair', {});
      const handed = await handOver(r.code);
      if (mounted.current) setPairing({ display: r.display, code: r.code, expires_at: Date.now() + r.expires_in * 1000, handed });
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      setProblem(status === 429 ? 'Too many codes just now. Try again in a few minutes.' : status === 503 ? 'Lumina cannot reach the browser service right now. Try again shortly.' : 'Could not get a code. Try again.');
    } finally { if (mounted.current) setBusy(false); }
  }

  async function remove(d: Device) {
    setBusy(true); setProblem('');
    try { await api('POST', `/v1/devices/${d.device_id}/revoke`, {}); await load(); }
    catch { setProblem('Could not remove that browser. Try again.'); }
    finally { if (mounted.current) setBusy(false); }
  }

  useEffect(() => {      // the chat-header switch sends people here (#your-browser) when there is nothing to run on yet; the router does not scroll to a hash by itself
    if (devices !== null && available && window.location.hash === '#your-browser') document.getElementById('your-browser')?.scrollIntoView?.({ block: 'start' });
  }, [devices, available]);

  if (devices === null || !available) return null;
  return (
    <section className="panel card" id="your-browser" style={{ marginBottom: 14 }} aria-labelledby="your-browser-h"><h2 id="your-browser-h">Your browser</h2>
      <p className="muted" style={{ marginTop: 10 }}>Let Lumina do browsing tasks in a tab of your own Chrome. It opens its own tabs, grouped as “Lumina”, and does not touch your other tabs. You can stop it at any time from the extension or with Cancel on Chrome’s “debugging” bar. Switch it on or off with the browser icon at the top of any chat.</p>
      <p className="muted" style={{ marginTop: 8 }}>While it is on, Lumina can use any site open in those tabs, including ones you are signed in to. For that reason we suggest installing the extension in a separate Chrome profile used only for Lumina.</p>
      {devices.length === 0 ? <p className="faint" style={{ marginTop: 10 }}>No browser connected.</p> : (
        <ul className="device-list" aria-label="Connected browsers">{devices.map(d => (
          <li key={d.device_id} className="device-row"><span className="device-name">{d.label}</span>
            <span className={`badge${d.connected ? ' success' : ''}`}>{seen(d)}</span>
            <button className="btn small danger" disabled={busy} onClick={() => remove(d)} aria-label={`Remove ${d.label}`}>Remove</button></li>))}</ul>)}
      {pairing && (
        <div className="pair-box" role="status" aria-live="polite">
          <p className="pair-code" aria-label={`Pairing code ${pairing.code.split('').join(' ')}`}>{pairing.display}</p>
          <p className="muted">{pairing.handed ? 'Sent to the Lumina extension. Your browser should connect in a few seconds.' : 'Type this code into the Lumina extension in Chrome (click its icon). It works once, for ten minutes.'}</p>
        </div>)}
      {problem && <p className="muted" role="alert" style={{ marginTop: 10 }}>{problem}</p>}
      <p style={{ marginTop: 12 }}><button className="btn primary" disabled={busy} aria-busy={busy} onClick={connect}>{devices.length ? 'Connect another browser' : 'Connect a browser'}</button></p>
    </section>);
}
