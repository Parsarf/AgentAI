import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import * as I from '../components/Icons';
import { ago } from '../lib/format';
import { isOpen, needLine, verdict, type Approval, type TaskSummary } from '../lib/work';
import { useTask, useWork } from '../state/work';
import Permission from '../components/work/Permission';
import TaskActions from '../components/work/TaskActions';
import TaskDetail from '../components/work/TaskDetail';
import { Elapsed, Status } from '../components/work/parts';

type Filter = 'all' | 'done' | 'unconfirmed' | 'incomplete' | 'failed' | 'stopped';
const FILTERS: { key: Filter; label: string; match(t: TaskSummary): boolean }[] = [
  { key: 'all', label: 'All', match: () => true },
  { key: 'done', label: 'Done', match: t => t.outcome === 'completed' && t.verification !== 'unverified' },
  { key: 'unconfirmed', label: 'Not confirmed', match: t => t.outcome === 'completed' && t.verification === 'unverified' },
  { key: 'incomplete', label: 'Partly done or blocked', match: t => t.outcome === 'partial' || t.outcome === 'blocked' },
  { key: 'failed', label: 'Failed', match: t => t.outcome === 'failed' },
  { key: 'stopped', label: 'Stopped', match: t => t.outcome === 'cancelled' },
];
const steps = (n: number) => `${n} ${n === 1 ? 'step' : 'steps'}`;

/** One task on a line: what was asked, where it stands in the server's words, and when. It opens the task's record. */
function Item({ task, children }: { task: TaskSummary; children?: React.ReactNode }) {
  return (
    <li className="wk-item">
      <Link className="wk-item-link" to={`/tasks/${task.id}`}>
        <span className="wk-item-title">{task.title}</span>
        <span className="wk-item-meta"><Status task={task} size="sm" />{task.activity?.detail && <span>{task.activity.detail}</span>}{task.phase === 'ended' && task.steps > 0 && <span>{steps(task.steps)}</span>}{task.goal && <span>Goal</span>}</span>
        <time className="wk-item-when">{ago(task.created_epoch)}</time>
      </Link>
      {children}
    </li>);
}

/** What needs the customer, with the thing to do right on the line: a permission prompt is answered here, the browser is one click away, a held task can be resumed. */
function NeedsYou({ task }: { task: TaskSummary }) {
  const approvals = task.needs.filter((n): n is Approval => n.kind === 'approval'); const others = task.needs.filter(n => n.kind !== 'approval');
  return (
    <Item task={task}>
      <div className="wk-item-extra">
        {approvals.map(a => <Permission key={a.id} call={a} />)}
        {others.map(n => <div key={n.kind} className="wk-need"><p>{needLine(n)}</p>{n.kind !== 'location_permission' && <Link className="btn primary small" to={`/live/${task.id}`}>Open the browser</Link>}</div>)}
        {task.attention === 'goal' && <p className="wk-verdict">{verdict(task)}</p>}
        <TaskActions task={task} />
      </div>
    </Item>);
}

/** Activity: everything Lumina has done and is doing for you, across every chat. Chat is the conversation; this is the account of the work.
 *  On top, what is waiting for you. Then what is in progress. Then the record of finished work, which can be read by how it ended. */
function Activity() {
  const { tasks, loaded, mode } = useWork(); const [filter, setFilter] = useState<Filter>('all');
  const needs = tasks.filter(t => t.attention); const going = tasks.filter(t => isOpen(t) && !t.attention);
  const ended = tasks.filter(t => !isOpen(t) && !t.attention); const match = FILTERS.find(f => f.key === filter)!.match; const shown = ended.filter(match);
  return (
    <div className="wk-page">
      <header className="wk-page-head"><h1>Activity</h1><p>{!loaded ? 'Loading…' : mode === 'stream' ? 'Up to date as it happens' : 'Refreshing every few seconds'}</p></header>
      <section className="wk-section" aria-labelledby="act-needs">
        <h2 id="act-needs">Needs you{needs.length > 0 && <span className="wk-count">{needs.length}</span>}</h2>
        {needs.length ? <ul className="wk-list">{needs.map(t => <NeedsYou key={t.id} task={t} />)}</ul> : <p className="wk-quiet">{loaded ? 'Nothing is waiting for you.' : 'Loading…'}</p>}
      </section>
      <section className="wk-section" aria-labelledby="act-going">
        <h2 id="act-going">In progress</h2>
        {going.length ? <ul className="wk-list">{going.map(t => <Item key={t.id} task={t} />)}</ul> : <p className="wk-quiet">{loaded ? <>Nothing is running. <Link to="/chat">Start something in a chat.</Link></> : 'Loading…'}</p>}
      </section>
      <section className="wk-section" aria-labelledby="act-ended">
        <h2 id="act-ended">Finished</h2>
        <div className="wk-filters" role="group" aria-label="Show finished work that">{FILTERS.map(f => <button key={f.key} className="chip small" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>{f.label}{f.key !== 'all' && ended.some(f.match) ? ` ${ended.filter(f.match).length}` : ''}</button>)}</div>
        {shown.length ? <ul className="wk-list">{shown.map(t => <Item key={t.id} task={t} />)}</ul>
          : <p className="wk-quiet">{!loaded ? 'Loading…' : ended.length ? 'No finished work ended that way.' : 'Finished work will be listed here, with how each task ended and what Lumina did for it.'}</p>}
        {ended.length >= 90 && <p className="wk-fine">The most recent 100 tasks are listed. Older work stays in its chat.</p>}
      </section>
    </div>);
}

const OUTCOME_WORDS: Record<string, string> = { completed: 'The run finished', partial: 'Only part of it was done', blocked: 'Something blocked it', failed: 'The run failed', cancelled: 'Stopped at your request' };
const CHECK_WORDS: Record<string, string> = { verified: 'Confirmed', unverified: 'Not confirmed', not_applicable: 'Nothing to confirm' };
const CHECK_HELP: Record<string, string> = {
  verified: 'Lumina checked the result against something it holds itself (a saved file, or what the page showed).',
  unverified: 'The assistant says it is done, but nothing Lumina can check confirms it. Look at the result before relying on it.',
  not_applicable: 'This was a question or a lookup: the answer is the result.',
};

/** One task's record: what was asked, how the run ended and (separately) whether the result was confirmed, and everything Lumina holds as evidence of the work. */
function Record({ id }: { id: string }) {
  const { loaded } = useWork(); const { task, full, rows } = useTask(id);
  if (!task) return <div className="wk-record"><Link className="wk-back" to="/tasks"><I.Chevron width={14} height={14} />Activity</Link><p className={loaded ? 'err' : 'muted'} role={loaded ? 'alert' : 'status'}>{loaded ? 'This task is not available.' : 'Loading…'}</p></div>;
  const approvals = task.needs.filter((n): n is Approval => n.kind === 'approval'); const others = task.needs.filter(n => n.kind !== 'approval'); const words = verdict(task);
  return (
    <article className="wk-record">
      <Link className="wk-back" to="/tasks"><I.Chevron width={14} height={14} />Activity</Link>
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

export default function Tasks() {
  const { id } = useParams();
  return id ? <Record key={id} id={id} /> : <Activity />;
}
