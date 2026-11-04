import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import './approval.css';

interface Pending { id: string; connection_id: string; tool_name: string; arguments: unknown; state: string }
interface Service { id: string; name: string; recipient: string }
interface Listing { pending_calls?: Pending[]; connections?: Service[] }

const words = (tool: string) => { const t = tool.replace(/[_-]+/g, ' ').trim(); return t ? t[0].toUpperCase() + t.slice(1) : 'a tool'; };
const short = (v: unknown) => { const s = typeof v === 'string' ? v : JSON.stringify(v); return s.length > 48 ? s.slice(0, 47) + '…' : s; };
/** One quiet line: the first few arguments, so the customer can see at a glance what is being asked. */
export const summary = (args: unknown) => {
  if (!args || typeof args !== 'object' || Array.isArray(args)) return '';
  const entries = Object.entries(args as Record<string, unknown>);
  return entries.slice(0, 3).map(([k, v]) => `${k}: ${short(v)}`).join(' · ') + (entries.length > 3 ? ` · +${entries.length - 3} more` : '');
};

/** The permission prompt for a remote tool call, shown in the chat itself. The decision is made by the customer's own signed-in click on the real approval endpoint (the
 *  assistant cannot make it for them); Lumina's rules for what an approval covers (this exact call, ten minutes, one use) are enforced by the server, not here. */
export default function ToolApproval({ active, onDecided }: { active: boolean; onDecided: (approved: boolean, tool: string) => void | Promise<void> }) {
  const [calls, setCalls] = useState<Pending[]>([]); const [services, setServices] = useState<Service[]>([]);
  const [busy, setBusy] = useState(''); const [done, setDone] = useState<Record<string, boolean>>({}); const [err, setErr] = useState('');
  const alive = useRef(true); useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const load = useCallback(async () => {
    try {
      const data = await api<Listing>('GET', '/v1/account/mcp');
      if (!alive.current) return;
      setCalls((data.pending_calls ?? []).filter(c => c.state === 'pending')); setServices(data.connections ?? []);
    } catch { /* the card is a convenience: the Integrations page still lists the same calls */ }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (!active) { const t = setTimeout(() => { void load(); }, 1200); return () => clearTimeout(t); } const t = setInterval(() => { void load(); }, 2500); return () => clearInterval(t); }, [active, load]);

  const decide = async (call: Pending, approved: boolean) => {
    setBusy(call.id); setErr('');
    try {
      await api('POST', `/v1/account/mcp-approvals/${call.id}`, { approved });
      setDone(d => ({ ...d, [call.id]: approved })); await onDecided(approved, call.tool_name);
    } catch { setErr('That did not go through. Please try again.'); }
    finally { if (alive.current) { setBusy(''); void load(); } }
  };
  const shown = calls.filter(c => !(c.id in done));
  const decided = Object.entries(done);
  if (!shown.length && !decided.length) return null;
  return <div className="approvals" aria-live="polite">
    {shown.map(call => {
      const service = services.find(s => s.id === call.connection_id); const line = summary(call.arguments);
      return <section className="approval" key={call.id} role="group" aria-label={`Permission to use ${words(call.tool_name)}`}>
        <span className="approval-mark" aria-hidden="true" />
        <div className="approval-body">
          <p className="approval-title">Lumina wants to use <strong>{words(call.tool_name)}</strong>{service && <> on <strong>{service.name}</strong></>}</p>
          {line && <p className="approval-line" title={line}>{line}</p>}
          <details className="approval-more"><summary>See the exact request</summary><pre tabIndex={0}>{JSON.stringify(call.arguments, null, 2)}</pre><p>{service?.recipient ?? 'Connected service'}. Allows this one request, for ten minutes.</p></details>
        </div>
        <div className="approval-actions">
          <button className="btn tertiary small" disabled={!!busy} onClick={() => void decide(call, false)}>Cancel</button>
          <button className="btn primary small" disabled={!!busy} onClick={() => void decide(call, true)}>{busy === call.id ? 'Allowing…' : 'Allow'}</button>
        </div>
      </section>;
    })}
    {decided.slice(-1).map(([id, ok]) => <p className="approval-done" key={id}>{ok ? 'Allowed. Continuing…' : 'Declined. Nothing was run.'}</p>)}
    {err && <p className="err" role="alert">{err}</p>}
  </div>;
}
