import { memo, useRef, useState } from 'react';
import { useData } from '../../state/data';
import { exportError, saveFrom, saveText, tableData, toCsv } from '../../lib/files';
import '../files/files.css';
import AppPlayer, { parseApplication } from '../apps/AppPlayer';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Root, PhrasingContent } from 'mdast';
import './response.css';
import { inlineCard } from '../../lib/genui/inline';
import { ChartCard, ComparisonCard, TableCard } from '../genui/Cards';
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
function dataCard(value: string) {
  const card = inlineCard(value);
  if (!card) return null;
  if (card.kind === 'chart') return <ChartCard spec={card.spec} />;
  if (card.kind === 'table') return <TableCard spec={card.spec} />;
  return <ComparisonCard spec={card.spec} />;
}
const COMPONENTS: Components = {
    a: ({ href, children }) => { const url = href && safeResponseUrl(href); return url ? <a href={url} target="_blank" rel="noopener noreferrer">{children}<span className="sr"> (opens in a new tab)</span></a> : <span>{children}</span>; },
    p: ({ node, children }) => {
      // An emoji picture counts as the text it stands for, so a JSON card containing emoji is still recognised as one.
      const textOf = (c: NonNullable<typeof node>['children'][number]) => c.type === 'text' ? c.value
        : c.type === 'element' && c.tagName === 'img' && isEmojiUrl(String(c.properties.src ?? '')) ? String(c.properties.alt ?? '') : null;
      const pieces = node?.children.map(textOf) ?? [];
      const value = pieces.length && pieces.every(x => x !== null) ? pieces.join('') : '';
      return dataCard(value) ?? <p className={node?.children.some(c => c.type === 'text' && /^Sources?:/i.test(c.value.trim())) ? 'answer-sources' : undefined}>{children}</p>;
    },
    pre: ({ node, children }) => {
      const code = node?.children.find(c => c.type === 'element' && c.tagName === 'code');
      if (code?.type === 'element') {
        const language = String(code.properties.className ?? '').replace('language-', '').trim().toLowerCase();
        if (language === 'lumina-app') {
          const app = parseApplication(code.children.map(c => c.type === 'text' ? c.value : '').join(''));
          if (app) return <AppPlayer key={app.code} app={app} />;
        }
        if (['', 'json', 'chart', 'genui', 'lumina'].includes(language)) {
          const value = code.children.map(c => c.type === 'text' ? c.value : '').join('');
          const card = dataCard(value);
          if (card) return card;
        }
      }
      return <pre role="region" aria-label="Code block" tabIndex={0}>{children}</pre>;
    },
    img: ({ alt, src }) => isEmojiUrl(src) ? <EmojiImg emoji={alt ?? ''} file={src!.slice(src!.lastIndexOf('/') + 1)} /> : <span>{alt || 'Image'}{src && safeResponseUrl(src) && <> — <a href={safeResponseUrl(src)} target="_blank" rel="noopener noreferrer">View image ↗</a></>}</span>,
    table: ({ children }) => <ResponseTable>{children}</ResponseTable>,
  };

/** A table in an answer, with the way to take it along: CSV is made here in the page; Excel is a real workbook made by the server. */
function ResponseTable({ children }: { children: React.ReactNode }) {
  const app = (useData() as ReturnType<typeof useData> | null)?.app;       // also rendered outside the signed-in shell (previews, tests): then nothing optional is offered
  const ref = useRef<HTMLTableElement>(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const csv = () => { if (!ref.current) return; const { columns, rows } = tableData(ref.current); saveText('Table.csv', toCsv(columns, rows), 'text/csv;charset=utf-8'); };
  const excel = async () => {
    if (!ref.current || busy) return;
    setBusy(true); setErr('');
    try { const { columns, rows } = tableData(ref.current); await saveFrom('/v1/export/table', { format: 'xlsx', name: 'Table', columns, rows }, 'Table.xlsx'); }
    catch (error) { setErr(exportError(error)); } finally { setBusy(false); }
  };
  return <>
    <div className="answer-table" role="region" aria-label="Response table" tabIndex={0}><table ref={ref}>{children}</table></div>
    <div className="answer-table-tools">
      {app?.features.convert && <button type="button" className="btn small tertiary" disabled={busy} onClick={excel}>{busy ? 'Preparing…' : 'Download as Excel'}</button>}
      <button type="button" className="btn small tertiary" onClick={csv}>Download as CSV</button>
    </div>
    {err && <p className="err" role="alert">{err}</p>}
  </>;
}

/** Parsed once per message: it only re-renders when its text changes, not on every chat refresh (that re-parse froze scrolling). */
function AgentResponse({ content }: { content: string }) {
  return <div className="agent-response"><Markdown remarkPlugins={PLUGINS} skipHtml components={COMPONENTS}>{content}</Markdown></div>;
}
export default memo(AgentResponse);
