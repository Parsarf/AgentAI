import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '../../lib/api';
import type { TaskSummary } from '../../lib/work';
import { useWorkClient } from '../../state/work';

export type TaskAction = 'stop' | 'pause' | 'resume' | 'retry' | 'goal_resume' | 'goal_clear';
const FAILED: Record<TaskAction, string> = {
  stop: 'Could not stop this task. Please try again.', pause: 'Could not pause this task. It may have just started.', resume: 'Could not resume this task.',
  retry: 'Could not retry this task.', goal_resume: 'Could not resume the goal.', goal_clear: 'Could not clear the goal.',
};
const key = () => crypto.randomUUID().replace(/-/g, '');

/** The things a customer can do to a task, on the routes that already do them. One place, so every surface offers the same actions with the same words when one fails. */
export function useTaskActions(task: Pick<TaskSummary, 'id' | 'conversation_id'> | undefined) {
  const client = useWorkClient(); const nav = useNavigate();
  const [busy, setBusy] = useState<TaskAction | ''>(''); const [err, setErr] = useState('');
  const run = useCallback(async (action: TaskAction) => {
    if (!task) return;
    setBusy(action); setErr('');
    try {
      if (action === 'stop') await api('POST', `/v1/requests/${task.id}/cancel`, {});
      else if (action === 'pause' || action === 'resume') await api('POST', `/v1/requests/${task.id}/${action}`, {});
      else if (action === 'retry') { const r = await api<{ request: { id: string; conversation_id?: string | null } }>('POST', `/v1/requests/${task.id}/retry`, {}); await client.refresh(); void nav(r.request.conversation_id ? `/chat/${r.request.conversation_id}` : `/tasks/${r.request.id}`); }
      else if (task.conversation_id) await api('POST', `/v1/conversations/${task.conversation_id}/goal`, { action: action === 'goal_resume' ? 'resume' : 'clear', key: key() });
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 402 ? 'Your plan allowance or task budget cannot fund another run right now.' : FAILED[action]);
    } finally { setBusy(''); void client.refresh(); }
  }, [task, client, nav]);
  return { run, busy, err };
}
