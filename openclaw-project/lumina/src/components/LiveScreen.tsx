import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { FALLBACK_AFTER, frameBackoff, toBrowser } from '../lib/live';

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/**
 * The page Lumina is working on, live. One request at a time asks the frame gateway for "the newest picture, if it changed"; the server
 * holds the question for a couple of seconds, so changes arrive at once and nothing is sent while the page is still. A slow connection
 * simply skips frames (it never queues them). Hidden tab = no requests, and the server stops capturing a few seconds later.
 * Frames are painted on a canvas (the page's security policy allows no blob images). If the live path is unavailable it shows `fallback`.
 */
export default function LiveScreen({ id, enabled, fallback, interactive, onPoint, onWheel }: {
  id: string; enabled: boolean; fallback: string | null; interactive: boolean; onPoint(p: { x: number; y: number }): void; onWheel?(dir: 'up' | 'down'): void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null); const img = useRef<HTMLImageElement>(null);
  const [state, setState] = useState<'connecting' | 'live' | 'snapshots'>('connecting'); const lastWheel = useRef(0);
  const [taps, setTaps] = useState<{ id: number; x: number; y: number }[]>([]); const tapId = useRef(0);

  useEffect(() => {
    if (!enabled) return; let stop = false; const ac = new AbortController();
    setState('connecting');
    (async () => {
      let ticket: { value: string; path: string; until: number } | null = null; let seq = '0'; let failures = 0;
      while (!stop) {
        if (document.hidden) { await sleep(500); continue; }
        try {
          if (!ticket || Date.now() > ticket.until) {
            const t = await api<{ ticket: string; path: string; expires_in: number }>('POST', `/v1/browse/${id}/live`, {});
            ticket = { value: t.ticket, path: t.path, until: Date.now() + Math.max(10, t.expires_in - 20) * 1000 };
          }
          const r = await fetch(`${ticket.path}?t=${encodeURIComponent(ticket.value)}&after=${seq}`, { cache: 'no-store', signal: ac.signal, credentials: 'omit' });
          if (stop) return;
          if (r.status === 200) {
            const bitmap = await createImageBitmap(await r.blob()); const c = canvas.current;
            if (c) {
              if (c.width !== bitmap.width || c.height !== bitmap.height) { c.width = bitmap.width; c.height = bitmap.height; }
              c.getContext('2d')?.drawImage(bitmap, 0, 0);
            }
            bitmap.close?.(); seq = r.headers.get('X-Seq') ?? seq; failures = 0; setState('live');
          } else if (r.status === 204) { failures = 0; }
          else { if (r.status === 403) ticket = null; failures += 1; }
        } catch { if (stop) return; failures += 1; ticket = failures > 1 ? null : ticket; }
        if (failures > 0) { if (failures >= FALLBACK_AFTER) setState('snapshots'); await sleep(frameBackoff(failures)); }
      }
    })();
    return () => { stop = true; ac.abort(); };
  }, [id, enabled]);

  const point = (e: React.MouseEvent) => {
    const el = state === 'live' ? canvas.current : img.current;
    if (!el || !interactive) return;
    onPoint(toBrowser(e.clientX, e.clientY, el.getBoundingClientRect()));
    // Instant feedback: the ring appears where you clicked right now; the page's own reaction arrives with the next live frame.
    const box = e.currentTarget.getBoundingClientRect(); const id = ++tapId.current;
    setTaps(t => [...t.slice(-3), { id, x: e.clientX - box.left, y: e.clientY - box.top }]);
    setTimeout(() => setTaps(t => t.filter(k => k.id !== id)), 600);
  };
  return (
    <div className={`live-screen${interactive ? ' driving' : ''}`} onClick={point}
      onWheel={e => { if (interactive && onWheel && Date.now() - lastWheel.current > 450) { lastWheel.current = Date.now(); onWheel(e.deltaY > 0 ? 'down' : 'up'); } }}>
      <canvas ref={canvas} aria-label="The page Lumina is working on, live" hidden={state !== 'live'} />
      {state !== 'live' && (fallback
        ? <img ref={img} alt="The page Lumina is working on" src={fallback} onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }} />
        : <p className="faint live-wait">{enabled ? 'Waiting for the first view of the page…' : 'No picture was saved for this task.'}</p>)}
      {taps.map(t => <span key={t.id} className="live-tap" style={{ left: t.x, top: t.y }} aria-hidden="true" />)}
      {enabled && <span className={`live-badge ${state}`} aria-live="polite">{state === 'live' ? '● Live' : state === 'snapshots' ? 'Snapshots' : 'Connecting…'}</span>}
    </div>);
}
