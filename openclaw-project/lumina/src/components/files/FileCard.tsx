import { useEffect, useState } from 'react';
import * as I from '../Icons';
import { api } from '../../lib/api';
import { fileKind, humanSize, KIND_LABEL, previewAs, previewUrl, splitPath, extension, type ArtifactRow } from '../../lib/files';
import './files.css';

/** Starts a download through a short-lived single-use ticket (the browser never gets a permanent link). */
export async function download(id: string, version: number) {
  const r = await api<{ download: { path: string } }>('POST', `/v1/artifacts/${id}/versions/${version}/ticket`, {});
  window.location.assign(r.download.path);
}

/** What the file looks like: the picture, the first page of a document, or the first lines of text. Shows nothing when there is nothing to show. */
export function FilePreview({ file, large = false }: { file: ArtifactRow; large?: boolean }) {
  const mode = previewAs(file.display_name);
  const [state, setState] = useState<'loading' | 'ready' | 'none'>(mode ? 'loading' : 'none');
  const [text, setText] = useState('');
  useEffect(() => {
    if (mode !== 'text') return; let stop = false;
    fetch(previewUrl(file), { credentials: 'same-origin' }).then(r => r.ok ? r.text() : Promise.reject(new Error('none')))
      .then(t => { if (!stop) { setText(t.slice(0, large ? 20000 : 600)); setState('ready'); } }).catch(() => { if (!stop) setState('none'); });
    return () => { stop = true; };
  }, [file.id, file.version, mode, large]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!mode || state === 'none') return null;
  if (mode === 'text') return state === 'ready' ? <pre className={`file-preview text${large ? ' large' : ''}`} aria-label={`Start of ${splitPath(file.display_name).name}`}>{text}</pre> : null;
  return <img className={`file-preview picture${large ? ' large' : ''}${state === 'loading' ? ' loading' : ''}`} src={previewUrl(file)} loading="lazy" decoding="async"
    alt={`Preview of ${splitPath(file.display_name).name}`} onLoad={() => setState('ready')} onError={() => setState('none')} />;
}

export function FileBadge({ name }: { name: string }) {
  const kind = fileKind(name);
  return <span className={`file-badge kind-${kind}`} aria-hidden="true">{(extension(name) || 'file').slice(0, 4).toUpperCase()}</span>;
}

/** A file Lumina made, as it appears under an answer: what it is, a look at it, and the download. */
export default function FileCard({ file, onError }: { file: ArtifactRow; onError?(message: string): void }) {
  const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false);
  const { name } = splitPath(file.display_name);
  const can = previewAs(file.display_name) !== null;
  const get = async () => { setBusy(true); try { await download(file.id, file.version); } catch { onError?.('That download did not work. Please try again.'); } finally { setBusy(false); } };
  return (
    <div className="file-card">
      <div className="file-card-row">
        <FileBadge name={file.display_name} />
        <div className="file-card-text"><b title={file.display_name}>{name}</b><span className="faint small">{KIND_LABEL[fileKind(file.display_name)]} · {humanSize(file.size_bytes)}{file.version > 1 ? ` · version ${file.version}` : ''}</span></div>
        {can && <button type="button" className="btn small tertiary" aria-expanded={open} onClick={() => setOpen(o => !o)}>{open ? 'Hide' : 'Preview'}</button>}
        <button type="button" className="btn small" disabled={busy} onClick={get}><I.Download width={16} height={16} /> Download</button>
      </div>
      {open && <FilePreview file={file} />}
    </div>);
}
