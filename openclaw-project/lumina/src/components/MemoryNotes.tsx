import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';

interface Note { id: string; kind: string; content: string; created: number }
interface State { available: boolean; memories: Note[] }

/** Settings card: what Lumina remembers about you, with delete. Shown only when the server says long-term memory is on for this account. Everything shown here, and everything deleted, is this account's alone. */
export default function MemoryNotes() {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false); const [confirmAll, setConfirmAll] = useState(false);
  const [problem, setProblem] = useState(''); const [note, setNote] = useState('');
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    try { const r = await api<State>('GET', '/v1/longterm-memory'); if (alive.current) setState(r); }
    catch { if (alive.current) setState({ available: false, memories: [] }); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function run(path: string, done: string) {
    setBusy(true); setProblem(''); setNote(''); setConfirmAll(false);
    try {
      const r = await api<{ pending?: boolean }>('POST', path, {});
      if (!alive.current) return;
      setNote(r.pending ? 'Removed from your list. Clearing the search copy is still finishing and will complete shortly.' : done);
      await load();
    } catch { if (alive.current) setProblem('Could not delete that. Try again.'); }
    finally { if (alive.current) setBusy(false); }
  }

  if (!state || !state.available) return null;
  return (
    <section className="panel card" id="memory" style={{ marginBottom: 14 }} aria-labelledby="memory-h"><h2 id="memory-h">Memory</h2>
      <p className="muted" style={{ marginTop: 10 }}>Short notes your assistant keeps about what you told it, so it can use them in later conversations. Each note is just a preference or a fact you stated. It never saves passwords, keys or card numbers, and nobody else can see your notes.</p>
      {state.memories.length === 0 ? <p className="faint" style={{ marginTop: 12 }}>Nothing saved yet.</p> : (
        <ul className="memory-notes" style={{ marginTop: 12, display: 'grid', gap: 8, listStyle: 'none', padding: 0 }}>
          {state.memories.map(m => (
            <li key={m.id} style={{ display: 'flex', gap: 10, alignItems: 'baseline', justifyContent: 'space-between' }}>
              <span><span className="faint">{m.kind === 'preference' ? 'Preference' : 'Fact'}: </span>{m.content}</span>
              <button type="button" className="btn small danger" disabled={busy} aria-label={`Delete note: ${m.content}`} onClick={() => run(`/v1/longterm-memory/${m.id}/forget`, 'Deleted.')}>Delete</button>
            </li>))}
        </ul>)}
      {state.memories.length > 0 && (
        <p style={{ marginTop: 12 }}>
          {confirmAll ? (<>
            <span className="muted">Delete every note? This cannot be undone. </span>
            <button type="button" className="btn small danger" disabled={busy} onClick={() => run('/v1/longterm-memory/forget-all', 'Everything was deleted.')}>Yes, delete everything</button>{' '}
            <button type="button" className="btn small" disabled={busy} onClick={() => setConfirmAll(false)}>Cancel</button></>)
            : <button type="button" className="btn small danger" disabled={busy} onClick={() => setConfirmAll(true)}>Delete everything</button>}
        </p>)}
      {problem && <p className="muted" role="alert" style={{ marginTop: 10 }}>{problem}</p>}
      {note && <p className="muted" role="status" style={{ marginTop: 10 }}>{note}</p>}
    </section>);
}
