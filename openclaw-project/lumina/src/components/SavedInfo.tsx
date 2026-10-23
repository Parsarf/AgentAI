import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';

interface Item { id: string; kind: 'login' | 'card'; label: string; site: string; hint: string }
interface Vault { enabled: boolean; items: Item[] }
interface Choice { field: string; value: string }

/** The notice shown before anything sensitive is kept. Plain words, what is kept, where, who can see it, how to remove it. */
export const NOTICE = [
  'Lumina keeps this encrypted, on its own server, tied to your account only.',
  'It is never shown to the AI models or to JEV. Lumina types it into the website for you, and only after you approve each use.',
  'The card security code (the 3 or 4 digits) is never saved: you type it yourself each time.',
  'You can delete it here at any time. Deleting removes it for good.',
];

export default function SavedInfo() {
  const [vault, setVault] = useState<Vault | null>(null); const [choices, setChoices] = useState<Choice[]>([]);
  const [adding, setAdding] = useState<'login' | 'card' | null>(null); const [asking, setAsking] = useState(false); const [accepted, setAccepted] = useState(false);
  const [f, setF] = useState<Record<string, string>>({}); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setVault(await api<Vault>('GET', '/v1/vault')); } catch { setVault({ enabled: false, items: [] }); }
    try { setChoices((await api<{ saved: Choice[] }>('GET', '/v1/saved')).saved); } catch { setChoices([]); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF(old => ({ ...old, [k]: e.target.value }));
  const close = () => { setAdding(null); setAsking(false); setAccepted(false); setF({}); setErr(''); };
  const save = async () => {
    if (!adding || !accepted) return;
    setBusy(true); setErr('');
    const secret = adding === 'card'
      ? { number: (f.number ?? '').replace(/[\s-]/g, ''), exp_month: Number(f.month), exp_year: Number(f.year), name: f.name ?? '' }
      : { username: f.username ?? '', password: f.password ?? '' };
    try { await api('POST', '/v1/vault/add', { kind: adding, secret, site: adding === 'login' ? f.site ?? '' : '', accepted: true }); close(); await load(); }
    catch (e) { setErr(e instanceof ApiError && e.status === 409 ? 'Saving is not switched on yet.' : 'That was not accepted. Check the details and try again.'); }
    setBusy(false);
  };
  const remove = async (path: string) => { try { await api('POST', path, {}); } catch { /* the list reload below shows what is left */ } await load(); };
  const ready = adding === 'card' ? !!(f.number && f.month && f.year) : !!(f.site && f.username && f.password);

  return (
    <section className="panel card" style={{ marginBottom: 14 }} aria-label="Saved info"><h2>Saved info</h2>
      <p className="muted" style={{ marginTop: 8 }}>What Lumina remembers so jobs go faster. You choose every item, and you can remove any of it.</p>
      {choices.length > 0 && <>
        <h3 className="saved-h">Choices</h3>
        <ul className="saved-list">{choices.map(c => <li key={c.field}><span>{c.field}: {c.value}</span><button className="btn small" onClick={() => remove(`/v1/saved/${encodeURIComponent(c.field)}/forget`)} aria-label={`Forget ${c.field}`}>Forget</button></li>)}</ul></>}
      <h3 className="saved-h">Logins and cards</h3>
      {vault && !vault.enabled && <p className="faint">Saving logins and cards is not switched on yet.</p>}
      {vault?.enabled && vault.items.length === 0 && <p className="faint">Nothing saved.</p>}
      {vault && vault.items.length > 0 && <ul className="saved-list">{vault.items.map(i => <li key={i.id}><span>{i.label}{i.hint && i.hint !== i.label ? ` · ${i.hint}` : ''}</span><button className="btn small danger" onClick={() => remove(`/v1/vault/${i.id}/delete`)} aria-label={`Delete ${i.label}`}>Delete</button></li>)}</ul>}
      {vault?.enabled && !adding && <p className="saved-add"><button className="btn" onClick={() => setAdding('login')}>Add a login</button> <button className="btn" onClick={() => setAdding('card')}>Add a card</button></p>}
      {adding && !asking && (
        <form className="saved-form" autoComplete="off" onSubmit={e => { e.preventDefault(); if (ready) setAsking(true); }}>
          {adding === 'login' ? <>
            <label>Website<input value={f.site ?? ''} onChange={set('site')} placeholder="shop.example.com" autoComplete="off" /></label>
            <label>Username or email<input value={f.username ?? ''} onChange={set('username')} autoComplete="off" /></label>
            <label>Password<input type="password" value={f.password ?? ''} onChange={set('password')} autoComplete="new-password" /></label></> : <>
            <label>Name on card<input value={f.name ?? ''} onChange={set('name')} autoComplete="off" /></label>
            <label>Card number<input inputMode="numeric" value={f.number ?? ''} onChange={set('number')} autoComplete="off" /></label>
            <label>Expiry month<input inputMode="numeric" value={f.month ?? ''} onChange={set('month')} placeholder="MM" maxLength={2} autoComplete="off" /></label>
            <label>Expiry year<input inputMode="numeric" value={f.year ?? ''} onChange={set('year')} placeholder="YYYY" maxLength={4} autoComplete="off" /></label>
            <p className="faint">The security code is not asked for and never saved.</p></>}
          <p><button className="btn primary" type="submit" disabled={!ready}>Continue</button> <button className="btn" type="button" onClick={close}>Cancel</button></p>
        </form>)}
      {adding && asking && (
        <div className="saved-notice" role="dialog" aria-modal="true" aria-label="Before you save">
          <h3>Before you save this</h3>
          <ul>{NOTICE.map(line => <li key={line}>{line}</li>)}</ul>
          <label className="ask-remember"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} />I understand and want Lumina to keep this</label>
          {err && <p className="err small" role="alert">{err}</p>}
          <p><button className="btn primary" disabled={!accepted || busy} onClick={save}>Save</button> <button className="btn" onClick={() => setAsking(false)}>Back</button> <button className="btn" onClick={close}>Cancel</button></p>
        </div>)}
    </section>);
}
