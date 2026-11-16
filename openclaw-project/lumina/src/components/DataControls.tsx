import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { useData } from '../state/data';

interface Rule { key: string; title: string; kept: string; you_can: string; note: string }
interface Job { id: string; state: string; has_archive: boolean; archive_bytes: number | null; waiting_for: string | null; not_before_epoch: number | null; created_epoch: number; steps: { step: string; state: string }[] }
interface Offboarding extends Job { remains_by_design: string[]; cooling_off_seconds: number }

export const size = (bytes: number | null) => (bytes == null ? '' : bytes < 1e6 ? `${Math.max(1, Math.round(bytes / 1e3))} KB` : `${(bytes / 1e6).toFixed(1)} MB`);
const failed = (e: unknown) => (e instanceof ApiError && e.status === 403 ? 'Your role does not allow this.' : e instanceof ApiError && e.status === 409 ? 'That is not possible right now.' : 'That did not go through. Please try again.');
const REMAINS = ['An empty record of the account, so its id can never be reused.', 'The line of the security record that says the account was deleted.',
  'The amounts and dates of what was charged, as accounting rules require.', 'Encrypted backups made before the deletion, for at most 30 days.'];

/** Settings > Account: how long each kind of data is kept (the server's one retention table), taking your data with you, and closing the account. Export and closing are shown only
 *  where the server offers them. Closing is a guided flow: work stops, you choose whether to export first, connections end, and after a waiting period you can still cancel, everything
 *  is deleted and you get a report. */
