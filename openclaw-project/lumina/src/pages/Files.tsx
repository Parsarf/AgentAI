import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AppPlayer, { runnableFile } from '../components/apps/AppPlayer';
import { Link } from 'react-router-dom';
import * as I from '../components/Icons';
import { api, ApiError } from '../lib/api';
import { FAMILY_WORDS, fileKind, groupFiles, humanSize, KIND_LABEL, previewAs, splitPath, UPLOAD_ACCEPT, uploadFiles, type Catalogue, type CatalogueFile, type FileGroup, type FileList, type Folder } from '../lib/files';
import { download, FileBadge, FilePreview } from '../components/files/FileCard';
import { useData } from '../state/data';
import Workspace from '../components/frame/Workspace';
import { EmptyState, Inspector } from '../components/frame/parts';
import { useSelection, type Action, type Looking } from '../components/frame/Assistant';
import { useFrame } from '../components/frame/FrameProvider';
import { useCommands } from '../components/frame/CommandBar';
import { useSearchParams } from 'react-router-dom';

export { download };

const when = (iso: string) => iso.slice(0, 16).replace('T', ' ');
const DRAG_TYPE = 'application/x-lumina-file';
const VIEW_KEY = 'lumina.files.view';
const SORTS: Record<string, { label: string; by(a: CatalogueFile, b: CatalogueFile): number }> = {
  newest: { label: 'Newest first', by: (a, b) => b.created_at.localeCompare(a.created_at) }, oldest: { label: 'Oldest first', by: (a, b) => a.created_at.localeCompare(b.created_at) },
  name: { label: 'Name', by: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }) }, size: { label: 'Largest first', by: (a, b) => b.size_bytes - a.size_bytes },
  kind: { label: 'Kind', by: (a, b) => KIND_LABEL[fileKind(a.original_name)].localeCompare(KIND_LABEL[fileKind(b.original_name)]) || a.name.localeCompare(b.name) },
};
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
function FileItem({ file, group, folders, busy, run, onChanged, onOpen, selected }: { file: CatalogueFile; group?: FileGroup; folders: Folder[]; busy: boolean; run: Run; onChanged(): void; onOpen(): void; selected: boolean }) {
  const [open, setOpen] = useState(false); const [confirm, setConfirm] = useState(false);
  // A file the assistant made can carry the folder it wrote it in ("reports/Q3 sales.xlsx"): that path is shown beside the name, which is its last part.
  const made = group?.latest; const { folder: path, name } = splitPath(file.name); const kindName = file.original_name;
  const more = !!made && (previewAs(kindName) !== null || (group?.versions ?? 1) > 1 || runnableFile(made));
  const remove = () => run(async () => { await api('POST', file.kind === 'made' ? `/v1/artifacts/${file.id}/delete` : `/v1/uploads/${file.id}/delete`, {}); onChanged(); });
  return (
    <div className={`file-item${selected ? ' selected' : ''}`} draggable onDragStart={e => { e.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ kind: file.kind, id: file.id })); e.dataTransfer.effectAllowed = 'move'; }}>
      <div className="file-item-row">
        <FileBadge name={kindName} />
        <div className="file-card-text"><button type="button" className="file-open" aria-pressed={selected} aria-label={`Details of ${name}`} onClick={onOpen}><b title={name}>{name}</b></button>
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

/** The inspector for one file: a look at it, its versions, where it came from, and where the customer keeps it. */
function FileDetails({ file, group, folders, busy, run, onChanged }: { file: CatalogueFile; group?: FileGroup; folders: Folder[]; busy: boolean; run: Run; onChanged(): void }) {
  const made = group?.latest; const { folder: path, name } = splitPath(file.name); const kindName = file.original_name;
  return <Inspector title={name} label={`Details of ${name}`} meta={<>{KIND_LABEL[fileKind(kindName)]} · {humanSize(file.size_bytes)} · {when(file.created_at)}</>}
    actions={made ? <button type="button" className="btn small" disabled={busy} onClick={() => run(() => download(file.id, made.version))}><I.Download width={16} height={16} /> Download</button> : undefined}>
    {made && previewAs(kindName) && <FilePreview file={made} large />}
    {made && runnableFile(made) && <AppPlayer key={`${file.id}-${made.version}`} file={made} />}
    {!made && <p className="faint small">A preview is shown for files your assistant made. This file stays exactly as you uploaded it.</p>}
    <section aria-label="Where it came from" className="file-facts"><h3 className="ci-h">Where it came from</h3>
      <p>{file.source === 'uploaded' ? 'You uploaded it.' : 'Your assistant made it.'}{path ? ` It was written in the folder “${path}”.` : ''}{file.copy_of ? ` It has the same content as “${file.copy_of.name}”.` : ''}</p>
      {file.conversation_id && <p><Link to={`/chat/${file.conversation_id}`}>Open the chat it came from</Link></p>}</section>
    {group && group.versions > 1 && <section aria-label={`Versions of ${name}`} className="file-versions"><h3 className="ci-h">Versions ({group.versions})</h3>{group.all.map(v => (
      <div key={v.version}><span>Version {v.version} · {humanSize(v.size_bytes)} · {when(v.created_at)}{v.version === made?.version ? ' · newest' : ''}</span>
        <button type="button" className="btn small tertiary" disabled={busy} onClick={() => run(() => download(v.id, v.version))}>Download</button></div>))}</section>}
    <section aria-label="Where you keep it" className="file-facts"><h3 className="ci-h">Where you keep it</h3><Organize file={file} folders={folders} busy={busy} run={run} onChanged={onChanged} /></section>
  </Inspector>;
}

