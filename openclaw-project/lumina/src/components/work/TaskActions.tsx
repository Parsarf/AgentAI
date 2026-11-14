import type { TaskSummary } from '../../lib/work';
import { useTaskActions } from './useTaskActions';

/** The buttons that apply to a task right now, from the controls the server says apply. `stop` is left out where the composer already carries Stop (the chat). */
export default function TaskActions({ task, stop = true, small = true }: { task: TaskSummary; stop?: boolean; small?: boolean }) {
  const { run, busy, err } = useTaskActions(task); const c = task.controls; const size = small ? ' small' : '';
  const any = (stop && c.stop) || c.pause || c.resume || c.retry || c.goal_resume;
  if (!any && !err) return null;
  return (
    <div className="wk-actions">
      {c.resume && <button className={`btn primary${size}`} disabled={!!busy} onClick={() => void run('resume')}>Resume</button>}
      {c.goal_resume && <button className={`btn primary${size}`} disabled={!!busy || !task.conversation_id} onClick={() => void run('goal_resume')}>Resume goal</button>}
      {c.goal_clear && <button className={`btn${size}`} disabled={!!busy || !task.conversation_id} onClick={() => void run('goal_clear')}>Clear goal</button>}
      {c.retry && <button className={`btn${size}`} disabled={!!busy} onClick={() => void run('retry')}>{busy === 'retry' ? 'Retrying…' : 'Try again'}</button>}
      {c.pause && <button className={`btn${size}`} disabled={!!busy} onClick={() => void run('pause')}>Pause</button>}
      {stop && c.stop && <button className={`btn danger${size}`} disabled={!!busy} onClick={() => void run('stop')}>{busy === 'stop' ? 'Stopping…' : task.phase === 'queued' || task.phase === 'paused' ? 'Cancel' : 'Stop'}</button>}
      {err && <p className="err" role="alert">{err}</p>}
    </div>);
}
