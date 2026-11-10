import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import type { ArtifactRow } from '../../lib/files';
import './apps.css';

export const APP_MAX_BYTES = 512 * 1024;
export type Application = { version: 1; title: string; runtime: 'html' | 'python' | 'javascript'; code: string };
export function parseApplication(text: string): Application | null {
  try {
    const a = JSON.parse(text);
    if (!a || typeof a !== 'object' || Array.isArray(a) || Object.keys(a).some(k => !['version', 'title', 'runtime', 'code'].includes(k)) || a.version !== 1 ||
      typeof a.title !== 'string' || !a.title.trim() || Array.from(a.title).length > 120 || !['html', 'python', 'javascript'].includes(a.runtime) ||
      typeof a.code !== 'string' || !a.code.trim() || new TextEncoder().encode(a.code).length > APP_MAX_BYTES) return null;
    return a as Application;
  } catch { return null; }
}
export function runnableFile(file: Pick<ArtifactRow, 'display_name' | 'size_bytes'>) {
  return /\.(html|py|js)$/i.test(file.display_name) && file.size_bytes > 0 && file.size_bytes <= APP_MAX_BYTES;
}

type Props = { app?: Application; file?: ArtifactRow };
const THEME_TOKENS = ['--surface', '--surface-raised', '--text-primary', '--text-secondary', '--border-default', '--accent', '--font', '--font-mono', '--radius-pill'];

/** A new source/version always gets a fresh environment, including when a caller reuses this component. */
export default function AppPlayer(props: Props) {
  const identity = props.app ? JSON.stringify(props.app) : `${props.file?.id}:${props.file?.version}`;
  return <Player key={identity} {...props} />;
}

function Player({ app, file }: Props) {
  const [payload, setPayload] = useState(app); const [open, setOpen] = useState(false); const [wide, setWide] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [generation, setGeneration] = useState(0);
  const launchButton = useRef<HTMLButtonElement>(null); const wasOpen = useRef(false);
  useEffect(() => { if (!open && wasOpen.current) launchButton.current?.focus(); wasOpen.current = open; }, [open]);
  const frame = useRef<HTMLIFrameElement>(null); const title = app?.title ?? file?.display_name ?? 'Application';
  useEffect(() => {
    if (!open) return;
    setError('');
    const timer = setTimeout(() => setError('The app player could not load. Restart it, or sign in again if your session expired.'), 20000);
    const ready = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === 'lumina.app.ready') { clearTimeout(timer); setError(''); }
      if (event.data?.type === 'lumina.app.error' && typeof event.data.message === 'string') {
        clearTimeout(timer); setError('App error: ' + event.data.message.slice(0, 1000));
      }
    };
    window.addEventListener('message', ready);
    return () => { clearTimeout(timer); window.removeEventListener('message', ready); };
  }, [open, generation]);
  const launch = async () => {
    setBusy(true); setError('');
    try {
      let next = payload;
      if (!next && file) {
        const result = await api<{ app: Application }>('GET', `/v1/artifacts/${file.id}/versions/${file.version}/app`, undefined, { timeoutMs: 15000 });
        next = parseApplication(JSON.stringify(result.app)) ?? undefined;
      }
      if (!next) throw new Error('Invalid application');
      setPayload(next); setOpen(true);
    } catch (error) {
      setError(error instanceof ApiError && error.status === 401 ? 'Sign in again to open this app.'
        : error instanceof ApiError && error.status === 404 ? 'This app file or version is no longer available.'
        : error instanceof ApiError && error.code === 'invalid_app_source' ? 'This app’s saved source is incomplete or invalid. Ask Lumina to rebuild it.'
        : error instanceof ApiError && error.status === 422 ? 'Use a standalone HTML, Python or browser JavaScript file up to 512 KiB.'
        : 'Could not load this app. Check your connection and try again.');
    }
    finally { setBusy(false); }
  };
  return <section className={`app-player panel${wide ? ' app-player-wide' : ''}`} aria-label={title}>
    <div className="app-player-bar"><strong>{title}</strong><div className="app-player-actions">
      {!open ? <button ref={launchButton} className="btn small" disabled={busy} onClick={launch}>{busy ? 'Opening…' : 'Open app'}</button> : <>
        <button className="btn small" onClick={() => setGeneration(g => g + 1)}>Restart</button>
        <button className="btn small" aria-pressed={wide} onClick={() => setWide(w => !w)}>{wide ? 'Compact' : 'Expand'}</button>
        <button className="btn small" onClick={() => { setOpen(false); setWide(false); setError(''); }}>Close app</button>
      </>}
    </div></div>
    {error && <p role="alert" className="err">{error}</p>}
    {open && payload && <iframe key={generation} ref={frame} className="app-player-frame" title={`${title} — app player`}
      src="/v1/apps/player" sandbox="allow-scripts" referrerPolicy="no-referrer"
      allow="camera 'none'; microphone 'none'; geolocation 'none'; payment 'none'; usb 'none'; clipboard-read 'none'; clipboard-write 'none'"
      onLoad={event => {
        const styles = getComputedStyle(document.documentElement);
        const theme = Object.fromEntries(THEME_TOKENS.map(token => [token, styles.getPropertyValue(token).trim()]));
        event.currentTarget.contentWindow?.postMessage({ type: 'lumina.app', app: payload, theme }, '*');
      }} />}
    {open && <details className="app-player-source"><summary>Source code</summary><pre tabIndex={0}>{payload?.code}</pre></details>}
  </section>;
}
