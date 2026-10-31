import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import * as I from './Icons';
import { useActivity } from '../lib/useActivity';
import { taskProgress, STEP_LABEL, type WorkProgress } from '../lib/taskProgress';
import { activeTask, counts, phase, statusLabel } from '../lib/tasks';
import { elapsed, title } from '../lib/format';
import { useData } from '../state/data';
import { agentActivityFor } from '../lib/orbs';
import Orb from './Orb';

function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (!active) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [active]);
  return now;
}

export function TaskSteps({ progress }: { progress: WorkProgress }) {
  const steps = progress.mode === 'direct' ? progress.steps.slice(-5) : progress.steps;
  return <ul className="steps task-steps" aria-label={progress.mode === 'plan' ? 'Phase plan' : 'Task activity'}>
    {steps.map(step => <li key={step.id} className={step.status === 'running' ? 'now' : step.status}>
      <span className="mk" aria-hidden="true">{step.status === 'done' && <I.Check width={12} height={12} />}</span>
      <div><span className="task-step-title">{step.title}</span><span className="task-step-status">{STEP_LABEL[step.status]}</span>
        {step.checkpoint && <p className="task-checkpoint">Checkpoint: {step.checkpoint}</p>}
        {step.result && <p className="task-checkpoint">{step.result}</p>}
      </div>
    </li>)}
  </ul>;
}

export function ActiveTask() {
  const { requests } = useData();
  // Show actual running work ahead of newer queued messages, then retain the latest result.
  const task = activeTask(requests.filter(r => phase(r.state) === 'running')) ?? activeTask(requests)
    ?? requests.filter(r => ['completed', 'failed', 'cancelled'].includes(r.state)).sort((a, b) => b.created_epoch - a.created_epoch)[0];
  const active = !!task && ['queued', 'running'].includes(phase(task.state));
  const { events, err } = useActivity(task?.id ?? '', active);
  const now = useNow(active);
  const progress = task ? taskProgress(events, task) : null;
  const activity = task ? agentActivityFor(task.state, events) : null;
  const label = task?.parked ? 'Waiting for you' : progress?.steps.find(s => s.status === 'running')?.title ?? activity?.label;
  return <section className="panel card active-task" aria-labelledby="at-h">
    <div className="card-h"><h2 id="at-h">Active Task</h2>{task && <span className={`pill${active && !task.parked && phase(task.state) === 'running' ? ' live' : ''}`}>{statusLabel(task)}</span>}</div>
    {!task ? <p className="muted">Nothing is running. Describe a task to get started.</p> : <>
      <Link to={`/tasks/${task.id}`} className="active-task-title">{title(task.message, 100)}</Link>
      {active && <p className="faint orb-row active-task-current" role="status">{!task.parked && activity && <Orb state={activity.orb} size={20} />}{label ?? 'Waiting to start'}<span>{elapsed(task.created_epoch, now)}</span></p>}
      {progress && progress.steps.length > 0 ? <TaskSteps progress={progress} /> : <p className="faint active-task-empty">{active ? 'Activity will appear as work begins.' : 'No step updates were recorded.'}</p>}
      {err && <p className="faint" role="status">{err}</p>}
    </>}
  </section>;
}

export function Today() {
  const { app } = useData();
  return (
    <section className="panel card" aria-labelledby="td-h">
      <div className="card-h"><h2 id="td-h">Today</h2></div>
      <p className="muted">{app?.features.connectors ? 'No events to show yet.' : 'Calendar is not connected.'}</p>
      <p className="faint" style={{ fontSize: 12.5, marginTop: 8 }}>Scheduled tasks and calendar events will appear here once a calendar and automations are available. <Link to="/calendar" style={{ color: 'var(--neon)' }}>Details</Link></p>
    </section>);
}

function Ring({ n, total, label, color }: { n: number; total: number; label: string; color: string }) {
  const p = total ? Math.round((n / total) * 100) : 0;
  return <div><div className="ring" style={{ ['--p' as any]: p, ['--c' as any]: color }} role="img" aria-label={`${n} ${label}`}><b>{n}</b></div><div className="muted">{label}</div></div>;
}

export function SystemStatus() {
  const { requests, health } = useData();
  const c = counts(requests); const total = c.running + c.queued + c.completed;
  return (
    <section className="panel card" aria-labelledby="ss-h">
      <div className="card-h"><h2 id="ss-h">System Status</h2>
        {health === 'ok' ? <span className="ok-text">● All systems operational</span> : health === 'degraded' ? <span className="warn-text">● Degraded</span> : <span className="faint">Checking…</span>}</div>
      <div className="rings"><Ring n={c.running} total={total} label="Running" color="var(--neon)" /><Ring n={c.queued} total={total} label="Queued" color="var(--warn)" /><Ring n={c.completed} total={total} label="Completed" color="var(--ok)" /></div>
    </section>);
}

export default function Rail() { return <><ActiveTask /><Today /><SystemStatus /></>; }
