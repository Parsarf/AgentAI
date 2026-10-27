import { useId } from 'react';
/** A labelled on/off setting: the shared switch with its text, announced as a switch. */
export default function Toggle({ label, hint, checked, onChange, disabled = false }: { label: string; hint?: string; checked: boolean; onChange(v: boolean): void; disabled?: boolean }) {
  const id = useId();
  return (
    <div className="toggle-row">
      <span className="toggle-text"><span id={id}>{label}</span>{hint && <small>{hint}</small>}</span>
      <button type="button" role="switch" aria-checked={checked} aria-labelledby={id} className={`switch${checked ? ' on' : ''}`} disabled={disabled} onClick={() => onChange(!checked)}><i /></button>
    </div>);
}
