import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import { toActivity, type ActivityItem } from './activity';
import { useWorkOptional } from '../state/work';

export type Ev = { sequence: number; kind: string; created_at?: string; payload?: Record<string, unknown> };

/** Follows one task's event stream by cursor: what it searched, opened, ran and wrote, as it happens. Where the push stream is on, the stream says when the task changed (its steps,
 *  its status line) and that is when this asks for the new events; a slow timer is only a safety net. Without the stream it asks about every 1.5 s while the task works. */
export function useActivity(taskId: string, active: boolean): { rows: ActivityItem[]; err: string; events: Ev[] } {
  const [events, setEvents] = useState<Ev[]>([]); const [err, setErr] = useState(''); const cursor = useRef(0);
  const work = useWorkOptional(); const streaming = work?.mode === 'stream'; const held = work?.details?.[taskId]?.task;
  const signal = streaming ? `${held?.steps ?? ''}|${held?.label ?? ''}|${held?.now?.length ?? ''}|${held?.phase ?? ''}|${held?.outcome ?? ''}` : '';
  useEffect(() => { cursor.current = 0; setEvents([]); setErr(''); }, [taskId]);
  useEffect(() => {
    if (!taskId) return;
    let stop = false; let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      let reresync = false;
      try {
        const r = await api<{ events: Ev[] }>('GET', `/v1/tasks/${taskId}/events?after=${cursor.current}&limit=200`);
        if (stop) return;
        if (r.events.length) { cursor.current = Math.max(cursor.current, ...r.events.map(e => e.sequence)); setEvents(old => [...old, ...r.events].slice(-2000)); }
        reresync = r.events.length === 200;
        setErr('');
      } catch { if (!stop) setErr('Could not refresh. Retrying…'); }
      if (!stop && (active || reresync)) timer = setTimeout(load, streaming && !reresync ? 30000 : 1500);
    };
    load(); return () => { stop = true; clearTimeout(timer); };
  }, [taskId, active, streaming, signal]);
  const rows = useMemo(() => toActivity(events), [events]);
  return { rows, err, events };
}
