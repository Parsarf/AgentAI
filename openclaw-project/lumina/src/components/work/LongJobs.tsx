import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../../lib/api';
import { ago } from '../../lib/format';

export interface Checkpoint { sequence: number; step: string; receipt_id: string | null; created_epoch: number }
export interface LongJob {
  id: string; conversation_id: string | null; state: string; cancelled: boolean; pause_reason: string | null; resume_policy: 'ask' | 'auto'; turns: number; max_turns: number;
  elapsed_seconds: number; max_seconds: number | null; over_budget: string | null; auto_resumes: number; checkpoints: Checkpoint[]; created_epoch: number; updated_epoch: number;
}

const STATE_WORDS: Record<string, string> = { active: 'Working', paused: 'Paused', needs_reconciliation: 'Checking what was done', completed: 'Finished', cancelled: 'Cancelled', failed: 'Stopped' };
const OPEN = new Set(['active', 'paused', 'needs_reconciliation']);
export const stateWord = (j: LongJob) => (j.cancelled ? 'Cancelled' : STATE_WORDS[j.state] ?? 'In progress');
export const stepWord = (step: string) => step.trim().slice(0, 120);       // the server writes each checkpoint as a plain sentence ("Turn 3: completed")
export const spent = (seconds: number) => (seconds < 90 ? `${Math.round(seconds)} s` : seconds < 5400 ? `${Math.round(seconds / 60)} min` : `${(seconds / 3600).toFixed(1).replace(/\.0$/, '')} h`);

/** Jobs that keep working until they are complete: what they have done so far (a checkpoint per finished turn), how much of their budget is used, why one is paused, and the
 *  controls the customer has: raise the budget, choose what happens after an interruption, stop it for good. Nothing here resumes a job: resuming stays in its chat. */
export default function LongJobs() {
  const [jobs, setJobs] = useState<LongJob[] | null>(null); const [problem, setProblem] = useState(''); const [busy, setBusy] = useState('');
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(() => api<{ objectives: LongJob[] }>('GET', '/v1/objectives').then(r => { if (alive.current) setJobs(r.objectives); }).catch(() => { /* not on this server: the section stays hidden */ }), []);
  useEffect(() => { void load(); const t = setInterval(() => void load(), 15000); return () => clearInterval(t); }, [load]);

  async function change(job: LongJob, body: Record<string, string>) {
    setBusy(job.id); setProblem('');
    try { const view = await api<LongJob>('POST', `/v1/objectives/${job.id}`, body); if (alive.current) setJobs(js => (js ?? []).map(j => (j.id === job.id ? view : j))); }
    catch (error) { if (alive.current) setProblem(error instanceof ApiError && error.status === 409 ? 'That job was cancelled, so it cannot be changed.' : 'Could not save that change. Try again.'); }
    finally { if (alive.current) setBusy(''); }
  }
  async function stop(job: LongJob) {
    setBusy(job.id); setProblem('');
    try { const view = await api<LongJob>('POST', `/v1/objectives/${job.id}/cancel`, {}); if (alive.current) setJobs(js => (js ?? []).map(j => (j.id === job.id ? view : j))); }
    catch { if (alive.current) setProblem('Could not stop that job. Try again.'); }
    finally { if (alive.current) setBusy(''); }
  }

  const open = (jobs ?? []).filter(j => !j.cancelled && OPEN.has(j.state));
  if (!jobs || jobs.length === 0) return null;
  const rest = jobs.filter(j => !open.includes(j)).slice(0, 5);
  const Card = ({ job }: { job: LongJob }) => {
    const last = job.checkpoints.slice(-5).reverse(); const live = !job.cancelled && OPEN.has(job.state);
    return (
      <li className="lj-card" data-state={job.cancelled ? 'cancelled' : job.state}>
        <header className="lj-head">
          <strong className="lj-state">{stateWord(job)}</strong>
          <span className="lj-meta">{job.turns} of {job.max_turns} turns · {spent(job.elapsed_seconds)}{job.max_seconds ? ` of ${spent(job.max_seconds)}` : ''}</span>
          {job.conversation_id && <Link className="btn small" to={`/chat/${job.conversation_id}`}>Open the chat</Link>}
        </header>
        {job.pause_reason && <p className="lj-reason" role="status">{job.pause_reason}</p>}
        {last.length > 0 && <ol className="lj-steps" aria-label="What it has done">{last.map(c => <li key={c.sequence}><span>{stepWord(c.step)}</span><time>{ago(c.created_epoch)}</time></li>)}</ol>}
        {live && (
          <div className="lj-controls">
            <label className="lj-policy">After an interruption{' '}
              <select className="input small auto" value={job.resume_policy} disabled={busy === job.id} onChange={e => void change(job, { resume_policy: e.target.value })} aria-label="After an interruption">
                <option value="ask">Ask me before carrying on</option>
                <option value="auto">Carry on by itself (up to 3 times)</option>
              </select>
            </label>
            <button className="btn small" disabled={busy === job.id} onClick={() => void change(job, { max_turns: String(Math.min(500, job.max_turns + 10)) })}>Allow 10 more turns</button>
            <button className="btn small" disabled={busy === job.id} onClick={() => void change(job, { max_hours: String(Math.min(720, Math.ceil((job.elapsed_seconds + 3600) / 3600))) })}>Allow 1 more hour</button>
            <button className="btn danger small" disabled={busy === job.id} onClick={() => void stop(job)}>Stop for good</button>
          </div>)}
      </li>);
  };
  return (
    <section className="wk-section" aria-labelledby="act-jobs">
      <h2 id="act-jobs">Long jobs{open.length > 0 && <span className="wk-count">{open.length}</span>}</h2>
      <p className="wk-fine">Jobs that keep working until they are complete. Each finished turn is saved, so an interruption never loses what was done.</p>
      {problem && <p className="err" role="alert">{problem}</p>}
      <ul className="lj-list">{open.map(j => <Card key={j.id} job={j} />)}{rest.map(j => <Card key={j.id} job={j} />)}</ul>
    </section>);
}
