import { useCallback, useEffect, useMemo, useState } from 'react';
import AppPlayer, { runnableFile } from '../components/apps/AppPlayer';
import { Link } from 'react-router-dom';
import * as I from '../components/Icons';
import { api } from '../lib/api';
import { fileKind, groupFiles, humanSize, KIND_LABEL, previewAs, splitPath, type FileGroup, type FileList } from '../lib/files';
import { download, FileBadge, FilePreview } from '../components/files/FileCard';
import { useData } from '../state/data';

export { download };

const when = (iso: string) => iso.slice(0, 16).replace('T', ' ');

/** One file: what it is, where it came from, a look at it, its earlier versions, download and delete. */
function FileItem({ group, busy, run, onDeleted }: { group: FileGroup; busy: boolean; run(fn: () => Promise<void>): Promise<void>; onDeleted(): void }) {
  const [open, setOpen] = useState(false); const [confirm, setConfirm] = useState(false);
  const file = group.latest; const { name } = splitPath(group.name);
  const more = previewAs(group.name) !== null || group.versions > 1 || runnableFile(file);
  const remove = () => run(async () => { await api('POST', `/v1/artifacts/${group.id}/delete`, {}); onDeleted(); });
  return (
    <div className="file-item">
      <div className="file-item-row">
        <FileBadge name={group.name} />
        <div className="file-card-text"><b title={group.name}>{name}</b>
          <span className="faint small">{KIND_LABEL[fileKind(group.name)]} · {humanSize(file.size_bytes)} · {when(file.created_at)}{group.versions > 1 ? ` · version ${file.version}` : ''}
            {file.conversation_id && <> · <Link to={`/chat/${file.conversation_id}`}>Open the chat</Link></>}</span></div>
        <div className="file-item-actions">
          {more && <button type="button" className="btn small tertiary" aria-expanded={open} onClick={() => setOpen(o => !o)}>{open ? 'Hide' : previewAs(group.name) || runnableFile(file) ? 'Preview' : 'Versions'}</button>}
          <button type="button" className="btn small" disabled={busy} onClick={() => run(() => download(group.id, file.version))}><I.Download width={16} height={16} /> Download</button>
          <button type="button" className="iconbtn small ghost" aria-label={`Delete ${name}`} title="Delete" disabled={busy} onClick={() => setConfirm(true)}><I.Trash width={16} height={16} /></button>
        </div>
      </div>
      {confirm && <div className="file-item-more"><div className="file-confirm" role="alertdialog" aria-label={`Delete ${name}?`}>
        <span>Delete <b>{name}</b>{group.versions > 1 ? ` and its ${group.versions} versions` : ''} for good? This cannot be undone.</span>
        <button type="button" className="btn small danger" disabled={busy} onClick={remove}>Delete</button>
        <button type="button" className="btn small" onClick={() => setConfirm(false)}>Keep</button></div></div>}
      {open && <div className="file-item-more">
        <FilePreview file={file} large />
        {runnableFile(file) && <AppPlayer key={`${group.id}-${file.version}`} file={file} />}
        {group.versions > 1 && <div className="file-versions" aria-label={`Versions of ${name}`}>{group.all.map(v => (
          <div key={v.version}><span>Version {v.version} · {humanSize(v.size_bytes)} · {when(v.created_at)}{v.version === file.version ? ' · newest' : ''}</span>
            <button type="button" className="btn small tertiary" disabled={busy} onClick={() => run(() => download(v.id, v.version))}>Download</button></div>))}</div>}
      </div>}
    </div>);
}

export default function Files() {
  const { app } = useData();
  const [list, setList] = useState<FileList | null>(null); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false); const [query, setQuery] = useState('');
  const load = useCallback(async () => {
    try { setList(await api<FileList>('GET', '/v1/files')); setErr(''); }
    catch { setErr('Could not load your files.'); setList(prev => prev ?? { files: [], used_bytes: 0, quota_bytes: 0 }); }
  }, []);
  useEffect(() => { if (app?.features.files) void load(); }, [app?.features.files, load]);

  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); setErr(''); } catch { setErr('That did not work. Please try again.'); } finally { setBusy(false); } };
  const zip = () => run(async () => { const r = await api<{ bundle: { artifact_id: string; version: number } }>('POST', '/v1/files/bundle', {}); await download(r.bundle.artifact_id, r.bundle.version); });

  const groups = useMemo(() => (list ? groupFiles(list.files) : []), [list]);
  const shown = useMemo(() => { const q = query.trim().toLowerCase(); return q ? groups.filter(g => g.name.toLowerCase().includes(q) || KIND_LABEL[fileKind(g.name)].toLowerCase().includes(q)) : groups; }, [groups, query]);
  // Folders the assistant used ("reports/Q3 sales.xlsx") become sections; files without one come first.
  const folders = useMemo(() => {
    const by = new Map<string, FileGroup[]>();
    for (const g of shown) { const { folder } = splitPath(g.name); by.set(folder, [...(by.get(folder) ?? []), g]); }
    return [...by.entries()].sort(([a], [b]) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b)));
  }, [shown]);

  if (app && !app.features.files) return (
    <div className="center"><h1 className="page-title">Files</h1><section className="panel card"><h2>Not available yet</h2>
      <p className="muted" style={{ marginTop: 8 }}>Saved files are switched off for now.</p><p style={{ marginTop: 16 }}><Link className="btn" to="/">Back to Home</Link></p></section></div>);
  const used = list?.used_bytes ?? 0; const quota = list?.quota_bytes ?? 0; const share = quota ? Math.min(100, Math.round((used / quota) * 100)) : 0;
  return (
    <div className="center"><h1 className="page-title">Files</h1>
      <section className="panel card">
        <div className="card-h"><h2>Made for you</h2>{groups.length > 0 && <button className="btn small" disabled={busy} onClick={zip}>Download all (.zip)</button>}</div>
        {groups.length > 3 && <div className="files-tools"><label className="sr" htmlFor="files-search">Search your files</label>
          <input id="files-search" className="input" type="search" placeholder="Search by name or type" value={query} onChange={e => setQuery(e.target.value)} /></div>}
        {list === null && <p className="muted" role="status" style={{ marginTop: 8 }}>Loading…</p>}
        {list && groups.length === 0 && <p className="faint" style={{ marginTop: 8 }}>Nothing yet. Ask Lumina for a file, such as “a PDF summary of this”, “an Excel sheet of these numbers” or “slides for my talk”, and it appears here.</p>}
        {list && groups.length > 0 && shown.length === 0 && <p className="faint" style={{ marginTop: 8 }}>No file matches “{query.trim()}”.</p>}
        {folders.map(([folder, items]) => (
          <div key={folder || '.'}>
            {folder && <div className="files-folder"><I.Folder width={16} height={16} /> {folder}</div>}
            {items.map(g => <FileItem key={g.id} group={g} busy={busy} run={run} onDeleted={() => { void load(); }} />)}
          </div>))}
        {err && <p className="err" role="alert" style={{ marginTop: 8 }}>{err}</p>}
        {list && quota > 0 && <div className="files-meter" aria-label="Storage used">
          <div className="files-meter-bar"><span className={share >= 95 ? 'full' : undefined} style={{ width: `${share}%` }} /></div>
          <span className="faint small">{humanSize(used)} of {humanSize(quota)} used{share >= 95 ? '. Delete files you no longer need to make room.' : ''}</span></div>}
      </section></div>);
}
