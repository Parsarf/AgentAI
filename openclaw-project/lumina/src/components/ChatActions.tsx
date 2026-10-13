import { useRef, useState } from 'react';
import { api } from '../lib/api';
import { chatTitle, type ChatSummary } from '../lib/chats';
export default function ChatActions({ chat, onChanged }: { chat: ChatSummary; onChanged(action: 'rename' | 'archive' | 'restore'): void }) {
  const [renaming, setRenaming] = useState(false); const [name, setName] = useState(chatTitle(chat)); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const menu = useRef<HTMLDetailsElement>(null);
  const perform = async (action: 'rename' | 'archive' | 'restore') => {
    if (busy) return;
    setBusy(true); setErr('');
    try { await api('POST', `/v1/conversations/${chat.id}/${action}`, action === 'rename' ? { title: name.trim() } : {}); setRenaming(false); if (menu.current) menu.current.open = false; onChanged(action); }
    catch { setErr('Could not update this chat. Please try again.'); } finally { setBusy(false); }
  };
  return <>
    <details className="chat-actions" ref={menu}><summary aria-label={`Options for ${chatTitle(chat)}`}>⋯</summary><div className="chat-actions-menu">
      <button onClick={() => { setName(chatTitle(chat)); setRenaming(true); if (menu.current) menu.current.open = false; }}>Rename</button>
      <button disabled={busy} onClick={() => perform(chat.archived_epoch ? 'restore' : 'archive')}>{chat.archived_epoch ? 'Restore chat' : 'Archive chat'}</button>
      {err && <p className="err" role="alert">{err}</p>}
    </div></details>
    {renaming && <div className="cmd-back" role="presentation" onMouseDown={() => setRenaming(false)}><form className="cmd chat-rename" role="dialog" aria-modal="true" aria-label="Rename chat" onMouseDown={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); perform('rename'); }}>
      <h2>Rename chat</h2><label htmlFor={`rename-${chat.id}`} className="sr">Chat name</label><input id={`rename-${chat.id}`} autoFocus value={name} maxLength={90} onChange={e => setName(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') setRenaming(false); }} />
      {err && <p className="err" role="alert">{err}</p>}<div><button type="button" className="btn" onClick={() => setRenaming(false)}>Cancel</button><button className="btn primary" disabled={busy || !name.trim()}>Save</button></div>
    </form></div>}
  </>;
}
