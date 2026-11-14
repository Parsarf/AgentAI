import { ApiError, csrfToken } from './api';

export interface ArtifactRow { id: string; version: number; display_name: string; media_type: string; size_bytes: number; created_at: string; task_id?: string | null; project_id?: string; conversation_id?: string | null }
export interface FileGroup { id: string; name: string; latest: ArtifactRow; versions: number; all: ArtifactRow[] }
export interface FileList { files: ArtifactRow[]; used_bytes: number; quota_bytes: number }

/** One entry per file: its newest version, plus the older ones. Bundles made for "Download all" are hidden. Newest file first. */
export function groupFiles(rows: ArtifactRow[]): FileGroup[] {
  const by = new Map<string, FileGroup>();
  for (const r of rows) {
    if (/-bundle\.zip$/.test(r.display_name)) continue;
    const g = by.get(r.id);                       // a file is its id: the same name in two chats is two files
    if (!g) by.set(r.id, { id: r.id, name: r.display_name, latest: r, versions: 1, all: [r] });
    else { g.versions += 1; g.all.push(r); if (r.version > g.latest.version) { g.latest = r; g.name = r.display_name; } }
  }
  for (const g of by.values()) g.all.sort((a, b) => b.version - a.version);
  return [...by.values()].sort((a, b) => (b.latest.created_at > a.latest.created_at ? 1 : b.latest.created_at < a.latest.created_at ? -1 : a.name.localeCompare(b.name)));
}

export const humanSize = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1073741824).toFixed(2)} GB`);

/** "reports/2026/Q3 sales.xlsx" -> folder "reports/2026", name "Q3 sales.xlsx". */
export function splitPath(path: string): { folder: string; name: string } {
  const at = path.lastIndexOf('/');
  return at === -1 ? { folder: '', name: path } : { folder: path.slice(0, at), name: path.slice(at + 1) };
}

export type FileKind = 'pdf' | 'doc' | 'sheet' | 'slides' | 'image' | 'text' | 'code' | 'audio' | 'video' | 'archive' | 'other';
const KINDS: Record<string, FileKind> = {
  pdf: 'pdf', docx: 'doc', doc: 'doc', odt: 'doc', rtf: 'doc', epub: 'doc', xlsx: 'sheet', xls: 'sheet', ods: 'sheet', csv: 'sheet', tsv: 'sheet', pptx: 'slides', ppt: 'slides', odp: 'slides',
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', svg: 'image', bmp: 'image', tif: 'image', tiff: 'image',
  txt: 'text', md: 'text', ics: 'text', vcf: 'text', html: 'code', htm: 'code', css: 'code', js: 'code', ts: 'code', tsx: 'code', jsx: 'code', py: 'code', json: 'code', xml: 'code', yaml: 'code', yml: 'code', sql: 'code', sh: 'code',
  mp3: 'audio', wav: 'audio', ogg: 'audio', m4a: 'audio', mp4: 'video', webm: 'video', mov: 'video', zip: 'archive', tar: 'archive', gz: 'archive', '7z': 'archive',
};
export const extension = (name: string) => { const base = splitPath(name).name; const at = base.lastIndexOf('.'); return at > 0 ? base.slice(at + 1).toLowerCase() : ''; };
export const fileKind = (name: string): FileKind => KINDS[extension(name)] ?? 'other';
export const KIND_LABEL: Record<FileKind, string> = { pdf: 'PDF', doc: 'Document', sheet: 'Spreadsheet', slides: 'Slides', image: 'Image', text: 'Text', code: 'Code', audio: 'Audio', video: 'Video', archive: 'Archive', other: 'File' };
/** What the preview route can show: a picture (the image itself, or the first page of a document) or the first lines of text. */
export const previewAs = (name: string): 'picture' | 'text' | null => {
  const kind = fileKind(name); const ext = extension(name);
  if (ext === 'svg') return 'text';
  if (kind === 'image') return ['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext) ? 'picture' : null;
  if (kind === 'pdf' || kind === 'slides' || (kind === 'doc' && ext !== 'epub') || (kind === 'sheet' && !['csv', 'tsv'].includes(ext))) return 'picture';
  return kind === 'text' || kind === 'code' || ext === 'csv' || ext === 'tsv' ? 'text' : null;
};
export const previewUrl = (file: Pick<ArtifactRow, 'id' | 'version'>) => `/v1/artifacts/${file.id}/versions/${file.version}/preview`;

/** POST that answers with a file (an export made on the spot): fetches it and hands it to the browser as a download. */
export async function saveFrom(path: string, body: unknown, fallbackName: string): Promise<void> {
  const res = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: '*/*', 'X-CSRFToken': await csrfToken() }, body: JSON.stringify(body) });
  if (!res.ok) { let data: any = {}; try { data = await res.json(); } catch { /* not JSON */ } throw new ApiError(data.error || `http_${res.status}`, res.status, undefined, data.reason); }
  const named = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(res.headers.get('Content-Disposition') ?? '');
  let name = fallbackName; try { if (named) name = decodeURIComponent(named[1]); } catch { /* keep the fallback */ }
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement('a'); link.href = url; link.download = name; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Why an export did not work, in words for the person. */
export function exportError(error: unknown): string {
  const e = error as ApiError;
  if (e?.code === 'convert_not_available') return 'That format is not available right now. Markdown and plain text still work.';
  if (e?.code === 'rate_limited') return 'Too many downloads in a short time. Try again in a few minutes.';
  if (e?.code === 'rejected' && e.detail) return e.detail;
  return 'That download did not work. Please try again.';
}

/** The cells of an HTML table as plain data: headings from the first row, numbers where a cell is nothing but a number. */
export function tableData(table: HTMLTableElement): { columns: string[]; rows: (string | number)[][] } {
  const text = (cell: Element) => (cell.textContent ?? '').replace(/\s+/g, ' ').trim();
  const lines = Array.from(table.rows).map(row => Array.from(row.cells).map(text));
  const value = (cell: string): string | number => /^-?\d{1,15}(\.\d{1,10})?$/.test(cell) && !/^-?0\d/.test(cell) ? Number(cell) : cell;
  return { columns: lines[0] ?? [], rows: lines.slice(1).map(row => row.map(value)) };
}

export function toCsv(columns: string[], rows: (string | number)[][]): string {
  // A cell that a spreadsheet would run as a formula is written as text.
  const cell = (v: string | number) => { let s = String(v); if (typeof v === 'string' && /^[=+@-]/.test(s) && !/^-?\d/.test(s)) s = `'${s}`; return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [columns, ...rows].map(row => row.map(cell).join(',')).join('\r\n') + '\r\n';
}

export function saveText(name: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob(['﻿', text], { type }));
  const link = document.createElement('a'); link.href = url; link.download = name; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
