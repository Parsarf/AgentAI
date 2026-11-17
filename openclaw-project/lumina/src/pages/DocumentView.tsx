import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../lib/api';
import { exportError, saveFrom, saveText, toCsv } from '../lib/files';
import { useData } from '../state/data';
import Workspace from '../components/frame/Workspace';
import { EmptyState } from '../components/frame/parts';
import type { Source } from './Knowledge';
import '../styles/documents.css';

interface Point { label: string; value: string; basis: 'printed' | 'estimated' }
export interface Block {
  id: string; kind: string; text: string; source?: string; page?: number | null; level?: number; rows?: string[][]; header_rows?: number; title?: string;
  confidence?: number | null; chart_type?: string; series?: { name: string; points: Point[] }[];
}
export interface DocumentData {
  source: Source; title: string | null; pages: number | null; format: string; notes: string[]; blocks: Block[];
  passages: { id: string; page: number | null; blocks: string[]; section: string | null }[];
}
const LOW = 0.75;           // the reader's own threshold (knowledge_parse.LOW_CONFIDENCE): text read from a picture below it may contain errors

function TableBlock({ block, convert }: { block: Block; convert: boolean }) {
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const rows = block.rows ?? []; const head = Math.min(block.header_rows ?? 0, rows.length);
  const columns = head ? rows[0] : rows[0]?.map((_, i) => `Column ${i + 1}`) ?? [];
  const body = rows.slice(head ? 1 : 0);
  const name = (block.title || 'Table').slice(0, 60);
  const excel = async () => {
    setBusy(true); setErr('');
    try { await saveFrom('/v1/export/table', { format: 'xlsx', name, columns, rows: body }, `${name}.xlsx`); } catch (e) { setErr(exportError(e)); } finally { setBusy(false); }
  };
  return <figure className="doc-table">
    {block.title && <figcaption>{block.title}</figcaption>}
    <div className="answer-table" role="region" aria-label={block.title || 'Table'} tabIndex={0}><table>
      {head > 0 && <thead><tr>{rows[0].map((c, i) => <th key={i} scope="col">{c}</th>)}</tr></thead>}
      <tbody>{body.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
    </table></div>
    <div className="answer-table-tools">
      {convert && <button type="button" className="btn small tertiary" disabled={busy} onClick={excel}>{busy ? 'Preparing…' : 'Download as Excel'}</button>}
      <button type="button" className="btn small tertiary" onClick={() => saveText(`${name}.csv`, toCsv(columns, body), 'text/csv;charset=utf-8')}>Download as CSV</button>
    </div>
    {err && <p className="err" role="alert">{err}</p>}
  </figure>;
}

function ChartBlock({ block }: { block: Block }) {
  const estimated = (block.series ?? []).some(s => s.points.some(p => p.basis === 'estimated'));
  return <figure className="doc-chart">
    <figcaption>{block.title || 'Chart'}{estimated && <span className="faint small"> · some values are estimated from the picture, not printed on it</span>}</figcaption>
    {(block.series ?? []).map((s, i) => <div key={i} className="answer-table" role="region" aria-label={s.name || `Series ${i + 1}`} tabIndex={0}><table>
      <caption className="faint small">{s.name}</caption>
      <tbody>{s.points.map((p, j) => <tr key={j}><th scope="row">{p.label}</th><td>{p.value}</td><td className="faint small">{p.basis === 'estimated' ? 'estimated' : 'printed'}</td></tr>)}</tbody>
    </table></div>)}
    {!block.series?.length && block.text && <p>{block.text}</p>}
  </figure>;
}

function BlockView({ block, cited, convert }: { block: Block; cited: boolean; convert: boolean }) {
  const unsure = block.confidence != null && block.confidence < LOW;
  const inner = block.kind === 'heading' ? <h3 className={`doc-h${Math.min(4, Math.max(1, block.level ?? 2))}`}>{block.text}</h3>
    : block.kind === 'table' ? <TableBlock block={block} convert={convert} />
    : block.kind === 'chart' ? <ChartBlock block={block} />
    : block.kind === 'code' ? <pre>{block.text}</pre>
    : block.kind === 'figure' ? <figure className="doc-figure"><figcaption className="faint small">Picture</figcaption>{block.text && <p>{block.text}</p>}</figure>
    : <p className={block.kind === 'list' ? 'doc-list' : undefined}>{block.text}</p>;
  return <div className={`doc-block${cited ? ' cited' : ''}`} data-block={block.id} aria-current={cited ? 'true' : undefined}>
    {inner}
    {unsure && <p className="doc-unsure faint small">Read from a scan or a picture: this part may contain errors.</p>}
  </div>;
}

/** One document as Lumina read it (#32): every part with its page, opened at the passage a citation names (?passage=), with that passage marked. Tables can be taken along
 *  as a spreadsheet; chart values say whether they were printed on the chart or estimated from its picture. */
export default function DocumentView() {
  const { sourceId = '' } = useParams(); const [params] = useSearchParams(); const passageId = params.get('passage');
  const { app } = useData();
  const [doc, setDoc] = useState<DocumentData | null>(null); const [err, setErr] = useState('');
  useEffect(() => {
    let live = true; setDoc(null); setErr('');
    api<DocumentData>('GET', `/v1/knowledge/sources/${encodeURIComponent(sourceId)}/document`)
      .then(d => { if (live) setDoc(d); })
      .catch(e => { if (live) setErr(e instanceof ApiError && e.status === 404 ? 'This document is not there, or you may not read it.' : 'The document could not be opened. Please try again.'); });
    return () => { live = false; };
  }, [sourceId]);
  const cited = useMemo(() => new Set(doc?.passages.find(p => p.id === passageId)?.blocks ?? []), [doc, passageId]);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!doc || !cited.size) return;
    const first = body.current?.querySelector('.doc-block.cited');
    if (first && 'scrollIntoView' in first) (first as HTMLElement).scrollIntoView({ block: 'center' });
  }, [doc, cited]);
  const pages = useMemo(() => {
    const out: { page: number | null; blocks: Block[] }[] = [];
    for (const b of doc?.blocks ?? []) { const page = b.page ?? null; const last = out[out.length - 1]; if (last && last.page === page) last.blocks.push(b); else out.push({ page, blocks: [b] }); }
    return out;
  }, [doc]);

  if (app && !app.features.knowledge) return <Workspace title="Document"><EmptyState title="Not available yet" action={<Link className="btn" to="/home">Back to Home</Link>}>Reading your documents is switched off for now.</EmptyState></Workspace>;
  const name = doc?.source.name ?? 'Document';
  return (
    <Workspace title={name} className="doc-page" tools={<Link className="btn small" to="/knowledge">All sources</Link>}>
      <article className="doc-body" ref={body} aria-label={name}>
        {err && <p className="notice warning" role="alert">{err}</p>}
        {!doc && !err && <div className="hub-loading" role="status"><div className="skeleton" style={{ height: 120 }} /><span className="sr">Loading…</span></div>}
        {doc && <>
          <p className="faint small">{doc.pages ? `${doc.pages} ${doc.pages === 1 ? 'page' : 'pages'} · ` : ''}{doc.source.passages} passages{doc.source.own ? '' : ' · shared with you'}
            {doc.source.read_by_model > 0 && ` · ${doc.source.read_by_model} ${doc.source.read_by_model === 1 ? 'page was' : 'pages were'} read from a picture`}</p>
          {passageId && !cited.size && <p className="notice" role="status">That passage is no longer in this document (it may have been read again since).</p>}
          {doc.notes.map(n => <p key={n} className="faint small">{n}</p>)}
          {pages.map((p, i) => <section key={i} className="doc-pagegroup" aria-label={p.page ? `Page ${p.page}` : 'Document'}>
            {p.page != null && <h2 className="doc-pageno">Page {p.page}</h2>}
            {p.blocks.map(b => <BlockView key={b.id} block={b} cited={cited.has(b.id)} convert={!!app?.features.convert} />)}
          </section>)}
        </>}
      </article>
    </Workspace>);
}
