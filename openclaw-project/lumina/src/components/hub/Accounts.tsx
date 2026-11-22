import { ago, type HubAccount, type SyncPart } from '../../lib/hub';
import { AddAccount, Reconnect, type Provider } from './Connect';

export const REASON_WORDS: Record<string, string> = { reconnect: 'It needs to be connected again.', consent: 'It needs a permission it does not have.' };

/** One line about how current an account's mail or calendar is. An account that needs its customer says so; what was synced before stays on screen with its age. */
export function freshness(account: HubAccount, part: SyncPart | null, now: number): string {
  if (account.state === 'needs_you') return part?.synced_epoch ? `Needs you. Last updated ${ago(part.synced_epoch, now)}.` : 'Needs you.';
  if (!part) return 'Nothing chosen to show yet.';
  if (!part.filled) return part.items ? `Loading… ${part.items} so far.` : 'Loading for the first time…';
  if (part.error) return `Could not update. Last updated ${ago(part.synced_epoch, now)}.`;
  return `Updated ${ago(part.synced_epoch, now)}.`;
}

/** The accounts on the left of the Inbox and the Calendar: which are shown, which work, how fresh each is. The provider is shown as its name only; nothing here decides by it. */
export default function Accounts({ accounts, part, chosen, onToggle, counts, now, providers, onChoose }: { accounts: HubAccount[]; part: 'mail' | 'calendar'; chosen: Set<string>; onToggle(id: string): void;
  counts?: Record<string, number>; now: number; providers?: Provider[]; onChoose?(account: HubAccount): void }) {
  const mine = accounts.filter(a => a.capabilities[part]);
  return (
    <section className="hub-accounts" aria-label="Accounts">
      <h2 className="hub-side-title">Accounts</h2>
      {mine.map(a => (
        <label key={a.id} className={`hub-account${a.state === 'needs_you' ? ' needs' : ''}`}>
          <input type="checkbox" checked={chosen.has(a.id)} onChange={() => onToggle(a.id)} />
          <span className="hub-account-text"><b title={a.identity}>{a.identity}</b>
            <span className="faint small">{a.provider_label} · {freshness(a, a[part], now)}</span>
            {a.state === 'needs_you' && <span className="hub-account-needs small">{REASON_WORDS[a.needs_reason ?? ''] ?? 'It needs your attention.'} <Reconnect account={a} /></span>}
            {a.state === 'working' && !a.granted[part] && onChoose && <button type="button" className="btn small tertiary hub-inline" onClick={e => { e.preventDefault(); onChoose(a); }}>Choose what to read</button>}</span>
          {!!counts?.[a.id] && <span className="badge accent" aria-label={`${counts[a.id]} unread`}>{counts[a.id]}</span>}
        </label>))}
      <AddAccount providers={providers ?? []} />
    </section>);
}
