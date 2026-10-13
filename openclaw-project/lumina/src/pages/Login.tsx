import { useEffect, useState } from 'react';
import * as I from '../components/Icons';
import Backdrop from '../components/Backdrop';
import { api, resetCsrf } from '../lib/api';
import { codeFromLocation, signInMessage, signUpMessage } from '../lib/signup';
import { useData } from '../state/data';

type Mode = 'in' | 'up' | 'sent' | 'verifying' | 'pending' | 'badlink';

export default function Login() {
  const { signIn } = useData();
  const code = codeFromLocation(window.location.pathname, window.location.search);
  const [mode, setMode] = useState<Mode>(code ? 'verifying' : 'in'); const [open, setOpen] = useState(false);
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [pw2, setPw2] = useState(''); const [trap, setTrap] = useState('');
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);

  useEffect(() => { fetch('/v1/signup/config', { credentials: 'same-origin' }).then(r => r.json()).then(r => setOpen(r.open === true)).catch(() => setOpen(false)); }, []);
  useEffect(() => {
    if (!code) return; let stop = false;
    api('POST', '/auth/signup/verify', { code }).then(() => { if (!stop) setMode('pending'); }).catch(() => { if (!stop) setMode('badlink'); });
    return () => { stop = true; };
  }, [code]);

  const signin = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('');
    try { await signIn(email, pw); } catch (x) { setErr(signInMessage(x)); } finally { setBusy(false); }
  };
  const signup = async (e: React.FormEvent) => {
    e.preventDefault(); setErr('');
    if (pw !== pw2) { setErr('The two passwords are different.'); return; }
    setBusy(true);
    try { await api('POST', '/auth/signup', { email, password: pw, website: trap }); resetCsrf(); setMode('sent'); } catch (x) { setErr(signUpMessage(x)); } finally { setBusy(false); }
  };
  const back = () => { window.history.replaceState(null, '', '/app/'); setMode('in'); setErr(''); };

  return (
    <div className="login"><Backdrop />
      {(mode === 'in' || mode === 'up') && (
        <form className="panel" onSubmit={mode === 'in' ? signin : signup}>
          <div className="brand" style={{ padding: 0 }}><I.Spark /> LUMINA</div>
          <p className="muted">{mode === 'in' ? (open ? 'Sign in to your workspace.' : 'Sign in to your workspace. Access is by invitation.') : 'Create your account. You will confirm your email, then we approve new accounts one by one.'}</p>
          <label className="sr" htmlFor="email">Email</label>
          <input id="email" name="email" type="email" autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus required placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} />
          <label className="sr" htmlFor="password">Password</label>
          <input id="password" name="password" type="password" autoComplete={mode === 'in' ? 'current-password' : 'new-password'} required minLength={mode === 'up' ? 12 : undefined} placeholder={mode === 'up' ? 'Password (12+ characters)' : 'Password'} value={pw} onChange={e => setPw(e.target.value)} />
          {mode === 'up' && <>
            <label className="sr" htmlFor="password2">Repeat password</label>
            <input id="password2" name="password2" type="password" autoComplete="new-password" required placeholder="Repeat password" value={pw2} onChange={e => setPw2(e.target.value)} />
            <input className="trap" tabIndex={-1} autoComplete="off" aria-hidden="true" name="website" value={trap} onChange={e => setTrap(e.target.value)} />
          </>}
          <button className="btn primary" disabled={busy}>{mode === 'in' ? (busy ? 'Signing in…' : 'Sign in') : (busy ? 'Creating…' : 'Create account')}</button>
          {err && <p className="err" role="alert">{err}</p>}
          {mode === 'in' && <a className="faint" href="/account/recover/">Forgot your password?</a>}
          {open && <button type="button" className="linkish" onClick={() => { setMode(mode === 'in' ? 'up' : 'in'); setErr(''); }}>{mode === 'in' ? 'New here? Create an account' : 'Have an account? Sign in'}</button>}
        </form>)}
      {mode === 'sent' && (
        <div className="panel card" style={{ width: 'min(420px,100%)', padding: 30 }}>
          <div className="brand" style={{ padding: 0 }}><I.Spark /> LUMINA</div>
          <h2 style={{ marginTop: 14 }}>Check your email</h2>
          <p className="muted" style={{ marginTop: 8 }}>If the address can receive mail, a confirmation link is on its way. It works for 15 minutes. After you confirm, your account waits for approval and we email you when it is ready.</p>
          <p style={{ marginTop: 16 }}><button className="btn" onClick={back}>Back to sign in</button></p></div>)}
      {mode === 'verifying' && <p className="muted" role="status">Confirming your email…</p>}
      {mode === 'pending' && (
        <div className="panel card" style={{ width: 'min(420px,100%)', padding: 30 }}>
          <div className="brand" style={{ padding: 0 }}><I.Spark /> LUMINA</div>
          <h2 style={{ marginTop: 14 }}>Email confirmed</h2>
          <p className="muted" style={{ marginTop: 8 }}>Your account is waiting for approval. We will email you as soon as it is ready, then you can sign in with the email and password you chose.</p>
          <p style={{ marginTop: 16 }}><button className="btn" onClick={back}>Go to sign in</button></p></div>)}
      {mode === 'badlink' && (
        <div className="panel card" style={{ width: 'min(420px,100%)', padding: 30 }}>
          <h2>This link did not work</h2>
          <p className="muted" style={{ marginTop: 8 }}>It may have expired (links last 15 minutes) or already been used. Create the account again with the same email to get a new link.</p>
          <p style={{ marginTop: 16 }}><button className="btn" onClick={back}>Back to sign in</button></p></div>)}
    </div>);
}
