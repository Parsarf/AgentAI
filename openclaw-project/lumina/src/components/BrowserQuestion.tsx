import { useState } from 'react';
import { api } from '../lib/api';
import type { BrowserQuestion as Question } from '../lib/live';

/** What Lumina's browser stopped to ask: a choice the request left open (a size, which product), whether to use a saved login or card, whether it may press one button that
 *  changes something, or details a form needs. The server holds the question and decides what an answer may be; this only shows it and sends the answer back.
 *  Before this existed the Live page showed nothing for a waiting question, so every one of them ran out after five minutes ("no answer to the question"). */
export default function BrowserQuestion({ id, question, onAnswered }: { id: string; question: Question; onAnswered: () => void }) {
  const fields = question.kind === 'fields' ? question.fields ?? [] : [];
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.filter(f => !f.sensitive).map(f => [f.id, f.prefill ?? ''])));
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const send = async (body: Record<string, unknown>) => {
    setBusy(true); setErr('');
    try { await api('POST', `/v1/browse/${id}/answer`, { question_id: question.id, ...body }); onAnswered(); }
    catch { setErr('That answer did not go through. Try again.'); }
    finally { setBusy(false); }
  };
  const filled = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v));
  const heading = question.use === 'approval' ? 'Lumina needs your permission' : question.use === 'login' || question.use === 'card' ? 'Use what you saved?' : 'Lumina has a question';
  return (
    <div className="ws-bar col" role="region" aria-label="A question from Lumina's browser">
      <h3>{heading}</h3>
      <p className="muted">{question.title || (fields.length ? 'A few details are needed for this form.' : 'Which one do you want?')}</p>
      {fields.length > 0 ? (
        <form className="live-type" autoComplete="off" onSubmit={e => { e.preventDefault(); if (Object.keys(filled).length) void send({ fields: filled }); }}>
          {fields.map(f => f.sensitive
            ? <p key={f.id} className="faint small">{f.label}: type this one into the page yourself, in the browser below.</p>
            : <label key={f.id} className="live-field"><span>{f.label}</span>
                <input className="input" type={f.input_type === 'email' || f.input_type === 'tel' || f.input_type === 'number' ? f.input_type : 'text'} maxLength={200} value={values[f.id] ?? ''}
                  onChange={e => setValues(v => ({ ...v, [f.id]: e.target.value }))} /></label>)}
          <button className="btn primary small" type="submit" disabled={busy || !Object.keys(filled).length}>Fill these in</button>
          <button className="btn small" type="button" disabled={busy} onClick={() => void send({ resume: true })}>I filled the form in myself, continue</button>
        </form>
      ) : (
        <div className="live-type">
          {question.options.map(o => <button key={o.id} className="btn small" type="button" disabled={busy} onClick={() => void send({ option: o.id })}>{o.label}</button>)}
          {question.menu && <button className="btn small ghost" type="button" disabled={busy} onClick={() => void send({ resume: true })}>I chose on the page, continue</button>}
        </div>
      )}
      <p className="faint small">Lumina waits for your answer for about five minutes. You can also click in the browser below.</p>
      {err && <p className="err small" role="alert">{err}</p>}
    </div>);
}
