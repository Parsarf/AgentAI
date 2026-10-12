import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import type { Block } from '../../lib/genui/schema';

export type SaveStatus = 'saved' | 'saving' | 'unsaved' | 'conflict' | 'error';

/** Debounced draft saving with optimistic version checks. Edits are local and instant; the server only stores them. */
export function useAutosave(block: Block, delay = 700, mode: 'state' | 'live' = 'state') {
  const [status, setStatus] = useState<SaveStatus>('saved');
  const version = useRef(block.version); const pending = useRef<unknown>(null); const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const inflight = useRef(false); const dirty = useRef(false);
  useEffect(() => { if (!dirty.current && !inflight.current) version.current = block.version; }, [block.version]);

  const flush = useCallback(async () => {
    if (inflight.current || !dirty.current) return;
    inflight.current = true; dirty.current = false; setStatus('saving');
    try {
      const body = mode === 'live' ? { version: version.current, plan: (pending.current as any).plan } : { version: version.current, state: pending.current };
      const r = await api<{ block: Block }>('POST', `/v1/blocks/${block.id}/${mode === 'live' ? 'live' : 'state'}`, body);
      version.current = r.block.version; setStatus(dirty.current ? 'unsaved' : 'saved');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setStatus('conflict'); else { dirty.current = true; setStatus('error'); }
    } finally { inflight.current = false; if (dirty.current && status !== 'conflict') { timer.current = setTimeout(flush, delay); } }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [block.id, delay, mode]);

  const save = useCallback((state: unknown) => {
    pending.current = state; dirty.current = true; setStatus('unsaved');
    clearTimeout(timer.current); timer.current = setTimeout(flush, delay);
  }, [flush, delay]);

  useEffect(() => () => clearTimeout(timer.current), []);
  const saveNow = useCallback(async () => { clearTimeout(timer.current); await flush(); return version.current; }, [flush]);
  return { status, save, saveNow, version: () => version.current, dirty: () => dirty.current || inflight.current };
}
