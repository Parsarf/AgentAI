import { useState, type ReactNode } from 'react';
import { OFF_FOR, type SafetyFeature } from '../../lib/safety';
import { helpFor } from '../../lib/safetyHelp';

// The parts of the Safety console. Everything is text: box-drawing characters for the tree, [x] / [ ] for a switch, [ON] / [OFF] for its state. Each part is a plain button or
// a line of text, styled by `con-*` classes in styles/safety.css, so the look can change without touching the behaviour (lib/useSafety.ts) or the wording (lib/safetyHelp.ts).

const TRUNK = '│  ';
/** The left edge of a setting row: the category's trunk, then a branch. */
export const branch = (last: boolean) => TRUNK + (last ? '└─ ' : '├─ ');
/** The left edge of a line under a setting: the trunk, whether the setting's own branch carries on, then a branch of its own. */
export const twig = (parentLast: boolean, last: boolean) => TRUNK + (parentLast ? '   ' : '│  ') + '   ' + (last ? '└─ ' : '├─ ');
const hang = (parentLast: boolean) => TRUNK + (parentLast ? '   ' : '│  ') + '   ';

/** One line: text on the left (its tree edge never wraps; long text hangs under itself), an optional note on the right. */
function Line({ edge, children, side }: { edge?: string; children: ReactNode; side?: ReactNode }) {
  return (
    <span className="con-line">
      <span className="con-cell">{edge && <span className="con-tree" aria-hidden>{edge}</span>}<span className="con-text">{children}</span></span>
      {side !== undefined && <span className="con-side">{side}</span>}
    </span>);
}

/** A plain gray line under a category ("Nobody else has access.", "No pending changes."). */
export function Note({ children, last = true }: { children: ReactNode; last?: boolean }) {
  return <span className="con-row con-note"><Line edge={branch(last)}>{children}</Line></span>;
}

/** A command that looks like text: `[ Apply Changes ]`. */
export function Action({ children, onClick, disabled, label, className = '' }: { children: string; onClick(): void; disabled?: boolean; label?: string; className?: string }) {
  return <button type="button" className={`con-act ${className}`.trim()} aria-label={label ?? children} disabled={disabled} onClick={onClick}>[ {children} ]</button>;
}

/** `▼ [1] Title` with a gray note on the right; click to fold or unfold what is under it. */
export function Category({ n, title, note, open, onToggle, children }: { n: number; title: string; note: string; open: boolean; onToggle(): void; children: ReactNode }) {
  return (
    <section className="con-cat">
      <button type="button" className="con-row con-cathead" aria-expanded={open} onClick={onToggle}>
        <Line side={note}><span className="con-caret" aria-hidden>{open ? '▼' : '▶'}</span> [{n}] {title}</Line>
      </button>
      {open && <div className="con-children">{children}</div>}
    </section>);
}

/** What the explanation says, in the four parts: what it does, why, while on, while off. */
function HelpBlock({ f, last }: { f: SafetyFeature; last: boolean }) {
  const h = helpFor(f);
  const lines: [string, string][] = [['What it does', h.does], ['Why it exists', h.why], ['When on', h.on], ['When off', h.off]];
  return (
    <div className="con-help" role="region" aria-label={`About ${f.title}`}>
      <span className="con-line"><span className="con-tree" aria-hidden>{hang(last)}</span></span>
      {lines.map(([label, text]) => (
        <span key={label} className="con-line con-helpline">
          <span className="con-cell"><span className="con-tree" aria-hidden>{hang(last)}</span><span className="con-text"><span className="dim">{label}:</span> {text}</span></span>
        </span>))}
      <span className="con-line"><span className="con-tree" aria-hidden>{hang(last)}</span></span>
    </div>);
}

