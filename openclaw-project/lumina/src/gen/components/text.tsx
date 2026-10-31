import { useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safeHttpUrl } from '../safety';
import { cx, type P } from './types';
import { useLocal } from './context';

const mdComponents = {
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => { const u = href ? safeHttpUrl(href) : null; return u ? <a href={u} target="_blank" rel="noopener noreferrer nofollow">{children}<span className="sr"> (opens in a new tab)</span></a> : <span>{children}</span>; },
  img: ({ alt }: { alt?: string }) => <span>{alt || 'Image'}</span>,           // remote images are never loaded from model text
};
export function Prose({ children }: { children: string }) { return <Markdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>{children}</Markdown>; }

export function TextBlock({ block }: P<'text'>) {
  const p = block.props; const [l, set] = useLocal(block.id, { expanded: block.expansion !== 'collapsed' });
  const long = block.expansion === 'collapsed' && p.content.length > 280;
  const body = p.format === 'plain' ? <p>{p.content}</p> : <Prose>{p.content}</Prose>;
  return <div className={cx('gen-text', block.variant && `v-${block.variant}`, long && !l.expanded && 'clamp')}>{body}
    {long && <button className="btn tertiary small" aria-expanded={!!l.expanded} onClick={() => set({ expanded: !l.expanded })}>{l.expanded ? 'Show less' : 'Show more'}</button>}</div>;
}
export function HeadingBlock({ block }: P<'heading'>) { const H = (`h${block.props.level}`) as 'h2'; return <H className="gen-heading">{block.props.text}</H>; }
export function ListBlock({ block }: P<'list'>) {
  const { items, ordered } = block.props; const check = items.some(i => i.checked !== undefined);
  if (check) return <ul className="gen-list check" role="list">{items.map((i, n) => <li key={n}><span className={cx('box', i.checked && 'on')} aria-hidden>{i.checked ? '✓' : ''}</span><span className="sr">{i.checked ? 'Done: ' : 'To do: '}</span><Prose>{i.text}</Prose></li>)}</ul>;
  const L = ordered ? 'ol' : 'ul';
  return <L className="gen-list">{items.map((i, n) => <li key={n}><Prose>{i.text}</Prose></li>)}</L>;
}
export function CalloutBlock({ block }: P<'callout'>) {
  const { tone, content, title } = block.props;
  return <aside className={cx('gen-callout', `tone-${tone}`)} role={tone === 'warning' || tone === 'danger' ? 'alert' : 'note'}>{title && <strong>{title}</strong>}<Prose>{content}</Prose></aside>;
}
export function QuoteBlock({ block }: P<'quote'>) { return <blockquote className="gen-quote"><Prose>{block.props.content}</Prose>{block.props.source && <footer>— {block.props.source}</footer>}</blockquote>; }
export function CitationList({ block }: P<'citation_list'>) {
  const detailed = block.variant === 'detailed';
  return <ol className="gen-cites" aria-label={block.props.title ?? 'Sources'}>{block.props.sources.map((s, n) => { const u = s.url ? safeHttpUrl(s.url) : null;
    return <li key={n} id={`${block.id}-${n + 1}`}>{u ? <a href={u} target="_blank" rel="noopener noreferrer nofollow">{s.label}<span className="sr"> (opens in a new tab)</span></a> : <span>{s.label}</span>}
      {s.publisher && <span className="faint"> · {s.publisher}</span>}{(detailed || block.variant === undefined) && s.snippet && <p className="gen-snip">{s.snippet}</p>}</li>; })}</ol>;
}
function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return <button className="btn tertiary small" onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ } }}>{done ? 'Copied' : label}</button>;
}
export function CodeBlock({ block }: P<'code_block'>) {
  const p = block.props;
  return <figure className="gen-code"><figcaption><span>{p.filename ?? p.language ?? 'code'}</span>{p.copyable && <CopyButton text={p.code} />}</figcaption>
    <pre role="region" aria-label={`Code${p.filename ? ': ' + p.filename : ''}`} tabIndex={0}><code>{p.code}</code></pre></figure>;
}
export function TerminalOutput({ block }: P<'terminal_output'>) {
  const p = block.props;
  return <figure className="gen-code term"><figcaption><span>{p.command ? `$ ${p.command}` : 'output'}</span><CopyButton text={p.lines.join('\n')} /></figcaption>
    <pre role="log" aria-label="Command output" tabIndex={0}>{p.lines.join('\n')}</pre></figure>;
}
export function JsonViewer({ block }: P<'json_viewer'>) {
  let shown: string; let bad = false;
  try { shown = JSON.stringify(JSON.parse(block.props.json), null, 2); } catch { shown = block.props.json; bad = true; }
  return <figure className="gen-code"><figcaption><span>JSON{bad ? ' (not valid JSON)' : ''}</span><CopyButton text={shown} /></figcaption><pre role="region" aria-label="JSON" tabIndex={0}><code>{shown}</code></pre></figure>;
}
export function DiffViewer({ block }: P<'diff_viewer'>) {
  const lines = block.props.diff.split('\n');
  return <figure className="gen-code diff"><figcaption><span>{block.props.filename ?? 'diff'}</span><CopyButton text={block.props.diff} /></figcaption>
    <pre role="region" aria-label="Diff" tabIndex={0}>{lines.map((l, n) => { const k = l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : l.startsWith('@@') ? 'hunk' : '';
      return <span key={n} className={cx('dl', k)}>{k === 'add' && <span className="sr">added: </span>}{k === 'del' && <span className="sr">removed: </span>}{l || ' '}{'\n'}</span>; })}</pre></figure>;
}
