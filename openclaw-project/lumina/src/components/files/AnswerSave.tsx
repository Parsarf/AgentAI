import { useState } from 'react';
import * as I from '../Icons';
import Menu from '../ui/Menu';
import { exportError, saveFrom, type ArtifactRow } from '../../lib/files';
import './files.css';

/** The newest version of each file one task made, in the order they were made. */
export function filesOf(made: ArtifactRow[], task: string | null | undefined): ArtifactRow[] {
  const by = new Map<string, ArtifactRow>();
  for (const a of made) { if (a.task_id !== task || /-bundle\.zip$/.test(a.display_name)) continue; const seen = by.get(a.id); if (!seen || a.version > seen.version) by.set(a.id, a); }
  return [...by.values()].sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
}

export const SAVE_FORMATS = [
  { id: 'pdf', label: 'PDF', converted: true }, { id: 'docx', label: 'Word document', converted: true },
  { id: 'md', label: 'Markdown', converted: false }, { id: 'txt', label: 'Plain text', converted: false },
] as const;

/** "Download as": one answer (or, without `message`, the whole chat) as a file in the format picked. Made on the spot; nothing is stored. */
export default function AnswerSave({ conversation, message, convert, onError, label = 'Download this answer as' }: { conversation: string; message?: number; convert: boolean; onError(message: string): void; label?: string }) {
  const [busy, setBusy] = useState(false);
  const save = async (format: string) => {
    if (busy) return;
    setBusy(true);
    try { await saveFrom(`/v1/conversations/${conversation}/export`, message === undefined ? { format } : { format, message: String(message) }, `Lumina.${format}`); }
    catch (error) { onError(exportError(error)); } finally { setBusy(false); }
  };
  return (
    <div className="answer-save">
      <Menu label={label} heading={label} items={SAVE_FORMATS.filter(f => convert || !f.converted).map(f => ({ id: f.id, label: f.label, disabled: busy, onSelect: () => { void save(f.id); } }))}
        trigger={({ props }) => <button type="button" className="chip small" aria-label={label} disabled={busy} {...props}><I.Download width={14} height={14} /> {busy ? 'Preparing…' : 'Download as'}</button>} />
    </div>);
}
