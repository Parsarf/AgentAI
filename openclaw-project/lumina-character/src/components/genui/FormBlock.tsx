import { useMemo, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { missingRequired, normalize, visibleFields } from '../../lib/genui/form';
import type { Answers, Block, FormField, FormSpec } from '../../lib/genui/schema';
import { useAutosave } from './useAutosave';
import { Saved } from './Saved';

function Field({ f, value, set, disabled }: { f: FormField; value: any; set(v: string | number | boolean): void; disabled: boolean }) {
  const id = 'f-' + f.id;
  switch (f.type) {
    case 'select':
      return <select id={id} disabled={disabled} value={String(value ?? '')} onChange={e => set(e.target.value)}>{value === undefined && <option value="">Choose…</option>}{f.options!.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>;
    case 'segmented': case 'radio':
      return <div className={f.type === 'segmented' ? 'seg' : 'radios'} role="radiogroup" aria-labelledby={id + '-l'}>{f.options!.map(o =>
        <button type="button" key={o.value} role="radio" aria-checked={value === o.value} disabled={disabled} className="chip" aria-pressed={value === o.value} onClick={() => set(o.value)}>{o.label}</button>)}</div>;
    case 'toggle': case 'checkbox':
      return <button type="button" id={id} role="switch" aria-checked={!!value} disabled={disabled} className={`switch${value ? ' on' : ''}`} onClick={() => set(!value)}><i /></button>;
    case 'slider':
      return <div className="slider"><input id={id} type="range" disabled={disabled} min={f.min} max={f.max} step={f.step ?? 1} value={Number(value ?? f.min)} onChange={e => set(Number(e.target.value))} /><output htmlFor={id}>{String(value ?? f.min)} {f.unit ?? ''}</output></div>;
    case 'number':
      return <input id={id} type="number" disabled={disabled} min={f.min} max={f.max} step={f.step ?? 1} value={Number(value ?? f.min)} onChange={e => set(Number(e.target.value))} />;
    case 'textarea':
      return <textarea id={id} rows={3} disabled={disabled} maxLength={2000} value={String(value ?? '')} onChange={e => set(e.target.value)} />;
    default:
      return <input id={id} type="text" disabled={disabled} maxLength={2000} value={String(value ?? '')} onChange={e => set(e.target.value)} />;
  }
}

export default function FormBlock({ block, spec, onChanged }: { block: Block; spec: FormSpec; onChanged(): void }) {
  const [answers, setAnswers] = useState<Answers>(() => normalize(spec, block.state?.answers ?? {}));
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const { status, save, saveNow } = useAutosave(block);
  const locked = block.status !== 'draft';
  const shown = useMemo(() => visibleFields(spec, answers), [spec, answers]);   // conditional questions: local, no AI call
  const set = (id: string, v: string | number | boolean) => { const next = normalize(spec, { ...answers, [id]: v }); setAnswers(next); save({ answers: next }); };
  const missing = missingRequired(spec, answers);

  const submit = async () => {
    setBusy(true); setErr('');
    try {
      const v = await saveNow();
      await api('POST', `/v1/blocks/${block.id}/submit`, { version: v }); onChanged();
    } catch (e) { setErr(e instanceof ApiError && e.code === 'budget_denied' ? 'Your plan allowance cannot fund this right now.' : 'Could not submit. Reload and try again.'); }
    finally { setBusy(false); }
  };
  return (
    <section className="gblock" aria-label={spec.title}>
      <header><h3>{spec.title}</h3>{spec.description && <p className="muted">{spec.description}</p>}</header>
      <div className="fields">
        {shown.map(f => (
          <div className="field" key={f.id}>
            <label id={'f-' + f.id + '-l'} htmlFor={'f-' + f.id}>{f.label}{f.required && <span aria-hidden> *</span>}</label>
            <Field f={f} value={answers[f.id]} set={v => set(f.id, v)} disabled={locked} />
            {f.help && <small className="faint">{f.help}</small>}
          </div>))}
      </div>
      <footer>
        {locked ? <span className="faint">Submitted — the plan is being prepared.</span> : <>
          <button className="btn primary" disabled={busy || missing.length > 0 || status === 'conflict'} onClick={submit}>{busy ? 'Working…' : spec.submit.label}</button>
          <Saved status={status} /></>}
        {missing.length > 0 && !locked && <span className="faint">Still needed: {missing.join(', ')}</span>}
        {err && <span className="err" role="alert">{err}</span>}
      </footer>
    </section>);
}
