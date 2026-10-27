import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../../lib/api';
import * as P from '../../lib/genui/plan';
import type { Block, Phase, PhaseRun, Plan } from '../../lib/genui/schema';
import { elapsed } from '../../lib/format';
import { phase as phaseOf } from '../../lib/tasks';
import { useData } from '../../state/data';
import * as I from '../Icons';
import { Saved } from './Saved';
import { useAutosave } from './useAutosave';

const RUN_LABEL: Record<string, string> = { pending: 'Queued', running: 'Running', awaiting_approval: 'Needs approval', completed: 'Done', failed: 'Failed', skipped: 'Skipped', cancelled: 'Stopped' };

function Card(props: {
  p: Phase; n: number; plan: Plan; locked: boolean; open: boolean; issue?: string; dragging: boolean; run?: PhaseRun; onAct?(action: 'approve' | 'skip' | 'retry'): void; now?: number;
  onToggleOpen(): void; onChange(next: Plan): void; onDragStart(): void; onDrop(): void; onDragEnd(): void;
}) {
  const { p, n, plan, locked, open, issue } = props;
  const [asking, setAsking] = useState<null | 'before' | 'after'>(null); const [newTitle, setNewTitle] = useState(''); const [removing, setRemoving] = useState(false);
  const deps = P.dependents(plan, p.id);
  const set = (patch: Partial<Phase>) => props.onChange(P.updatePhase(plan, p.id, patch));
  const state = props.run ? RUN_LABEL[props.run.state] : !p.enabled ? 'Off' : p.requiresApproval ? 'Approval gate' : p.optional ? 'Optional' : 'On';
  return (
    <div className={`phase${p.enabled ? '' : ' off'}${issue ? ' bad' : ''}${props.dragging ? ' dragging' : ''}`} draggable={!locked && !open}
         onDragStart={e => { e.dataTransfer.effectAllowed = 'move'; props.onDragStart(); }} onDragOver={e => { if (!locked) e.preventDefault(); }}
         onDrop={e => { e.preventDefault(); props.onDrop(); }} onDragEnd={props.onDragEnd}>
      <div className="phase-head">
        <span className="grip" aria-hidden title="Drag to reorder">⠿</span>
        <button className="phase-title" aria-expanded={open} onClick={props.onToggleOpen}><span className="num">{n}</span><span>{p.title}</span></button>
        <span className={`badge ${props.run ? 'run-' + props.run.state : state === 'On' ? '' : 'alt'}`}>{state}{props.run?.state === 'running' && props.run.started_epoch ? ` · ${elapsed(props.run.started_epoch, props.now)}` : ''}</span>
        {!locked && <button type="button" role="switch" aria-checked={p.enabled} aria-label={`${p.title} enabled`} className={`switch sm${p.enabled ? ' on' : ''}`} onClick={() => props.onChange(P.setEnabled(plan, p.id, !p.enabled))}><i /></button>}
      </div>
      {issue && <p className="err small" role="alert">{issue}</p>}
      {props.run?.state === 'awaiting_approval' && (
        <div className="approval" role="group" aria-label={`Approval needed: ${p.title}`}>
          <p><b>Approval needed before “{p.title}” runs.</b></p>
          {p.description && <p className="muted small">{p.description}</p>}
          <div className="actions"><button className="btn small primary" onClick={() => props.onAct?.('approve')}>Approve and run</button><button className="btn small" onClick={() => props.onAct?.('skip')}>Skip this phase</button></div>
        </div>)}
      {props.run?.state === 'failed' && (
        <div className="approval bad" role="group" aria-label={`Failed: ${p.title}`}>
          <p>{props.run.summary || 'This phase did not finish.'}</p>
          <div className="actions"><button className="btn small primary" onClick={() => props.onAct?.('retry')}>Retry</button><button className="btn small" onClick={() => props.onAct?.('skip')}>Skip and continue</button></div>
        </div>)}
      {props.run?.state === 'completed' && props.run.summary && !open && <p className="muted small phase-sum">{props.run.summary.length > 160 ? props.run.summary.slice(0, 160) + '…' : props.run.summary}</p>}
      {open && (
        <div className="phase-body">
          {props.run?.summary && props.run.state !== 'failed' && <div className="result" style={{ marginTop: 0 }}><small className="faint">Result</small><br />{props.run.summary}</div>}
          <label>Name<input value={p.title} maxLength={80} disabled={locked} onChange={e => set({ title: e.target.value || ' ' })} /></label>
          <label>Instructions<textarea rows={3} maxLength={1000} disabled={locked} value={p.description} onChange={e => set({ description: e.target.value })} /></label>
          <fieldset disabled={locked}><legend>Runs after</legend>
            {plan.phases.filter(o => o.id !== p.id).length === 0 && <span className="faint">No other phases.</span>}
            {plan.phases.filter(o => o.id !== p.id).map(o => {
              const blocked = !p.dependsOn.includes(o.id) && P.wouldCycle(plan, p.id, o.id);
              return <label key={o.id} className="check"><input type="checkbox" disabled={blocked} checked={p.dependsOn.includes(o.id)}
                onChange={e => props.onChange(P.setDependencies(plan, p.id, e.target.checked ? [...p.dependsOn, o.id] : p.dependsOn.filter(d => d !== o.id)))} />{o.title}{blocked && <span className="faint"> (would loop)</span>}</label>;
            })}</fieldset>
          <div className="flags">
            <label className="check"><input type="checkbox" disabled={locked} checked={p.optional} onChange={e => set({ optional: e.target.checked })} />Optional</label>
            <label className="check"><input type="checkbox" disabled={locked} checked={p.requiresApproval} onChange={e => set({ requiresApproval: e.target.checked })} />Ask me before running</label>
          </div>
          {!locked && (
            <div className="actions">
              <button className="btn small" onClick={() => props.onChange(P.movePhase(plan, p.id, -1))}>Move up</button>
              <button className="btn small" onClick={() => props.onChange(P.movePhase(plan, p.id, 1))}>Move down</button>
              <button className="btn small" onClick={() => setAsking('before')}>Add before</button>
              <button className="btn small" onClick={() => setAsking('after')}>Add after</button>
              <button className="btn small" onClick={() => props.onChange(P.duplicatePhase(plan, p.id))}>Duplicate</button>
              <button className="btn small danger" onClick={() => (deps.length ? setRemoving(true) : props.onChange(P.removePhase(plan, p.id, true)))}>Remove</button>
            </div>)}
          {asking && (
            <form className="inline" onSubmit={e => { e.preventDefault(); if (newTitle.trim()) { props.onChange(P.addPhase(plan, { [asking]: p.id } as any, newTitle)); setAsking(null); setNewTitle(''); } }}>
              <input autoFocus aria-label="New phase name" placeholder={`New phase ${asking} “${p.title}”`} value={newTitle} maxLength={80} onChange={e => setNewTitle(e.target.value)} />
              <button type="submit" className="btn small primary">Add</button><button type="button" className="btn small" onClick={() => setAsking(null)}>Cancel</button>
            </form>)}
          {removing && (
            <div className="confirm" role="alertdialog" aria-label="Remove phase">
              <p>{deps.map(d => `“${d.title}”`).join(', ')} {deps.length === 1 ? 'depends' : 'depend'} on this phase.</p>
              <button className="btn small primary" onClick={() => { props.onChange(P.removePhase(plan, p.id, true)); setRemoving(false); }}>Remove and reconnect</button>
              <button className="btn small" onClick={() => { props.onChange(P.removePhase(plan, p.id, false)); setRemoving(false); }}>Remove, drop the link</button>
              <button className="btn small" onClick={() => setRemoving(false)}>Keep it</button>
            </div>)}
        </div>)}
    </div>);
}

