import { useState } from 'react';
import * as I from './Icons';
import Menu from './ui/Menu';
import { api } from '../lib/api';
import { chatTitle, type ChatSummary } from '../lib/chats';
import { exportError, saveFrom } from '../lib/files';
import { useData } from '../state/data';
export default function ChatActions({ chat, onChanged }: { chat: ChatSummary; onChanged(action: 'rename' | 'archive' | 'restore'): void }) {
  const app = (useData() as ReturnType<typeof useData> | null)?.app;       // also rendered outside the signed-in shell (previews, tests): then nothing optional is offered
  const save = async (format: string) => {
    if (busy) return;
    setBusy(true); setErr('');
    try { await saveFrom(`/v1/conversations/${chat.id}/export`, { format }, `${chatTitle(chat)}.${format}`); } catch (error) { setErr(exportError(error)); } finally { setBusy(false); }
  };
  const [renaming, setRenaming] = useState(false); const [name, setName] = useState(chatTitle(chat)); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const perform = async (action: 'rename' | 'archive' | 'restore') => {
    if (busy) return;
    setBusy(true); setErr('');
    try { await api('POST', `/v1/conversations/${chat.id}/${action}`, action === 'rename' ? { title: name.trim() } : {}); setRenaming(false); onChanged(action); }
    catch { setErr('Could not update this chat. Please try again.'); } finally { setBusy(false); }
  };
  return <>
    <Menu label={`Options for ${chatTitle(chat)}`} align="end" className="chat-actions"
      items={[{ id: 'rename', label: 'Rename', onSelect: () => { setName(chatTitle(chat)); setRenaming(true); } },
        { id: 'archive', label: chat.archived_epoch ? 'Restore chat' : 'Archive chat', disabled: busy, onSelect: () => { void perform(chat.archived_epoch ? 'restore' : 'archive'); } },
        ...(app?.features.convert ? [{ id: 'pdf', label: 'Download chat as PDF', separatorBefore: true, disabled: busy, onSelect: () => { void save('pdf'); } },
          { id: 'docx', label: 'Download chat as Word', disabled: busy, onSelect: () => { void save('docx'); } }] : []),
        { id: 'md', label: 'Download chat as Markdown', separatorBefore: !app?.features.convert, disabled: busy, onSelect: () => { void save('md'); } }]}
      trigger={({ props }) => <button type="button" className="iconbtn small ghost" aria-label={`Options for ${chatTitle(chat)}`} {...props}><I.More width={18} height={18} /></button>} />
    {err && !renaming && <p className="err" role="alert">{err}</p>}
    {renaming && <div className="cmd-back" role="presentation" onMouseDown={() => setRenaming(false)}><form className="cmd chat-rename" role="dialog" aria-modal="true" aria-label="Rename chat" onMouseDown={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); void perform('rename'); }}>
      <h2>Rename chat</h2><label htmlFor={`rename-${chat.id}`} className="sr">Chat name</label><input id={`rename-${chat.id}`} autoFocus value={name} maxLength={90} onChange={e => setName(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') setRenaming(false); }} />
      {err && <p className="err" role="alert">{err}</p>}<div><button type="button" className="btn" onClick={() => setRenaming(false)}>Cancel</button><button type="submit" className="btn primary" disabled={busy || !name.trim()}>Save</button></div>
    </form></div>}
  </>;
}
