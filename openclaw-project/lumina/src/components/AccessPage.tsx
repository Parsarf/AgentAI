import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { ago } from '../lib/format';
import { useData } from '../state/data';

interface Grant { resource_kind: string; resource_id: string; resource_name: string; access: 'read' | 'write' }
interface Fresh { resource_kind: string; resource_id: string; last_read_epoch: number | null; last_full_sync_epoch: number | null; item_count: number | null; last_error: string | null; stale: boolean }
export interface Connection {
  id: string; service: string; label: string; identity: string; state: string; needs_you: boolean; says: string; grants: Grant[]; can_be_limited: boolean; resource_kinds: string[];
  last_used_epoch: number | null; freshness: Fresh[]; kinds_of_change: { name: string; label: string; can_undo: boolean; rule: string }[];
  automatic_approvals: { kind: string; include_irreversible: boolean }[]; allowed_by_organization: boolean;
}
export interface AccessView {
  role: string | null; connections: Connection[];
  remote_tools: { id: string; name: string; recipient: string; state: string; enabled: boolean; tools_allowed: string[]; says: string }[];
  tools: { name: string; group: string | null; allowed: boolean; set_by_organization: boolean }[];
  saved_logins: { kind: string; label: string; site: string }[]; model_key: { host: string; hint: string } | null; own_model_key_allowed: boolean;
  memory: { count: number; where: string } | null; acts_without_you: { kind: string; name: string; state: string; pause_reason: string | null }[];
  waits: { kind: string; label: string; seconds: number }[]; set_by_organization: string[];
}
interface Offered { kind: string; id: string; name: string }

const TOOL_WORDS: Record<string, string> = { browser: 'Use a browser', files: 'Give you files', memory: 'Remember things', display: 'Show tables, charts and forms', location: 'Ask for your location',
  remote_tools: 'Use remote tools you connected', connectors: 'Read connected services and prepare changes' };
const ERROR_WORDS: Record<string, string> = { retry_later: 'the service was busy', needs_customer: 'it needs you', refused: 'it was not allowed', not_found: 'it was not found', conflict: 'the record had changed', invalid: 'the request was not accepted' };
export const length = (seconds: number) => (seconds >= 86400 ? `${Math.round(seconds / 86400)} day${Math.round(seconds / 86400) === 1 ? '' : 's'}` : `${Math.round(seconds / 60)} minutes`);
const failed = (e: unknown) => (e instanceof ApiError && e.status === 403 ? 'Your role or your organization does not allow this.' : e instanceof ApiError && e.status === 409 ? 'That is not possible right now.' : 'That did not go through. Please try again.');

/** Choosing what one connection may reach: the service's own list, nothing ticked until the customer ticks it. "Everything" is its own explicit choice per kind. */
function Picker({ connection, onSaved }: { connection: Connection; onSaved(next: Connection): void }) {
  const [offered, setOffered] = useState<Offered[] | null>(null); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const start = () => new Map(connection.grants.map(g => [`${g.resource_kind}|${g.resource_id}`, g.access]));
  const [chosen, setChosen] = useState<Map<string, 'read' | 'write'>>(start);
  const canChange = connection.kinds_of_change.length > 0;
  useEffect(() => { api<{ resources: Offered[] }>('GET', `/v1/integrations/${connection.id}/resources`).then(r => setOffered(r.resources)).catch(e => setErr(failed(e))); }, [connection.id]);
  const set = (key: string, access: 'read' | 'write' | null) => setChosen(prev => { const next = new Map(prev); if (access) next.set(key, access); else next.delete(key); return next; });
  const save = async () => {
    setBusy(true); setErr('');
    const names = new Map((offered ?? []).map(o => [`${o.kind}|${o.id}`, o.name]));
    const grants = [...chosen].map(([key, access]) => { const [kind, id] = [key.slice(0, key.indexOf('|')), key.slice(key.indexOf('|') + 1)]; return { kind, id, access, name: id === '*' ? '' : names.get(key) ?? '' }; });
    try { onSaved((await api<{ connection: Connection }>('POST', `/v1/integrations/${connection.id}/grants`, { grants })).connection); }
    catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };
  if (!offered) return <p className="faint" role="status">{err || 'Loading what this service offers…'}</p>;
  const row = (key: string, label: string) => (
    <li key={key} className="acc-pick-row">
      <label className="check"><input type="checkbox" checked={chosen.has(key)} disabled={busy} onChange={e => set(key, e.target.checked ? 'read' : null)} />{label}</label>
      {canChange && chosen.has(key) && (
        <label className="acc-pick-write"><input type="checkbox" checked={chosen.get(key) === 'write'} disabled={busy} onChange={e => set(key, e.target.checked ? 'write' : 'read')} />may prepare changes here</label>)}
    </li>);
  return (
    <div className="acc-pick" role="group" aria-label={`What ${connection.label} may reach`}>
      <p className="muted">Nothing is reachable until you tick it. Changes are always shown to you for approval first.</p>
      {connection.resource_kinds.map(kind => (
        <ul key={kind} className="acc-pick-list">
          {row(`${kind}|*`, `Everything (every ${kind}, including ones added later)`)}
          {!chosen.has(`${kind}|*`) && offered.filter(o => o.kind === kind).map(o => row(`${o.kind}|${o.id}`, o.name))}
        </ul>))}
      {err && <p className="err" role="alert">{err}</p>}
      <div className="int-row"><button className="btn" disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save what it can reach'}</button></div>
    </div>);
}

