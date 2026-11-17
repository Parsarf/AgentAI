import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../lib/api';
import { humanSize } from '../lib/files';
import { useData } from '../state/data';
import Workspace from '../components/frame/Workspace';
import { EmptyState } from '../components/frame/parts';

export interface Source {
  id: string; kind: string; name: string; media_type: string; size_bytes: number; state: string; step: string | null; error: string | null; pages: number | null; passages: number;
  tables: number; charts: number; read_by_model: number; low_confidence: boolean; unread_pages: number; parser: string | null; scope: string; origin: string | null;
  added_epoch: number; updated_epoch: number; indexed_epoch: number | null; own: boolean;
}
interface Overview { available: boolean; sources: Source[]; shared_with_me: Source[]; groups: { id: string; name: string }[] }
export interface Commitment {
  id: string; kind: string; what: string; owner: string; due_epoch: number | null; due_zone: string; due_has_time: boolean; source_kind: string; origin: string; state: string; suggested: boolean;
  source: { name?: string; label?: string } | null;
}

const day = (epoch: number | null, zone: string) => {
  if (epoch == null) return '';
  try { return new Date(epoch * 1000).toLocaleDateString(undefined, { timeZone: zone, day: 'numeric', month: 'short', year: 'numeric' }); } catch { return new Date(epoch * 1000).toLocaleDateString(); }
};
const STATE_WORDS: Record<string, string> = { queued: 'Waiting to be read', indexing: 'Being read', ready: 'Ready', failed: 'Could not be read', removing: 'Being removed' };
const sourceState = (s: Source) => s.state === 'failed' && s.error ? `Could not be read: ${s.error}` : STATE_WORDS[s.state] ?? s.state;
const failed = (e: unknown) => (e instanceof ApiError && e.status === 503 ? 'That is not available right now. Please try again in a moment.' : 'That did not work. Please try again.');

function SourceRow({ s, busy, act }: { s: Source; busy: boolean; act(path: string, label: string): void }) {
  const [confirm, setConfirm] = useState(false);
  return (
    <li className="file-item">
      <div className="file-item-row">
        <div className="file-card-text"><b title={s.name}>{s.name}</b>
          <span className="faint small">{sourceState(s)} · {humanSize(s.size_bytes)}{s.state === 'ready' && ` · ${s.passages} passages${s.pages ? ` on ${s.pages} pages` : ''}`}
            {s.tables > 0 && ` · ${s.tables} tables`}{s.charts > 0 && ` · ${s.charts} charts`}{s.scope === 'organization' && ' · shared with your organization'}{!s.own && ' · shared with you'}</span>
          {s.low_confidence && <span className="faint small">Some of this was read from a scan and may contain errors.</span>}
          {s.unread_pages > 0 && <span className="faint small">{s.unread_pages} {s.unread_pages === 1 ? 'page' : 'pages'} could not be read.</span>}</div>
        {s.own && <div className="file-item-actions">
          <button type="button" className="btn small tertiary" disabled={busy} onClick={() => act(`/v1/knowledge/sources/${s.id}/reindex`, `Read ${s.name} again`)}>Read again</button>
          <button type="button" className="btn small tertiary" disabled={busy} onClick={() => setConfirm(true)}>Remove</button></div>}
      </div>
      {confirm && <div className="file-confirm" role="alertdialog" aria-label={`Remove ${s.name}?`}>
        <span>Remove <b>{s.name}</b> from what your assistant can search? Its text and search data are deleted now. The file stays in Files.</span>
        <button type="button" className="btn small danger" disabled={busy} onClick={() => { setConfirm(false); act(`/v1/knowledge/sources/${s.id}/remove`, `Removed ${s.name}`); }}>Remove</button>
        <button type="button" className="btn small" onClick={() => setConfirm(false)}>Keep</button></div>}
    </li>);
}

function CommitmentRow({ c, busy, change }: { c: Commitment; busy: boolean; change(id: string, state: string): void }) {
  const from = c.source?.name || c.source?.label;
  return (
    <li className="file-item">
      <div className="file-item-row">
        <div className="file-card-text"><b>{c.what}</b>
          <span className="faint small">{c.kind === 'decision' ? 'Decision' : 'Commitment'}{c.owner && ` · ${c.owner}`}{c.due_epoch != null && ` · due ${day(c.due_epoch, c.due_zone)}`}{from && ` · from ${from}`}</span>
          {c.suggested && <span className="faint small">Suggested from {c.source_kind}. It counts only once you confirm it.</span>}</div>
        <div className="file-item-actions">
          {c.suggested ? <>
            <button type="button" className="btn small primary" disabled={busy} onClick={() => change(c.id, 'open')}>Confirm</button>
            <button type="button" className="btn small tertiary" disabled={busy} onClick={() => change(c.id, 'dropped')}>Dismiss</button></>
            : <>
              <button type="button" className="btn small" disabled={busy} onClick={() => change(c.id, 'done')}>Done</button>
              <button type="button" className="btn small tertiary" disabled={busy} onClick={() => change(c.id, 'dropped')}>Drop</button></>}
        </div>
      </div>
    </li>);
}

