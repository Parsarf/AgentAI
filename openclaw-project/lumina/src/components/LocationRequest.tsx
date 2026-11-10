import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';

type Pending = { id: string; expires_epoch: number };
type Answer = { status: 'granted' | 'denied' | 'timeout' | 'unavailable'; position?: { latitude: number; longitude: number; accuracy: number } };
type View = { id: string; message: string };

/** Device permission belongs to the customer browser, never the agent browser.
 * Positions stay in this effect until acknowledged, never in browser storage. */
export default function LocationRequest() {
  const [view, setView] = useState<View | null>(null);
  const client = useRef(crypto.randomUUID());
  const share = useRef<() => void>(() => {});
  const skip = useRef<() => void>(() => {});
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let current: Pending | null = null;
    let response: Answer | null = null;
    let attempted = false;
    let asking = false;
    const message = (text: string) => { if (!stopped && current) setView({ id: current.id, message: text }); };
    const start = (manual = false) => {
      if (stopped || !current || (asking && !manual) || response || Date.now() >= current.expires_epoch * 1000) return;
      if (!window.isSecureContext || !navigator.geolocation) { response = { status: 'unavailable' }; return; }
      asking = true; attempted = true;
      const id = current.id;
      message('Waiting for location permission in your browser. Check the location icon in the address bar.');
      try {
        navigator.geolocation.getCurrentPosition(pos => {
          if (stopped || current?.id !== id || response) return;
          asking = false;
          response = { status: 'granted', position: { latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy } };
          message('Sharing your location with this task…');
        }, err => {
          if (stopped || current?.id !== id || response) return;
          asking = false;
          response = { status: err.code === 1 ? 'denied' : err.code === 3 ? 'timeout' : 'unavailable' };
        }, { enableHighAccuracy: false, maximumAge: 0, timeout: 15000 });
      } catch { asking = false; response = { status: 'unavailable' }; }
    };
    share.current = () => start(true);
    skip.current = () => { if (current) { response = { status: 'denied' }; asking = false; message('Continuing without location…'); } };
    const tick = async () => {
      try {
        if (current && Date.now() >= current.expires_epoch * 1000) { current = null; response = null; setView(null); }
        if (document.visibilityState !== 'visible') return;
        const { request } = await api<{ request: Pending | null }>('GET', '/v1/location', undefined, { timeoutMs: 5000 });
        if (stopped) return;
        if (!request || request.id !== current?.id) {
          current = null; response = null; attempted = false; asking = false; setView(null);
        }
        if (!request) return;
        const result = await api<{ accepted: boolean; status: string }>('POST', `/v1/location/${request.id}`, { client_id: client.current, action: 'claim' }, { timeoutMs: 5000 });
        if (stopped) return;
        if (!result.accepted) { current = null; response = null; asking = false; setView(null); return; }
        current = request;
        if (response) {
          const sent = await api<{ accepted: boolean; status: string }>('POST', `/v1/location/${request.id}`, { client_id: client.current, action: 'respond', ...response }, { timeoutMs: 5000 });
          if (stopped) return;
          if (sent.accepted || sent.status !== 'pending') { current = null; response = null; setView(null); }
        } else if (!attempted) {
          message('Lumina needs your location for this task. Your browser controls permission.');
          start();
        }
      } catch { if (!stopped && current) message('Could not send the location response. Retrying…'); }
      finally { if (!stopped) timer = setTimeout(() => { void tick(); }, 5000); }
    };
    void tick();
    // The normal timer keeps running while hidden, without network or prompts.
    // No permission request is issued until the page becomes visible.
    return () => { stopped = true; clearTimeout(timer); current = null; response = null; share.current = () => {}; skip.current = () => {}; };
  }, []);
  if (!view) return null;
  return <section className="notice" aria-label="Location permission">
    <p role="status">{view.message}</p>
    <p className="faint">A one-time device location and its accuracy will be shared with the agent for this task.</p>
    <button className="btn" onClick={() => share.current()}>Share my location</button>{' '}
    <button className="btn tertiary" onClick={() => skip.current()}>Continue without location</button>
  </section>;
}
