import { useState } from 'react';
import { questionTitle, rememberText, type Answer, type Question } from '../lib/live';

/** The box Lumina shows when the browser reaches a choice that is yours: pick one, or open the page and choose there, then Continue.
 *  Saving is always your tick, never a default. */
export default function AskBox({ question, menuOpen, busy, onMenu, onAnswer }: {
  question: Question; menuOpen: boolean; busy: boolean; onMenu: () => void;
  onAnswer: (body: Answer) => void;
}) {
  const [picked, setPicked] = useState<string | null>(null); const [remember, setRemember] = useState(false);
  const keep = rememberText(question, picked);
  const hasOptions = question.options.length > 0;
  return (
    <div className="ask-box" role="region" aria-label="Lumina has a question">
      <h3>{questionTitle(question)}</h3>
      {hasOptions && !menuOpen && (
        <div className="ask-options" role="radiogroup" aria-label={questionTitle(question)}>
          {question.options.map(o => (
            <button key={o.id} type="button" role="radio" aria-checked={picked === o.id} className={`ask-option${picked === o.id ? ' on' : ''}`} onClick={() => setPicked(o.id)}>{o.label}</button>))}
        </div>)}
      {menuOpen && <p className="muted">Choose on the page below, then press Continue. Lumina picks up from there.</p>}
      {hasOptions && !menuOpen && keep && (
        <label className="ask-remember"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />{keep}</label>)}
      <div className="ask-actions">
        {hasOptions && !menuOpen && <button className="btn primary" disabled={!picked || busy} onClick={() => picked && onAnswer({ option: picked, remember: remember && !!keep })}>Use this</button>}
        {!menuOpen && question.menu && <button className="btn" disabled={busy} onClick={onMenu}>{hasOptions ? 'View full menu' : 'Choose on the page'}</button>}
        {menuOpen && <button className="btn primary" disabled={busy} onClick={() => onAnswer({ resume: true })}>Continue</button>}
      </div>
    </div>);
}