export default function PlanBlock({ block, original, onChanged }: { block: Block; original: Plan; onChanged(): void }) {
  const launched = block.status === 'launched';
  const initial: Plan = block.state?.plan ?? original;
  const history = useRef(new P.History<Plan>(initial)); const [plan, setPlan] = useState<Plan>(initial);
  const [open, setOpen] = useState<string | null>(null); const [drag, setDrag] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState(''); const [busy, setBusy] = useState(false); const [err, setErr] = useState(''); const [now, setNow] = useState(Date.now());
  const { status, save, saveNow, dirty } = useAutosave(block, 700, launched ? 'live' : 'state');
  const run = block.run ?? {};
  const locked = block.status !== 'draft' && !launched;
  // A phase is editable until it starts. Before launch every phase is editable.
  const phaseLocked = (id: string) => locked || (launched && !!run[id] && !['pending', 'awaiting_approval', 'skipped'].includes(run[id].state));
  // While running, server state moves (phases finish, are skipped): adopt it unless the user has unsaved local edits.
  useEffect(() => { if (launched && !dirty() && block.state?.plan) setPlan(block.state.plan); }, [block.version, block.state, launched]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!launched || block.run_status !== 'running') return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [launched, block.run_status]);
  const issues = useMemo(() => P.validate(plan), [plan]);
  const rows = useMemo(() => P.layers(plan), [plan]);
  const order = useMemo(() => new Map(plan.phases.map((p, i) => [p.id, i + 1])), [plan]);
  const issueFor = (id: string) => issues.find(i => i.phaseId === id)?.message;
  const general = issues.filter(i => !i.phaseId);
  const enabledCount = plan.phases.filter(p => p.enabled).length;
  const doneCount = Object.values(run).filter(r => r.state === 'completed').length;
  const total = Object.values(run).filter(r => r.state !== 'skipped').length;

  const commit = (next: Plan) => { if (!P.samePlan(next, plan)) { history.current.push(next); setPlan(next); save({ plan: next }); } };
  const go = (next: Plan | null) => { if (next) { setPlan(next); save({ plan: next }); } };
  const post = async (path: string, body: unknown) => { setErr(''); try { await api('POST', `/v1/blocks/${block.id}/${path}`, body); onChanged(); } catch (e) { setErr(e instanceof ApiError && e.status === 409 ? 'That is no longer possible (the plan changed). Reload to continue.' : 'Could not do that. Try again.'); } };

  const launch = async () => {
    setBusy(true); setErr('');
    try { const v = await saveNow(); await api('POST', `/v1/blocks/${block.id}/launch`, { version: v }); onChanged(); }
    catch (e) { setErr(e instanceof ApiError && e.code === 'budget_denied' ? 'Your plan allowance cannot fund this right now.' : e instanceof ApiError && e.status === 409 ? 'This plan changed in another window. Reload to continue.' : 'Could not launch. Fix the issues listed or try again.'); }
    finally { setBusy(false); }
  };
  const stop = async () => { if (window.confirm('Stop this plan? Phases that have not run will be cancelled.')) await post('stop', {}); };
  const badge = !launched ? (block.status === 'submitted' ? 'Submitted' : 'Draft')
    : block.run_status === 'completed' ? 'Done' : block.run_status === 'awaiting_approval' ? 'Needs your approval' : block.run_status === 'failed' ? 'Needs attention' : block.run_status === 'stopped' ? 'Stopped' : 'Running';

  return (
    <section className="gblock plan" aria-label={`Plan: ${plan.title}`}>
      <header>
        <div className="plan-head"><h3>{plan.title}</h3>
          <span className={`badge ${launched && block.run_status === 'running' ? 'run-running' : launched && block.run_status === 'completed' ? 'run-completed' : launched && (block.run_status === 'failed' || block.run_status === 'awaiting_approval') ? 'run-awaiting_approval' : 'alt'}`}>{badge}</span>
          {launched && total > 0 && <span className="faint small">{doneCount} of {total} phases done</span>}</div>
        {plan.summary && <p className="muted">{plan.summary}</p>}
        {!locked && !launched && (
          <div className="toolbar" role="toolbar" aria-label="Plan tools">
            <button className="btn small" disabled={!history.current.canUndo} onClick={() => go(history.current.undo())}>Undo</button>
            <button className="btn small" disabled={!history.current.canRedo} onClick={() => go(history.current.redo())}>Redo</button>
            <button className="btn small" disabled={P.samePlan(plan, original)} onClick={() => commit(original)}>Reset to AI plan</button>
            <Saved status={status} />
          </div>)}
        {launched && (
          <div className="toolbar" role="toolbar" aria-label="Run tools">
            {block.run_status !== 'completed' && block.run_status !== 'stopped' && <button className="btn small danger" onClick={stop}>Stop plan</button>}
            <span className="faint small">You can still edit phases that have not started.</span>
            <Saved status={status} />
          </div>)}
      </header>
      <div className="diagram">
        {rows.map((row, ri) => (
          <div key={ri} className="layer-wrap">
            {ri > 0 && <div className="link" aria-hidden>↓</div>}
            <div className="layer">
              {row.map(p => (
                <Card key={p.id} p={p} n={order.get(p.id)!} plan={plan} locked={phaseLocked(p.id)} open={open === p.id} issue={issueFor(p.id)} dragging={drag === p.id}
                  run={launched ? run[p.id] : undefined} now={now} onAct={a => post('phase', { phase_id: p.id, action: a })}
                  onToggleOpen={() => setOpen(open === p.id ? null : p.id)} onChange={commit}
                  onDragStart={() => setDrag(p.id)} onDrop={() => { if (drag) commit(P.movePhaseTo(plan, drag, p.id)); setDrag(null); }} onDragEnd={() => setDrag(null)} />))}
            </div>
          </div>))}
      </div>
      {rows.some(r => r.length > 1) && <p className="faint small">Phases side by side can run independently. Moving a phase changes the order within its row; “Runs after” controls what must finish first.</p>}
      {!locked && (
        <form className="inline" onSubmit={e => { e.preventDefault(); if (newTitle.trim()) { commit(P.addPhase(plan, null, newTitle)); setNewTitle(''); } }}>
          <input aria-label="Add a phase" placeholder="Add a phase at the end…" value={newTitle} maxLength={80} onChange={e => setNewTitle(e.target.value)} /><button type="submit" className="btn small">Add phase</button>
        </form>)}
      {general.length > 0 && !locked && <ul className="issues" role="alert">{general.map((i, n) => <li key={n}>{i.message}</li>)}</ul>}
      <footer>
        {!launched && !locked ? (<>
          <button className="btn primary" disabled={busy || issues.length > 0 || status === 'conflict' || status === 'saving'} onClick={launch}>{busy ? 'Launching…' : `Launch plan (${enabledCount} phase${enabledCount === 1 ? '' : 's'})`}</button>
          <span className="faint">Phases run one after another, each reporting its result here. Phases marked “ask me first” wait for your approval. A task is capped at $5.</span></>)
          : launched ? <span className="faint">Each phase is a separate step in the chat. Open a finished phase to read its result.</span>
          : <span className="faint">Waiting for the plan to be created.</span>}
        {issues.some(i => i.phaseId) && !locked && <span className="err small">Fix the highlighted phases to continue.</span>}
        {err && <span className="err" role="alert">{err}</span>}
      </footer>
    </section>);
}
