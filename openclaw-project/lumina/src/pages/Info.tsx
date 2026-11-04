import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useEffect, useState } from 'react';
import { useData } from '../state/data';
import Toggle from '../components/ui/Toggle';
import { useSettings } from '../state/settings';
import { STYLES, STYLE_INFO, useAnswerStyle } from '../lib/answerStyle';
import Credits from '../components/Credits';
import YourBrowser from '../components/YourBrowser';
import OwnModel from '../components/OwnModel';
import MemoryNotes from '../components/MemoryNotes';
import McpConnections from '../components/McpConnections';
import ServiceIcon from '../components/ServiceIcon';

function Soon({ name, what, needs }: { name: string; what: string; needs: string }) {
  return (
    <div className="center"><h1 className="page-title">{name}</h1>
      <section className="panel card"><h2>Not available yet</h2><p className="muted" style={{ marginTop: 8 }}>{what}</p>
        <p className="faint" style={{ marginTop: 10 }}>What it needs: {needs}</p>
        <p style={{ marginTop: 16 }}><Link className="btn" to="/">Back to Home</Link></p></section></div>);
}
export const Calendar = () => <Soon name="Calendar" what="Your events and scheduled tasks in one place." needs="a calendar connection (Google/Microsoft sign-in is not registered yet) and recurring task scheduling." />;
export const Automations = () => <Soon name="Automations" what="Recurring tasks, triggers and approval gates." needs="the schedule engine to be switched on for customers; it is built but locked until the safety checks for unattended work pass." />;

const BUILT_IN = [{ key: 'gmail', label: 'Gmail', match: /gmail|mail/i }, { key: 'calendar', label: 'Calendar', match: /calendar/i }, { key: 'drive', label: 'Drive', match: /drive/i }, { key: 'github', label: 'GitHub', match: /github/i }] as const;

export function Integrations() {
  const { app } = useData();
  const [items, setItems] = useState<any[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { api('GET', '/v1/account/connections').then(r => setItems(r.connections ?? [])).catch(() => setItems([])); }, []);
  /* The API lists every service Lumina knows with a `state`; a tile only shows a green dot when that service is really connected. */
  const stateOf = (match: RegExp) => (items ?? []).find(c => match.test(String(c.service ?? c.label ?? '')));
  const mcp = !!app?.features.mcp;
  return (
    <div className="center">
      <header className="page-head"><div><h1>Integrations</h1><p>Connect the tools you use with Lumina.</p></div>
        {mcp && <button className="btn primary large" onClick={() => setAdding(true)}>Choose a service</button>}</header>
      {mcp && <div className="sec"><McpConnections adding={adding} onAdding={setAdding} /></div>}
      <section className="sec" aria-labelledby="builtin-h"><div className="sec-head"><h2 id="builtin-h">Built-in integrations</h2></div>
        <div className="tiles">{BUILT_IN.map(b => { const c = stateOf(b.match); const on = c?.state === 'connected';
          return <button key={b.key} type="button" className={`tile${on ? '' : ' muted'}`} aria-label={`${b.label}, ${on ? 'connected' : 'not connected'}`} onClick={() => setNote(on ? `${b.label} is connected${c?.identity ? ` as ${String(c.identity)}` : ''}.` : app?.features.connectors ? `${b.label} is not connected yet.` : `Connecting ${b.label} is switched off for now.`)}>
            <span className="tile-art"><ServiceIcon name={b.label} kind={b.key} /><i className={`dot ${on ? 'success' : 'idle'}`} /></span><span className="tile-label">{b.label}</span></button>; })}</div>
        {note && <p className="notice" role="status" style={{ marginTop: 16 }}>{note}</p>}</section>
    </div>);
}

export function Settings() {
  const { app, signOut } = useData(); const s = useSettings(); const [style, setStyle] = useAnswerStyle();
  const [usage, setUsage] = useState<any>(null);
  useEffect(() => { api('GET', '/v1/costs').then(setUsage).catch(() => setUsage(null)); }, []);
  const usd = (m?: number) => (m == null ? '—' : `$${(m / 1e6).toFixed(2)}`);
  return (
    <div className="center"><h1 className="page-title">Settings</h1>
      <section className="panel card" style={{ marginBottom: 14 }}><h2>Appearance</h2>
        <div className="toggle-list"><Toggle label="Reduce motion" hint="Stops the planet and animations" checked={s.reducedMotion} onChange={s.setReducedMotion} />
          <Toggle label="Compact layout" hint="Tighter spacing throughout" checked={s.compact} onChange={s.setCompact} /></div></section>
      <section className="panel card" style={{ marginBottom: 14 }} aria-labelledby="answer-style-h"><h2 id="answer-style-h">Answer style</h2>
        <p className="muted">How much interface Lumina may put in an answer. Longer instructions cost a little more on every message.</p>
        <div className="style-choices" role="radiogroup" aria-labelledby="answer-style-h">{STYLES.map(k => <label key={k} className={`style-choice${style === k ? ' on' : ''}`}><input type="radio" name="answer-style" value={k} checked={style === k} onChange={() => setStyle(k)} /><span>{STYLE_INFO[k].label}</span></label>)}</div>
        <p className="muted" aria-live="polite">{STYLE_INFO[style].hint}</p>
        <p className="muted">Ultra (generated code in a sandbox) is planned and not available.</p></section>
      <section className="panel card" style={{ marginBottom: 14 }}><h2>Usage this period</h2>
        {usage ? <p className="muted" style={{ marginTop: 10 }}>Used {usd(usage.reported_microusd)} · held {usd(usage.held_microusd)} · remaining {usd(usage.period_remaining_microusd)} of {usd(usage.period_limit_microusd)}</p> : <p className="faint" style={{ marginTop: 10 }}>Usage is not available right now.</p>}
        <p className="faint" style={{ marginTop: 6 }}>Plan access: {app?.features.billing_mode === 'open' ? 'free access' : app?.features.billing_mode === 'paid_required' ? 'subscription' : 'invitation'}</p></section>
      <YourBrowser />
      <OwnModel />
      <MemoryNotes />
      <Credits />
      <section className="panel card"><h2>Account</h2><p className="muted" style={{ marginTop: 10 }}>{app?.user.email}</p>
        <p style={{ marginTop: 12 }}><button className="btn" onClick={signOut}>Sign out</button> <a className="btn" href="/account/">Classic view</a></p></section></div>);
}
