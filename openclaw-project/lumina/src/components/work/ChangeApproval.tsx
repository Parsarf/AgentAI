import { useState } from 'react';
import { api, ApiError } from '../../lib/api';
import type { ActionNeed, AskOption, ChangePreview, Need, QuestionNeed, WorkflowNeed } from '../../lib/work';
import { useWorkClientOptional } from '../../state/work';

const shown = (value: unknown): string => (value === null || value === undefined || value === '' ? 'nothing' : typeof value === 'string' ? value : JSON.stringify(value));
export const waitWords = (expires: number, now = Date.now() / 1000): string => {
  const left = Math.max(0, expires - now);
  return left >= 2 * 86400 ? `Waits ${Math.round(left / 86400)} more days for you` : left >= 7200 ? `Waits ${Math.round(left / 3600)} more hours for you` : left >= 120 ? `Waits ${Math.round(left / 60)} more minutes for you` : 'Waits a little longer for you';
};
const problem = (e: unknown) => (e instanceof ApiError && e.status === 409 ? 'This is no longer waiting, or it changed since it was shown. Nothing was done.'
  : e instanceof ApiError && e.status === 403 ? 'Your role does not allow this.' : 'That did not go through. Please try again.');

/** What one prepared change will do: where it goes, each thing it changes (before and after), how many records, and what cannot be taken back. Every word comes from the server's
 *  preview of the exact payload; nothing here is the assistant's description. */
export function Preview({ preview, step }: { preview: ChangePreview; step?: number }) {
  return (
    <div className="wk-change">
      <p className="wk-permission-title">{step ? <span className="wk-change-step">{step}. </span> : null}<strong>{preview.summary}</strong></p>
      <p className="wk-change-where">Goes to: {preview.destination}{preview.affected > 1 ? ` · ${preview.affected} records` : ''}</p>
      {preview.changes.length > 0 && (
        <table className="wk-change-table"><thead><tr><th scope="col">What</th><th scope="col">Now</th><th scope="col">After</th></tr></thead>
          <tbody>{preview.changes.map(c => <tr key={c.field}><th scope="row">{c.field}</th><td>{shown(c.before)}</td><td>{shown(c.after)}</td></tr>)}</tbody></table>)}
      {preview.irreversible
        ? <p className="wk-change-warn" role="note"><strong>Cannot be taken back.</strong> {preview.irreversible}{preview.compensations.length > 0 && ` If it turns out wrong, Lumina can offer: ${preview.compensations.map(c => c.label.toLowerCase()).join(', ')}.`}</p>
        : preview.can_undo && <p className="wk-change-note">Can be undone{preview.undo_seconds ? ` for ${Math.round(preview.undo_seconds / 60)} minutes afterwards` : ''}.</p>}
    </div>);
}

/** A change Lumina prepared in a service the customer connected. Approving is the customer's own signed-in click, for exactly the payload shown (its hash goes with the click): if
 *  anything about it changed, the server refuses. Lumina then sends it once, checks it, and tells the assistant by itself. */
export function ChangeApproval({ need }: { need: ActionNeed }) {
  const work = useWorkClientOptional();
  const [busy, setBusy] = useState<'' | 'approve' | 'decline'>(''); const [err, setErr] = useState(''); const [note, setNote] = useState('');
  const decide = async (approve: boolean) => {
    setBusy(approve ? 'approve' : 'decline'); setErr('');
    try {
      const r = await api<{ action: { state: string; needs_admin: boolean } }>('POST', `/v1/actions/${need.id}/${approve ? 'approve' : 'decline'}`, approve ? { payload_hash: need.payload_hash } : {});
      setNote(!approve ? 'Declined. Nothing was changed.' : r.action.state === 'approved' ? 'Approved. Lumina is making the change now.' : 'Approved by you. An admin of your organization has to approve it as well.');
    } catch (e) { setErr(problem(e)); }
    finally { setBusy(''); void work?.refresh(); }
  };
  if (note) return <p className="wk-permission-done" role="status">{note}</p>;
  return (
    <section className="wk-permission wk-change-card" role="group" aria-label={`Approve: ${need.preview.summary}`}>
      <div className="wk-permission-body">
        <p className="wk-change-kicker">Lumina prepared a change. Nothing has been sent.</p>
        <Preview preview={need.preview} />
        {need.needs_admin && <p className="wk-change-note">Your organization asks for an admin to approve this as well{need.approved_by_you ? '. You have approved it; it is waiting for them.' : '.'}</p>}
        <p className="wk-change-note">{waitWords(need.expires_epoch)}. If you do not decide, nothing is done.</p>
        {err && <p className="err" role="alert">{err}</p>}
      </div>
      {!need.approved_by_you && (
        <div className="wk-permission-actions">
          <button className="btn tertiary small" disabled={!!busy} onClick={() => void decide(false)}>{busy === 'decline' ? 'Declining…' : 'Decline'}</button>
          <button className="btn primary small" disabled={!!busy} onClick={() => void decide(true)}>{busy === 'approve' ? 'Approving…' : 'Approve this change'}</button>
        </div>)}
    </section>);
}

