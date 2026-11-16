import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useSelection } from '../components/frame/Assistant';
import { useCommands } from '../components/frame/CommandBar';
import Workspace from '../components/frame/Workspace';
import { EmptyState, Table } from '../components/frame/parts';
import { ago } from '../lib/format';
import { isOpen, isPrompt, needLine, verdict, type Approval, type TaskSummary } from '../lib/work';
import Prompts from '../components/work/ChangeApproval';
import { useTask, useWork } from '../state/work';
import Permission from '../components/work/Permission';
import TaskActions from '../components/work/TaskActions';
import TaskDetail from '../components/work/TaskDetail';
import { Elapsed, Status } from '../components/work/parts';
import LongJobs from '../components/work/LongJobs';

/** What kind of thing an item is, from what the server says it needs. */
type Kind = 'task' | 'approval' | 'question' | 'plan' | 'goal';
const KIND_WORDS: Record<Kind, string> = { task: 'Task', approval: 'Approval', question: 'Question', plan: 'Plan', goal: 'Goal' };
export function kindOf(t: TaskSummary): Kind {
  if (t.needs.some(n => n.kind === 'question')) return 'question';
  if (t.needs.some(n => n.kind === 'workflow')) return 'plan';
  if (t.needs.some(n => n.kind === 'approval' || n.kind === 'action')) return 'approval';
  return t.goal ? 'goal' : 'task';
}
type State = 'all' | 'needs' | 'going' | 'done' | 'unconfirmed' | 'incomplete' | 'failed' | 'stopped';
const STATES: { key: State; label: string; match(t: TaskSummary): boolean }[] = [
  { key: 'all', label: 'Everything', match: () => true },
  { key: 'needs', label: 'Needs you', match: t => !!t.attention },
  { key: 'going', label: 'In progress', match: t => isOpen(t) && !t.attention },
  { key: 'done', label: 'Done', match: t => !isOpen(t) && !t.attention && t.outcome === 'completed' && t.verification !== 'unverified' },
  { key: 'unconfirmed', label: 'Not confirmed', match: t => !isOpen(t) && !t.attention && t.outcome === 'completed' && t.verification === 'unverified' },
  { key: 'incomplete', label: 'Partly done or blocked', match: t => !isOpen(t) && !t.attention && (t.outcome === 'partial' || t.outcome === 'blocked') },
  { key: 'failed', label: 'Failed', match: t => !isOpen(t) && !t.attention && t.outcome === 'failed' },
  { key: 'stopped', label: 'Stopped', match: t => !isOpen(t) && !t.attention && t.outcome === 'cancelled' },
];
const KINDS: (Kind | 'all')[] = ['all', 'task', 'approval', 'question', 'plan', 'goal'];
const steps = (n: number) => `${n} ${n === 1 ? 'step' : 'steps'}`;
const rank = (t: TaskSummary) => (t.attention ? 0 : isOpen(t) ? 1 : 2);

const OUTCOME_WORDS: Record<string, string> = { completed: 'The run finished', partial: 'Only part of it was done', blocked: 'Something blocked it', failed: 'The run failed', cancelled: 'Stopped at your request' };
const CHECK_WORDS: Record<string, string> = { verified: 'Confirmed', unverified: 'Not confirmed', not_applicable: 'Nothing to confirm' };
const CHECK_HELP: Record<string, string> = {
  verified: 'Lumina checked the result against something it holds itself (a saved file, or what the page showed).',
  unverified: 'The assistant says it is done, but nothing Lumina can check confirms it. Look at the result before relying on it.',
  not_applicable: 'This was a question or a lookup: the answer is the result.',
};

