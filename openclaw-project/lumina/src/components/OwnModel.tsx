import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';

interface State { available: boolean; configured: boolean; host?: string; model?: string; hint?: string }

const PRESETS = [
  { name: 'OpenAI', url: 'https://api.openai.com/v1' },
  { name: 'OpenRouter', url: 'https://openrouter.ai/api/v1' },
  { name: 'Groq', url: 'https://api.groq.com/openai/v1' },
];

/** Settings card: use your own model API key. Shown only when the server says it is on for this account. The key is sent once, tested, stored encrypted, and never shown again. */
export default function OwnModel() {
  const [state, setState] = useState<State | null>(null);
  const [url, setUrl] = useState(''); const [model, setModel] = useState(''); const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false); const [problem, setProblem] = useState(''); const [note, setNote] = useState('');
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    try { const r = await api<State>('GET', '/v1/model-key'); if (alive.current) setState(r); }
    catch { if (alive.current) setState({ available: false, configured: false }); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setProblem(''); setNote('');
    try {
      const r = await api<State & { applies?: string }>('POST', '/v1/model-key/save', { base_url: url, api_key: key, model });
      if (!alive.current) return;
      setState({ available: true, configured: true, host: r.host, model: r.model, hint: r.hint }); setKey(''); setUrl(''); setModel('');          // the key leaves the page at once
      setNote(`Saved. Your assistant switches to it ${r.applies ?? 'the next time it starts'}.`);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setProblem(status === 422 && err instanceof ApiError && err.detail ? err.detail : status === 429 ? 'Too many tries. Wait a few minutes, then try again.' : status === 409 ? 'This is not available for your account.' : 'Could not save it. Try again.');
    } finally { if (alive.current) setBusy(false); }
  }

  async function remove() {
    setBusy(true); setProblem(''); setNote('');
    try { await api('POST', '/v1/model-key/remove', {}); if (alive.current) { setState({ available: true, configured: false }); setNote('Removed. Your assistant goes back to Lumina’s models the next time it starts.'); } }
    catch { if (alive.current) setProblem('Could not remove it. Try again.'); }
    finally { if (alive.current) setBusy(false); }
  }

  if (!state || !state.available) return null;
  return (
    <section className="panel card" id="own-model" style={{ marginBottom: 14 }} aria-labelledby="own-model-h"><h2 id="own-model-h">Your own model</h2>
      <p className="muted" style={{ marginTop: 10 }}>Use your own API key, so your assistant answers with a model from the company you choose instead of Lumina’s. You pay that company directly, and Lumina’s spending limits do not apply to you.</p>
      <p className="muted" style={{ marginTop: 8 }}>Your messages, and the web pages your assistant reads for you, go to that company instead of Anthropic. Your key is stored encrypted, is never shown again, and is never placed inside your assistant’s workspace. This is for text only: the browser’s own decisions still use Lumina’s.</p>
      {state.configured ? (
        <div className="own-model-current" style={{ marginTop: 12 }}>
          <p><strong>{state.model}</strong> at {state.host}, key ending in <code>{state.hint}</code></p>
          <p style={{ marginTop: 10 }}><button type="button" className="btn small danger" disabled={busy} onClick={remove}>Remove my key</button></p>
        </div>) : (
        <form onSubmit={save} style={{ marginTop: 12, display: 'grid', gap: 10 }}>
          <div className="own-model-presets" role="group" aria-label="Fill in a common address">{PRESETS.map(p => <button key={p.name} type="button" className="chip small" onClick={() => setUrl(p.url)}>{p.name}</button>)}</div>
          <label className="own-model-field">Endpoint address<input className="input" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://api.openai.com/v1" inputMode="url" autoComplete="off" spellCheck={false} required maxLength={300} /></label>
          <label className="own-model-field">Model name<input className="input" value={model} onChange={e => setModel(e.target.value)} placeholder="gpt-4o-mini" autoComplete="off" spellCheck={false} required maxLength={100} /></label>
          <label className="own-model-field">API key<input className="input" type="password" value={key} onChange={e => setKey(e.target.value)} placeholder="Paste your key" autoComplete="off" spellCheck={false} required maxLength={500} /></label>
          <p className="faint">We send one tiny request to check that the address, key and model work, before anything is saved.</p>
          <p><button type="submit" className="btn primary" disabled={busy || !url || !model || !key} aria-busy={busy}>{busy ? 'Testing…' : 'Test and save'}</button></p>
        </form>)}
      {problem && <p className="muted" role="alert" style={{ marginTop: 10 }}>{problem}</p>}
      {note && <p className="muted" role="status" style={{ marginTop: 10 }}>{note}</p>}
    </section>);
}
