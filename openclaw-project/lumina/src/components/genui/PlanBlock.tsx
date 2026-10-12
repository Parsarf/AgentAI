import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../../lib/api';
import * as P from '../../lib/genui/plan';
import type { Block, Phase, Plan } from '../../lib/genui/schema';
import { phase as phaseOf } from '../../lib/tasks';
import { useData } from '../../state/data';
import * as I from '../Icons';
import { Saved } from './Saved';
import { useAutosave } from './useAutosave';

function Card(props: {
  p: Phase; n: number; plan: Plan; locked: boolean; open: boolean; issue?: string; dragging: boolean;
  onToggleOpen(): void; onChange(next: Plan): void; onDragStart(): void; onDrop(): void; onDragEnd(): void;
}) {
  const { p, n, plan, locked, open, issue } = props;
  const [asking, setAsking] = useState<null | 'before' | 'after'>(null); const [newTitle, setNewTitle] = useState(''); const [removing, setRemoving] = useState(false);
  const deps = P.dependents(plan, p.id);
  const set = (patch: Partial<Phase>) => props.onChange(P.updatePhase(plan, p.id, patch));
  const state = !p.enabled ? 'Off' : p.requiresApproval ? 'Approval gate' : p.optional ? 'Optional' : 'On';
  return (
    <div className={`phase${p.enabled ? '' : ' off'}${issue ? ' bad' : ''}${props.dragging ? ' dragging' : ''}`} draggable={!locked && !open}
         onDragStart={e => { e.dataTransfer.effectAllowed = 'move'; props.onDragStart(); }} onDragOver={e => { if (!locked) e.preventDefault(); }}
         onDrop={e => { e.preventDefault(); props.onDrop(); }} onDragEnd={props.onDragEnd}>
      <div className="phase-head">
        <span className="grip" aria-hidden title="Drag to reorder">⠿</span>
        <button className="phase-title" aria-expanded={open} onClick={props.onToggleOpen}><span className="num">{n}</span><span>{p.title}</span></button>
        <span className={`badge ${state === 'On' ? '' : 'alt'}`}>{state}</span>
        {!locked && <button type="button" role="switch" aria-checked={p.enabled} aria-label={`${p.title} enabled`} className={`switch sm${p.enabled ? ' on' : ''}`} onClick={() => props.onChange(P.setEnabled(plan, p.id, !p.enabled))}><i /></button>}
      </div>
      {issue && <p className="err small" role="alert">{issue}</p>}
      {open && (
        <div className="phase-body">
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
              <button className="btn small primary">Add</button><button type="button" className="btn small" onClick={() => setAsking(null)}>Cancel</button>
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
  const initial: Plan = block.state?.plan ?? original;
  const history = useRef(new P.History<Plan>(initial)); const [plan, setPlan] = useState<Plan>(initial);
  const [open, setOpen] = useState<string | null>(null); const [drag, setDrag] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState(''); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const { status, save, saveNow } = useAutosave(block);
  const { requests } = useData();
  const locked = block.status !== 'draft';
  const issues = useMemo(() => P.validate(plan), [plan]);
  const rows = useMemo(() => P.layers(plan), [plan]);
  const order = useMemo(() => new Map(plan.phases.map((p, i) => [p.id, i + 1])), [plan]);
  const issueFor = (id: string) => issues.find(i => i.phaseId === id)?.message;
  const general = issues.filter(i => !i.phaseId);
  const enabledCount = plan.phases.filter(p => p.enabled).length;

  const commit = (next: Plan) => { if (!P.samePlan(next, plan)) { history.current.push(next); setPlan(next); save({ plan: next }); } };
  const go = (next: Plan | null) => { if (next) { setPlan(next); save({ plan: next }); } };

  const launch = async () => {
    setBusy(true); setErr('');
    try { const v = await saveNow(); await api('POST', `/v1/blocks/${block.id}/launch`, { version: v }); onChanged(); }
    catch (e) { setErr(e instanceof ApiError && e.code === 'budget_denied' ? 'Your plan allowance cannot fund this right now.' : e instanceof ApiError && e.status === 409 ? 'This plan changed in another window. Reload to continue.' : 'Could not launch. Fix the issues listed or try again.'); }
    finally { setBusy(false); }
  };
  const run = block.launched_request_id ? requests.find(r => r.id === block.launched_request_id) : undefined;
  const runPhase = run ? phaseOf(run.state) : null;

  return (
    <section className="gblock plan" aria-label={`Plan: ${plan.title}`}>
      <header>
        <div className="plan-head"><h3>{plan.title}</h3>
          {locked ? <span className="badge">{block.status === 'launched' ? 'Launched' : 'Submitted'}</span> : <span className="badge alt">Draft</span>}</div>
        {plan.summary && <p className="muted">{plan.summary}</p>}
        {!locked && (
          <div className="toolbar" role="toolbar" aria-label="Plan tools">
            <button className="btn small" disabled={!history.current.canUndo} onClick={() => go(history.current.undo())}>Undo</button>
            <button className="btn small" disabled={!history.current.canRedo} onClick={() => go(history.current.redo())}>Redo</button>
            <button className="btn small" disabled={P.samePlan(plan, original)} onClick={() => commit(original)}>Reset to AI plan</button>
            <Saved status={status} />
          </div>)}
      </header>
      <div className="diagram">
        {rows.map((row, ri) => (
          <div key={ri} className="layer-wrap">
            {ri > 0 && <div className="link" aria-hidden>↓</div>}
            <div className="layer">
              {row.map(p => (
                <Card key={p.id} p={p} n={order.get(p.id)!} plan={plan} locked={locked} open={open === p.id} issue={issueFor(p.id)} dragging={drag === p.id}
                  onToggleOpen={() => setOpen(open === p.id ? null : p.id)} onChange={commit}
                  onDragStart={() => setDrag(p.id)} onDrop={() => { if (drag) commit(P.movePhaseTo(plan, drag, p.id)); setDrag(null); }} onDragEnd={() => setDrag(null)} />))}
            </div>
          </div>))}
      </div>
      {rows.some(r => r.length > 1) && <p className="faint small">Phases side by side can run independently. Moving a phase changes the order within its row; “Runs after” controls what must finish first.</p>}
      {!locked && (
        <form className="inline" onSubmit={e => { e.preventDefault(); if (newTitle.trim()) { commit(P.addPhase(plan, null, newTitle)); setNewTitle(''); } }}>
          <input aria-label="Add a phase" placeholder="Add a phase at the end…" value={newTitle} maxLength={80} onChange={e => setNewTitle(e.target.value)} /><button className="btn small">Add phase</button>
        </form>)}
      {general.length > 0 && !locked && <ul className="issues" role="alert">{general.map((i, n) => <li key={n}>{i.message}</li>)}</ul>}
      <footer>
        {!locked ? (<>
          <button className="btn primary" disabled={busy || issues.length > 0 || status === 'conflict' || status === 'saving'} onClick={launch}>{busy ? 'Launching…' : `Launch plan (${enabledCount} phase${enabledCount === 1 ? '' : 's'})`}</button>
          <span className="faint">Estimated cost isn’t available per phase. A task is capped at $5 and stays within your plan allowance.</span></>)
          : (<span className="faint">{run ? <>Run status: <b>{runPhase}</b>. Progress is reported for the whole run, not per phase. <Link to={`/tasks/${run.id}`} style={{ color: 'var(--neon)' }}>Open task</Link></> : 'Waiting for the run to start.'}</span>)}
        {issues.some(i => i.phaseId) && !locked && <span className="err small">Fix the highlighted phases to launch.</span>}
        {err && <span className="err" role="alert">{err}</span>}
      </footer>
    </section>);
}
