import { Link } from 'react-router-dom';
import FileCard from '../files/FileCard';
import { Checklist, Elapsed, Status } from '../work/parts';
import type { ArtifactRow } from '../../lib/files';
import type { Block } from '../../lib/genui/schema';
import { isOpen, type TaskSummary } from '../../lib/work';
import { useTask } from '../../state/work';
import { ago } from '../../lib/format';
import { EmptyState } from './parts';

const PLAN_WORDS: Record<Block['status'], string> = { draft: 'Not started', submitted: 'Being planned', launched: 'Started', superseded: 'Replaced', final: 'Finished' };

/** Chat's inspector: what this conversation produced (its tasks, files and plans) and the details of the task that is running. Every fact comes from the same shared
 *  task state and lists as the thread itself. */
export default function ChatInspector({ tasks, files, blocks, onError }: { tasks: TaskSummary[]; files: ArtifactRow[]; blocks: Block[]; onError(message: string): void }) {
  const open = tasks.find(isOpen);
  const { task, full } = useTask(open?.id);
  const plans = blocks.filter(b => b.kind === 'task_plan');
  if (!tasks.length && !files.length && !plans.length) return <EmptyState title="Nothing made yet">Tasks, files and plans from this chat will be listed here.</EmptyState>;
  return <div className="chat-inspector">
    {task && <section aria-labelledby="ci-now" className="ci-section">
      <h3 id="ci-now" className="ci-h">Working now</h3>
      <p className="ci-task"><Status task={task} size="sm" /><Elapsed task={full ?? task} /></p>
      {task.attention && <Link className="btn primary small" to={`/activity/${task.id}`}>See what it needs</Link>}
      {full?.checklist && <Checklist checklist={full.checklist} />}
    </section>}
    {tasks.length > 0 && <section aria-labelledby="ci-tasks" className="ci-section">
      <h3 id="ci-tasks" className="ci-h">Tasks ({tasks.length})</h3>
      <ul className="ci-list">{tasks.map(t => <li key={t.id}><Link to={`/activity/${t.id}`} className="ci-row"><span className="ci-name">{t.title}</span><span className="ci-meta"><Status task={t} size="sm" /><span className="faint">{ago(t.created_epoch)}</span></span></Link></li>)}</ul>
    </section>}
    {files.length > 0 && <section aria-labelledby="ci-files" className="ci-section">
      <h3 id="ci-files" className="ci-h">Files ({files.length})</h3>
      <div className="file-cards ci-files">{files.map(f => <FileCard key={`${f.id}-${f.version}`} file={f} onError={onError} />)}</div>
    </section>}
    {plans.length > 0 && <section aria-labelledby="ci-plans" className="ci-section">
      <h3 id="ci-plans" className="ci-h">Plans ({plans.length})</h3>
      <ul className="ci-list">{plans.map(b => { const spec = b.spec as { title?: string }; return <li key={b.id} className="ci-row static"><span className="ci-name">{spec?.title || 'Plan'}</span><span className="badge">{PLAN_WORDS[b.status]}</span></li>; })}</ul>
    </section>}
  </div>;
}
