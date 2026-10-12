import { useState } from 'react';
import * as I from '../components/Icons';
import Backdrop from '../components/Backdrop';
import { ApiError } from '../lib/api';
import { useData } from '../state/data';

export default function Login() {
  const { signIn } = useData(); const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('');
    try { await signIn(email, pw); } catch (x) { setErr(x instanceof ApiError && x.status === 429 ? 'Too many attempts. Wait a few minutes.' : 'Those details did not work.'); }
    finally { setBusy(false); }
  };
  return (
    <div className="login"><Backdrop />
      <form className="panel" onSubmit={submit}>
        <div className="brand" style={{ padding: 0 }}><I.Spark /> LUMINA</div>
        <p className="muted">Sign in to your workspace. Access is by invitation.</p>
        <label className="sr" htmlFor="email">Email</label>
        <input id="email" name="email" type="email" autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus required placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} />
        <label className="sr" htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required placeholder="Password" value={pw} onChange={e => setPw(e.target.value)} />
        <button className="btn primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        {err && <p className="err" role="alert">{err}</p>}
        <a className="faint" href="/account/recover/">Forgot your password?</a>
      </form></div>);
}