export default function DataControls() {
  const app = (useData() as ReturnType<typeof useData> | null)?.app; const self = !!app?.features.self_service;
  const [rules, setRules] = useState<Rule[] | null>(null); const [exports, setExports] = useState<Job[]>([]); const [closing, setClosing] = useState<Offboarding | null>(null);
  const [days, setDays] = useState(7); const [busy, setBusy] = useState(''); const [err, setErr] = useState(''); const [note, setNote] = useState(''); const [sure, setSure] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(async () => {
    try { const r = await api<{ rules: Rule[] }>('GET', '/v1/retention'); if (alive.current) setRules(r.rules); } catch { /* not on this server: the section stays hidden */ }
    if (!self) return;
    try {
      const [e, o] = await Promise.all([api<{ exports: Job[] }>('GET', '/v1/exports'), api<{ offboarding: Offboarding | null; cooling_off_seconds: number }>('GET', '/v1/account/offboarding')]);
      if (alive.current) { setExports(e.exports); setClosing(o.offboarding); setDays(Math.max(0, Math.round(o.cooling_off_seconds / 86400))); }
    } catch { /* shown as unavailable below */ }
  }, [self]);
  useEffect(() => { void load(); }, [load]);
  const run = async (key: string, fn: () => Promise<unknown>, done = '') => {
    setBusy(key); setErr(''); setNote('');
    try { await fn(); if (alive.current) { setNote(done); await load(); } } catch (e) { if (alive.current) setErr(failed(e)); } finally { if (alive.current) setBusy(''); }
  };
  const download = (id: string) => run('download', async () => { const t = await api<{ path: string }>('POST', `/v1/exports/${id}/ticket`, {}); window.location.assign(t.path); });
  const open = closing && ['requested', 'running', 'waiting'].includes(closing.state);
  const deleting = !!closing?.steps.some(s => s.step === 'deletion_started');
  return <>
    {rules && (
      <section className="panel card set-card" aria-labelledby="keep-h">
        <h2 id="keep-h">How long we keep things</h2>
        <div className="acc-table-wrap" tabIndex={0}>
          <table className="acc-table"><thead><tr><th scope="col">What</th><th scope="col">How long</th><th scope="col">What you can do</th></tr></thead>
            <tbody>{rules.map(r => <tr key={r.key}><th scope="row">{r.title}</th><td>{r.kept}{r.note && <span className="faint"> {r.note}</span>}</td><td>{r.you_can || '—'}</td></tr>)}</tbody></table>
        </div>
      </section>)}
    {self && (
      <section className="panel card set-card" aria-labelledby="export-h">
        <h2 id="export-h">Take your data with you</h2>
        <p className="muted">One archive with your chats, files, memory, plans, schedules, connections (never their tokens), settings and usage. It is kept for 7 days.</p>
        <div className="int-row"><button className="btn" disabled={!!busy || exports.some(e => ['requested', 'running', 'waiting'].includes(e.state))} onClick={() => void run('export', () => api('POST', '/v1/exports', {}), 'Your export is being made. It appears here when it is ready.')}>
          {busy === 'export' ? 'Asking…' : 'Export my data'}</button></div>
        {exports.length > 0 && <ul className="acc-plain">{exports.slice(0, 3).map(e => (
          <li key={e.id}>{new Date(e.created_epoch * 1000).toLocaleDateString()}: {e.state === 'completed' && e.has_archive ? <>ready ({size(e.archive_bytes)}) <button className="btn small" disabled={!!busy} onClick={() => void download(e.id)}>Download</button></>
            : e.state === 'expired' || (e.state === 'completed' && !e.has_archive) ? 'removed after 7 days' : e.state === 'failed' ? 'could not be made' : 'being made…'}</li>))}</ul>}
      </section>)}
    {self && (
      <section className="panel card set-card" aria-labelledby="close-h">
        <h2 id="close-h">Close your account</h2>
        {!open ? <>
          <p className="muted">Closing stops your assistant's work, ends every connection, cancels your subscription and, after {days} day{days === 1 ? '' : 's'} in which you can change your mind, deletes everything. You are asked first whether you want an export.</p>
          <p className="faint">What remains afterwards: {REMAINS.join(' ')}</p>
          {sure ? <div className="int-row"><span className="muted">Start closing your account?</span>
            <button className="btn danger" disabled={!!busy} onClick={() => void run('start', () => api('POST', '/v1/account/offboarding', {}).then(() => setSure(false)))}>{busy === 'start' ? 'Starting…' : 'Yes, start closing it'}</button>
            <button className="btn tertiary" disabled={!!busy} onClick={() => setSure(false)}>No, keep my account</button></div>
            : <div className="int-row"><button className="btn tertiary" disabled={!!busy} onClick={() => setSure(true)}>Close my account…</button></div>}
        </> : closing!.waiting_for === 'export_choice' ? <>
          <p role="status"><strong>Your account is being closed.</strong> Your assistant's work has been stopped. Do you want an archive of your data first?</p>
          <div className="int-row"><button className="btn" disabled={!!busy} onClick={() => void run('choice', () => api('POST', '/v1/account/offboarding/export', {}))}>Yes, export my data first</button>
            <button className="btn tertiary" disabled={!!busy} onClick={() => void run('choice', () => api('POST', '/v1/account/offboarding/skip', {}))}>No export</button>
            <button className="btn tertiary" disabled={!!busy} onClick={() => void run('cancel', () => api('POST', '/v1/account/offboarding/cancel', {}), 'Closing was cancelled. Nothing was deleted.')}>Keep my account</button></div>
        </> : <>
          <p role="status"><strong>Your account is being closed.</strong> {deleting ? 'Your data is being deleted now. This can no longer be stopped.'
            : closing!.not_before_epoch ? `Everything is deleted on ${new Date(closing!.not_before_epoch * 1000).toLocaleDateString()}. Until then you can change your mind.` : 'Connections are being ended and your subscription cancelled.'}</p>
          {!deleting && <div className="int-row"><button className="btn" disabled={!!busy} onClick={() => void run('cancel', () => api('POST', '/v1/account/offboarding/cancel', {}), 'Closing was cancelled. Nothing was deleted. Connections that were ended stay ended: connect them again if you need them.')}>
            {busy === 'cancel' ? 'Cancelling…' : 'Keep my account after all'}</button></div>}
        </>}
      </section>)}
    {note && <p className="muted" role="status">{note}</p>}
    {err && <p className="err" role="alert">{err}</p>}
  </>;
}
