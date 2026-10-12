import { useCallback, useEffect, useState } from 'react';
import Composer from '../components/Composer';
import { api } from '../lib/api';
import BlockView from '../components/genui/BlockView';
import type { Block } from '../lib/genui/schema';
import { phase } from '../lib/tasks';
import { useData } from '../state/data';

interface Msg { id: number; provenance: string; content: string; created_at: string }

export default function Chat() {
  const { requests } = useData();
  const [conv, setConv] = useState<string | null>(null); const [msgs, setMsgs] = useState<Msg[]>([]); const [blocks, setBlocks] = useState<Block[]>([]); const [err, setErr] = useState('');
  const working = requests.some(r => ['queued', 'running'].includes(phase(r.state))) || blocks.some(b => b.status === 'submitted');

  const load = useCallback(async () => {
    try {
      let list = (await api<{ conversations: { id: string }[] }>('GET', '/v1/conversations')).conversations;
      if (!list.length) {
        const pj = (await api<{ projects: { id: string }[] }>('GET', '/v1/projects')).projects;
        list = [(await api<{ conversation: { id: string } }>('POST', '/v1/conversations', { project_id: pj[0].id })).conversation];
      }
      const id = list[list.length - 1].id; setConv(id);
      const [m, b] = await Promise.all([api<{ messages: Msg[] }>('GET', `/v1/conversations/${id}/messages`), api<{ blocks: Block[] }>('GET', `/v1/conversations/${id}/blocks`)]);
      setMsgs(m.messages); setBlocks(b.blocks); setErr('');
    } catch { setErr('Could not load the conversation.'); }
  }, []);
  useEffect(() => { load(); }, [load, requests.length, working]);
  useEffect(() => { if (!working) return; const t = setInterval(load, 4000); return () => clearInterval(t); }, [working, load]);
  const clear = async () => { if (conv) { await api('POST', `/v1/conversations/${conv}/archive`, {}); load(); } };

  return (
    <div className="center">
      <h1 className="page-title">Chat</h1>
      {err && <p className="err" role="alert">{err}</p>}
      <div className="thread" aria-live="polite">
        {msgs.map(m => (
          <div key={m.id}>
            <div className={`bubble ${m.provenance === 'agent' ? 'agent' : 'you'}`}><small>{m.provenance === 'agent' ? 'Lumina' : 'You'}</small>{m.content}</div>
            {blocks.filter(b => b.anchor_message_id === m.id).map(b => <BlockView key={b.id} block={b} onChanged={load} />)}
          </div>))}
        {blocks.filter(b => !msgs.some(m => m.id === b.anchor_message_id)).map(b => <BlockView key={b.id} block={b} onChanged={load} />)}
        {working && <div className="bubble agent"><small>Lumina</small><span className="muted">Working…</span></div>}
        {!msgs.length && !err && <div className="empty">No messages yet.</div>}
      </div>
      <Composer onSent={() => load()} />
      {msgs.length > 0 && <p style={{ marginTop: 14 }}><button className="btn" onClick={clear}>Clear conversation</button> <span className="faint">History and cost records are kept; the conversation is hidden.</span></p>}
    </div>);
}
