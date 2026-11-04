import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { useData } from '../state/data';
import Toggle from '../components/ui/Toggle';
import { useSettings } from '../state/settings';
import { STYLES, STYLE_INFO, useAnswerStyle } from '../lib/answerStyle';
import Credits from '../components/Credits';
import YourBrowser from '../components/YourBrowser';
import OwnModel from '../components/OwnModel';
import MemoryNotes from '../components/MemoryNotes';
import '../components/settings.css';

const TABS = [{ id: 'general', label: 'General' }, { id: 'assistant', label: 'Assistant' }, { id: 'usage', label: 'Usage' }, { id: 'account', label: 'Account' }] as const;
type Tab = (typeof TABS)[number]['id'];
const usd = (m?: number) => (m == null ? '—' : `$${(m / 1e6).toFixed(2)}`);

function UsageCard() {
  const { app } = useData(); const [usage, setUsage] = useState<any>(null); const [done, setDone] = useState(false);
  useEffect(() => { api('GET', '/v1/costs').then(setUsage).catch(() => setUsage(null)).finally(() => setDone(true)); }, []);
  const plan = app?.features.billing_mode === 'open' ? 'Free access' : app?.features.billing_mode === 'paid_required' ? 'Subscription' : 'Invitation';
  const limit = usage?.period_limit_microusd, spent = (usage?.reported_microusd ?? 0) + (usage?.held_microusd ?? 0);
  const pct = limit > 0 ? Math.min(100, Math.round((spent / limit) * 100)) : 0;
  return <section className="panel card set-card" aria-labelledby="usage-h">
    <div className="set-head"><h2 id="usage-h">This period</h2><span className="badge alt">{plan}</span></div>
    {usage ? <>
      <p className="set-big">{usd(usage.period_remaining_microusd)}<span> left of {usd(limit)}</span></p>
      <div className="meter" role="img" aria-label={`${pct}% of this period's allowance used`}><i style={{ width: `${pct}%` }} /></div>
      <dl className="set-facts"><div><dt>Used</dt><dd>{usd(usage.reported_microusd)}</dd></div><div><dt>Reserved for running tasks</dt><dd>{usd(usage.held_microusd)}</dd></div></dl>
    </> : <p className="faint">{done ? 'Usage is not available right now.' : 'Loading…'}</p>}
  </section>;
}

export function Settings() {
  const { app, signOut } = useData(); const s = useSettings(); const [style, setStyle] = useAnswerStyle();
  const [tab, setTab] = useState<Tab>('general'); const list = useRef<HTMLDivElement>(null);
  const move = (e: React.KeyboardEvent, i: number) => {
    const next = e.key === 'ArrowRight' ? (i + 1) % TABS.length : e.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length : e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : -1;
    if (next < 0) return; e.preventDefault(); setTab(TABS[next].id); list.current?.querySelectorAll<HTMLElement>('[role=tab]')[next]?.focus();
  };
  return (
    <div className="center">
      <header className="page-head"><div><h1>Settings</h1><p>Make Lumina work the way you like.</p></div></header>
      <div className="tabs" role="tablist" aria-label="Settings sections" ref={list}>{TABS.map((t, i) =>
        <button key={t.id} type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} tabIndex={tab === t.id ? 0 : -1} className="tab" onClick={() => setTab(t.id)} onKeyDown={e => move(e, i)}>{t.label}</button>)}</div>
      <div className="set-panel" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'general' && <>
          <section className="panel card set-card" aria-labelledby="look-h"><h2 id="look-h">Look and feel</h2>
            <div className="toggle-list"><Toggle label="Reduce motion" hint="Stops the planet and animations" checked={s.reducedMotion} onChange={s.setReducedMotion} />
              <Toggle label="Compact layout" hint="Tighter spacing throughout" checked={s.compact} onChange={s.setCompact} /></div></section>
          <section className="panel card set-card" aria-labelledby="answer-style-h"><h2 id="answer-style-h">Answer style</h2>
            <div className="seg wide" role="radiogroup" aria-labelledby="answer-style-h">{STYLES.map(k =>
              <button key={k} type="button" role="radio" aria-checked={style === k} className="seg-item" onClick={() => setStyle(k)}>{STYLE_INFO[k].label}</button>)}</div>
            <p className="muted" aria-live="polite">{STYLE_INFO[style].hint}</p>
            <p className="faint">Longer answers cost a little more. Ultra (generated code in a sandbox) is planned and not available.</p></section></>}
        {tab === 'assistant' && <><YourBrowser /><OwnModel /><MemoryNotes /></>}
        {tab === 'usage' && <><UsageCard /><Credits /></>}
        {tab === 'account' && <section className="panel card set-card" aria-labelledby="acct-h"><h2 id="acct-h" className="sr">Account</h2>
          <div className="set-id"><span className="set-avatar" aria-hidden="true">{(app?.user.email?.[0] ?? '?').toUpperCase()}</span><div><b>{app?.user.email}</b><p className="faint">Signed in</p></div></div>
          <div className="int-row"><button className="btn" onClick={signOut}>Sign out</button><a className="btn tertiary" href="/account/">Classic view</a></div></section>}
      </div>
    </div>);
}
