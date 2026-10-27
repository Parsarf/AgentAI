import { createContext, memo, useContext, useState, type ReactNode } from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Root, PhrasingContent } from 'mdast';
import './response.css';
import { inlineCard } from '../../lib/genui/inline';
import { CardFor } from '../genui/CardView';
import { isEmojiUrl, remarkEmoji } from '../../lib/emojify';
import { EmojiImg } from '../Emoji';

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
const PLUGINS = [remarkGfm, sourceLinks, remarkEmoji];
/** True when this reply already has its card stored and drawn under it: a card still sitting in the reply's own text is then not drawn a second time. */
const CardsStored = createContext(false);
function dataCard(value: string) {
  const card = inlineCard(value);
  return card ? <CardFor kind={card.kind} spec={card.spec} /> : null;
}
const COMPONENTS: Components = {
    a: ({ href, children }) => { const url = href && safeResponseUrl(href); return url ? <a href={url} target="_blank" rel="noopener noreferrer">{children}<span className="sr"> (opens in a new tab)</span></a> : <span>{children}</span>; },
    p: ({ node, children }) => {
      // An emoji picture counts as the text it stands for, so a JSON card containing emoji is still recognised as one.
      const textOf = (c: NonNullable<typeof node>['children'][number]) => c.type === 'text' ? c.value
        : c.type === 'element' && c.tagName === 'img' && isEmojiUrl(String(c.properties.src ?? '')) ? String(c.properties.alt ?? '') : null;
      const pieces = node?.children.map(textOf) ?? [];
      const value = pieces.length && pieces.every(x => x !== null) ? pieces.join('') : '';
      const card = dataCard(value);
      return card ? <StoredOr>{card}</StoredOr> : <p className={node?.children.some(c => c.type === 'text' && /^Sources?:/i.test(c.value.trim())) ? 'answer-sources' : undefined}>{children}</p>;
    },
    pre: ({ node, children }) => {
      const code = node?.children.find(c => c.type === 'element' && c.tagName === 'code');
      if (code?.type === 'element') {
        const language = String(code.properties.className ?? '').replace('language-', '').trim().toLowerCase();
        if (['', 'json', 'chart', 'genui', 'lumina'].includes(language)) {
          const value = code.children.map(c => c.type === 'text' ? c.value : '').join('');
          const card = dataCard(value);
          if (card) return <StoredOr>{card}</StoredOr>;
        }
      }
      return <pre role="region" aria-label="Code block" tabIndex={0}>{children}</pre>;
    },
    img: ({ alt, src }) => isEmojiUrl(src) ? <EmojiImg emoji={alt ?? ''} file={src!.slice(src!.lastIndexOf('/') + 1)} /> : <span>{alt || 'Image'}{src && safeResponseUrl(src) && <> — <a href={safeResponseUrl(src)} target="_blank" rel="noopener noreferrer">View image ↗</a></>}</span>,
    table: ({ children }) => <div className="answer-table" role="region" aria-label="Response table" tabIndex={0}><table>{children}</table></div>,
  };

function StoredOr({ children }: { children: ReactNode }) {
  return useContext(CardsStored) ? null : <>{children}</>;
}

/** How a plain-text reply is laid out, when JEV chose one (routing/display.py): the words are never changed, only how they are shown. */
export type ReplyLayout = 'steps' | 'answer' | 'list';
const InSteps = createContext(false);
function StepItem({ children }: { children: ReactNode }) {
  const [done, setDone] = useState(false);
  return <li className={done ? 'done' : undefined}><label><input type="checkbox" checked={done} onChange={() => setDone(!done)} /> <span>{children}</span></label></li>;
}
const STEP_COMPONENTS: Components = {
  ...COMPONENTS,
  ol: ({ children }) => <InSteps.Provider value={true}><ol className="as-steps">{children}</ol></InSteps.Provider>,
  ul: ({ children }) => <InSteps.Provider value={false}><ul>{children}</ul></InSteps.Provider>,
  li: function Li({ children }) { return useContext(InSteps) ? <StepItem>{children}</StepItem> : <li>{children}</li>; },
};

/** Parsed once per message: it only re-renders when its text or layout changes, not on every chat refresh (that re-parse froze scrolling). */
function AgentResponse({ content, layout, cardsStored = false }: { content: string; layout?: ReplyLayout; cardsStored?: boolean }) {
  return (
    <CardsStored.Provider value={cardsStored}>
      <div className={`agent-response${layout ? ` layout-${layout}` : ''}`}>
        <Markdown remarkPlugins={PLUGINS} skipHtml components={layout === 'steps' ? STEP_COMPONENTS : COMPONENTS}>{content}</Markdown>
      </div>
    </CardsStored.Provider>);
}
export default memo(AgentResponse);
