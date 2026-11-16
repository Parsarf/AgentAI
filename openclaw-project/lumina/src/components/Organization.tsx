import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';

interface Member { actor_id: string; account_id: string; role: string; you: boolean }
interface Policy { key: string; plain: string; value: unknown; set: boolean }
export interface Org {
  id: string; name: string; your_role: string | null; members: Member[]; can: Record<string, boolean>; policy: Policy[]; tool_groups: string[]; write_rules: string[];
}
const ROLE_WORDS: Record<string, string> = { owner: 'Owner', admin: 'Admin', member: 'Member', viewer: 'Viewer' };
const ROLE_HINT: Record<string, string> = { owner: 'Everything, including billing and deleting the organization.', admin: 'Members, connections and policy.',
  member: 'Their own assistant and their own connections.', viewer: 'Can read what is shared with them. Cannot run tasks or connect anything.' };
const GROUP_WORDS: Record<string, string> = { browser: 'Browser', files: 'Files', memory: 'Memory', display: 'Tables and charts', location: 'Location', remote_tools: 'Remote tools', connectors: 'Connected services' };
const failed = (e: unknown) => (e instanceof ApiError && e.status === 403 ? 'Your role does not allow this.' : e instanceof ApiError && e.status === 409 ? 'That is not possible: an organization keeps at least one owner.' : 'That did not go through. Please try again.');

/** Settings > Account: your organization. Who belongs with which role, and what the organization decides for its members. Someone who may not change it sees it as it is. An
 *  organization of one (most people) only sees its own role; the member and policy controls appear once there is someone to manage or something to set. */
export default function Organization() {
  const [org, setOrg] = useState<Org | null>(null); const [busy, setBusy] = useState(''); const [err, setErr] = useState(''); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(() => api<{ organization: Org }>('GET', '/v1/organization').then(r => { if (alive.current) setOrg(r.organization); }).catch(() => { /* not on this server: hidden */ }), []);
  useEffect(() => { void load(); }, [load]);
  if (!org) return null;
  const post = async (key: string, path: string, body: unknown) => {
    setBusy(key); setErr('');
    try { const r = await api<{ organization: Org }>('POST', path, body); if (alive.current) setOrg(r.organization); } catch (e) { if (alive.current) setErr(failed(e)); } finally { if (alive.current) setBusy(''); }
  };
  const policy = (key: string) => org.policy.find(p => p.key === key);
  const setPolicy = (key: string, value: unknown) => post('policy-' + key, '/v1/organization/policy', { key, value });
  const tools = policy('tools_allowed'); const allowed = (tools?.value as string[] | null) ?? null;
  const ownKey = policy('own_model_key'); const manage = !!org.can['policy.change']; const several = org.members.length > 1;
  return (
    <section className="panel card set-card" aria-labelledby="org-h">
      <div className="set-head"><h2 id="org-h">Your organization</h2><span className="badge alt">{ROLE_WORDS[org.your_role ?? ''] ?? 'Member'}</span></div>
      <p className="muted">{several ? `${org.members.length} people. Each has their own assistant; nobody sees another member's chats, files or connections.` : 'You are the only person in it. Each person you add later gets their own assistant.'}</p>
      {several && <div role="list" aria-label="Members">{org.members.map(m => (
        <div key={m.actor_id} className="org-row" role="listitem">
          <span>{m.you ? 'You' : `Member ${m.actor_id}`}<span className="faint"> · {ROLE_HINT[m.role]}</span></span>
          {org.can['member.role'] && !m.you ? (
            <span className="int-row">
              <label className="sr" htmlFor={`role-${m.actor_id}`}>Role of member {m.actor_id}</label>
              <select id={`role-${m.actor_id}`} className="input" value={m.role} disabled={!!busy} onChange={e => void post('role', `/v1/organization/members/${m.actor_id}/role`, { role: e.target.value })}>
                {['owner', 'admin', 'member', 'viewer'].map(r => <option key={r} value={r}>{ROLE_WORDS[r]}</option>)}</select>
              {org.can['member.remove'] && <button className="btn tertiary small" disabled={!!busy} onClick={() => void post('remove', `/v1/organization/members/${m.actor_id}/remove`, {})}>Remove</button>}
            </span>) : <span className="badge">{ROLE_WORDS[m.role]}</span>}
        </div>))}</div>}
      {(manage || org.policy.some(p => p.set)) && <>
        <h3 className="acc-sub">What the organization decides for its members</h3>
        <div className="org-row"><span>Members may use their own model key</span>
          <label className="check"><input type="checkbox" checked={ownKey?.value !== false} disabled={!manage || !!busy} onChange={e => void setPolicy('own_model_key', e.target.checked ? null : false)} />{ownKey?.value === false ? 'No' : 'Yes'}</label></div>
        <div className="org-row"><span>Tools members' assistants may use{allowed === null && <span className="faint"> · all of them</span>}</span>
          <span className="org-groups">{org.tool_groups.map(g => (
            <label key={g} className="check"><input type="checkbox" checked={allowed === null || allowed.includes(g)} disabled={!manage || !!busy}
              onChange={e => { const now = allowed ?? org.tool_groups; const next = e.target.checked ? [...new Set([...now, g])] : now.filter(x => x !== g); void setPolicy('tools_allowed', next.length === org.tool_groups.length ? null : next); }} />{GROUP_WORDS[g] ?? g}</label>))}</span></div>
        {!manage && <p className="faint">Set by your organization. Ask an owner or admin to change it.</p>}
      </>}
      {err && <p className="err" role="alert">{err}</p>}
    </section>);
}