/** Files: everything the customer uploaded and everything their assistant made, in one list, in folders they choose. Context: the folders of each project (a file dropped
 *  on one moves there). Canvas: the files, as a list or a grid, sorted as chosen. Inspector: the open file. */
export default function Files() {
  const { app } = useData(); const frame = useFrame();
  const [list, setList] = useState<FileList | null>(null); const [cat, setCat] = useState<Catalogue | null>(null); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState(''); const [source, setSource] = useState(''); const [family, setFamily] = useState(''); const [project, setProject] = useState(''); const [folder, setFolder] = useState<string | null | undefined>(undefined);
  const [naming, setNaming] = useState(false); const [folderName, setFolderName] = useState(''); const [note, setNote] = useState<string[]>([]);
  const [opened, setOpened] = useState<string | null>(null); const [sort, setSort] = useState('newest'); const [dropOn, setDropOn] = useState<string | null>(null);
  const [view, setViewState] = useState<'list' | 'grid'>(() => { try { return localStorage.getItem(VIEW_KEY) === 'grid' ? 'grid' : 'list'; } catch { return 'list'; } });
  const setView = (v: 'list' | 'grid') => { setViewState(v); try { localStorage.setItem(VIEW_KEY, v); } catch { /* private mode */ } };
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
      && words.every(w => f.name.toLowerCase().includes(w) || KIND_LABEL[fileKind(f.original_name)].toLowerCase().includes(w))).sort(SORTS[sort].by); }, [cat, project, folder, source, family, query, sort]);
  const families = useMemo(() => [...new Set((cat?.files ?? []).map(f => f.family))].sort(), [cat]);
  const openFile = (cat?.files ?? []).find(f => f.kind + f.id === opened) ?? null;

  const addFolder = () => run(async () => { await api('POST', '/v1/folders', { project_id: activeProject, name: folderName.trim(), ...(folder ? { parent_id: folder } : {}) }); setNaming(false); setFolderName(''); await load(); });
  const removeFolder = (f: Folder) => run(async () => { await api('POST', `/v1/folders/${f.id}`, { delete: true }); if (folder === f.id) setFolder(undefined); await load(); });
  const moveTo = (raw: string, folderId: string | null) => { try { const { kind, id } = JSON.parse(raw) as { kind: string; id: string }; void run(async () => { await api('POST', '/v1/catalogue/place', { kind, id, folder_id: folderId }); await load(); }); } catch { /* not a file of ours */ } };
  const upload = (chosen: FileList | File[] | null) => { const files = Array.from((chosen as ArrayLike<File> | null) ?? []); if (!files.length || !activeProject) return;
    void run(async () => { const r = await uploadFiles(activeProject, files, folder || null);
      setNote([...r.accepted.filter(a => a.already_here).map(a => `“${a.name}” is already here: nothing was added.`), ...r.accepted.filter(a => a.same_as && !a.already_here).map(a => `“${a.name}” has the same content as a file you already have. It was linked, not stored twice.`),
        ...r.rejected.map(x => `“${x.name}” was not kept: ${x.reason}.`)]); if (picker.current) picker.current.value = ''; await load(); }); };

  const current = folders.find(f => f.id === folder);
  const looking: Looking = openFile ? { kind: 'file', source: openFile.kind, id: openFile.id } : current ? { kind: 'folder', id: current.id } : { kind: 'page', page: 'files' };
  const words = openFile ? `the file “${splitPath(openFile.name).name}”` : current ? `the folder “${current.name}”` : 'your files';
  const actions: Action[] = openFile ? [{ label: 'What is this?', message: 'What is this file, and what is it for?' }, { label: 'Where did it come from?', message: 'Which task or chat made or used this file?' }]
    : current ? [{ label: 'What is in this folder?', message: 'What is in this folder, in short?' }] : [];
  useSelection(app?.features.files ? { looking, words, actions } : null);
  useCommands(app?.features.files ? [...(activeProject ? [{ id: 'files-folder', label: 'New folder', run: () => { frame?.reveal('context'); setNaming(true); } }] : []),
    ...(cat?.uploads ? [{ id: 'files-upload', label: 'Upload files', run: () => picker.current?.click() }] : []),
    { id: 'files-view', label: view === 'grid' ? 'Show files as a list' : 'Show files as a grid', run: () => setView(view === 'grid' ? 'list' : 'grid') }] : []);
  // Opened from the command bar: ?open=<kind>:<id> opens that file's details.
  const [params] = useSearchParams();
  useEffect(() => { const want = params.get('open'); if (want && cat) setOpened(want.replace(':', '')); }, [params, cat]);

  if (app && !app.features.files) return (
    <Workspace title="Files"><EmptyState title="Not available yet" action={<Link className="btn" to="/home">Back to Home</Link>}>Saved files are switched off for now.</EmptyState></Workspace>);
  const used = list?.used_bytes ?? 0; const quota = list?.quota_bytes ?? 0; const share = quota ? Math.min(100, Math.round((used / quota) * 100)) : 0;
  const total = cat?.files.length ?? 0;
  const drop = (target: string | null) => ({
    onDragOver: (e: React.DragEvent) => { if (e.dataTransfer.types.includes(DRAG_TYPE)) { e.preventDefault(); setDropOn(target ?? 'none'); } },
    onDragLeave: () => setDropOn(null),
    onDrop: (e: React.DragEvent) => { e.preventDefault(); setDropOn(null); moveTo(e.dataTransfer.getData(DRAG_TYPE), target); },
  });
  const tree = (parent: string | null, projectId: string, depth: number): React.ReactNode => folders.filter(f => f.parent_id === parent && f.project_id === projectId).map(f => <li key={f.id}>
    <button type="button" className={`files-folder${dropOn === f.id ? ' drop' : ''}`} style={{ paddingLeft: 10 + depth * 14 }} aria-pressed={folder === f.id} onClick={() => setFolder(f.id)} {...drop(f.id)}>
      <I.Folder width={14} height={14} /> {f.name} <span className="faint">{f.files}</span></button>
    {folders.some(c => c.parent_id === f.id) && <ul>{tree(f.id, projectId, depth + 1)}</ul>}</li>);
  const picked = () => { if (frame?.sheet === 'context') frame.setSheet(null); };

  const context = cat && (folders.length > 0 || cat.uploads || total > 0) && <nav className="files-folders" aria-label="Folders" onClick={e => { if ((e.target as HTMLElement).closest('.files-folder, .chip')) picked(); }}>
    <button type="button" className={`files-folder${dropOn === 'all' ? ' drop' : ''}`} aria-pressed={folder === undefined} onClick={() => setFolder(undefined)}>All files</button>
    {folders.length > 0 && <button type="button" className={`files-folder${dropOn === 'none' ? ' drop' : ''}`} aria-pressed={folder === null} onClick={() => setFolder(null)} {...drop(null)}>Not in a folder</button>}
    {(project ? projects.filter(p => p.id === project) : projects).map(p => folders.some(f => f.project_id === p.id) && <section key={p.id} aria-label={projects.length > 1 ? `Folders in ${p.name}` : undefined}>
      {projects.length > 1 && <h3 className="ci-h files-project">{p.name}</h3>}<ul className="files-tree">{tree(null, p.id, 0)}</ul></section>)}
    {naming ? <form className="file-rename" onSubmit={e => { e.preventDefault(); if (folderName.trim()) addFolder(); }}>
      <input className="input" aria-label="Name of the new folder" placeholder={current ? `New folder in ${current.name}` : 'New folder'} value={folderName} onChange={e => setFolderName(e.target.value)} maxLength={120} autoFocus />
      <button type="submit" className="btn small primary" disabled={busy || !folderName.trim()}>Create</button><button type="button" className="btn small tertiary" onClick={() => setNaming(false)}>Cancel</button></form>
      : activeProject && <button type="button" className="chip small" onClick={() => setNaming(true)}><I.Plus width={14} height={14} /> New folder</button>}
  </nav>;

  const tools = <>
    {cat?.uploads && <><input ref={picker} type="file" multiple hidden accept={UPLOAD_ACCEPT} aria-label="Choose files to upload" onChange={e => upload(e.target.files as unknown as FileList)} />
      <button className="btn small primary" disabled={busy || !activeProject} onClick={() => picker.current?.click()}><I.Up width={16} height={16} /> Upload</button></>}
    {(app?.features.knowledge || app?.features.commitments) && <Link className="btn small" to="/knowledge">Sources</Link>}
    {(list?.files.length ?? 0) > 0 && <button className="btn small" disabled={busy} onClick={zip}>Download all (.zip)</button>}
    <div className="seg" role="group" aria-label="Show files as"><button type="button" className="seg-item" aria-pressed={view === 'list'} onClick={() => setView('list')}>List</button>
      <button type="button" className="seg-item" aria-pressed={view === 'grid'} onClick={() => setView('grid')}>Grid</button></div>
  </>;

  return (
    <Workspace title={current ? current.name : 'Files'} tools={tools} context={context || null} contextLabel="Folders" className="files-page"
      inspector={openFile ? <FileDetails file={openFile} group={openFile.kind === 'made' ? groups.get(openFile.id) : undefined} folders={cat?.folders ?? []} busy={busy} run={run} onChanged={() => { void load(); }} /> : null}
      inspectorLabel="File" onInspectorClose={() => setOpened(null)}>
      <section className="files-body" aria-label="Your files">
        {cat?.uploads && <p className="faint small">Documents, spreadsheets, slides, PDFs, pictures and text, up to 10 MB each. Every file is checked before it is kept; files with macros or scripts are refused.</p>}
        {note.length > 0 && <div className="notice" role="status">{note.map(n => <p key={n}>{n}</p>)}</div>}
        {total > 0 && <div className="files-tools">
          <label className="sr" htmlFor="files-search">Search your files</label>
          <input id="files-search" className="input" type="search" placeholder="Search by name or type" value={query} onChange={e => setQuery(e.target.value)} />
          <label className="sr" htmlFor="files-source">Where a file came from</label>
          <select id="files-source" className="input files-filter" value={source} onChange={e => setSource(e.target.value)}><option value="">From anywhere</option><option value="uploaded">Uploaded by you</option><option value="made">Made by your assistant</option></select>
          <label className="sr" htmlFor="files-kind">Kind of file</label>
          <select id="files-kind" className="input files-filter" value={family} onChange={e => setFamily(e.target.value)}><option value="">Every kind</option>{families.map(f => <option key={f} value={f}>{FAMILY_WORDS[f] ?? f}</option>)}</select>
          {projects.length > 1 && <><label className="sr" htmlFor="files-project">Project</label>
            <select id="files-project" className="input files-filter" value={project} onChange={e => { setProject(e.target.value); setFolder(undefined); }}><option value="">Every project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></>}
          <label className="sr" htmlFor="files-sort">Sort files</label>
          <select id="files-sort" className="input files-filter" value={sort} onChange={e => setSort(e.target.value)}>{Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        </div>}
        {current && <p className="files-current"><button type="button" className="btn small tertiary" disabled={busy} onClick={() => removeFolder(current)} title="What is inside moves up; nothing is deleted">Remove the folder “{current.name}”</button></p>}
        {cat === null && <div className="hub-loading" role="status">{[0, 1, 2].map(n => <div key={n} className="skeleton" style={{ height: 56 }} />)}<span className="sr">Loading…</span></div>}
        {cat && total === 0 && <EmptyState>Nothing yet. Ask Lumina for a file, such as “a PDF summary of this”, “an Excel sheet of these numbers” or “slides for my talk”, and it appears here.{cat.uploads ? ' You can also upload your own.' : ''}</EmptyState>}
        {cat && total > 0 && shown.length === 0 && <p className="faint">{query.trim() ? `No file matches “${query.trim()}”.` : 'No file here.'}</p>}
        {view === 'grid' ? <ul className="files-grid" aria-label="Files">{shown.map(f => { const k = f.kind + f.id; const { name } = splitPath(f.name); return <li key={k}>
          <button type="button" className="file-tile" aria-pressed={opened === k} draggable onDragStart={e => { e.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ kind: f.kind, id: f.id })); e.dataTransfer.effectAllowed = 'move'; }}
            onClick={() => setOpened(k)}><FileBadge name={f.original_name} /><b title={name}>{name}</b><span className="faint small">{KIND_LABEL[fileKind(f.original_name)]} · {humanSize(f.size_bytes)}</span></button></li>; })}</ul>
          : shown.map(f => <FileItem key={f.kind + f.id} file={f} group={f.kind === 'made' ? groups.get(f.id) : undefined} folders={cat?.folders ?? []} busy={busy} run={run} onChanged={() => { void load(); }}
            onOpen={() => setOpened(f.kind + f.id)} selected={opened === f.kind + f.id} />)}
        {err && <p className="err" role="alert">{err}</p>}
        {list && quota > 0 && <div className="files-meter" aria-label="Storage used">
          <div className="files-meter-bar"><span className={share >= 95 ? 'full' : undefined} style={{ width: `${share}%` }} /></div>
          <span className="faint small">{humanSize(used)} of {humanSize(quota)} used{share >= 95 ? '. Delete files you no longer need to make room.' : ''}</span></div>}
      </section>
    </Workspace>);
}