/** One task's record: what was asked, how the run ended and (separately) whether the result was confirmed, and everything Lumina holds as evidence of the work. */
export function Record({ id }: { id: string }) {
  const { loaded } = useWork(); const { task, full, rows } = useTask(id);
  if (!task) return <div className="wk-record"><p className={loaded ? 'err' : 'muted'} role={loaded ? 'alert' : 'status'}>{loaded ? 'This task is not available.' : 'Loading…'}</p></div>;
  const approvals = task.needs.filter((n): n is Approval => n.kind === 'approval'); const others = task.needs.filter(n => !isPrompt(n)); const words = verdict(task);   // approvals, changes, plans and questions are answered right here; the rest say what is needed
  return (
    <article className="wk-record">
      <header className="wk-record-head">
        <h1>{task.title}</h1>
        <div className="wk-record-status"><Status task={task} /><Elapsed task={full ?? task} /><span>Started {new Date(task.created_epoch * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</span>{task.retry_of && <Link to={`/tasks/${task.retry_of}`}>A retry of an earlier task</Link>}{task.follows && <Link to={`/tasks/${task.follows}`}>Carries on an earlier task</Link>}</div>
        <div className="wk-record-bar">
          {task.conversation_id && <Link className="btn primary small" to={`/chat/${task.conversation_id}`}>{isOpen(task) ? 'Open the chat' : 'Continue in the chat'}</Link>}
          {full?.browser && <Link className="btn small" to={`/live/${task.id}`}>{full.browser.live ? 'Open the browser' : 'Open the workspace'}</Link>}
          <TaskActions task={task} />
        </div>
      </header>
      {approvals.map(a => <Permission key={a.id} call={a} />)}
      <Prompts needs={task.needs} />
      {task.attention === 'goal' && <p className="wk-verdict">{verdict(task)}</p>}
      {others.map(n => <div key={n.kind} className="wk-need"><p>{needLine(n)}</p>{n.kind !== 'location_permission' && <Link className="btn primary small" to={`/live/${task.id}`}>Open the browser</Link>}</div>)}
      {task.outcome && (
        <dl className="wk-outcome" aria-label="How it ended">
          <div><dt>How the run ended</dt><dd>{OUTCOME_WORDS[task.outcome]}{task.outcome !== 'completed' && words && <small>{words}</small>}</dd></div>
          <div><dt>Was the result confirmed?</dt><dd>{task.outcome === 'completed' ? <>{CHECK_WORDS[task.verification ?? 'not_applicable']}<small>{task.verification === 'unverified' && task.note ? task.note : CHECK_HELP[task.verification ?? 'not_applicable']}</small></> : <>No<small>The task did not finish, so there is no result to confirm.</small></>}</dd></div>
        </dl>)}
      {full && <section aria-labelledby="rec-ask"><h2 id="rec-ask">What you asked</h2><p className="wk-request">{full.request}</p></section>}
      {full ? <TaskDetail task={full} rows={rows} links={false} /> : <p className="wk-empty" role="status">Loading the record…</p>}
    </article>);
}


/** Activity: one table of everything the assistant is doing, did, or is waiting on, across every chat. Context: filters by kind and state. Inspector: one item with its
 *  steps and its controls (stop, approve, answer, retry). What needs the person comes first. It replaces the old Tasks page, the right rail and the Automations page. */
export default function Activity() {
  const { id } = useParams(); const nav = useNavigate(); const [params, setParams] = useSearchParams();
  const { tasks, loaded, mode } = useWork();
  const state = (STATES.find(s => s.key === params.get('state'))?.key ?? 'all') as State;
  const kind = (KINDS.find(k => k === params.get('kind')) ?? 'all') as Kind | 'all';
  const set = (key: 'state' | 'kind', value: string) => { const next = new URLSearchParams(params); if (value === 'all') next.delete(key); else next.set(key, value); setParams(next, { replace: true }); };
  const shown = useMemo(() => tasks.filter(t => STATES.find(s => s.key === state)!.match(t) && (kind === 'all' || kindOf(t) === kind)).sort((a, b) => rank(a) - rank(b) || b.created_epoch - a.created_epoch), [tasks, state, kind]);
  const count = (key: State) => tasks.filter(STATES.find(s => s.key === key)!.match).length;
  const { task } = useTask(id, false);
  useSelection(id ? { looking: { kind: 'task', id }, words: task ? `the task “${task.title}”` : 'this task', actions: [{ label: 'What happened?', message: 'What happened in this task, in short?' }] }
    : { looking: { kind: 'page', page: 'activity' }, words: 'Activity', actions: count('needs') ? [{ label: 'What is waiting for me?', message: 'What is waiting for me in Activity, and what should I decide first?' }] : [] });
  useCommands([{ id: 'act-needs', label: 'Show what needs you', run: () => set('state', 'needs') }, { id: 'act-going', label: 'Show what is in progress', run: () => set('state', 'going') },
    { id: 'act-all', label: 'Show everything in Activity', run: () => { setParams({}, { replace: true }); } }]);
  const open = (t: TaskSummary) => nav({ pathname: `/activity/${t.id}`, search: params.toString() ? `?${params}` : '' });

  const context = <div className="act-filters">
    <section aria-label="State"><h3 className="ci-h">State</h3>
      <div className="act-filter-list">{STATES.map(s => { const n = s.key === 'all' ? tasks.length : count(s.key); return <button key={s.key} type="button" className="files-folder" aria-pressed={state === s.key} onClick={() => set('state', s.key)}>
        {s.label}{n > 0 && <span className={s.key === 'needs' ? 'wk-count' : 'faint'}>{n}</span>}</button>; })}</div></section>
    <section aria-label="Kind"><h3 className="ci-h">Kind</h3>
      <div className="act-filter-list">{KINDS.map(k => <button key={k} type="button" className="files-folder" aria-pressed={kind === k} onClick={() => set('kind', k)}>{k === 'all' ? 'Every kind' : KIND_WORDS[k]}</button>)}</div></section>
    <p className="faint small">Schedules and automations will be listed here too once they are switched on for your account.</p>
  </div>;

  return (
    <Workspace title="Activity" context={context} contextLabel="Filters" inspector={id ? <Record key={id} id={id} /> : null} inspectorLabel="Item" onInspectorClose={() => nav({ pathname: '/activity', search: params.toString() ? `?${params}` : '' })}
      tools={<span className="faint small act-live">{!loaded ? 'Loading…' : mode === 'stream' ? 'Up to date as it happens' : 'Refreshing every few seconds'}</span>}>
      <LongJobs />
      {count('needs') > 0 && state !== 'needs' && <p className="notice act-needs" role="status">{count('needs') === 1 ? 'One thing is waiting for you.' : `${count('needs')} things are waiting for you.`}
        <button type="button" className="btn small" onClick={() => set('state', 'needs')}>Show {count('needs') === 1 ? 'it' : 'them'}</button></p>}
      {!loaded ? <div className="hub-loading" role="status">{[0, 1, 2].map(n => <div key={n} className="skeleton" style={{ height: 44 }} />)}<span className="sr">Loading…</span></div>
        : <Table label="Activity" rows={shown} rowKey={t => t.id} selected={id} onOpen={open}
          empty={<EmptyState>{!tasks.length ? <>Nothing yet. Work you start in a chat is listed here, with how each task ended and what Lumina did for it. <Link to="/chat">Start something in a chat.</Link></> : 'Nothing here ended that way.'}</EmptyState>}
          columns={[
            { key: 'title', label: 'What', className: 'act-what', render: t => <span className="act-title"><Link to={`/activity/${t.id}`} onClick={e => e.stopPropagation()}>{t.title}</Link>{t.activity?.detail && <span className="faint small">{t.activity.detail}</span>}</span>, sort: t => t.title.toLowerCase() },
            { key: 'kind', label: 'Kind', className: 'act-kind', render: t => KIND_WORDS[kindOf(t)], sort: t => kindOf(t) },
            { key: 'state', label: 'State', render: t => <Status task={t} size="sm" />, sort: t => rank(t) },
            { key: 'steps', label: 'Steps', className: 'act-steps', render: t => (t.phase === 'ended' && t.steps > 0 ? steps(t.steps) : ''), sort: t => t.steps },
            { key: 'when', label: 'Started', className: 'act-when', render: t => <time dateTime={new Date(t.created_epoch * 1000).toISOString()}>{ago(t.created_epoch)}</time>, sort: t => t.created_epoch },
          ]} />}
      {tasks.length >= 90 && <p className="wk-fine">The most recent 100 tasks are listed. Older work stays in its chat.</p>}
    </Workspace>);
}
