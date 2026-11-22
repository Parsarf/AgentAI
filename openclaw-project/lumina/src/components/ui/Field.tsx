import { useId, type ReactNode } from 'react';

/** What a field's control needs so that its label, hint and error belong to it: spread these on the input, select or textarea. */
export interface FieldProps { id: string; 'aria-invalid'?: true; 'aria-describedby'?: string }

/** One labelled field of a form, the same everywhere: the label above the control, a quiet note at the label's right ("Required"), a hint under the control, and the
 *  error right under the field it is about (announced, and tied to the control). The control itself is the shared `.input`. */
export default function Field({ label, note, hint, error, className = '', children }: {
  label: string; note?: string; hint?: ReactNode; error?: string; className?: string; children(props: FieldProps): ReactNode;
}) {
  const id = useId();
  const described = [error ? `${id}-error` : '', hint ? `${id}-hint` : ''].filter(Boolean).join(' ');
  return (
    <div className={`field ${className}`}>
      <div className="field-label"><label htmlFor={id}>{label}</label>{note && <span className="field-note">{note}</span>}</div>
      {children({ id, ...(error ? { 'aria-invalid': true as const } : {}), ...(described ? { 'aria-describedby': described } : {}) })}
      {error && <p className="field-error" id={`${id}-error`} role="alert">{error}</p>}
      {hint && <p className="field-hint" id={`${id}-hint`}>{hint}</p>}
    </div>);
}
