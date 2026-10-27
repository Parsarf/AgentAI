import { useEffect, useState } from 'react';
import * as I from './Icons';
import { api, ApiError } from '../lib/api';

interface Feature { key: string; group: string; title: string; plain: string; wired: boolean; on: boolean; expires_epoch: number | null }
interface State { groups: { key: string; title: string }[]; features: Feature[]; off_count: number }

const FOR = [{ label: 'Until I turn it back on', minutes: 0 }, { label: '30 minutes', minutes: 30 }, { label: '2 hours', minutes: 120 }, { label: '8 hours', minutes: 480 }, { label: '24 hours', minutes: 1440 }];

/** The owner's Safety popup. The server answers 404 to everyone else, so the button only appears for the owner account. */
export default function SafetyButton() {
  const [state, setState] = useState<State | null>(null); const [open, setOpen] = useState(false);
  const load = async () => { try { const s = await api<State>('GET', '/v1/safety'); setState(Array.isArray(s.features) ? s : null); } catch { setState(null); } };
  useEffect(() => { void load(); }, []);
  if (!state) return null;
  return (<>
    <button className="safety-btn" onClick={() => setOpen(true)} title="Safety"><I.Shield width={20} height={20} /><span className="lbl">Safety{state.off_count > 0 ? ` · ${state.off_count} off` : ''}</span></button>
    {open && <SafetyDialog state={state} onClose={() => setOpen(false)} onSaved={setState} />}
  </>);
}

export function SafetyDialog({ state, onClose, onSaved }: { state: State; onClose(): void; onSaved(s: State): void }) {
  const [draft, setDraft] = useState<Record<string, boolean>>(() => Object.fromEntries(state.features.map(f => [f.key, f.on])));
  const [password, setPassword] = useState(''); const [minutes, setMinutes] = useState(0); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const changes = Object.fromEntries(state.features.filter(f => draft[f.key] !== f.on).map(f => [f.key, draft[f.key]]));
  const dirty = Object.keys(changes).length;
  const anyOff = Object.values(draft).some(v => !v);
  const setAll = (on: boolean) => setDraft(Object.fromEntries(state.features.map(f => [f.key, on])));
  const apply = async () => {
    setBusy(true); setErr('');
    try { onSaved(await api<State>('POST', '/v1/safety/change', { password, changes, ...(minutes && Object.values(changes).includes(false) ? { minutes } : {}) })); setPassword(''); onClose(); }
    catch (e) { setErr(e instanceof ApiError && e.status === 403 ? 'That password is not right.' : 'That was not accepted. Try again.'); }
    setBusy(false);
  };
  return (
    <div className="safety-scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="panel safety-box" role="dialog" aria-modal="true" aria-label="Safety">
        <header><h2>Safety</h2><button className="btn small" onClick={onClose} aria-label="Close">Close</button></header>
        <p className="muted">Each switch is on or off for your account only. On means the protection works. Changes need your password.</p>
        <p className="safety-all"><button className="btn small" onClick={() => setAll(true)}>Turn everything on</button> <button className="btn small danger" onClick={() => setAll(false)}>Turn everything off</button></p>
        <div className="safety-list">
          {state.groups.map(g => <section key={g.key}><h3>{g.title}</h3>
            {state.features.filter(f => f.group === g.key).map(f => (
              <label key={f.key} className="safety-row">
                <span><b>{f.title}</b>{!f.wired && <em className="faint"> · not enforced yet</em>}<small className="muted">{f.plain}</small></span>
                <input type="checkbox" role="switch" aria-label={f.title} checked={draft[f.key]} onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.checked }))} />
              </label>))}
          </section>)}
        </div>
        {anyOff && <label className="safety-for">Turn off for <select value={minutes} onChange={e => setMinutes(Number(e.target.value))}>{FOR.map(o => <option key={o.minutes} value={o.minutes}>{o.label}</option>)}</select></label>}
        <footer>
          <input type="password" autoComplete="current-password" placeholder="Your password" value={password} onChange={e => setPassword(e.target.value)} aria-label="Your password" />
          <button className="btn primary" disabled={!dirty || !password || busy} onClick={apply}>{busy ? 'Saving…' : `Apply${dirty ? ` ${dirty} change${dirty > 1 ? 's' : ''}` : ''}`}</button>
        </footer>
        {err && <p className="err" role="alert">{err}</p>}
      </div>
    </div>);
}