/** Several changes approved together. Every step is shown; one approval covers exactly these steps in this order, and any change to any of them makes it void. */
export function WorkflowApproval({ need }: { need: WorkflowNeed }) {
  const work = useWorkClientOptional();
  const [busy, setBusy] = useState<'' | 'approve' | 'decline'>(''); const [err, setErr] = useState(''); const [note, setNote] = useState('');
  const decide = async (approve: boolean) => {
    setBusy(approve ? 'approve' : 'decline'); setErr('');
    try {
      await api('POST', `/v1/workflows/${need.id}/${approve ? 'approve' : 'decline'}`, approve ? { steps_hash: need.steps_hash } : {});
      setNote(approve ? 'Approved. Lumina is carrying out the steps in order. If one fails, the finished ones are reversed.' : 'Declined. Nothing was changed.');
    } catch (e) { setErr(problem(e)); }
    finally { setBusy(''); void work?.refresh(); }
  };
  if (note) return <p className="wk-permission-done" role="status">{note}</p>;
  const last = need.steps.filter(s => s.irreversible).length;
  return (
    <section className="wk-permission wk-change-card" role="group" aria-label={`Approve ${need.steps.length} changes: ${need.title}`}>
      <div className="wk-permission-body">
        <p className="wk-change-kicker">Lumina prepared {need.steps.length} changes to make together. Nothing has been sent.</p>
        <p className="wk-permission-title"><strong>{need.title}</strong></p>
        <ol className="wk-change-steps">{need.steps.map((s, i) => <li key={i}><Preview preview={s} step={i + 1} /></li>)}</ol>
        <p className="wk-change-note">They run in this order. If a step fails, the steps already done are reversed{last > 0 ? `; ${last === 1 ? 'the step' : 'the steps'} that cannot be taken back ${last === 1 ? 'runs' : 'run'} last` : ''}.</p>
        <p className="wk-change-note">{waitWords(need.expires_epoch)}. If you do not decide, nothing is done.</p>
        {err && <p className="err" role="alert">{err}</p>}
      </div>
      <div className="wk-permission-actions">
        <button className="btn tertiary small" disabled={!!busy} onClick={() => void decide(false)}>{busy === 'decline' ? 'Declining…' : 'Decline'}</button>
        <button className="btn primary small" disabled={!!busy} onClick={() => void decide(true)}>{busy === 'approve' ? 'Approving…' : `Approve all ${need.steps.length}`}</button>
      </div>
    </section>);
}

type Given = { choice: string } | { text: string } | { skip: true };
const said = (g: Given | undefined) => !!g && ('skip' in g || ('choice' in g && !!g.choice) || ('text' in g && !!g.text.trim()));

/** One option as a button: its label, and its price and a few words when the assistant gave them. */
function OptionButton({ option, chosen, disabled, onPick }: { option: AskOption; chosen: boolean; disabled: boolean; onPick: () => void }) {
  const rich = !!(option.price || option.details);
  return (
    <button type="button" className={rich ? 'wk-question-option' : 'chip'} aria-pressed={chosen} disabled={disabled} onClick={onPick}>
      {rich ? <><span className="wk-question-option-head"><strong>{option.label}</strong>{option.price && <span className="wk-question-price">{option.price}</span>}</span>
        {option.details && <span className="wk-question-details">{option.details}</span>}</> : option.label}
    </button>);
}

/** A question the assistant asked: one to three, each answered by an option, in the customer's own words, or skipped. One question with options is answered in one tap.
 *  While the task waits in place the answer goes straight back to the run that asked; otherwise Lumina hands it on and the task carries on from where it stopped. */