function ConnectionCard({ connection, writes, onChanged, onRemoved }: { connection: Connection; writes: boolean; onChanged(next: Connection): void; onRemoved(): void }) {
  const [picking, setPicking] = useState(false); const [busy, setBusy] = useState(''); const [err, setErr] = useState(''); const [confirm, setConfirm] = useState(false);
  const remove = async () => {
    setBusy('remove'); setErr('');
    try { await api('POST', `/v1/integrations/${connection.id}/remove`, {}); onRemoved(); } catch (e) { setErr(failed(e)); setBusy(''); }
  };
  const auto = async (kind: string, enabled: boolean, irreversible: boolean) => {
    setBusy(kind); setErr('');
    try {
      const r = await api<{ automatic_approvals: Connection['automatic_approvals'] }>('POST', `/v1/integrations/${connection.id}/auto-approve`, { kind, enabled, include_irreversible: irreversible });
      onChanged({ ...connection, automatic_approvals: r.automatic_approvals });
    } catch (e) { setErr(failed(e)); } finally { setBusy(''); }
  };
  return (
    <li className="acc-card" data-state={connection.state}>
      <header className="acc-head"><div><strong>{connection.label}</strong><span className="faint"> · {connection.identity}</span></div>
        {connection.needs_you ? <span className="badge warning">Needs you: reconnect it</span> : !connection.allowed_by_organization ? <span className="badge warning">Not allowed by your organization</span> : <span className="badge alt">Connected</span>}</header>
      <p className="acc-says">{connection.says}</p>
      <p className="faint">{connection.last_used_epoch ? `Last used ${ago(connection.last_used_epoch)}.` : 'Not used yet.'}</p>
      {connection.freshness.length > 0 && (
        <ul className="acc-fresh" aria-label="How fresh its data is">{connection.freshness.map(f => (
          <li key={`${f.resource_kind}|${f.resource_id}`}>{f.resource_kind} “{f.resource_id}”: {f.last_read_epoch ? `as of ${ago(f.last_read_epoch)}` : 'not read yet'}
            {f.last_full_sync_epoch ? `, read completely ${ago(f.last_full_sync_epoch)}${f.item_count != null ? ` (${f.item_count} items)` : ''}` : ''}
            {f.stale && <span className="badge warning"> older than its limit</span>}{f.last_error && <span className="faint"> · last problem: {ERROR_WORDS[f.last_error] ?? 'a problem'}</span>}</li>))}</ul>)}
      {writes && connection.kinds_of_change.length > 0 && (
        <details className="acc-more"><summary>Changes it can prepare ({connection.kinds_of_change.length})</summary>
          <ul className="acc-kinds">{connection.kinds_of_change.map(k => {
            const on = connection.automatic_approvals.find(a => a.kind === k.name); const locked = k.rule !== 'allowed';
            return (
              <li key={k.name}><span>{k.label}{!k.can_undo && <span className="faint"> · cannot be taken back</span>}</span>
                {k.rule === 'blocked' ? <span className="faint">Blocked by your organization</span> : k.rule === 'admin_approval' ? <span className="faint">Needs an admin as well (set by your organization)</span> : (
                  <label className="check"><input type="checkbox" checked={!!on} disabled={!!busy || locked}
                    onChange={e => void auto(k.name, e.target.checked, !k.can_undo)} />{k.can_undo ? 'Go ahead without asking me' : 'Go ahead without asking me, even though it cannot be taken back'}</label>)}
              </li>);
          })}</ul>
          <p className="faint">Unless you tick a kind here, every change is shown to you first and waits for your approval.</p></details>)}
      {picking && connection.can_be_limited && <Picker connection={connection} onSaved={next => { onChanged(next); setPicking(false); }} />}
      {err && <p className="err" role="alert">{err}</p>}
      <div className="int-row">
        {connection.can_be_limited && <button className="btn" disabled={!!busy} onClick={() => setPicking(p => !p)}>{picking ? 'Close' : 'Choose what it can reach'}</button>}
        {confirm ? <><span className="muted">Remove it? Its access ends at once.</span><button className="btn danger" disabled={!!busy} onClick={() => void remove()}>{busy === 'remove' ? 'Removing…' : 'Yes, remove'}</button>
          <button className="btn tertiary" disabled={!!busy} onClick={() => setConfirm(false)}>Keep it</button></>
          : <button className="btn tertiary" disabled={!!busy} onClick={() => setConfirm(true)}>Remove</button>}
      </div>
    </li>);
}

