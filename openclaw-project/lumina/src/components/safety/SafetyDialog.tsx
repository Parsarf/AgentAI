import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { notesOf, switchable } from '../../lib/safety';
import type { SafetyModel } from '../../lib/useSafety';
import { Action, branch, Category, DurationRow, Note, PasswordPrompt, Setting } from './ConsoleParts';
import '../../styles/safety.css';

const TAB: Record<string, string> = { mine: 'My account', all: 'All users' };
const NOTE: Record<string, string> = {
  mine: 'Each switch is on or off for your account only. A switch that is off for all users shows as off here unless you turn it on for your account.',
  all: "These are the defaults for every account. An account's own setting wins over them. Privacy protections can't be turned off for everyone.",
};

/** What the password is for, shown above the masked field. */
type Ask = { kind: 'apply' } | { kind: 'grant'; email: string } | { kind: 'revoke'; email: string };

/** The Safety console: a text-only terminal window, drawn from a SafetyModel. Only presentation lives here and in ConsoleParts; behaviour is lib/useSafety.ts, the words of the
 *  explanations are lib/safetyHelp.ts, the look is styles/safety.css. `data-safety` marks the parts a redesign or a test may want to find. */
export default function SafetyDialog({ model }: { model: SafetyModel }) {
  const { account, state, scope, hide } = model;
  const box = useRef<HTMLDivElement>(null);
  const [folded, setFolded] = useState<Record<string, boolean>>({});                 // category -> open?  (a category not listed is open, except the review)
  const [helpOpen, setHelpOpen] = useState<Set<string>>(new Set());                  // which explanations are open
  const [selecting, setSelecting] = useState(false);                                 // the duration list
  const [ask, setAsk] = useState<Ask | null>(null);                                  // the password prompt
  const [email, setEmail] = useState('');
  const [minimized, setMinimized] = useState(false); const [maximized, setMaximized] = useState(false);

  // Escape closes the innermost open thing first: the duration list, then the password prompt, then the console.
  useEffect(() => { box.current?.focus(); }, []);                                // once, when the console opens: never again, or it would take focus from the field being typed into
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (selecting) setSelecting(false); else if (ask) setAsk(null); else hide();
    };
    document.addEventListener('keydown', onKey); return () => document.removeEventListener('keydown', onKey);
  }, [hide, selecting, ask]);

  if (!account) return null;
  const isOpen = (key: string, fallback = true) => folded[key] ?? fallback;
  const toggleCat = (key: string, fallback = true) => setFolded(f => ({ ...f, [key]: !(f[key] ?? fallback) }));
  const toggleHelp = (key: string) => setHelpOpen(s => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const isOwnerAll = scope === 'all' && account.role === 'owner';
  const groups = state ? state.groups.map(g => ({ g, rows: state.features.filter(f => f.group === g.key) })).filter(x => x.rows.length > 0) : [];
  const accessN = groups.length + 1, reviewN = groups.length + (isOwnerAll ? 2 : 1);
  const pending = state ? state.features.filter(f => model.draft[f.key] !== undefined && model.draft[f.key] !== f.on) : [];
  const confirm = async (password: string) => {
    if (!ask) return false;
    const ok = ask.kind === 'apply' ? await model.apply(password) : ask.kind === 'grant' ? await model.grant(ask.email, password) : await model.revoke(ask.email, password);
    if (ok) { setAsk(null); if (ask.kind === 'grant') setEmail(''); }
    return ok;
  };
  const whatFor = !ask ? '' : ask.kind === 'apply' ? `Confirm saving ${model.dirty} change${model.dirty === 1 ? '' : 's'}.` : ask.kind === 'grant' ? `Confirm giving ${ask.email} access to this console.` : `Confirm removing ${ask.email}.`;

  return createPortal(
    <div className="scrim safety-layer" data-safety="layer" onMouseDown={e => { if (e.target === e.currentTarget) hide(); }}>
      <div className={`con-window${maximized ? ' con-max' : ''}${minimized ? ' con-min' : ''}`} role="dialog" aria-modal="true" aria-label="Safety" tabIndex={-1} ref={box}>
        <div className="con-titlebar">
          <span className="con-title">root@lumina: ~</span>
          <span className="con-controls">
            <button type="button" aria-label="Minimize" onClick={() => setMinimized(m => !m)}>–</button>
            <button type="button" aria-label="Maximize" onClick={() => setMaximized(m => !m)}>□</button>
            <button type="button" aria-label="Close" onClick={hide}>×</button>
          </span>
        </div>
        {!minimized && (
          <div className="con-body">
            <header className="con-head">
              <span className="con-logo" aria-hidden>L U M I N A</span><span className="con-vrule" aria-hidden />
              <div><h2 className="con-h">SECURITY CONSOLE</h2><div className="dim">Configure protection layers for your account.</div></div>
            </header>
            <hr className="con-rule" />
            {model.scopes.length > 1 && (
              <div className="con-tabs" role="tablist" aria-label="Whose switches" data-safety="scopes">
                <span className="dim">view:</span>
                {model.scopes.map(s => <button key={s} type="button" role="tab" aria-selected={scope === s} aria-label={TAB[s]} className="con-tab" onClick={() => model.setScope(s)}>{scope === s ? `[ ${TAB[s]} ]` : TAB[s]}</button>)}
              </div>)}
            <p className="dim con-intro">{NOTE[scope]} Changes need your password.</p>
            {!state ? <p className="dim" role="status">Loading…</p> : (<>
              <div className="con-bulk"><Action onClick={() => model.setAll(true)}>Turn everything on</Action><Action onClick={() => model.setAll(false)}>Turn everything off</Action></div>
              <div className="con-tree-root" data-safety="list">
                {groups.map(({ g, rows }, i) => {
                  const off = rows.filter(f => !(model.draft[f.key] ?? f.on)).length;
                  return (
                    <Category key={g.key} n={i + 1} title={g.title} note={`${rows.length} switch${rows.length === 1 ? '' : 'es'} · ${off} off`} open={isOpen(g.key)} onToggle={() => toggleCat(g.key)}>
                      <div data-group={g.key}>
                        {rows.map((f, j) => (
                          <Setting key={f.key} f={f} last={j === rows.length - 1} checked={model.draft[f.key] ?? f.on} pending={model.draft[f.key] !== undefined && model.draft[f.key] !== f.on}
                            notes={notesOf(f, scope)} canToggle={switchable(f)} helpOpen={helpOpen.has(f.key)} onToggle={on => model.toggle(f.key, on)} onHelp={() => toggleHelp(f.key)} />))}
                      </div>
                    </Category>);
                })}
                {isOwnerAll && (
                  <Category n={accessN} title="Access" note="who can open this console" open={isOpen('access')} onToggle={() => toggleCat('access')}>
                    <div data-safety="access">
                      {model.access === null ? <Note last={false}>Loading…</Note> : model.access.length === 0 ? <Note last={false}>Nobody else has access.</Note> : model.access.map(a => (
                        <div key={a.email} className="con-row con-line">
                          <span className="con-cell"><span className="con-tree" aria-hidden>{branch(false)}</span><span className="con-text">{a.email}</span></span>
                          <span className="con-side"><Action label={`Remove ${a.email}`} onClick={() => setAsk({ kind: 'revoke', email: a.email })}>remove</Action></span>
                        </div>))}
                      <div className="con-row con-line">
                        <span className="con-cell"><span className="con-tree" aria-hidden>{branch(true)}</span><label className="con-text">add account: <input type="email" className="con-input" aria-label="Email to give access" value={email} onChange={e => setEmail(e.target.value)} /></label></span>
                        <span className="con-side"><Action label="Give access" disabled={!email.trim() || model.busy} onClick={() => setAsk({ kind: 'grant', email: email.trim() })}>give access</Action></span>
                      </div>
                    </div>
                  </Category>)}
                <Category n={reviewN} title="Review Configuration" note="show pending changes" open={isOpen('review', false)} onToggle={() => toggleCat('review', false)}>
                  <div data-safety="review">
                    {pending.length === 0 ? <Note>No pending changes.</Note> : pending.map((f, i) => (
                      <span key={f.key} className="con-row con-line"><span className="con-cell"><span className="con-tree" aria-hidden>{branch(i === pending.length - 1)}</span>
                        <span className="con-text">{f.title}: {f.on ? '[ON]' : '[OFF]'} → {f.on ? '[OFF]' : '[ON]'}</span></span></span>))}
                  </div>
                </Category>
              </div>
              <hr className="con-rule" />
              {model.turningOff && <DurationRow minutes={model.minutes} open={selecting} onOpen={setSelecting} onPick={model.setMinutes} />}
              <div className="con-bar">
                <span>Pending changes: {model.dirty}</span>
                <span className="con-bar-actions">
                  <Action disabled={!model.dirty || model.busy} onClick={() => setAsk({ kind: 'apply' })}>Apply Changes</Action>
                  <Action disabled={!model.dirty || model.busy} onClick={() => { model.discard(); setAsk(a => a?.kind === 'apply' ? null : a); }}>Discard Changes</Action>
                </span>
              </div>
              {ask && <PasswordPrompt what={whatFor} busy={model.busy} onConfirm={confirm} onCancel={() => setAsk(null)} />}
              {model.error && <p className="con-msg" role="alert">[!] {model.error}</p>}
              {model.done && <p className="con-msg" role="status">[+] {model.done}</p>}
            </>)}
          </div>)}
      </div>
    </div>, document.body);
}
