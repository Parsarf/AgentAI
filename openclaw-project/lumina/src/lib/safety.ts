// The safety switches: types, pure helpers and the API calls (platform/accounts/safety.py).
// Two scopes: "mine" (this account only) and "all" (the default for every account; the owner only). The owner can also grant other accounts the menu.
// Nothing here imports a component or a stylesheet, so the popup can be redesigned (or replaced by a page) without touching this.
import { api, ApiError } from './api';

export type Scope = 'mine' | 'all';
/** Why a switch cannot be changed: server-wide ('shared'), never switched off ('core'), or a privacy protection that is never switched off for everyone ('privacy'). */
export type Lock = 'shared' | 'core' | 'privacy';
export interface SafetyFeature {
  key: string; group: string; title: string; plain: string; wired: boolean; on: boolean; expires_epoch: number | null;
  /** where the setting comes from: this account's own, the all-users default, or nothing set */
  source: 'account' | 'all' | 'default';
  lock: Lock | null;
  /** all-users view only: how many accounts have their own setting for this switch */
  overridden?: number;
}
export interface SafetyGroup { key: string; title: string }
export interface SafetyState { role: 'owner' | 'member'; scope: Scope; scopes: Scope[]; groups: SafetyGroup[]; features: SafetyFeature[]; off_count: number }
export interface AccessEntry { email: string; granted_epoch: number }
/** What the owner wants each switch to be: feature key -> on. */
export type Draft = Record<string, boolean>;

/** How long "off" lasts before it switches itself back on. 0 = until the owner turns it back on. */
export const OFF_FOR = [
  { label: 'Until I turn it back on', minutes: 0 }, { label: '30 minutes', minutes: 30 }, { label: '2 hours', minutes: 120 },
  { label: '8 hours', minutes: 480 }, { label: '24 hours', minutes: 1440 },
] as const;

/** Can this switch be set to `on`? A privacy protection can always be switched back ON, never off for everyone; shared and core ones never change here. */
export const canSet = (f: SafetyFeature, on: boolean): boolean => !f.lock || (f.lock === 'privacy' && on);
/** Is there anything to do with this switch? (A privacy protection that is currently off can be turned on.) */
export const switchable = (f: SafetyFeature): boolean => !f.lock || (f.lock === 'privacy' && !f.on);

/** The short notes shown after a switch's description (plain words, so every design says the same thing). */
export const notesOf = (f: SafetyFeature, scope: Scope): string[] => {
  const notes: string[] = [];
  if (!f.wired && f.lock !== 'shared' && f.lock !== 'core') notes.push('not enforced yet');                   // server-wide and core protections are never enforced by this menu: not a to-do
  if (f.lock === 'shared') notes.push('set on the server for everyone, not here');
  else if (f.lock === 'core') notes.push('always on');
  else if (f.lock === 'privacy') notes.push(f.on ? "can't be turned off for everyone (you can for your own account)" : 'off for everyone: you can turn it back on');
  if (scope === 'mine' && f.source === 'all' && !f.on) notes.push('off for all users');
  if (scope === 'all' && f.overridden) notes.push(`${f.overridden} account${f.overridden > 1 ? 's' : ''} set differently`);
  return notes;
};

export const draftOf = (s: SafetyState): Draft => Object.fromEntries(s.features.map(f => [f.key, f.on]));
/** "Turn everything on/off": every switch that may be set that way; the rest keep their value. */
export const allDraft = (s: SafetyState, on: boolean): Draft => Object.fromEntries(s.features.map(f => [f.key, canSet(f, on) ? on : f.on]));
/** Only the switches whose wanted value differs from what the server has. */
export const changesOf = (s: SafetyState, draft: Draft): Draft => Object.fromEntries(s.features.filter(f => draft[f.key] !== undefined && draft[f.key] !== f.on).map(f => [f.key, draft[f.key]]));
/** A duration only means something when a switch is being turned off; `scope` is sent only for the all-users view. */
export const requestBody = (password: string, changes: Draft, minutes: number, scope: Scope = 'mine') =>
  ({ password, changes, ...(minutes && Object.values(changes).includes(false) ? { minutes } : {}), ...(scope === 'all' ? { scope } : {}) });

/** null = no access to the menu (the server answers 404), or the answer is not usable: the UI then shows nothing at all. */
export async function loadSafety(scope: Scope = 'mine'): Promise<SafetyState | null> {
  try {
    const s = await api<SafetyState>('GET', `/v1/safety${scope === 'all' ? '?scope=all' : ''}`);
    return Array.isArray(s?.features) && Array.isArray(s?.groups) ? s : null;
  } catch { return null; }
}
export const changeSafety = (password: string, changes: Draft, minutes: number, scope: Scope = 'mine') =>
  api<SafetyState>('POST', '/v1/safety/change', requestBody(password, changes, minutes, scope));

/** Owner only: who else may open the menu. */
export async function loadAccess(): Promise<AccessEntry[] | null> {
  try { const r = await api<{ access: AccessEntry[] }>('GET', '/v1/safety/access'); return Array.isArray(r?.access) ? r.access : null; } catch { return null; }
}
export const changeAccess = async (password: string, change: { grant: string } | { revoke: string }): Promise<AccessEntry[]> =>
  (await api<{ access: AccessEntry[] }>('POST', '/v1/safety/access/change', { password, ...change })).access;

export const explainSafetyError = (e: unknown): string => {
  if (e instanceof ApiError) {
    if (e.status === 403) return 'That password is not right.';
    if (e.code === 'locked') return 'That switch cannot be changed here.';
    if (e.code === 'unknown_account') return 'There is no other account with that email.';
  }
  return 'That was not accepted. Try again.';
};
