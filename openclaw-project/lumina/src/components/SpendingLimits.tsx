import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError } from '../lib/api';

type Field = 'task' | 'daily' | 'period';
interface View { limits: { task_microusd: number | null; daily_microusd: number | null; period_microusd: number | null }; chosen: boolean; set_by_organization?: boolean }

const FIELDS: { id: Field; label: string; hint: string }[] = [
  { id: 'task', label: 'One task', hint: 'A task that reaches this is stopped and keeps what it finished.' },
  { id: 'daily', label: 'One day', hint: 'Counted over the last 24 hours. New tasks wait once it is reached.' },
  { id: 'period', label: 'One billing period', hint: 'New tasks wait once it is reached, until the period turns over or you raise it.' },
];
const shown = (micro: number | null) => (micro == null ? '' : (micro / 1e6).toFixed(2).replace(/\.00$/, ''));
/** A dollar amount a person typed: empty (no limit) or a positive number with at most two decimals. */
export const validAmount = (text: string) => { const t = text.trim().replace(/^\$/, ''); return t === '' || (/^\d{1,6}(\.\d{1,2})?$/.test(t) && Number(t) > 0); };

/** Settings > Usage: the spending limits you choose for yourself. Lumina sets none; an empty field means no limit. */
export default function SpendingLimits() {
  const [values, setValues] = useState<Record<Field, string> | null>(null);
  const [busy, setBusy] = useState(false); const [note, setNote] = useState(''); const [problem, setProblem] = useState(''); const [locked, setLocked] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const apply = (v: View) => { setLocked(!!v.set_by_organization); setValues({ task: shown(v.limits.task_microusd), daily: shown(v.limits.daily_microusd), period: shown(v.limits.period_microusd) }); };
  useEffect(() => { api<View>('GET', '/v1/spending-limits').then(v => { if (alive.current) apply(v); }).catch(() => { /* not on this server: the card stays hidden */ }); }, []);

  if (!values) return null;
  const bad = FIELDS.filter(f => !validAmount(values[f.id])).map(f => f.id);
  const none = FIELDS.every(f => values[f.id].trim() === '');

  async function save(e: FormEvent) {
    e.preventDefault();
    if (bad.length || !values) return;
    setBusy(true); setNote(''); setProblem('');
    try {
      const body = { task: values.task.trim(), daily: values.daily.trim(), period: values.period.trim() };
      const v = await api<View>('POST', '/v1/spending-limits', body);
      if (!alive.current) return;
      apply(v); setNote(FIELDS.every(f => body[f.id] === '') ? 'Saved. You have no spending limit.' : 'Saved. Your limits apply from now on, including to a task that is running.');
    } catch (error) {
      if (alive.current) setProblem(error instanceof ApiError && error.status === 400 ? 'Enter dollar amounts like 5 or 2.50, or leave a field empty for no limit.' : 'Could not save your limits. Try again.');
    } finally { if (alive.current) setBusy(false); }
  }

  return (
    <section className="panel card set-card" aria-labelledby="limits-h">
      <div className="set-head"><h2 id="limits-h">Spending limits</h2><span className="badge alt">{none ? 'No limit' : 'Your limits'}</span></div>
      <p className="muted">Lumina does not limit what you spend. Set your own limits here if you want them; leave a field empty for no limit.</p>
      {locked && <p className="muted" role="note">These limits are set by your organization. Ask an owner or admin to change them.</p>}
      <form onSubmit={save} style={{ display: 'grid', gap: 'var(--space-3)' }} noValidate>
        {FIELDS.map(f => (
          <label key={f.id}>{f.label} (US dollars)
            <input className="input" inputMode="decimal" autoComplete="off" placeholder="No limit" value={values[f.id]} disabled={busy || locked} maxLength={10}
              aria-invalid={bad.includes(f.id)} aria-describedby={`limit-${f.id}-hint`} onChange={e => { setNote(''); setValues({ ...values, [f.id]: e.target.value }); }} />
            <span className="faint" id={`limit-${f.id}-hint`}>{f.hint}</span>
          </label>))}
        <div className="int-row">
          <button className="btn" type="submit" disabled={busy || locked || bad.length > 0}>{busy ? 'Saving…' : 'Save limits'}</button>
          {!none && <button className="btn tertiary" type="button" disabled={busy} onClick={() => { setNote(''); setValues({ task: '', daily: '', period: '' }); }}>Clear all</button>}
        </div>
      </form>
      {bad.length > 0 && <p className="muted" role="alert">Enter dollar amounts like 5 or 2.50, or leave a field empty for no limit.</p>}
      {problem && <p className="muted" role="alert">{problem}</p>}
      {note && <p className="muted" role="status">{note}</p>}
    </section>);
}
