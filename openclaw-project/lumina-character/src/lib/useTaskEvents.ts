import { useEffect, useState } from 'react';
import { api, type EventRow } from './api';

/** The live event feed of one task, drained by the server's sequence cursor. Stops when the task is no longer active. */
export function useTaskEvents(taskId: string | undefined, active: boolean): { taskId?: string; events: EventRow[] } {
  const [snapshot, setSnapshot] = useState<{ taskId?: string; events: EventRow[] }>({ events: [] });
  useEffect(() => {
    if (!taskId || !active) return;
    let stopped = false; let cursor = 0; let history: EventRow[] = [];
    let timer: ReturnType<typeof setTimeout>;
    setSnapshot({ taskId, events: [] });
    const load = async () => {
      try {
        while (!stopped) {
          const { events } = await api<{ events: EventRow[] }>('GET', `/v1/tasks/${taskId}/events?after=${cursor}&limit=200`);
          if (stopped) return;
          history = [...history, ...events];
          setSnapshot({ taskId, events: history });
          const next = events.at(-1)?.sequence ?? events.at(-1)?.id ?? cursor;
          if (next <= cursor) break;
          cursor = next;
          if (events.length < 200) break;
        }
      } catch { /* keep the last known events through a transient failure */ }
      if (!stopped) timer = setTimeout(load, 2500);
    };
    void load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [taskId, active]);
  return snapshot;
}