interface Change { id: string; state: string; preview: { summary: string; destination: string }; can_undo: boolean; undo_until_epoch: number | null; compensations: string[]; verified: boolean | null; verify_note: string | null; ended_words: string; executed_epoch: number | null; undo_of: string | null; compensates: string | null }
const STATE_WORDS: Record<string, string> = { proposed: 'Waiting for your approval', approved: 'Approved, being made', executing: 'Being made', uncertain: 'Being checked', done: 'Done', failed: 'Not made', undone: 'Undone',
  compensated: 'Followed by its correction', expired: 'Expired, nothing was done', declined: 'Declined' };

/** What Lumina changed in connected services, newest first, with what can still be taken back. Undo and a follow-up are themselves changes: they are prepared here and then wait
 *  for approval like any other (in Activity, under "Needs you"). */
export function RecentChanges() {
  const [changes, setChanges] = useState<Change[] | null>(null); const [busy, setBusy] = useState(''); const [note, setNote] = useState(''); const [err, setErr] = useState('');
  const load = useCallback(() => api<{ actions: Change[] }>('GET', '/v1/actions').then(r => setChanges(r.actions)).catch(() => setChanges([])), []);
  useEffect(() => { void load(); }, [load]);
  const prepare = async (change: Change, path: string, body: unknown) => {
    setBusy(change.id); setErr(''); setNote('');
    try { await api('POST', `/v1/actions/${change.id}/${path}`, body); setNote('Prepared. It is waiting for your approval in Activity, under "Needs you".'); await load(); }
    catch (e) { setErr(failed(e)); } finally { setBusy(''); }
  };
  if (!changes || changes.length === 0) return null;
  const now = Date.now() / 1000;
  return (
    <section className="panel card set-card" aria-labelledby="acc-changes-h">
      <h2 id="acc-changes-h">Recent changes in connected services</h2>
      <ul className="acc-list">{changes.slice(0, 10).map(c => {
        const taken = changes.some(o => (o.undo_of === c.id || o.compensates === c.id) && !['failed', 'expired', 'declined'].includes(o.state));
        return (
          <li key={c.id} className="acc-card"><header className="acc-head"><strong>{c.preview.summary}</strong><span className="badge">{STATE_WORDS[c.state] ?? c.state}</span></header>
            <p className="faint">{c.preview.destination}{c.executed_epoch ? ` · ${ago(c.executed_epoch)}` : ''}</p>
            {c.state === 'done' && c.verified === false && <p className="err" role="note">Checked afterwards: {c.verify_note}.</p>}
            {c.state === 'failed' && c.ended_words && <p className="muted">{c.ended_words}</p>}
            {c.state === 'done' && !taken && (
              <div className="int-row">
                {c.can_undo && c.undo_until_epoch && c.undo_until_epoch > now && <button className="btn small" disabled={!!busy} onClick={() => void prepare(c, 'undo', {})}>Undo</button>}
                {c.compensations.map(k => <button key={k} className="btn small" disabled={!!busy} onClick={() => void prepare(c, 'compensate', { kind: k })}>Send a correction</button>)}
              </div>)}
          </li>);
      })}</ul>
      {note && <p className="muted" role="status">{note}</p>}{err && <p className="err" role="alert">{err}</p>}
    </section>);
}

/** Settings > Access: "What your assistant can access". Every line is the server's own picture, generated from the records it enforces: connections with what each may reach and how
 *  fresh its data is, remote tools, the tools the assistant has, saved logins (names only), the model key (host and last four characters), memory, and what acts without you. */
