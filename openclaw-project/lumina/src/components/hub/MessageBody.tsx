import { useCallback, useEffect, useRef, useState } from 'react';
import { frameUrl } from '../../lib/hub';

/** The theme's values a plain message is drawn with: its page reads them as `--lm-*`. */
const TOKENS: Record<string, string> = { '--lm-fg': '--text-primary', '--lm-muted': '--text-secondary', '--lm-link': '--accent-text', '--lm-line': '--border-default',
  '--lm-accent': '--accent', '--lm-font': '--font' };
const MIN = 24, MAX = 30000;

/** The app's own font files, as the rules that name them, so a message in the theme is set in the same type as the rest of Lumina. */
function fontRules(): string {
  const out: string[] = [];
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try { rules = sheet.cssRules; } catch { continue; }                  // a sheet from elsewhere: not ours to read
    for (const rule of Array.from(rules)) if (rule.constructor.name === 'CSSFontFaceRule' || rule.cssText.startsWith('@font-face')) out.push(rule.cssText);
  }
  return out.join('\n');
}

/** A message's content. It is a page of its own, fetched from Lumina's server with its own content policy and shown in a frame that can run nothing: the server rebuilt
 *  the message from an allow-list (hub_html.py), the page's policy lets it load nothing but its own styles and, once the customer asks, pictures. It has to come from
 *  the server: a page written into the frame here would inherit the app's policy, which refuses a message's styles and pictures, and every message was then shown as
 *  unstyled black-on-white text.
 *
 *  A plain message (no background of its own) is drawn in the theme: this component hands the theme's colours and type to the page once it has loaded, and again when
 *  the theme changes. A designed one (a newsletter, a receipt) is shown as sent, on a light page of its own. The frame is as tall as its content, and content wider than
 *  the frame is scaled down to fit, as a phone's mail program does. "Same origin" in the sandbox is there only so this component can do those things; with no script able
 *  to run inside, it gives the message nothing. */
export default function MessageBody({ connection, id, images, designed, title }: { connection: string; id: string; images: boolean; designed: boolean; title: string }) {
  const frame = useRef<HTMLIFrameElement>(null); const [height, setHeight] = useState(designed ? 160 : 60); const [ready, setReady] = useState(false);
  const watching = useRef<ResizeObserver | null>(null); const queued = useRef(0);

  const fit = useCallback(() => {
    const el = frame.current; const doc = el?.contentDocument; const body = doc?.body;
    if (!el || !doc || !body) return;
    body.style.removeProperty('zoom');
    const wide = doc.documentElement.scrollWidth, room = el.clientWidth;
    if (room > 0 && wide > room + 1) body.style.setProperty('zoom', String(Math.max(0.35, room / wide)));
    const tall = Math.ceil(body.getBoundingClientRect().height);
    if (tall > 0) setHeight(Math.min(Math.max(tall, MIN), MAX));
  }, []);
  const later = useCallback(() => { window.cancelAnimationFrame(queued.current); queued.current = window.requestAnimationFrame(fit); }, [fit]);

  const theme = useCallback(() => {
    const doc = frame.current?.contentDocument; if (!doc || designed) return;
    const style = getComputedStyle(document.documentElement); const root = doc.documentElement;
    root.style.setProperty('color-scheme', style.colorScheme && style.colorScheme !== 'normal' ? style.colorScheme : 'dark');
    for (const [name, token] of Object.entries(TOKENS)) { const value = style.getPropertyValue(token).trim(); if (value) root.style.setProperty(name, value); }
    if (!doc.getElementById('lumina-fonts')) { const fonts = doc.createElement('style'); fonts.id = 'lumina-fonts'; fonts.textContent = fontRules(); doc.head?.appendChild(fonts); }
  }, [designed]);

  const loaded = useCallback(() => {
    const doc = frame.current?.contentDocument;
    if (!doc?.body) { setReady(true); return; }                          // nothing to reach (a browser that keeps the frame apart): shown as the page itself decides
    theme(); fit(); setReady(true);
    watching.current?.disconnect();
    if (typeof ResizeObserver !== 'undefined') { watching.current = new ResizeObserver(later); watching.current.observe(doc.body); if (frame.current) watching.current.observe(frame.current); }
    doc.fonts?.ready.then(later).catch(() => undefined);
    for (const picture of Array.from(doc.images)) if (!picture.complete) picture.addEventListener('load', later, { once: true });
  }, [theme, fit, later]);

  useEffect(() => { setReady(false); }, [connection, id, images]);
  useEffect(() => () => { watching.current?.disconnect(); window.cancelAnimationFrame(queued.current); }, []);
  // The theme changed while the message was open (contrast, a future light theme): hand the new values over.
  useEffect(() => {
    if (typeof MutationObserver === 'undefined') return;
    const seen = new MutationObserver(() => { theme(); later(); });
    seen.observe(document.documentElement, { attributes: true, attributeFilter: ['data-contrast', 'data-theme', 'class', 'style'] });
    return () => seen.disconnect();
  }, [theme, later]);

  return <iframe ref={frame} className={`hub-body-frame${designed ? ' designed' : ''}${ready ? ' ready' : ''}`} title={title} src={frameUrl(connection, id, images)}
    sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" style={{ height }} onLoad={loaded} />;
}
