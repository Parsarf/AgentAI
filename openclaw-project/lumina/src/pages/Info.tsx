import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useEffect, useState } from 'react';
import { useData } from '../state/data';
import { useSettings } from '../state/settings';

function Soon({ name, what, needs }: { name: string; what: string; needs: string }) {
  return (
    <div className="center"><h1 className="page-title">{name}</h1>
      <section className="panel card"><h2>Not available yet</h2><p className="muted" style={{ marginTop: 8 }}>{what}</p>
        <p className="faint" style={{ marginTop: 10 }}>What it needs: {needs}</p>
        <p style={{ marginTop: 16 }}><Link className="btn" to="/">Back to Home</Link></p></section></div>);
}
export const Browser = () => <Soon name="Browser" what="A live view of the pages Lumina is working on, with the option to take over." needs="a connected live browser session for tasks (the isolated browser runs today, but is not yet streamed to this page)." />;
export const Calendar = () => <Soon name="Calendar" what="Your events and scheduled tasks in one place." needs="a calendar connection (Google/Microsoft sign-in is not registered yet) and recurring task scheduling." />;
export const Automations = () => <Soon name="Automations" what="Recurring tasks, triggers and approval gates." needs="the schedule engine to be switched on for customers; it is built but locked until the safety checks for unattended work pass." />;

export function Files() {
  const { app } = useData();
  if (!app?.features.files) return <Soon name="Files" what="Uploads, generated documents and saved outputs." needs="file storage to be enabled on the server (it is built but switched off)." />;
  return <Soon name="Files" what="File storage is on. The Lumina file browser is the next screen to build; the classic page works today." needs={'the new file screen. Use the classic page at /account/chat/ for now.'} />;
}

export function Integrations() {
  const { app } = useData();
  const [items, setItems] = useState<any[] | null>(null);
  useEffect(() => { api('GET', '/v1/account/connections').then(r => setItems(r.connections ?? [])).catch(() => setItems([])); }, []);
  return (
    <div className="center"><h1 className="page-title">Integrations</h1>
      <section className="panel card">
        {!app?.features.connectors && <p className="muted">Connecting Gmail, Calendar, Drive and GitHub is switched off for now.</p>}
        {items && items.length > 0 ? items.map((c, n) => <p key={n}>{String(c.provider ?? c.name ?? 'Connection')} · {String(c.status ?? 'connected')}</p>) : <p className="faint" style={{ marginTop: 8 }}>No services connected.</p>}
      </section></div>);
}

export function Settings() {
  const { app, signOut } = useData(); const s = useSettings();
  const [usage, setUsage] = useState<any>(null);
  useEffect(() => { api('GET', '/v1/costs').then(setUsage).catch(() => setUsage(null)); }, []);
  const usd = (m?: number) => (m == null ? '—' : `$${(m / 1e6).toFixed(2)}`);
  return (
    <div className="center"><h1 className="page-title">Settings</h1>
      <section className="panel card" style={{ marginBottom: 14 }}><h2>Appearance</h2>
        <p style={{ marginTop: 12 }}><label><input type="checkbox" checked={s.reducedMotion} onChange={e => s.setReducedMotion(e.target.checked)} /> Reduce motion (stops the planet and animations)</label></p>
        <p style={{ marginTop: 8 }}><label><input type="checkbox" checked={s.compact} onChange={e => s.setCompact(e.target.checked)} /> Compact layout</label></p></section>
      <section className="panel card" style={{ marginBottom: 14 }}><h2>Usage this period</h2>
        {usage ? <p className="muted" style={{ marginTop: 10 }}>Used {usd(usage.reported_microusd)} · held {usd(usage.held_microusd)} · remaining {usd(usage.period_remaining_microusd)} of {usd(usage.period_limit_microusd)}</p> : <p className="faint" style={{ marginTop: 10 }}>Usage is not available right now.</p>}
        <p className="faint" style={{ marginTop: 6 }}>Plan access: {app?.features.billing_mode === 'open' ? 'free access' : app?.features.billing_mode === 'paid_required' ? 'subscription' : 'invitation'}</p></section>
      <section className="panel card"><h2>Account</h2><p className="muted" style={{ marginTop: 10 }}>{app?.user.email}</p>
        <p style={{ marginTop: 12 }}><button className="btn" onClick={signOut}>Sign out</button> <a className="btn" href="/account/">Classic view</a></p></section></div>);
}
