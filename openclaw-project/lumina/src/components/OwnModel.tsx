import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';

type Key = { id: string; host: string; model: string; hint: string };
type State = { available: boolean; configured: boolean; selected: string; keys: Key[]; lumina_models: { id: string; name: string }[] };
const PRESETS = [
  { name: 'OpenAI', url: 'https://api.openai.com/v1' },
  { name: 'OpenRouter', url: 'https://openrouter.ai/api/v1' },
  { name: 'Groq', url: 'https://api.groq.com/openai/v1' },
];

/** Saved credentials are separate from selection. The server owns available models. */
export default function OwnModel() {
  const [state, setState] = useState<State | null>(null);
  const [url, setUrl] = useState(''); const [model, setModel] = useState(''); const [key, setKey] = useState('');
  const [choice, setChoice] = useState('');
  const [busy, setBusy] = useState(false); const [problem, setProblem] = useState(''); const [note, setNote] = useState('');
  const alive = useRef(true);
  const update = (r: State) => { const value = { ...r, keys: r.keys ?? [], lumina_models: r.lumina_models ?? [], selected: r.selected ?? 'lumina-default' }; setState(value); setChoice(value.selected); };
  useEffect(() => {
    alive.current = true;
    void api<State>('GET', '/v1/model-key').then(r => { if (alive.current) update(r); }).catch(() => { if (alive.current) setProblem('Could not load model settings. Reload the page to try again.'); });
    return () => { alive.current = false; };
  }, []);

  async function change(path: string, body: unknown, message: string) {
    setBusy(true); setProblem(''); setNote('');
    try {
      const r = await api<State>('POST', path, body);
      if (!alive.current) return;
      update(r); setNote(message);
      if (path.endsWith('/save')) { setUrl(''); setModel(''); }
    } catch (err) {
      if (alive.current && path.endsWith('/select') && state) setChoice(state.selected);
      if (alive.current) setProblem(err instanceof ApiError && err.detail ? err.detail : err instanceof ApiError && err.status === 429 ? 'Too many tries. Wait a few minutes, then try again.' : 'Could not update model settings. Try again.');
    } finally { if (alive.current) { setBusy(false); setKey(''); } }
  }
  const known = state && [...state.lumina_models, ...state.keys].some(m => m.id === state.selected);
  if (!state) return problem ? <p role="alert">{problem}</p> : null;
  return <section className="panel card" id="own-model" style={{ marginBottom: 14 }} aria-labelledby="own-model-h">
    <h2 id="own-model-h">Models</h2>
    <p className="muted" style={{ marginTop: 10 }}>Choose a Lumina model or a model using one of your saved API keys. Switching keeps your saved keys and applies to your next task. Finish or stop pending tasks before changing these settings.</p>
    <form onSubmit={e => { e.preventDefault(); void change('/v1/model-key/select', { id: choice }, 'Selected. Your next task will use this model.'); }} style={{ marginTop: 12 }}>
      <label>Assistant model<select className="input" aria-label="Assistant model" value={choice} disabled={busy} onChange={e => setChoice(e.target.value)}>
        {!known && <option value={state.selected} disabled>Previously selected model is unavailable</option>}
        <optgroup label="Lumina">{state.lumina_models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</optgroup>
        {!!state.keys.length && <optgroup label="Your API keys">{state.keys.map(k => <option key={k.id} value={k.id} disabled={!state.available}>{k.model} · {k.host} · ending {k.hint}{state.available ? '' : ' (unavailable)'}</option>)}</optgroup>}
      </select></label>{' '}
      <button className="btn small" disabled={busy || choice === state.selected} type="submit">Use model</button>
    </form>
    <p className="faint" style={{ marginTop: 8 }}>{state.selected.startsWith('key:') ? 'Your provider bills model usage directly. Browser decisions still use Lumina.' : 'Lumina models use your Lumina allowance and spending limits.'}</p>
    {!!state.keys.length && <div style={{ marginTop: 12 }} aria-label="Saved API keys">{state.keys.map(k => <p key={k.id}>
      <strong>{k.model}</strong> at {k.host}, key ending in <code>{k.hint}</code>{' '}
      <button type="button" className="btn small danger" disabled={busy} aria-label={`Remove ${k.model} key ending ${k.hint}`} onClick={() => { void change('/v1/model-key/remove', { id: k.id }, 'Key removed. Removing the selected key returns your next task to Lumina.'); }}>Remove key</button>
    </p>)}</div>}
    {state.available && <form onSubmit={e => { e.preventDefault(); const secret = key; setKey(''); void change('/v1/model-key/save', { base_url: url, api_key: secret, model }, 'Key saved. Choose it above when you want to use it.'); }} style={{ marginTop: 12, display: 'grid', gap: 10 }}>
      <h3>Add an API key</h3>
      <p className="muted">Keys are stored encrypted and never returned. When selected, your messages and tool results go to that provider. Use an OpenAI-compatible endpoint and model.</p>
      <div role="group" aria-label="Fill in a common address">{PRESETS.map(p => <button key={p.name} type="button" className="chip small" disabled={busy} onClick={() => setUrl(p.url)}>{p.name}</button>)}</div>
      <label>Endpoint address<input className="input" value={url} disabled={busy} onChange={e => setUrl(e.target.value)} placeholder="https://api.openai.com/v1" inputMode="url" autoComplete="off" spellCheck={false} required maxLength={300} /></label>
      <label>Model name<input className="input" value={model} disabled={busy} onChange={e => setModel(e.target.value)} placeholder="Model ID from your provider" autoComplete="off" spellCheck={false} required maxLength={100} /></label>
      <label>API key<input className="input" type="password" value={key} disabled={busy} onChange={e => setKey(e.target.value)} placeholder="Paste your key" autoComplete="off" spellCheck={false} required maxLength={500} /></label>
      <p className="faint">We send one tiny request to check the address, key and model before saving. Up to 20 keys can be saved.</p>
      <p><button type="submit" className="btn primary" disabled={busy || !url || !model || !key || state.keys.length >= 20} aria-busy={busy}>{busy ? 'Saving…' : 'Test and save'}</button></p>
    </form>}
    {problem && <p className="muted" role="alert" style={{ marginTop: 10 }}>{problem}</p>}
    {note && <p className="muted" role="status" style={{ marginTop: 10 }}>{note}</p>}
  </section>;
}
