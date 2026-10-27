import { useEffect, useId, useState } from 'react';
import mermaid from 'mermaid';

// Diagrams are data. Configuration, click handlers and resource URLs are never accepted.
mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true, maxTextSize: 8000, maxEdges: 160, flowchart: { htmlLabels: false } });
export default function MermaidView({ source, label }: { source: string; label: string }) {
  const id = useId().replace(/[^a-z0-9]/gi, ''); const [svg, setSvg] = useState(''); const [error, setError] = useState(''); const [aspect, setAspect] = useState('6 / 1'); const [background, setBackground] = useState('transparent');
  useEffect(() => {
    let stopped = false; setSvg(''); setError('');
    if (/%%\s*\{|^\s*---|\bclick\b|\burl\s*\(|https?:|data:|javascript:|@\s*\{/i.test(source)) { setError('Diagram configuration, links and resource URLs are not allowed.'); return; }
    const css = getComputedStyle(document.documentElement); const token = (name: string) => css.getPropertyValue(name).trim();
    const bg = token('--surface'); setBackground(bg || 'transparent');
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true, maxTextSize: 8000, maxEdges: 160, theme: 'base', themeVariables: { primaryColor: token('--surface-raised') || undefined, primaryTextColor: token('--text-primary') || undefined, primaryBorderColor: token('--border-strong') || undefined, lineColor: token('--text-secondary') || undefined, background: bg || undefined, fontFamily: token('--font') || undefined }, flowchart: { htmlLabels: false } });
    mermaid.render(`gen-mermaid-${id}`, source).then(result => { if (!stopped) { const viewBox = new DOMParser().parseFromString(result.svg, 'image/svg+xml').documentElement.getAttribute('viewBox')?.split(/\s+/).map(Number); if (viewBox && viewBox[2] > 0 && viewBox[3] > 0) setAspect(`${viewBox[2]} / ${viewBox[3]}`); setSvg(result.svg); } }).catch(() => { if (!stopped) setError('This Mermaid source is invalid. Inspect its source and correct the diagram syntax.'); });
    return () => { stopped = true; };
  }, [source, id]);
  const html = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><style>body{margin:0;background:${background}}svg{max-width:100%;height:auto}</style>${svg}`;
  return <figure>{error ? <p role="alert">{error}</p> : svg ? <iframe className="gen-diagram-frame" style={{ aspectRatio: aspect }} title={label} sandbox="" referrerPolicy="no-referrer" srcDoc={html} /> : <p role="status">Rendering diagram…</p>}<details><summary>Diagram source</summary><pre tabIndex={0}>{source}</pre></details></figure>;
}
