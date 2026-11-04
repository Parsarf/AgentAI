import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useEffect, useState } from 'react';
import { useData } from '../state/data';
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

export { Settings } from './Settings';
