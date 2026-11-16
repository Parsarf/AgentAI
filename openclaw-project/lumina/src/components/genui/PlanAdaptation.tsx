import { useState } from 'react';
import { api, ApiError } from '../../lib/api';
import type { Block, PlanDiff, Proposal } from '../../lib/genui/schema';
import { Emojified } from '../Emoji';

const FIELD_WORDS: Record<string, string> = { title: 'name', description: 'instructions', checkpoint: 'checkpoint', enabled: 'on or off', optional: 'optional', requiresApproval: 'approval', dependsOn: 'what it runs after' };
/** `titles`: the current plan's phase titles by id, so a removed phase is named as the customer knows it (its id is only the fallback). */
export const changeLines = (d: PlanDiff, titles: Record<string, string> = {}): string[] => [
  ...d.added.map(p => `Adds “${p.title}”`),
  ...d.removed.map(id => `Removes the phase “${titles[id] ?? id}”`),
  ...d.changed.map(c => `Changes “${c.title}” (${c.fields.map(f => FIELD_WORDS[f] ?? f).join(', ')})`),
  ...(d.reordered ? ['Changes the order of the phases'] : []),
  ...(d.title_changed ? ['Renames the plan'] : []),
];
const TRIGGER_WORDS: Record<Proposal['trigger'], string> = { failure: 'A phase failed', invalidated: 'An earlier result changes what comes next', instruction: 'You asked for a change' };

/** Adapting a running plan: the assistant's suggested revision as a list of changes (what it adds, removes and changes; finished phases are never touched), the customer's decision, an
 *  automatic-revision choice with its limit, and a place to ask for a change. Nothing here changes the plan: only Approve does, and only exactly what is listed. */
export default function PlanAdaptation({ block, onChanged, failed }: { block: Block; onChanged(): void; failed: boolean }) {
  const [text, setText] = useState(''); const [busy, setBusy] = useState(''); const [err, setErr] = useState('');
  const proposals = block.proposals ?? []; const latest = proposals[0]; const waiting = proposals.find(p => p.state === 'requested'); const ready = proposals.find(p => p.state === 'proposed');
  const replan = block.replan ?? { auto: false, auto_used: 0, auto_limit: 2 };
  const titles: Record<string, string> = Object.fromEntries(((block.state?.plan?.phases ?? []) as { id: string; title: string }[]).map(p => [p.id, p.title]));
  const done = block.run_status === 'completed' || block.run_status === 'stopped';
  const call = async (key: string, path: string, body: unknown) => {
    setBusy(key); setErr('');
    try { await api('POST', `/v1/blocks/${block.id}/${path}`, body); onChanged(); }
    catch (e) { setErr(e instanceof ApiError && e.status === 409 ? 'That is no longer possible: the plan changed, or a revision is already being prepared.' : e instanceof ApiError && e.status === 402 ? 'Your plan allowance cannot fund that right now.' : 'Something went wrong. Try again.'); }
    finally { setBusy(''); }
  };
  return (
    <div className="adapt" role="group" aria-label="Change the plan">
      {waiting && <p className="muted small" role="status">The assistant is working on a revision…</p>}
      {ready && (
        <div className="adapt-card" role="group" aria-label="Suggested revision">
          <p><b>Suggested change to the plan</b><span className="faint small"> · {TRIGGER_WORDS[ready.trigger]}{ready.auto ? ' · it will be applied by itself' : ''}</span></p>
          {ready.instruction && <p className="muted small">You wrote: <Emojified text={ready.instruction} /></p>}
          {ready.diff && <ul className="adapt-list">{changeLines(ready.diff, titles).map(l => <li key={l}><Emojified text={l} /></li>)}</ul>}
          <p className="faint small">Phases that are running or finished stay exactly as they are.</p>
          {!ready.auto && <div className="actions"><button className="btn small primary" disabled={!!busy} onClick={() => void call('approve', 'proposal', { proposal_id: ready.id, action: 'approve' })}>{busy === 'approve' ? 'Applying…' : 'Apply this change'}</button>
            <button className="btn small" disabled={!!busy} onClick={() => void call('decline', 'proposal', { proposal_id: ready.id, action: 'decline' })}>No thanks</button></div>}
        </div>)}
      {latest && latest.state === 'failed' && !waiting && <p className="muted small" role="status">{latest.summary || 'The assistant could not make a usable revision. The plan is unchanged.'}</p>}
      {latest && latest.state === 'superseded' && !waiting && !ready && latest.summary && <p className="muted small" role="status">{latest.summary}</p>}
      {!done && (
        <form className="inline" onSubmit={e => { e.preventDefault(); if (text.trim()) { void call('ask', 'replan', { trigger: 'instruction', instruction: text.trim() }); setText(''); } }}>
          <input aria-label="Ask for a change to the plan" placeholder="Ask for a change to the plan…" value={text} maxLength={2000} disabled={!!waiting || !!busy} onChange={e => setText(e.target.value)} />
          <button type="submit" className="btn small" disabled={!text.trim() || !!waiting || !!busy}>Suggest a change</button>
          {failed && <button type="button" className="btn small primary" disabled={!!waiting || !!busy} onClick={() => void call('failure', 'replan', { trigger: 'failure' })}>Suggest a new plan for what failed</button>}
        </form>)}
      {!done && (
        <label className="check adapt-auto"><input type="checkbox" checked={replan.auto} disabled={!!busy} onChange={e => void call('auto', 'auto-replan', { enabled: e.target.checked })} />
          Let the assistant revise the plan by itself when a phase fails (at most {replan.auto_limit} times){replan.auto_used > 0 ? ` · used ${replan.auto_used}` : ''}</label>)}
      {err && <p className="err small" role="alert">{err}</p>}
    </div>);
}