export default function AccessPage() {
  const app = (useData() as ReturnType<typeof useData> | null)?.app;
  const [view, setView] = useState<AccessView | null>(null); const [available, setAvailable] = useState<{ service: string; label: string; disclosure: string }[]>([]);
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(async () => {
    try {
      const [controls, services] = await Promise.all([api<AccessView>('GET', '/v1/controls'), api<{ available: typeof available }>('GET', '/v1/integrations').catch(() => ({ available: [] }))]);
      if (alive.current) { setView(controls); setAvailable(services.available); }
    } catch { if (alive.current) setErr('This page could not be loaded. Try again.'); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const connectTest = async () => {
    setBusy(true); setErr('');
    try { await api('POST', '/v1/integrations/synthetic/connect', {}); await load(); } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };
  if (!view) return <section className="panel card set-card"><p className="faint" role="status">{err || 'Loading…'}</p></section>;
  const replace = (next: Connection) => setView(v => v && { ...v, connections: v.connections.map(c => (c.id === next.id ? next : c)) });
  const groups = [...new Set(view.tools.map(t => t.group).filter((g): g is string => !!g))];
  const offerTest = available.some(a => a.service === 'synthetic') && !view.connections.some(c => c.service === 'synthetic');
  return <>
    <section className="panel card set-card" aria-labelledby="acc-conn-h">
      <div className="set-head"><h2 id="acc-conn-h">Connected services</h2><span className="badge alt">{view.connections.length + view.remote_tools.length}</span></div>
      <p className="muted">What your assistant can reach outside Lumina. A new connection can reach nothing until you choose what; you can remove one at any time.</p>
      {view.connections.length === 0 && view.remote_tools.length === 0 && <p className="faint">Nothing is connected.</p>}
      <ul className="acc-list">
        {view.connections.map(c => <ConnectionCard key={c.id} connection={c} writes={!!app?.features.connector_writes} onChanged={replace} onRemoved={() => void load()} />)}
        {view.remote_tools.map(r => (
          <li key={r.id} className="acc-card"><header className="acc-head"><div><strong>{r.name}</strong><span className="faint"> · {r.recipient}</span></div><span className="badge alt">{r.enabled ? 'Connected' : 'Off'}</span></header>
            <p className="acc-says">{r.says}</p>{r.tools_allowed.length > 0 && <p className="faint">Allowed: {r.tools_allowed.join(', ')}</p>}
            <p className="faint">Manage it in Integrations.</p></li>))}
      </ul>
      {offerTest && <div className="int-row"><button className="btn" disabled={busy} onClick={() => void connectTest()}>{busy ? 'Connecting…' : 'Connect the test service'}</button><span className="faint">A fake service inside Lumina, for testing.</span></div>}
      {err && <p className="err" role="alert">{err}</p>}
    </section>
    {app?.features.connector_writes && <RecentChanges />}
    <section className="panel card set-card" aria-labelledby="acc-tools-h">
      <h2 id="acc-tools-h">What your assistant can do</h2>
      <ul className="acc-plain">{groups.map(g => { const tools = view.tools.filter(t => t.group === g); const off = tools.every(t => !t.allowed); const org = tools.some(t => t.set_by_organization);
        return <li key={g}>{TOOL_WORDS[g] ?? g}{off && <span className="faint"> · {org ? 'switched off by your organization' : 'not available to your role'}</span>}</li>; })}</ul>
    </section>
    <section className="panel card set-card" aria-labelledby="acc-kept-h">
      <h2 id="acc-kept-h">What it holds for you</h2>
      <dl className="set-facts">
        <div><dt>Saved logins and cards</dt><dd>{view.saved_logins.length ? view.saved_logins.map(s => s.label || s.site).join(', ') : 'None'}</dd></div>
        <div><dt>Your own model key</dt><dd>{!view.own_model_key_allowed ? 'Not allowed by your organization' : view.model_key ? `${view.model_key.host}, key ending ${view.model_key.hint}` : 'None'}</dd></div>
        <div><dt>Long-term memory</dt><dd>{view.memory ? `${view.memory.count} note${view.memory.count === 1 ? '' : 's'} (${view.memory.where})` : 'Off'}</dd></div>
      </dl>
    </section>
    <section className="panel card set-card" aria-labelledby="acc-auto-h">
      <h2 id="acc-auto-h">What acts without you</h2>
      {view.acts_without_you.length === 0 ? <p className="faint">Nothing runs on a schedule or by itself.</p>
        : <ul className="acc-plain">{view.acts_without_you.map(a => <li key={`${a.kind}-${a.name}`}>{a.kind === 'schedule' ? 'Schedule' : 'Watcher'} “{a.name}”: {a.state}{a.pause_reason ? ` (${a.pause_reason})` : ''}</li>)}</ul>}
      <h3 className="acc-sub">How long Lumina waits for you</h3>
      <ul className="acc-plain">{view.waits.map(w => <li key={w.kind}>{w.label}: {length(w.seconds)}. Then it ends and nothing is done.</li>)}</ul>
    </section>
  </>;
}
