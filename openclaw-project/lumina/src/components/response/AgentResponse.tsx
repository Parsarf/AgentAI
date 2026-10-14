import { memo } from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Root, PhrasingContent } from 'mdast';
import './response.css';

export function safeResponseUrl(value: string): string | undefined {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; } catch { return undefined; }
}
function sourceLinks() {
  return (tree: Root) => {
    for (const node of tree.children) {
      if (node.type !== 'paragraph' || !node.children.some(c => c.type === 'text' && /^Sources?:/i.test(c.value.trim()))) continue;
      node.children = node.children.flatMap((child): PhrasingContent[] => {
        if (child.type !== 'text') return [child];
        const parts: PhrasingContent[] = []; let offset = 0;
        const pattern = /\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}(?:\/[^\s,;<>]*)?/gi;
        for (const match of child.value.matchAll(pattern)) {
          const start = match.index!; const domain = match[0].replace(/[.)]+$/, '');
          if (start && /[@/]/.test(child.value[start - 1])) continue;
          parts.push({ type: 'text', value: child.value.slice(offset, start) }, { type: 'link', url: `https://${domain}`, children: [{ type: 'text', value: domain }] });
          offset = start + domain.length;
        }
        parts.push({ type: 'text', value: child.value.slice(offset) }); return parts;
      });
    }
  };
}
const PLUGINS = [remarkGfm, sourceLinks];
const COMPONENTS: Components = {
    a: ({ href, children }) => { const url = href && safeResponseUrl(href); return url ? <a href={url} target="_blank" rel="noopener noreferrer">{children}<span className="sr"> (opens in a new tab)</span></a> : <span>{children}</span>; },
    p: ({ node, children }) => <p className={node?.children.some(c => c.type === 'text' && /^Sources?:/i.test(c.value.trim())) ? 'answer-sources' : undefined}>{children}</p>,
    img: ({ alt, src }) => <span>{alt || 'Image'}{src && safeResponseUrl(src) && <> — <a href={safeResponseUrl(src)} target="_blank" rel="noopener noreferrer">View image ↗</a></>}</span>,
    table: ({ children }) => <div className="answer-table" role="region" aria-label="Response table" tabIndex={0}><table>{children}</table></div>,
  };

/** Parsed once per message: it only re-renders when its text changes, not on every chat refresh (that re-parse froze scrolling). */
function AgentResponse({ content }: { content: string }) {
  return <div className="agent-response"><Markdown remarkPlugins={PLUGINS} skipHtml components={COMPONENTS}>{content}</Markdown></div>;
}
export default memo(AgentResponse);
