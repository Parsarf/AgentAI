import { useCallback, useEffect, useState } from 'react';
import { api } from './api';
import type { Answer, Question } from './live';

/** The question a task's browser is waiting on, if any, for a chat that is not on the Live page. Polls while the task is active; a task with no browser run simply has none. */
export function useBrowseQuestion(taskId: string, active: boolean) {
  const [question, setQuestion] = useState<Question | null>(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const load = useCallback(async () => {
    try {
      const r = await api<{ status: string; question?: Question | null }>('GET', `/v1/browse/${taskId}?since=999999999`);
      setQuestion(r.status === 'asking' && r.question ? r.question : null);
    } catch { setQuestion(null); }                           // not a browser task (yet): nothing to answer
  }, [taskId]);
  useEffect(() => {
    if (!active) { setQuestion(null); return; }
    let stop = false; let timer: ReturnType<typeof setTimeout>;
    const tick = async () => { await load(); if (!stop) timer = setTimeout(tick, 2000); };
    void tick(); return () => { stop = true; clearTimeout(timer); };
  }, [active, load]);
  const answer = useCallback(async (body: Answer) => {
    if (!question) return;
    setBusy(true);
    try { await api('POST', `/v1/browse/${taskId}/answer`, { question_id: question.id, ...body }); setErr(''); }
    catch { setErr('That answer did not go through. If the question has gone, Lumina has already moved on.'); }
    setBusy(false); await load();
  }, [question, taskId, load]);
  return { question, busy, err, answer };
}
