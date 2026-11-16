import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AppPlayer, { runnableFile } from '../components/apps/AppPlayer';
import { Link } from 'react-router-dom';
import * as I from '../components/Icons';
import { api, ApiError } from '../lib/api';
import { FAMILY_WORDS, fileKind, groupFiles, humanSize, KIND_LABEL, previewAs, splitPath, UPLOAD_ACCEPT, uploadFiles, type Catalogue, type CatalogueFile, type FileGroup, type FileList, type Folder } from '../lib/files';
import { download, FileBadge, FilePreview } from '../components/files/FileCard';
import { useData } from '../state/data';

export { download };

const when = (iso: string) => iso.slice(0, 16).replace('T', ' ');
type Run = (fn: () => Promise<void>) => Promise<void>;
const placeError = (e: unknown) => (e instanceof ApiError && e.status === 409 ? 'That is not possible: a folder with that name is already there, or it cannot go there.' : 'That did not work. Please try again.');

/** Move to a folder and rename: the customer's own organization. The file itself is never changed. */
function Organize({ file, folders, busy, run, onChanged }: { file: CatalogueFile; folders: Folder[]; busy: boolean; run: Run; onChanged(): void }) {
  const [renaming, setRenaming] = useState(false); const [name, setName] = useState(file.name);
  const mine = folders.filter(f => f.project_id === file.project_id);
  const place = (change: Record<string, unknown>) => run(async () => { await api('POST', '/v1/catalogue/place', { kind: file.kind, id: file.id, ...change }); onChanged(); });
  return (
    <div className="file-organize">
      {mine.length > 0 && <label className="file-move"><span className="sr">Folder of {file.name}</span>
        <select className="input" disabled={busy} value={file.folder_id ?? ''} onChange={e => place({ folder_id: e.target.value || null })}>
          <option value="">No folder</option>{mine.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label>}
      {renaming ? <form className="file-rename" onSubmit={e => { e.preventDefault(); if (name.trim()) { setRenaming(false); void place({ name: name.trim() }); } }}>
        <input className="input" aria-label={`New name for ${file.name}`} value={name} onChange={e => setName(e.target.value)} maxLength={128} autoFocus />
        <button type="submit" className="btn small primary" disabled={busy || !name.trim()}>Save</button>
        {file.name !== file.original_name && <button type="button" className="btn small" disabled={busy} onClick={() => { setRenaming(false); void place({ name: null }); }}>Use “{file.original_name}”</button>}
        <button type="button" className="btn small tertiary" onClick={() => { setRenaming(false); setName(file.name); }}>Cancel</button></form>
        : <button type="button" className="btn small tertiary" disabled={busy} onClick={() => { setName(file.name); setRenaming(true); }}>Rename</button>}
    </div>);
}

/** One file: what it is, where it came from, a look at it, its earlier versions, download and delete; and where the customer put it. */
function FileItem({ file, group, folders, busy, run, onChanged }: { file: CatalogueFile; group?: FileGroup; folders: Folder[]; busy: boolean; run: Run; onChanged(): void }) {
  const [open, setOpen] = useState(false); const [confirm, setConfirm] = useState(false);
  // A file the assistant made can carry the folder it wrote it in ("reports/Q3 sales.xlsx"): that path is shown beside the name, which is its last part.
  const made = group?.latest; const { folder: path, name } = splitPath(file.name); const kindName = file.original_name;
  const more = !!made && (previewAs(kindName) !== null || (group?.versions ?? 1) > 1 || runnableFile(made));
  const remove = () => run(async () => { await api('POST', file.kind === 'made' ? `/v1/artifacts/${file.id}/delete` : `/v1/uploads/${file.id}/delete`, {}); onChanged(); });
  return (
    <div className="file-item">
      <div className="file-item-row">
        <FileBadge name={kindName} />
        <div className="file-card-text"><b title={name}>{name}</b>
          <span className="faint small">{path && <><span className="files-path"><I.Folder width={12} height={12} /> <span>{path}</span></span> · </>}{KIND_LABEL[fileKind(kindName)]} · {humanSize(file.size_bytes)} · {when(file.created_at)}{made && (group?.versions ?? 1) > 1 ? ` · version ${made.version}` : ''} · {file.source === 'uploaded' ? 'You uploaded it' : 'Made by your assistant'}{file.copy_of ? ` · same content as “${file.copy_of.name}”` : ''}
            {file.conversation_id && <> · <Link to={`/chat/${file.conversation_id}`}>Open the chat</Link></>}</span></div>
        <div className="file-item-actions">
          {more && <button type="button" className="btn small tertiary" aria-expanded={open} onClick={() => setOpen(o => !o)}>{open ? 'Hide' : previewAs(kindName) || (made && runnableFile(made)) ? 'Preview' : 'Versions'}</button>}
          {made && <button type="button" className="btn small" disabled={busy} onClick={() => run(() => download(file.id, made.version))}><I.Download width={16} height={16} /> Download</button>}
          <button type="button" className="iconbtn small ghost" aria-label={`Delete ${name}`} title="Delete" disabled={busy} onClick={() => setConfirm(true)}><I.Trash width={16} height={16} /></button>
        </div>
      </div>
      <Organize file={file} folders={folders} busy={busy} run={run} onChanged={onChanged} />
      {confirm && <div className="file-item-more"><div className="file-confirm" role="alertdialog" aria-label={`Delete ${name}?`}>
        <span>Delete <b>{name}</b>{(group?.versions ?? 1) > 1 ? ` and its ${group!.versions} versions` : ''} for good? This cannot be undone.</span>
        <button type="button" className="btn small danger" disabled={busy} onClick={remove}>Delete</button>
        <button type="button" className="btn small" onClick={() => setConfirm(false)}>Keep</button></div></div>}
      {open && made && group && <div className="file-item-more">
        <FilePreview file={made} large />
        {runnableFile(made) && <AppPlayer key={`${group.id}-${made.version}`} file={made} />}
        {group.versions > 1 && <div className="file-versions" aria-label={`Versions of ${name}`}>{group.all.map(v => (
          <div key={v.version}><span>Version {v.version} · {humanSize(v.size_bytes)} · {when(v.created_at)}{v.version === made.version ? ' · newest' : ''}</span>
            <button type="button" className="btn small tertiary" disabled={busy} onClick={() => run(() => download(v.id, v.version))}>Download</button></div>))}</div>}
      </div>}
    </div>);
}

/** Files: everything the customer uploaded and everything their assistant made, in one list, in folders they choose. */
export default function Files() {
  const { app } = useData();
  const [list, setList] = useState<FileList | null>(null); const [cat, setCat] = useState<Catalogue | null>(null); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState(''); const [source, setSource] = useState(''); const [family, setFamily] = useState(''); const [project, setProject] = useState(''); const [folder, setFolder] = useState<string | null | undefined>(undefined);
  const [naming, setNaming] = useState(false); const [folderName, setFolderName] = useState(''); const [note, setNote] = useState<string[]>([]);
  const picker = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    try { const [files, catalogue] = await Promise.all([api<FileList>('GET', '/v1/files'), api<Catalogue>('GET', '/v1/catalogue')]); setList(files); setCat(catalogue); setErr(''); }
    catch { setErr('Could not load your files.'); setList(prev => prev ?? { files: [], used_bytes: 0, quota_bytes: 0 }); setCat(prev => prev ?? { files: [], folders: [], projects: [], total: 0, uploads: false }); }
  }, []);
  useEffect(() => { if (app?.features.files) void load(); }, [app?.features.files, load]);

  const run: Run = async fn => { setBusy(true); try { await fn(); setErr(''); } catch (e) { setErr(placeError(e)); } finally { setBusy(false); } };
  const zip = () => run(async () => { const r = await api<{ bundle: { artifact_id: string; version: number } }>('POST', '/v1/files/bundle', {}); await download(r.bundle.artifact_id, r.bundle.version); });

  const groups = useMemo(() => new Map((list ? groupFiles(list.files) : []).map(g => [g.id, g])), [list]);
  const projects = cat?.projects ?? []; const activeProject = project || projects[0]?.id || '';
  const folders = useMemo(() => (cat?.folders ?? []).filter(f => !project || f.project_id === project), [cat, project]);
  const shown = useMemo(() => { const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return (cat?.files ?? []).filter(f => (!project || f.project_id === project) && (folder === undefined || f.folder_id === folder) && (!source || f.source === source) && (!family || f.family === family)
      && words.every(w => f.name.toLowerCase().includes(w) || KIND_LABEL[fileKind(f.original_name)].toLowerCase().includes(w))); }, [cat, project, folder, source, family, query]);
  const families = useMemo(() => [...new Set((cat?.files ?? []).map(f => f.family))].sort(), [cat]);

  const addFolder = () => run(async () => { await api('POST', '/v1/folders', { project_id: activeProject, name: folderName.trim(), ...(folder ? { parent_id: folder } : {}) }); setNaming(false); setFolderName(''); await load(); });
  const removeFolder = (f: Folder) => run(async () => { await api('POST', `/v1/folders/${f.id}`, { delete: true }); if (folder === f.id) setFolder(undefined); await load(); });
  const upload = (chosen: FileList | File[] | null) => { const files = Array.from((chosen as ArrayLike<File> | null) ?? []); if (!files.length || !activeProject) return;
    void run(async () => { const r = await uploadFiles(activeProject, files, folder || null);
      setNote([...r.accepted.filter(a => a.already_here).map(a => `“${a.name}” is already here: nothing was added.`), ...r.accepted.filter(a => a.same_as && !a.already_here).map(a => `“${a.name}” has the same content as a file you already have. It was linked, not stored twice.`),
        ...r.rejected.map(x => `“${x.name}” was not kept: ${x.reason}.`)]); if (picker.current) picker.current.value = ''; await load(); }); };

  if (app && !app.features.files) return (
    <div className="center"><h1 className="page-title">Files</h1><section className="panel card"><h2>Not available yet</h2>
      <p className="muted" style={{ marginTop: 8 }}>Saved files are switched off for now.</p><p style={{ marginTop: 16 }}><Link className="btn" to="/">Back to Home</Link></p></section></div>);
  const used = list?.used_bytes ?? 0; const quota = list?.quota_bytes ?? 0; const share = quota ? Math.min(100, Math.round((used / quota) * 100)) : 0;
  const total = cat?.files.length ?? 0; const current = folders.find(f => f.id === folder);
  return (
    <div className="center"><h1 className="page-title">Files</h1>
      <section className="panel card">
        <div className="card-h"><h2>Your files</h2>
          <div className="files-head-actions">
            {cat?.uploads && <><input ref={picker} type="file" multiple hidden accept={UPLOAD_ACCEPT} aria-label="Choose files to upload" onChange={e => upload(e.target.files as unknown as FileList)} />
              <button className="btn small primary" disabled={busy || !activeProject} onClick={() => picker.current?.click()}><I.Up width={16} height={16} /> Upload</button></>}
            {(list?.files.length ?? 0) > 0 && <button className="btn small" disabled={busy} onClick={zip}>Download all (.zip)</button>}</div></div>
        {cat?.uploads && <p className="faint small" style={{ marginTop: 6 }}>Documents, spreadsheets, slides, PDFs, pictures and text, up to 10 MB each. Every file is checked before it is kept; files with macros or scripts are refused.</p>}
        {note.length > 0 && <div className="notice" role="status" style={{ marginTop: 10 }}>{note.map(n => <p key={n}>{n}</p>)}</div>}
        {total > 0 && <div className="files-tools">
          <label className="sr" htmlFor="files-search">Search your files</label>
          <input id="files-search" className="input" type="search" placeholder="Search by name or type" value={query} onChange={e => setQuery(e.target.value)} />
          <label className="sr" htmlFor="files-source">Where a file came from</label>
          <select id="files-source" className="input files-filter" value={source} onChange={e => setSource(e.target.value)}><option value="">From anywhere</option><option value="uploaded">Uploaded by you</option><option value="made">Made by your assistant</option></select>
          <label className="sr" htmlFor="files-kind">Kind of file</label>
          <select id="files-kind" className="input files-filter" value={family} onChange={e => setFamily(e.target.value)}><option value="">Every kind</option>{families.map(f => <option key={f} value={f}>{FAMILY_WORDS[f] ?? f}</option>)}</select>
          {projects.length > 1 && <><label className="sr" htmlFor="files-project">Project</label>
            <select id="files-project" className="input files-filter" value={project} onChange={e => { setProject(e.target.value); setFolder(undefined); }}><option value="">Every project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></>}
        </div>}
        {cat && (folders.length > 0 || cat.uploads || total > 0) && <nav className="files-folders" aria-label="Folders">
          <button type="button" className="chip small" aria-pressed={folder === undefined} onClick={() => setFolder(undefined)}>All files</button>
          {folders.length > 0 && <button type="button" className="chip small" aria-pressed={folder === null} onClick={() => setFolder(null)}>Not in a folder</button>}
          {folders.map(f => <button key={f.id} type="button" className="chip small" aria-pressed={folder === f.id} onClick={() => setFolder(f.id)}><I.Folder width={14} height={14} /> {f.name} <span className="faint">{f.files}</span></button>)}
          {naming ? <form className="file-rename" onSubmit={e => { e.preventDefault(); if (folderName.trim()) addFolder(); }}>
            <input className="input" aria-label="Name of the new folder" placeholder={current ? `New folder in ${current.name}` : 'New folder'} value={folderName} onChange={e => setFolderName(e.target.value)} maxLength={120} autoFocus />
            <button type="submit" className="btn small primary" disabled={busy || !folderName.trim()}>Create</button><button type="button" className="btn small tertiary" onClick={() => setNaming(false)}>Cancel</button></form>
            : activeProject && <button type="button" className="chip small" onClick={() => setNaming(true)}><I.Plus width={14} height={14} /> New folder</button>}
          {current && <button type="button" className="btn small tertiary" disabled={busy} onClick={() => removeFolder(current)} title="What is inside moves up; nothing is deleted">Remove the folder “{current.name}”</button>}
        </nav>}
        {cat === null && <p className="muted" role="status" style={{ marginTop: 8 }}>Loading…</p>}
        {cat && total === 0 && <p className="faint" style={{ marginTop: 8 }}>Nothing yet. Ask Lumina for a file, such as “a PDF summary of this”, “an Excel sheet of these numbers” or “slides for my talk”, and it appears here.{cat.uploads ? ' You can also upload your own.' : ''}</p>}
        {cat && total > 0 && shown.length === 0 && <p className="faint" style={{ marginTop: 8 }}>{query.trim() ? `No file matches “${query.trim()}”.` : 'No file here.'}</p>}
        {shown.map(f => <FileItem key={f.kind + f.id} file={f} group={f.kind === 'made' ? groups.get(f.id) : undefined} folders={cat?.folders ?? []} busy={busy} run={run} onChanged={() => { void load(); }} />)}
        {err && <p className="err" role="alert" style={{ marginTop: 8 }}>{err}</p>}
        {list && quota > 0 && <div className="files-meter" aria-label="Storage used">
          <div className="files-meter-bar"><span className={share >= 95 ? 'full' : undefined} style={{ width: `${share}%` }} /></div>
          <span className="faint small">{humanSize(used)} of {humanSize(quota)} used{share >= 95 ? '. Delete files you no longer need to make room.' : ''}</span></div>}
      </section></div>);
}
