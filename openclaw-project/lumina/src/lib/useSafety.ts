// The Safety popup's behaviour, with no markup: any design (popup, page, settings section) takes this model and draws it.
// The password is never kept here: the design collects it, passes it to the one call that needs it, and drops it.
import { useCallback, useEffect, useState } from 'react';
import {
  allDraft, changeAccess, changeSafety, changesOf, draftOf, explainSafetyError, loadAccess, loadSafety,
  type AccessEntry, type Draft, type SafetyState, type Scope,
} from './safety';

export interface SafetyModel {
  /** This account's own switches ("mine"): null until loaded, and for good when the account has no access. The Safety button shows only when this exists. */
  account: SafetyState | null;
  /** The scope being shown: null while it loads. */
  state: SafetyState | null;
  scope: Scope;
  /** ['mine'] for a granted account, ['mine', 'all'] for the owner */
  scopes: Scope[];
  open: boolean;
  /** what the owner wants each switch of the CURRENT scope to be (each scope keeps its own unsaved choices) */
  draft: Draft;
  /** switches of the current scope whose wanted value differs from the server's */
  dirty: number;
  /** true when a change turns a switch off (a duration then applies) */
  turningOff: boolean;
  minutes: number;
  busy: boolean;
  error: string;
  /** set only after the server confirmed a save; cleared by the next edit */
  done: string;
  /** owner only, loaded with the all-users view: the accounts the owner has granted the menu */
  access: AccessEntry[] | null;
  show(): void;
  hide(): void;
  setScope(scope: Scope): void;
  toggle(key: string, on: boolean): void;
  setAll(on: boolean): void;
  setMinutes(minutes: number): void;
  /** drop this view's unsaved choices */
  discard(): void;
  /** true when the server confirmed. The popup stays open and says so; a failure keeps the choices. */
  apply(password: string): Promise<boolean>;
  /** owner only; true when it worked */
  grant(email: string, password: string): Promise<boolean>;
  revoke(email: string, password: string): Promise<boolean>;
}

type States = Partial<Record<Scope, SafetyState>>;
type Drafts = Partial<Record<Scope, Draft>>;

export function useSafety(): SafetyModel {
  const [states, setStates] = useState<States>({});
  const [drafts, setDrafts] = useState<Drafts>({});
  const [scope, setScopeState] = useState<Scope>('mine');
  const [open, setOpen] = useState(false);
  const [minutes, setMinutesState] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');
  const [access, setAccess] = useState<AccessEntry[] | null>(null);

  useEffect(() => { let live = true; void loadSafety('mine').then(s => { if (live && s) setStates(m => ({ ...m, mine: s })); }); return () => { live = false; }; }, []);

  const account = states.mine ?? null;
  const state = states[scope] ?? null;
  const scopes = account?.scopes ?? [];
  const draft = drafts[scope] ?? {};
  const changes = state ? changesOf(state, draft) : {};
  const dirty = Object.keys(changes).length;

  const adopt = useCallback((next: SafetyState) => {
    setStates(m => ({ ...m, [next.scope]: next })); setDrafts(d => ({ ...d, [next.scope]: draftOf(next) }));
  }, []);
  const edited = useCallback(() => { setDone(''); setError(''); }, []);

  const show = useCallback(() => {
    if (!account) return;
    setScopeState('mine'); setDrafts({ mine: draftOf(account) }); setMinutesState(0); setError(''); setDone(''); setOpen(true);       // every opening starts from what the server has
  }, [account]);
  const hide = useCallback(() => { setOpen(false); setScopeState('mine'); }, []);

  const setScope = useCallback((next: Scope) => {
    if (!scopes.includes(next)) return;
    setScopeState(next); edited(); setMinutesState(0);
    const have = states[next];
    if (have) setDrafts(d => d[next] ? d : { ...d, [next]: draftOf(have) });
    else void loadSafety(next).then(s => { if (s) adopt(s); else setError('That view could not be loaded.'); });
    if (next === 'all' && access === null) void loadAccess().then(a => { if (a) setAccess(a); });
  }, [scopes, states, access, adopt, edited]);

  const toggle = useCallback((key: string, on: boolean) => { edited(); setDrafts(d => ({ ...d, [scope]: { ...d[scope], [key]: on } })); }, [scope, edited]);
  const setAll = useCallback((on: boolean) => { if (state) { edited(); setDrafts(d => ({ ...d, [scope]: allDraft(state, on) })); } }, [state, scope, edited]);
  const setMinutes = useCallback((n: number) => { edited(); setMinutesState(n); }, [edited]);
  const discard = useCallback(() => { if (state) { edited(); setDrafts(d => ({ ...d, [scope]: draftOf(state) })); setMinutesState(0); } }, [state, scope, edited]);

  const apply = useCallback(async (password: string): Promise<boolean> => {
    if (!state || busy || !dirty || !password) return false;
    setBusy(true); setError(''); setDone('');
    try {
      adopt(await changeSafety(password, changes, minutes, scope));
      if (scope === 'all') { const mine = await loadSafety('mine'); if (mine) adopt(mine); }           // what everyone gets changes what this account sees
      setMinutesState(0); setDone('Configuration saved successfully.');                                    // only after the server confirmed
      return true;
    } catch (e) { setError(explainSafetyError(e)); return false; }                                         // the choices stay, so they can be tried again
    finally { setBusy(false); }
  }, [state, busy, dirty, changes, minutes, scope, adopt]);

  const changeWho = useCallback(async (change: { grant: string } | { revoke: string }, password: string): Promise<boolean> => {
    if (busy || !password) return false;
    setBusy(true); setError(''); setDone('');
    try { setAccess(await changeAccess(password, change)); return true; }
    catch (e) { setError(explainSafetyError(e)); return false; }
    finally { setBusy(false); }
  }, [busy]);
  const grant = useCallback((email: string, password: string) => changeWho({ grant: email.trim() }, password), [changeWho]);
  const revoke = useCallback((email: string, password: string) => changeWho({ revoke: email }, password), [changeWho]);

  return { account, state, scope, scopes, open, draft, dirty, turningOff: Object.values(changes).includes(false), minutes, busy, error, done, access, show, hide, setScope, toggle, setAll, setMinutes, discard, apply, grant, revoke };
}
