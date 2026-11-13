import { useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { argumentLine, toolWords, type Approval } from '../../lib/work';
import { useWorkClient } from '../../state/work';

/** A permission prompt for one exact tool call. The decision is the customer's own signed-in click on the approval route (the assistant cannot make it); what an approval covers
 *  (this exact call, ten minutes, one use) is enforced by the server. Lumina then tells the assistant by itself: nothing is typed or sent in the customer's name. */
export default function Permission({ call }: { call: Approval }) {
  const client = useWorkClient();
  const [busy, setBusy] = useState<'' | 'allow' | 'decline'>(''); const [err, setErr] = useState(''); const [note, setNote] = useState('');
  const line = argumentLine(call.arguments);
  const decide = async (approved: boolean) => {
    setBusy(approved ? 'allow' : 'decline'); setErr('');
    try {
      const r = await api<{ continued?: boolean }>('POST', `/v1/account/mcp-approvals/${call.id}`, { approved });
      if (!r.continued) setNote(approved ? 'Allowed. Send a message to carry on.' : 'Declined. Nothing was run.');
      await client.refresh();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 409 ? 'This request is no longer waiting. It may have expired.' : 'That did not go through. Please try again.');
      await client.refresh();
    } finally { setBusy(''); }
  };
  if (note) return <p className="wk-permission-done" role="status">{note}</p>;
  return (
    <section className="wk-permission" role="group" aria-label={`Permission to use ${toolWords(call.tool)}`}>
      <div className="wk-permission-body">
        <p className="wk-permission-title">Lumina wants to use <strong>{toolWords(call.tool)}</strong>{call.service && <> on <strong>{call.service}</strong></>}</p>
        {line && <p className="wk-permission-line" title={line}>{line}</p>}
        <details className="wk-permission-more"><summary>See the exact request</summary><pre tabIndex={0}>{JSON.stringify(call.arguments, null, 2)}</pre>
          <p>Allowing covers this one request only, for ten minutes.</p></details>
        {err && <p className="err" role="alert">{err}</p>}
      </div>
      <div className="wk-permission-actions">
        <button className="btn tertiary small" disabled={!!busy} onClick={() => void decide(false)}>{busy === 'decline' ? 'Declining…' : 'Decline'}</button>
        <button className="btn primary small" disabled={!!busy} onClick={() => void decide(true)}>{busy === 'allow' ? 'Allowing…' : 'Allow'}</button>
      </div>
    </section>);
}
