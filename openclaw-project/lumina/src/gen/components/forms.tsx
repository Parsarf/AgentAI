import { useId, useState } from 'react';
import { formMessage } from '../actions';
import type { B, P } from './types';
import { cx } from './types';
import { useGen, useLocal } from './context';

type Field = B<'form'>['props']['fields'][number];
type Val = string | number | boolean;
const initialOf = (f: Field): Val => f.default ?? (f.type === 'toggle' || f.type === 'checkbox' ? false : f.type === 'slider' || f.type === 'number' ? (f.min ?? 0) : f.type === 'radio' || f.type === 'segmented' || f.type === 'select' ? '' : '');

/** Which fields are visible given the answers so far (showIf). Hidden fields are never sent. */
export function visibleFields(fields: Field[], values: Record<string, Val>): Field[] {
  return fields.filter(f => !f.showIf || values[f.showIf.field] === f.showIf.equals);
}
export function describe(f: Field, v: Val | undefined): string {
  if (v === undefined || v === '') return '';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  const o = f.options?.find(x => x.value === v);
  return `${o ? o.label : v}${f.unit && typeof v === 'number' ? ' ' + f.unit : ''}`;
}

export function FormBlock({ block }: P<'form'>) {
  const g = useGen(); const p = block.props; const uid = useId();
  const defaults = Object.fromEntries(p.fields.map(f => [f.id, initialOf(f)])) as Record<string, Val>;
  const [l, set] = useLocal(block.id, { values: defaults as Record<string, Val> });
  const values = { ...defaults, ...(l.values as Record<string, Val>) };
  const [status, setStatus] = useState<{ kind: 'idle' | 'busy' | 'done' | 'error'; msg: string }>({ kind: 'idle', msg: '' });
  const [missing, setMissing] = useState<string[]>([]);
  const shown = visibleFields(p.fields, values);
  const setV = (id: string, v: Val) => set({ values: { ...values, [id]: v } });
  const grouped = block.variant === 'grouped'; const groups = grouped ? [...new Set(shown.map(f => f.group ?? ''))] : [''];
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const need = shown.filter(f => f.required && (values[f.id] === '' || values[f.id] === undefined)).map(f => f.id); setMissing(need);
    if (need.length) { setStatus({ kind: 'error', msg: 'Fill in the required fields first.' }); return; }
    const a = p.submit.action;
    const action = a.kind === 'agent.request' ? { ...a, message: formMessage(a.message, shown.map(f => ({ label: f.label, value: describe(f, values[f.id]) }))) } : a;
    setStatus({ kind: 'busy', msg: '' }); const r = await g.act(action, { nonce: block.id });
    setStatus(r.ok ? { kind: 'done', msg: 'Sent.' } : { kind: r.reason === 'declined' ? 'idle' : 'error', msg: r.reason === 'declined' ? '' : r.message });
  };
  const off = block.disabled || g.readOnly || status.kind === 'done';
  return <form className={cx('gen-form', block.variant)} onSubmit={submit} noValidate aria-label={p.title ?? 'Form'}>
    {p.title && <h4>{p.title}</h4>}{p.description && <p className="faint">{p.description}</p>}
    {groups.map(gr => <fieldset key={gr} className="gen-group" disabled={off}>{gr && <legend>{gr}</legend>}
      {shown.filter(f => !grouped || (f.group ?? '') === gr).map(f => <FieldView key={f.id} f={f} id={`${uid}-${f.id}`} value={values[f.id]} onChange={v => setV(f.id, v)} invalid={missing.includes(f.id)} />)}</fieldset>)}
    <div className="gen-row"><button className="btn primary" type="submit" disabled={off || status.kind === 'busy'}>{status.kind === 'done' ? '✓ ' : ''}{p.submit.label}</button>
      <span role="status" className={cx('gen-act-msg', status.kind === 'error' && 'err')}>{status.msg}</span></div></form>;
}

function FieldView({ f, id, value, onChange, invalid }: { f: Field; id: string; value: Val | undefined; onChange(v: Val): void; invalid: boolean }) {
  const hint = f.help ? `${id}-h` : undefined; const common = { id, 'aria-describedby': hint, 'aria-invalid': invalid || undefined, 'aria-required': f.required || undefined };
  const label = <span className="gen-label">{f.label}{f.required && <span aria-hidden> *</span>}</span>;
  let control: React.ReactNode;
  switch (f.type) {
    case 'select': control = <select className="gen-input" {...common} value={String(value ?? '')} onChange={e => onChange(e.target.value)}><option value="">Choose…</option>{f.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>; break;
    case 'radio': case 'segmented': return <fieldset className="gen-field" aria-describedby={hint}><legend className="gen-label">{f.label}{f.required && <span aria-hidden> *</span>}</legend>
      <div className={cx('gen-choices', f.type)} role="radiogroup">{f.options?.map(o => <label key={o.value} className={cx('gen-choice', value === o.value && 'on')}><input type="radio" name={id} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} /><span>{o.label}</span></label>)}</div>{f.help && <p id={hint} className="faint">{f.help}</p>}</fieldset>;
    case 'toggle': return <div className="gen-field row"><label className="gen-switch"><input type="checkbox" role="switch" {...common} checked={!!value} onChange={e => onChange(e.target.checked)} /><i aria-hidden />{label}</label>{f.help && <p id={hint} className="faint">{f.help}</p>}</div>;
    case 'checkbox': return <div className="gen-field row"><label className="gen-check"><input type="checkbox" {...common} checked={!!value} onChange={e => onChange(e.target.checked)} />{label}</label>{f.help && <p id={hint} className="faint">{f.help}</p>}</div>;
    case 'slider': control = <div className="gen-slider"><input type="range" {...common} min={f.min ?? 0} max={f.max ?? 100} step={f.step ?? 1} value={Number(value ?? 0)} onChange={e => onChange(Number(e.target.value))} /><output htmlFor={id}>{Number(value ?? 0).toLocaleString()}{f.unit ? ` ${f.unit}` : ''}</output></div>; break;
    case 'number': control = <input className="gen-input" type="number" {...common} min={f.min} max={f.max} step={f.step ?? 1} value={String(value ?? '')} onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value))} />; break;
    case 'textarea': control = <textarea className="gen-input" rows={3} maxLength={500} {...common} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />; break;
    case 'date': case 'time': control = <input className="gen-input" type={f.type} {...common} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />; break;
    default: control = <input className="gen-input" type="text" maxLength={500} {...common} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />;
  }
  return <div className="gen-field"><label htmlFor={id}>{label}</label>{control}{invalid && <p className="gen-err" role="alert">Required</p>}{f.help && <p id={hint} className="faint">{f.help}</p>}</div>;
}
