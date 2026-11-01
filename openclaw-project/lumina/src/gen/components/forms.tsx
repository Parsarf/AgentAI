import { useId, useRef, useState } from 'react';
import { validateFields } from '../formValidation';
import { formMessage } from '../actions';
import type { B, P } from './types';
import { cx } from './types';
import { useGen, useLocal } from './context';

type Field = B<'form'>['props']['fields'][number];
type Val = string | number | boolean | Array<string | number>;
const initialOf = (f: Field): Val => f.default ?? (['multiselect', 'range', 'date-range', 'tags'].includes(f.type) ? [] : f.type === 'toggle' || f.type === 'checkbox' ? false : f.type === 'slider' || f.type === 'number' ? (f.min ?? 0) : f.type === 'radio' || f.type === 'segmented' || f.type === 'select' ? '' : '');

/** Which fields are visible given the answers so far (showIf). Hidden fields are never sent. */
export function visibleFields(fields: Field[], values: Record<string, Val>): Field[] {
  return fields.filter(f => !f.showIf || values[f.showIf.field] === f.showIf.equals);
}
export function describe(f: Field, v: Val | undefined): string {
  if (v === undefined || v === '') return '';
  if (Array.isArray(v)) return v.map(x => f.options?.find(o => o.value === x)?.label ?? String(x)).join(', ');
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  const o = f.options?.find(x => x.value === v);
  return `${o ? o.label : v}${f.unit && typeof v === 'number' ? ' ' + f.unit : ''}`;
}