/** One switch: `├─ [x] Title            [ON]`, its notes, and `[?] What does this do?` that opens the explanation under it. Clicking the explanation never touches the switch. */
export function Setting({ f, checked, pending, last, notes, helpOpen, canToggle, onToggle, onHelp }: {
  f: SafetyFeature; checked: boolean; pending: boolean; last: boolean; notes: string[]; helpOpen: boolean; canToggle: boolean; onToggle(on: boolean): void; onHelp(): void;
}) {
  return (
    <div className="con-setting" data-key={f.key}>
      <button type="button" role="switch" aria-checked={checked} aria-label={f.title} className="con-row" disabled={!canToggle} onClick={() => onToggle(!checked)}>
        <Line edge={branch(last)} side={<>{checked ? '[ON]' : '[OFF]'}{pending ? ' *' : ''}</>}><span aria-hidden>{checked ? '[x]' : '[ ]'}</span> {f.title}</Line>
      </button>
      {notes.map(note => <span key={note} className="con-row con-note"><Line edge={twig(last, false)}>{note}</Line></span>)}
      <button type="button" className="con-row con-ask" aria-expanded={helpOpen} aria-label={`What does ${f.title} do?`} onClick={onHelp}>
        <Line edge={twig(last, true)}><span aria-hidden>[{helpOpen ? '▼' : '?'}]</span> What does this do?</Line>
      </button>
      {helpOpen && <HelpBlock f={f} last={last} />}
    </div>);
}

const MAX_MINUTES = 7 * 24 * 60;     // the server's own ceiling for how long an "off" may last
const nameOf = (minutes: number) => OFF_FOR.find(o => o.minutes === minutes)?.label ?? `${minutes} minutes`;

/** `Disable duration   Until re-enabled ▾`: click for a text list of the choices the server accepts, or type your own number of minutes. */
export function DurationRow({ minutes, open, onOpen, onPick }: { minutes: number; open: boolean; onOpen(open: boolean): void; onPick(minutes: number): void }) {
  const [custom, setCustom] = useState(false); const [text, setText] = useState(''); const [problem, setProblem] = useState('');
  const choose = (n: number) => { onPick(n); onOpen(false); setCustom(false); setProblem(''); };
  const submit = () => {
    const n = Number(text.trim());
    if (!/^\d+$/.test(text.trim()) || n < 1 || n > MAX_MINUTES) { setProblem(`Enter a whole number of minutes from 1 to ${MAX_MINUTES}.`); return; }
    choose(n);
  };
  return (
    <div className="con-select" data-safety="duration">
      <button type="button" className="con-row" aria-haspopup="listbox" aria-expanded={open} aria-label={`Disable duration: ${nameOf(minutes)}`} onClick={() => { onOpen(!open); setCustom(false); }}>
        <Line side={<>{nameOf(minutes)} ▾</>}>Disable duration</Line>
      </button>
      {open && (
        <div className="con-list" role="listbox" aria-label="Disable duration">
          {OFF_FOR.map(o => (
            <button key={o.minutes} type="button" role="option" aria-selected={o.minutes === minutes} className="con-opt" onClick={() => choose(o.minutes)}>
              <span aria-hidden>{o.minutes === minutes ? '> ' : '  '}</span>{o.label}
            </button>))}
          <button type="button" role="option" aria-selected={custom} className="con-opt" onClick={() => { setCustom(true); setText(''); setProblem(''); }}><span aria-hidden>  </span>Custom...</button>
          {custom && (
            <div className="con-custom">
              <label>minutes: <input className="con-input" inputMode="numeric" autoFocus value={text} aria-label="Custom minutes" onChange={e => { setText(e.target.value); setProblem(''); }}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submit(); } }} /></label>
              <Action onClick={submit} label="Use this duration">Use</Action>
              {problem && <span className="con-bad" role="alert">[!] {problem}</span>}
            </div>)}
        </div>)}
    </div>);
}

/** `password: ******` typed into a masked field right in the tree. It lives in this component only: it goes to the one call that needs it and is dropped. */
export function PasswordPrompt({ what, busy, onConfirm, onCancel }: { what: string; busy: boolean; onConfirm(password: string): Promise<boolean>; onCancel(): void }) {
  const [value, setValue] = useState('');
  const go = async () => { if (!value || busy) return; if (await onConfirm(value)) setValue(''); };
  return (
    <div className="con-prompt" data-safety="password">
      <div className="dim">{what}</div>
      <label>password: <input type="password" className="con-input" autoComplete="current-password" aria-label="Your password" autoFocus value={value}
        onChange={e => setValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); void go(); } }} /></label>
      <Action onClick={() => void go()} disabled={!value || busy} label="Confirm">{busy ? 'Saving...' : 'Confirm'}</Action>
      <Action onClick={onCancel} label="Cancel">Cancel</Action>
    </div>);
}
