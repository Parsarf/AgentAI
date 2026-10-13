import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { groupFiles, humanSize, type ArtifactRow } from '../lib/files';
import { useData } from '../state/data';

/** Starts a download through a short-lived single-use ticket (the browser never gets a permanent link). */
export async function download(id: string, version: number) {
  const r = await api<{ download: { path: string } }>('POST', `/v1/artifacts/${id}/versions/${version}/ticket`, {});
  window.location.assign(r.download.path);
}

export default function Files() {
  const { app } = useData();
  const [rows, setRows] = useState<ArtifactRow[] | null>(null); const [project, setProject] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const { projects } = await api<{ projects: { id: string }[] }>('GET', '/v1/projects');
      const results = await Promise.all(projects.map(p => api<{ artifacts: ArtifactRow[] }>('GET', `/v1/projects/${p.id}/files`)));
      setProject(projects[0]?.id ?? ''); setRows(results.flatMap(r => r.artifacts)); setErr('');
    } catch { setErr('Could not load your files.'); setRows(prev => prev ?? []); }
  }, []);
  useEffect(() => { if (app?.features.files) load(); }, [app?.features.files, load]);

  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); setErr(''); } catch { setErr('That did not work. Please try again.'); } finally { setBusy(false); } };
  const zip = () => run(async () => { const r = await api<{ bundle: { artifact_id: string; version: number } }>('POST', `/v1/projects/${project}/bundle`, {}); await download(r.bundle.artifact_id, r.bundle.version); });

  if (app && !app.features.files) return (
    <div className="center"><h1 className="page-title">Files</h1><section className="panel card"><h2>Not available yet</h2>
      <p className="muted" style={{ marginTop: 8 }}>Saved files are switched off for now.</p><p style={{ marginTop: 16 }}><Link className="btn" to="/">Back to Home</Link></p></section></div>);
  const groups = rows ? groupFiles(rows) : [];
  return (
    <div className="center"><h1 className="page-title">Files</h1>
      <section className="panel card">
        <div className="card-h"><h2>Made for you</h2>{groups.length > 0 && <button className="btn small" disabled={busy} onClick={zip}>Download all (.zip)</button>}</div>
        {rows === null && <p className="muted" role="status" style={{ marginTop: 8 }}>Loading…</p>}
        {rows && groups.length === 0 && <p className="faint" style={{ marginTop: 8 }}>Nothing yet. When Lumina writes a file for you, such as code, a document or a spreadsheet, it appears here.</p>}
        {groups.map(g => (
          <div key={g.name} className="filerow">
            <div><b>{g.name}</b><div className="faint small">{humanSize(g.latest.size_bytes)} · {g.latest.created_at.slice(0, 16).replace('T', ' ')}{g.versions > 1 ? ` · version ${g.latest.version}` : ''}</div></div>
            <button className="btn small" disabled={busy} onClick={() => run(() => download(g.id, g.latest.version))}>Download</button>
          </div>))}
        {err && <p className="err" role="alert" style={{ marginTop: 8 }}>{err}</p>}
      </section></div>);
}
