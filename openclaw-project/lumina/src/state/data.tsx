import { clearArtifactDrafts, pauseArtifactDrafts, bindDraftAccount } from '../gen/drafts';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, ApiError, onUnauthorized, resetCsrf, type AppInfo } from '../lib/api';
import { clearDrafts } from '../lib/drafts';
import type { ChatSummary } from '../lib/chats';

interface Data {
  status: 'loading' | 'anon' | 'in' | 'error';
  app: AppInfo | null;
  chats: ChatSummary[];
  refreshChats(): Promise<void>;
  health: 'ok' | 'degraded' | 'unknown';
  refresh(): Promise<void>;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
}
const Ctx = createContext<Data>(null as any);

export function DataProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Data['status']>('loading');
  const [app, setApp] = useState<AppInfo | null>(null);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [health, setHealth] = useState<Data['health']>('unknown');
  const alive = useRef(true); const authVersion = useRef(0);

  const refresh = useCallback(async () => {
    const version = authVersion.current;
    try {
      const info = await api<AppInfo>('GET', '/v1/app');
      if (!alive.current || authVersion.current !== version) return;
      bindDraftAccount(info.user.email); setApp(info); setStatus('in');
    } catch (e) {
      if (!alive.current || authVersion.current !== version) return;
      if (e instanceof ApiError && e.status === 401) { ++authVersion.current; setStatus('anon'); setApp(null); setChats([]); clearDrafts(); pauseArtifactDrafts(); }
      else setStatus(s => (s === 'in' ? 'in' : 'error'));   // a blip while signed in keeps the last good data on screen
    }
  }, []);

  const refreshChats = useCallback(async () => {
    const version = authVersion.current;
    try { const r = await api<{ conversations: ChatSummary[] }>('GET', '/v1/conversations'); if (alive.current && authVersion.current === version) setChats(r.conversations); } catch { /* keep the last list */ }
  }, []);

  useEffect(() => { alive.current = true; refresh(); return () => { alive.current = false; }; }, [refresh]);
  useEffect(() => onUnauthorized(() => { ++authVersion.current; setStatus('anon'); setApp(null); setChats([]); clearDrafts(); pauseArtifactDrafts(); }), []);

  const live = status === 'in';
  useEffect(() => { if (live) refreshChats(); }, [live, refreshChats]);
  // Account facts and the chat list change rarely. Tasks are not kept here: every screen reads them from the shared work state (state/work.tsx), which is pushed.
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => { if (document.visibilityState === 'visible') { refresh(); refreshChats(); } }, 15000);
    return () => clearInterval(t);
  }, [live, refresh, refreshChats]);

  useEffect(() => {
    if (!live) return;
    let stop = false;
    const probe = async () => {
      try { const r = await fetch('/readyz', { credentials: 'same-origin' }); if (!stop) setHealth(r.ok ? 'ok' : 'degraded'); }
      catch { if (!stop) setHealth('degraded'); }
    };
    probe(); const t = setInterval(probe, 30000);
    return () => { stop = true; clearInterval(t); };
  }, [live]);

  const signIn = useCallback(async (email: string, password: string) => {
    ++authVersion.current;
    await api('POST', '/auth/login', { email, password }); resetCsrf(); await refresh();
  }, [refresh]);
  const signOut = useCallback(async () => {
    ++authVersion.current;
    try { await api('POST', '/auth/logout', {}); } finally { resetCsrf(); ++authVersion.current; setStatus('anon'); setApp(null); setChats([]); clearDrafts(); clearArtifactDrafts(); }
  }, []);

  const value = useMemo(() => ({ status, app, chats, refreshChats, health, refresh, signIn, signOut }), [status, app, chats, refreshChats, health, refresh, signIn, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export const useData = () => useContext(Ctx);
