import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import type { Row } from './work';
import { useWorkClientOptional, useWorkOptional } from '../state/work';

export type Ev = { sequence: number; kind: string; created_at?: string; payload?: Record<string, unknown> };

const NO_ROWS: Row[] = [];
/** One task's record for a block inside an answer. `rows` are the server's own timeline, the same rows every other screen shows (one row per tool call, the browser's steps
 *  inside their call, each failed step with its reason): this file used to build a second timeline of its own from the raw events, which had none of that. `events` are the
 *  raw notes, still read by cursor for the blocks that list checkpoints: where the push stream is on, the stream says when the task changed and that is when this asks for the
 *  new events (a slow timer is only a safety net); without the stream it asks about every 1.5 s while the task works. */
export function useActivity(taskId: string, active: boolean): { rows: Row[]; err: string; events: Ev[] } {
  const [events, setEvents] = useState<Ev[]>([]); const [err, setErr] = useState(''); const cursor = useRef(0);
  const work = useWorkOptional(); const client = useWorkClientOptional(); const streaming = work?.mode === 'stream'; const held = work?.details?.[taskId]?.task;
  useEffect(() => (client && taskId ? client.watch(taskId) : undefined), [client, taskId]);       // keep the task's full record current while this block is on screen
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
  const rows = work?.details?.[taskId]?.rows ?? NO_ROWS;
  return useMemo(() => ({ rows, err, events }), [rows, err, events]);
}
