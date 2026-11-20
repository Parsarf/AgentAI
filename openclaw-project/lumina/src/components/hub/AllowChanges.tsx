import { useState } from 'react';
import { failed, hub, type HubAccount } from '../../lib/hub';

/** Where the provider can make a change but this account has not allowed it yet (roadmap Phase 6): what the permission allows, in words, and the one button that asks for it
 *  at the provider. Nothing changes here: the provider shows what is asked, and the customer comes back to the same account with the permission added. */
export default function AllowChanges({ account, capability }: { account: HubAccount; capability: string }) {
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const name = account.capabilities.missing?.[capability];
  const grant = account.grants?.find(g => g.name === name);
  if (!name || !grant) return null;
  const ask = async () => {
    setBusy(true); setErr('');
    try { window.location.assign((await hub.allow(account, [name])).authorize_url); } catch (e) { setErr(failed(e)); setBusy(false); }
  };
  return (
    <div className="notice" role="note" aria-label={`Allow changes for ${account.identity}`}>
      <p className="small">{grant.words}</p>
      <button type="button" className="btn small" onClick={ask} disabled={busy}>Allow changes for {account.identity}</button>
      {err && <p className="notice warning small" role="alert">{err}</p>}
    </div>);
}
