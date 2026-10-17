import { useEffect, useState } from 'react';
import { api, type EventRow } from '../lib/api';
import { isActive } from '../lib/tasks';
import { agentActivityFor } from '../lib/orbs';
import Orb from './Orb';

export interface ThreadTask { id: string; state: string; created_epoch: number; result?: string | null; paused?: boolean }

/** Assistant-side pending reply, never a task card. Details and Stop live in the header. */
export default function AgentThinking({ task }: { task: ThreadTask }) {
  const active = isActive(task);
  const [snapshot, setSnapshot] = useState<{ taskId: string; events: EventRow[] }>({ taskId: task.id, events: [] });
  useEffect(() => {
    if (!active) return;
    let stopped = false; let cursor = 0; let history: EventRow[] = [];
    let timer: ReturnType<typeof setTimeout>;
    setSnapshot({ taskId: task.id, events: [] });
    const load = async () => {
      try {
        // Drain pages using the server's sequence cursor; long tasks must not
        // remain stuck showing one of their first 50 events.
        while (!stopped) {
          const { events } = await api<{ events: EventRow[] }>('GET', `/v1/tasks/${task.id}/events?after=${cursor}&limit=200`);
          if (stopped) return;
          history = [...history, ...events];
          setSnapshot({ taskId: task.id, events: history });
          const next = events.at(-1)?.sequence ?? events.at(-1)?.id ?? cursor;
          if (next <= cursor) break;
          cursor = next;
          if (events.length < 200) break;
        }
      } catch { /* retain the last known activity through a transient failure */ }
      if (!stopped) timer = setTimeout(load, 2500);
    };
    void load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [task.id, active]);
  if (task.state === 'failed' || task.state === 'cancelled') return <div className="agent-status-error" role="status">{task.state === 'failed' ? task.result || 'Something went wrong. Open Activity for details.' : 'Stopped.'}</div>;
  if (task.state === 'waiting' && task.paused) return <div className="agent-thinking" role="status"><span>Paused. Resume it from Tasks when you want it to run.</span></div>;
  const activity = agentActivityFor(task.state, snapshot.taskId === task.id ? snapshot.events : []);
  if (!activity) return null;
  return <div className="agent-thinking" role="status" aria-live="polite" aria-atomic="true" data-orb-state={activity.orb}>
    <Orb state={activity.orb} size={48} /><span>{activity.label}…</span>
  </div>;
}