/** What the assistant can search (the Sources) and what the customer has decided or promised (the Commitments). */
export default function Knowledge() {
  const { app } = useData();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [items, setItems] = useState<Commitment[] | null>(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(''); const [note, setNote] = useState('');
  const [what, setWhat] = useState(''); const [owner, setOwner] = useState(''); const [due, setDue] = useState('');
  const load = useCallback(async () => {
    try { setOverview(await api<Overview>('GET', '/v1/knowledge')); } catch { setOverview({ available: false, sources: [], shared_with_me: [], groups: [] }); }
    try { const r = await api<{ available: boolean; items: Commitment[] }>('GET', '/v1/commitments'); setItems(r.available ? r.items : []); } catch { setItems([]); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  // A source that is still being read changes by itself: look again while any is.
  const reading = overview?.sources.some(s => s.state === 'queued' || s.state === 'indexing' || s.state === 'removing');
  useEffect(() => { if (!reading) return; const t = setInterval(() => { void load(); }, 4000); return () => clearInterval(t); }, [reading, load]);
  const run = async (fn: () => Promise<void>, done = '') => { setBusy(true); setErr(''); setNote(''); try { await fn(); setNote(done); await load(); } catch (e) { setErr(failed(e)); } finally { setBusy(false); } };
  const act = (path: string, label: string) => { void run(async () => { await api('POST', path, {}); }, label); };
  const change = (id: string, state: string) => { void run(async () => { await api('POST', `/v1/commitments/${id}`, { state }); }); };
  const add = () => { const text = what.trim(); if (!text) return; void run(async () => { await api('POST', '/v1/commitments', { what: text, owner: owner.trim() || undefined, due: due || undefined }); setWhat(''); setOwner(''); setDue(''); }); };

  const hasSources = !!app?.features.knowledge; const hasCommitments = !!app?.features.commitments;
  if (app && !hasSources && !hasCommitments) return (
    <Workspace title="Sources"><EmptyState title="Not available yet" action={<Link className="btn" to="/home">Back to Home</Link>}>Searching your documents is switched off for now.</EmptyState></Workspace>);
  return (
    <Workspace title="Sources and commitments" className="files-page">
      <section className="files-body" aria-label="Sources">
        {hasSources && <>
          <h2 className="ci-h">Sources</h2>
          <p className="faint small">Your assistant searches and cites these. Every file you upload is added; removing a source deletes its text and search data, not the file.</p>
          {overview === null && <div className="hub-loading" role="status"><div className="skeleton" style={{ height: 56 }} /><span className="sr">Loading…</span></div>}
          {overview && overview.sources.length === 0 && <EmptyState>Nothing is indexed yet. Upload a file in Files and it appears here.</EmptyState>}
          {overview && overview.sources.length > 0 && <ul aria-label="Your sources">{overview.sources.map(s => <SourceRow key={s.id} s={s} busy={busy} act={act} />)}</ul>}
          {overview && overview.shared_with_me.length > 0 && <><h3 className="ci-h">Shared with you</h3>
            <ul aria-label="Shared with you">{overview.shared_with_me.map(s => <SourceRow key={s.id} s={s} busy={busy} act={act} />)}</ul></>}
        </>}
        {hasCommitments && <>
          <h2 className="ci-h">Commitments</h2>
          <p className="faint small">Decisions and promises. Ones your assistant finds in mail or documents are only suggestions until you confirm them.</p>
          <form className="file-rename" onSubmit={e => { e.preventDefault(); add(); }}>
            <input className="input" aria-label="What was decided or promised" placeholder="What was decided or promised" value={what} maxLength={500} onChange={e => setWhat(e.target.value)} />
            <input className="input" aria-label="Who owns it" placeholder="Who" value={owner} maxLength={200} onChange={e => setOwner(e.target.value)} />
            <input className="input" type="date" aria-label="Due date" value={due} onChange={e => setDue(e.target.value)} />
            <button type="submit" className="btn small primary" disabled={busy || !what.trim()}>Add</button></form>
          {items === null && <div className="hub-loading" role="status"><div className="skeleton" style={{ height: 56 }} /><span className="sr">Loading…</span></div>}
          {items && items.length === 0 && <EmptyState>No open commitments.</EmptyState>}
          {items && items.length > 0 && <ul aria-label="Commitments">{items.map(c => <CommitmentRow key={c.id} c={c} busy={busy} change={change} />)}</ul>}
        </>}
        {note && <div className="notice" role="status"><p>{note}</p></div>}
        {err && <p className="err" role="alert">{err}</p>}
      </section>
    </Workspace>);
}