export function FormBlock({ block }: P<'form'>) {
  const g = useGen(); const p = block.props; const uid = useId();
  const defaults = Object.fromEntries(p.fields.map(f => [f.id, initialOf(f)])) as Record<string, Val>;
  const [l, set] = useLocal(block.id, { values: defaults as Record<string, Val>, answered: false });
  const values = { ...defaults, ...(l.values as Record<string, Val>) };
  const [status, setStatus] = useState<{ kind: 'idle' | 'busy' | 'done' | 'error'; msg: string }>({ kind: 'idle', msg: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const form = useRef<HTMLFormElement>(null);
  const shown = visibleFields(p.fields, values);
  const setV = (id: string, v: Val) => { set({ values: { ...values, [id]: v } }); setErrors(e => { const next = { ...e }; delete next[id]; return next; }); };
  const grouped = block.variant === 'grouped'; const groups = grouped ? [...new Set(shown.map(f => f.group ?? ''))] : [''];
  /** `vals` is what is sent. A device location is passed in here and never put in the saved form state. */
  const send = async (vals: Record<string, Val>) => {
    const invalid = validateFields(shown, vals); setErrors(invalid);
    if (Object.keys(invalid).length) {
      setStatus({ kind: 'error', msg: 'Check the fields marked below.' });
      setTimeout(() => form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0);
      return;
    }
    const a = p.submit.action;
    const action = a.kind === 'agent.request' ? { ...a, message: formMessage(a.message, shown.map(f => ({ label: f.label, value: describe(f, vals[f.id]) }))) } : a;
    setStatus({ kind: 'busy', msg: 'Sending…' }); const r = await (a.kind === 'agent.request' && g.submit ? g.submit('submit', Object.fromEntries(shown.map(f => [f.id, vals[f.id]]))) : g.act(action, { nonce: block.id }));
    if (!r.ok && r.fieldErrors) { setErrors(r.fieldErrors); setTimeout(() => form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0); }
    setStatus(r.ok ? { kind: 'done', msg: 'Sent.' } : { kind: r.reason === 'declined' ? 'idle' : 'error', msg: r.reason === 'declined' ? '' : r.message });
    if (r.ok) set({ values: vals, answered: true });       // the answer is final: this form stays locked with what was sent, also after a reload
  };
  const submit = (e: React.FormEvent) => { e.preventDefault(); return send(values); };
  const locked = !!l.answered || status.kind === 'done';
  const off = block.disabled || g.readOnly || locked || status.kind === 'busy';
  return <form ref={form} aria-busy={status.kind === 'busy'} className={cx('gen-form', block.variant)} onSubmit={submit} noValidate aria-label={p.title ?? 'Form'}>
    {p.title && <h4>{p.title}</h4>}{p.description && <p className="faint">{p.description}</p>}
    {groups.map(gr => <fieldset key={gr} className="gen-group" disabled={off}>{gr && <legend>{gr}</legend>}
      {shown.filter(f => !grouped || (f.group ?? '') === gr).map(f => <FieldView key={f.id} f={f} id={`${uid}-${f.id}`} value={values[f.id]} onChange={v => setV(f.id, v)} onShare={v => send({ ...values, [f.id]: v })} error={errors[f.id]} />)}</fieldset>)}
    <div className="gen-row"><button className="btn primary" type="submit" disabled={off || status.kind === 'busy'}>{locked ? '✓ ' : ''}{p.submit.label}</button>
      <span role="status" className={cx('gen-act-msg', status.kind === 'error' && 'err')}>{status.msg || (locked ? 'Answered. This can’t be changed.' : '')}</span></div></form>;
}

function FieldView({ f, id, value, onChange, onShare, error }: { f: Field; id: string; value: Val | undefined; onChange(v: Val): void; onShare?(v: string): void; error?: string }) {
  const hint = [f.help ? `${id}-h` : '', error ? `${id}-e` : ''].filter(Boolean).join(' ') || undefined; const common = { id, 'aria-describedby': hint, 'aria-invalid': !!error || undefined, 'aria-required': f.required || undefined };
  const errorText = error && <p id={`${id}-e`} className="gen-err" role="alert">{error}</p>;
  const label = <span className="gen-label">{f.label}{f.required && <span aria-hidden> *</span>}</span>;
  let control: React.ReactNode;
  switch (f.type) {
    case 'multiselect': control = <select className="gen-input" {...common} multiple value={Array.isArray(value) ? value.map(String) : []} onChange={e => onChange(Array.from(e.target.selectedOptions).map(o => o.value))}>{f.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>; break;
    case 'range': case 'date-range': {
      const values = Array.isArray(value) ? value : [];
      control = <div className="gen-row">{['Start', 'End'].map((part, i) => <label key={part}>{part}<input className="gen-input" type={f.type === 'date-range' ? 'date' : 'number'} aria-label={`${f.label} ${part.toLowerCase()}`} aria-describedby={hint} aria-invalid={!!error || undefined} min={f.min} max={f.max} step={f.step} value={String(values[i] ?? '')} onChange={e => { const next = [...values]; next[i] = f.type === 'date-range' ? e.target.value : +e.target.value; onChange(next); }} /></label>)}</div>; break;
    }
    case 'tags': control = <input className="gen-input" {...common} value={Array.isArray(value) ? value.join(', ') : ''} onChange={e => onChange(e.target.value.split(',').map(v => v.trim()).slice(0, 50))} />; break;
    case 'autocomplete': control = <><input className="gen-input" {...common} list={`${id}-options`} value={String(value ?? '')} onChange={e => onChange(e.target.value)} /><datalist id={`${id}-options`}>{f.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</datalist></>; break;
    case 'location': control = <LocationControl common={common} value={String(value ?? '')} onChange={onChange} onShare={onShare} />; break;
    case 'search': case 'color': control = <input className="gen-input" {...common} type={f.type} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />; break;
    case 'rating': control = <input className="gen-input" {...common} type="number" min={f.min ?? 1} max={f.max ?? 5} step={1} value={String(value ?? '')} onChange={e => onChange(+e.target.value)} />; break;
    case 'select': control = <select className="gen-input" {...common} value={String(value ?? '')} onChange={e => onChange(e.target.value)}><option value="">Choose…</option>{f.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>; break;
    case 'radio': case 'segmented': return <fieldset className="gen-field" aria-describedby={hint} aria-invalid={!!error || undefined} tabIndex={error ? -1 : undefined}><legend className="gen-label">{f.label}{f.required && <span aria-hidden> *</span>}</legend>
      <div className={cx('gen-choices', f.type)} role="radiogroup" aria-label={f.label} aria-required={f.required || undefined}>{f.options?.map(o => <label key={o.value} className={cx('gen-choice', value === o.value && 'on')}><input type="radio" name={id} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} /><span>{o.label}</span></label>)}</div>{errorText}{f.help && <p id={`${id}-h`} className="faint">{f.help}</p>}</fieldset>;
    case 'toggle': return <div className="gen-field row"><label className="gen-switch"><input type="checkbox" role="switch" {...common} checked={!!value} onChange={e => onChange(e.target.checked)} /><i aria-hidden />{label}</label>{errorText}{f.help && <p id={`${id}-h`} className="faint">{f.help}</p>}</div>;
    case 'checkbox': return <div className="gen-field row"><label className="gen-check"><input type="checkbox" {...common} checked={!!value} onChange={e => onChange(e.target.checked)} />{label}</label>{errorText}{f.help && <p id={`${id}-h`} className="faint">{f.help}</p>}</div>;
    case 'slider': control = <div className="gen-slider"><input type="range" {...common} min={f.min ?? 0} max={f.max ?? 100} step={f.step ?? 'any'} value={Number(value ?? 0)} onChange={e => onChange(Number(e.target.value))} /><output htmlFor={id}>{Number(value ?? 0).toLocaleString()}{f.unit ? ` ${f.unit}` : ''}</output></div>; break;
    case 'number': control = <input className="gen-input" type="number" {...common} min={f.min} max={f.max} step={f.step ?? 'any'} value={String(value ?? '')} onChange={e => onChange(e.target.value === '' ? '' : Number(e.target.value))} />; break;
    case 'textarea': control = <textarea className="gen-input" rows={3} maxLength={500} {...common} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />; break;
    case 'date': case 'time': control = <input className="gen-input" type={f.type} {...common} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />; break;
    default: control = <input className="gen-input" type="text" maxLength={500} {...common} value={String(value ?? '')} onChange={e => onChange(e.target.value)} />;
  }
  if (f.type === 'range' || f.type === 'date-range') return <fieldset className="gen-field" aria-describedby={hint}><legend>{label}</legend>{control}{errorText}{f.help && <p id={`${id}-h`} className="faint">{f.help}</p>}</fieldset>;
  return <div className="gen-field"><label htmlFor={id}>{label}</label>{control}{errorText}{f.help && <p id={`${id}-h`} className="faint">{f.help}</p>}</div>;
}

/** Where the reader is: a button that asks the browser (only when pressed, never on load), or a typed ZIP, city or address.
 *  A device position is rounded to about 1 km and sent as the answer straight away; it is not kept in the form's saved state. */
const GEO_ERRORS: Record<number, string> = {
  1: 'Your browser did not allow location access for this site. You can allow it in the address bar, or type where you are instead.',
  2: 'Your device could not work out where you are. Type it instead.',
  3: 'Finding your location took too long. Try again, or type it instead.',
};
export const deviceLocation = (lat: number, lon: number) => `Shared from my device, approximate (about 1 km): ${lat.toFixed(2)}, ${lon.toFixed(2)}`;
function LocationControl({ common, value, onChange, onShare }: { common: Record<string, unknown>; value: string; onChange(v: string): void; onShare?(v: string): void }) {
  const [state, setState] = useState<{ kind: 'idle' | 'asking' | 'error'; msg: string }>({ kind: 'idle', msg: '' });
  const supported = typeof navigator !== 'undefined' && 'geolocation' in navigator && !!onShare;
  const share = () => {
    setState({ kind: 'asking', msg: 'Waiting for your browser to ask you…' });
    navigator.geolocation.getCurrentPosition(
      pos => { setState({ kind: 'idle', msg: '' }); onShare!(deviceLocation(pos.coords.latitude, pos.coords.longitude)); },
      err => setState({ kind: 'error', msg: GEO_ERRORS[err.code] ?? GEO_ERRORS[2] }),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  };
  return <div className="gen-location">
    {supported && <><button type="button" className="btn" onClick={share} disabled={state.kind === 'asking'} aria-busy={state.kind === 'asking'}>Share my location</button>
      <p className="faint">Your browser asks first. Only an approximate point (about 1 km) is sent, once.</p>
      <p className="faint" aria-hidden>or type it</p></>}
    <input className="gen-input" type="text" maxLength={500} autoComplete="off" placeholder="ZIP code, city or address" {...common} value={value} onChange={e => onChange(e.target.value)} />
    <p role="status" className={cx('gen-act-msg', state.kind === 'error' && 'err')}>{state.msg}</p>
  </div>;
}