export function Question({ need }: { need: QuestionNeed }) {
  const work = useWorkClientOptional();
  const questions = need.questions ?? [{ question: need.question, options: need.options.map(label => ({ label })) }];
  const single = questions.length === 1;
  const [given, setGiven] = useState<(Given | undefined)[]>(() => questions.map(() => undefined));
  const [text, setText] = useState<string[]>(() => questions.map(() => ''));
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(''); const [note, setNote] = useState('');
  const post = async (body: { answer: string } | { answers: Given[] }) => {
    if (busy) return;
    setBusy(true); setErr('');
    try { await api('POST', `/v1/handoffs/${need.id}/answer`, body); setNote('Answered. Lumina is carrying on.'); }
    catch (e) { setErr(problem(e)); }
    finally { setBusy(false); void work?.refresh(); }
  };
  // An older row (no `questions`) is answered the way it always was: its words, as one answer.
  const sendOne = (g: Given) => void post(need.questions ? { answers: [g] } : 'choice' in g ? { answer: g.choice } : 'text' in g ? { answer: g.text.trim() } : { answers: [g] });
  const pick = (n: number, g: Given) => { if (single && !('text' in g)) { sendOne(g); return; } setGiven(all => all.map((x, i) => (i === n ? g : x))); };
  const typed = (n: number, value: string) => { setText(all => all.map((x, i) => (i === n ? value : x))); setGiven(all => all.map((x, i) => (i === n ? (value.trim() ? { text: value } : undefined) : x))); };
  const ready = given.every(said);
  if (note) return <p className="wk-permission-done" role="status">{note}</p>;
  return (
    <section className="wk-permission wk-change-card" role="group" aria-label="A question from Lumina">
      <div className="wk-permission-body">
        <p className="wk-change-kicker">{need.in_place ? 'Lumina is waiting for your answer to carry on' : 'Lumina has a question for you'}</p>
        <form className="wk-question-form" onSubmit={e => { e.preventDefault(); if (single) { if (text[0].trim()) sendOne({ text: text[0] }); } else if (ready) void post({ answers: given as Given[] }); }}>
          {questions.map((q, n) => (
            <div key={n} className="wk-question" {...(single ? {} : { role: 'group', 'aria-labelledby': `${need.id}-q${n}` })}>
              <p id={`${need.id}-q${n}`} className="wk-permission-title"><strong>{q.question}</strong></p>
              {q.options.length > 0 && <div className="wk-question-options">{q.options.map(o => {
                const g = given[n];
                return <OptionButton key={o.label} option={o} disabled={busy} chosen={!!g && 'choice' in g && g.choice === o.label} onPick={() => pick(n, { choice: o.label })} />;
              })}</div>}
              <div className="inline">
                <input className="input" aria-label={single ? 'Your answer' : `Your answer to: ${q.question}`} placeholder={q.options.length ? 'Or type your answer…' : 'Type your answer…'}
                  value={text[n]} maxLength={2000} disabled={busy} onChange={e => typed(n, e.target.value)} />
                {single && <button type="submit" className="btn primary small" disabled={busy || !text[0].trim()}>{busy ? 'Sending…' : 'Answer'}</button>}
                <button type="button" className="btn tertiary small" aria-pressed={!single && given[n] !== undefined && 'skip' in (given[n] as Given)} disabled={busy}
                  onClick={() => pick(n, { skip: true })}>{single ? 'Skip, let Lumina choose' : 'Skip'}</button>
              </div>
            </div>))}
          {!single && <div className="wk-permission-actions"><button type="submit" className="btn primary small" disabled={busy || !ready}>{busy ? 'Sending…' : 'Send answers'}</button></div>}
        </form>
        <p className="wk-change-note">{need.in_place ? 'If you answer later, Lumina carries on then.' : `${waitWords(need.expires_epoch)}.`}</p>
        {err && <p className="err" role="alert">{err}</p>}
      </div>
    </section>);
}

/** Every prompt of a task that is answered right where the task is shown: changes to approve, several to approve together, questions. */
export default function Prompts({ needs }: { needs: Need[] }) {
  return <>{needs.map(n => n.kind === 'action' ? <ChangeApproval key={n.id} need={n} /> : n.kind === 'workflow' ? <WorkflowApproval key={n.id} need={n} /> : n.kind === 'question' ? <Question key={n.id} need={n} /> : null)}</>;
}
