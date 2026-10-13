import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import { toActivity, type ActivityItem } from './activity';

export type Ev = { sequence: number; kind: string; created_at?: string; payload?: Record<string, unknown> };

/** Follows one task's event stream by cursor: what it searched, opened, ran and wrote, as it happens (about every 1.5 s while it works). */
export function useActivity(taskId: string, active: boolean): { rows: ActivityItem[]; err: string } {
  const [events, setEvents] = useState<Ev[]>([]); const [err, setErr] = useState(''); const cursor = useRef(0);
  useEffect(() => { cursor.current = 0; setEvents([]); setErr(''); }, [taskId]);
  useEffect(() => {
    let stop = false; let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const r = await api<{ events: Ev[] }>('GET', `/v1/tasks/${taskId}/events?after=${cursor.current}&limit=200`);
        if (stop) return;
        if (r.events.length) { cursor.current = Math.max(cursor.current, ...r.events.map(e => e.sequence)); setEvents(old => [...old, ...r.events]); }
        setErr('');
      } catch { if (!stop) setErr('Could not refresh. Retrying…'); }
      if (!stop && (active || cursor.current === 0)) timer = setTimeout(load, 1500);
    };
    load(); return () => { stop = true; clearTimeout(timer); };
  }, [taskId, active]);
  const rows = useMemo(() => toActivity(events), [events]);
  return { rows, err };
}
