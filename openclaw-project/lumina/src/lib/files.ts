export interface ArtifactRow { id: string; version: number; display_name: string; media_type: string; size_bytes: number; created_at: string; task_id?: string | null }
export interface FileGroup { id: string; name: string; latest: ArtifactRow; versions: number }

/** One entry per file name: the newest version, plus how many versions exist. Bundles made for "Download all" are hidden. */
export function groupFiles(rows: ArtifactRow[]): FileGroup[] {
  const by = new Map<string, FileGroup>();
  for (const r of rows) {
    if (/-bundle\.zip$/.test(r.display_name)) continue;
    const g = by.get(r.display_name);
    if (!g) by.set(r.display_name, { id: r.id, name: r.display_name, latest: r, versions: 1 });
    else { g.versions += 1; if (r.version > g.latest.version) g.latest = r; }
  }
  return [...by.values()].sort((a, b) => (b.latest.created_at > a.latest.created_at ? 1 : b.latest.created_at < a.latest.created_at ? -1 : a.name.localeCompare(b.name)));
}

export const humanSize = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
