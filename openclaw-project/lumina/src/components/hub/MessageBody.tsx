import { useEffect, useMemo, useRef, useState } from 'react';

const TOKENS = ['--text-primary', '--text-secondary', '--accent-text', '--border-default', '--font'] as const;

/** The page a message is shown in. It is put inside a frame that can run nothing: the server already rebuilt the message from an allow-list (hub_html.py); this is the
 *  second wall. The frame's own policy lets it load pictures and nothing else, and it cannot reach Lumina's page, its cookies or its session. */
export function frameDocument(html: string, tokens: Record<string, string>): string {
  const t = (name: string, fallback: string) => tokens[name] || fallback;
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src http: https:; style-src 'unsafe-inline'">`
    + `<base target="_blank"><style>html{color-scheme:dark}body{margin:0;padding:2px 0;font:14px/1.55 ${t('--font', 'system-ui, sans-serif')};color:${t('--text-primary', 'CanvasText')};`
    + `overflow-wrap:anywhere;background:transparent}a{color:${t('--accent-text', 'LinkText')}}img{max-width:100%;height:auto}table{max-width:100%}`
    + `blockquote{margin:8px 0;padding-left:12px;border-left:2px solid ${t('--border-default', 'GrayText')};color:${t('--text-secondary', 'GrayText')}}`
    + `pre{white-space:pre-wrap;font:inherit;margin:0}</style></head><body>${html}</body></html>`;
}

/** A message's content, shown safely. `sandbox` never includes scripts; "same origin" is there only so the frame's height can be read to fit it (with no script able to run
 *  inside, it gives the message nothing). */
export default function MessageBody({ html, title }: { html: string; title: string }) {
  const frame = useRef<HTMLIFrameElement>(null); const [height, setHeight] = useState(120);
  const doc = useMemo(() => {
    const style = typeof window !== 'undefined' ? getComputedStyle(document.documentElement) : null;
    return frameDocument(html, Object.fromEntries(TOKENS.map(name => [name, style?.getPropertyValue(name).trim() ?? ''])));
  }, [html]);
  const fit = () => { const h = frame.current?.contentDocument?.documentElement?.scrollHeight; if (h) setHeight(Math.min(Math.max(h + 4, 40), 20000)); };
  useEffect(() => { const timer = window.setTimeout(fit, 400); return () => window.clearTimeout(timer); }, [doc]);      // pictures that load late change the height once more
  return <iframe ref={frame} className="hub-body-frame" title={title} sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer"
    srcDoc={doc} style={{ height }} onLoad={fit} />;
}
