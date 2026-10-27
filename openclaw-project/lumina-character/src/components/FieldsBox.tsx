import { useMemo, useState } from 'react';
import { fieldLabel, inputKind, type QField, type Question } from '../lib/live';

type Body = { fields: Record<string, string>; remember_fields: string[] } | { resume: true };

/** A form needs the customer's own details. One field at a time: Next, Save & next (remember it for later forms), Back, Cancel the task, or "I'll enter them
 *  myself": the page opens, they fill it in, and Continue resumes. A review step shows everything before it is typed in. Passwords and card numbers are never asked here. */
export default function FieldsBox({ question, menuOpen, busy, onMenu, onAnswer, onCancel }: {
  question: Question; menuOpen: boolean; busy: boolean; onMenu: () => void; onAnswer: (body: Body) => void; onCancel: () => void;
}) {
  const fields = useMemo(() => (question.fields ?? []).filter(f => !f.sensitive), [question]);
  const manual = useMemo(() => (question.fields ?? []).filter(f => f.sensitive), [question]);
  const [i, setI] = useState(0);
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.map(f => [f.id, f.prefill])));
  const [keep, setKeep] = useState<Set<string>>(new Set());
  const review = i >= fields.length; const f: QField | undefined = fields[i];
  const value = (f ? values[f.id] : '')?.trim() ?? '';
  const entered = fields.filter(x => (values[x.id] ?? '').trim());
  const go = (to: number) => setI(Math.max(0, Math.min(fields.length, to)));
  const next = (save: boolean) => { if (!f) return; if (save) setKeep(k => new Set(k).add(f.id)); else setKeep(k => { const n = new Set(k); n.delete(f.id); return n; }); go(i + 1); };
  const submit = () => onAnswer({ fields: Object.fromEntries(entered.map(x => [x.id, values[x.id].trim()])), remember_fields: entered.filter(x => keep.has(x.id)).map(x => x.id) });

  if (menuOpen) return (
    <div className="ask-box fields-box" role="region" aria-label="Fill in the details yourself">
      <h3>Fill it in on the page</h3>
      <p className="muted">Click the fields in the browser below and type your details, then press Continue. Lumina picks up from there.</p>
      <div className="ask-actions"><button className="btn primary" disabled={busy} onClick={() => onAnswer({ resume: true })}>Continue</button><button className="btn" onClick={onCancel}>Cancel task</button></div>
    </div>);

  return (
    <div className="ask-box fields-box" role="region" aria-label="Lumina needs some details">
      <div className="fields-top">
        <h3>{question.title || 'A few details are needed'}</h3>
        <span className="faint fields-step" aria-live="polite">{review ? 'Review' : `${i + 1} of ${fields.length}`}</span>
      </div>
      <div className="fields-bar" role="progressbar" aria-valuemin={0} aria-valuemax={fields.length} aria-valuenow={Math.min(i, fields.length)} aria-label="Progress">
        <span style={{ width: `${((Math.min(i, fields.length) + 1) / (fields.length + 1)) * 100}%` }} />
      </div>

      {!review && f && (
        <form className="fields-step-body" autoComplete="off" onSubmit={e => { e.preventDefault(); if (value) next(false); }}>
          <label className="fields-label" htmlFor={`fld-${f.id}`}>{fieldLabel(f.label)}</label>
          <input id={`fld-${f.id}`} key={f.id} autoFocus className="fields-input" type={inputKind(f.input_type)} autoComplete="off" spellCheck={false} maxLength={200} value={values[f.id] ?? ''}
            onChange={e => setValues(v => ({ ...v, [f.id]: e.target.value }))} placeholder={fieldLabel(f.label)} />
          {f.prefill && values[f.id] === f.prefill && <p className="faint small">From your saved info. Change it if it is not right.</p>}
          <div className="fields-actions">
            <button type="button" className="btn" disabled={i === 0} onClick={() => go(i - 1)}>Back</button>
            <button type="button" className="btn danger" onClick={onCancel}>Cancel</button>
            <span className="spacer" />
            <button type="button" className="btn" disabled={!value} onClick={() => next(true)} title="Remember this for the next form">Save &amp; next</button>
            <button type="submit" className="btn primary" disabled={!value}>Next</button>
          </div>
          <p className="fields-alt"><button type="button" className="linklike" onClick={() => go(i + 1)}>Skip this one</button> · <button type="button" className="linklike" onClick={onMenu}>I&rsquo;ll enter these myself on the page</button></p>
        </form>)}

      {review && (
        <div className="fields-step-body">
          {entered.length === 0 && <p className="muted">Nothing entered yet. Go back to add your details, or fill the form in on the page yourself.</p>}
          <ul className="fields-review">
            {entered.map(x => (
              <li key={x.id}><span className="fields-k">{fieldLabel(x.label)}</span><span className="fields-v">{values[x.id]}</span>{keep.has(x.id) && <em className="faint small">will be saved</em>}
                <button type="button" className="linklike" onClick={() => go(fields.indexOf(x))}>Edit</button></li>))}
          </ul>
          {manual.length > 0 && <p className="faint small">You will type these yourself on the page: {manual.map(m => fieldLabel(m.label)).join(', ')}.</p>}
          <p className="faint small">Lumina types these into the form. They are not shown to its models, but the page itself will show them.</p>
          <div className="fields-actions">
            <button type="button" className="btn" onClick={() => go(fields.length - 1)}>Back</button>
            <button type="button" className="btn danger" onClick={onCancel}>Cancel</button>
            <span className="spacer" />
            <button type="button" className="btn" onClick={onMenu}>Enter them myself</button>
            <button type="button" className="btn primary" disabled={busy || entered.length === 0} onClick={submit}>Fill it in</button>
          </div>
        </div>)}
    </div>);
}
