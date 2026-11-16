import { useEffect, useRef, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import Workspace from '../components/frame/Workspace';
import { useFrame } from '../components/frame/FrameProvider';
import { useSelection } from '../components/frame/Assistant';
import { Integrations } from './Info';
import { api } from '../lib/api';
import { useData } from '../state/data';
import Toggle from '../components/ui/Toggle';
import { useSettings } from '../state/settings';
import { STYLES, STYLE_INFO, useAnswerStyle } from '../lib/answerStyle';
import Credits from '../components/Credits';
import YourBrowser from '../components/YourBrowser';
import OwnModel from '../components/OwnModel';
import MemoryNotes from '../components/MemoryNotes';
import SpendingLimits from '../components/SpendingLimits';
import AccessPage from '../components/AccessPage';
import DataControls from '../components/DataControls';
import Organization from '../components/Organization';
import '../components/settings.css';

const TABS = [{ id: 'general', label: 'General' }, { id: 'assistant', label: 'Assistant' }, { id: 'access', label: 'Access' }, { id: 'integrations', label: 'Integrations' }, { id: 'usage', label: 'Usage' }, { id: 'account', label: 'Account' }] as const;
/** Older names of sections (links in mail, the command bar), mapped to where they live now. */
const ALIASES: Record<string, Tab> = { appearance: 'general', memory: 'assistant', model: 'assistant', browser: 'assistant', data: 'account' };
type Tab = (typeof TABS)[number]['id'];
const usd = (m?: number) => (m == null ? '—' : `$${(m / 1e6).toFixed(2)}`);

function UsageCard() {
  const { app } = useData(); const [usage, setUsage] = useState<any>(null); const [done, setDone] = useState(false);
  useEffect(() => { api('GET', '/v1/costs').then(setUsage).catch(() => setUsage(null)).finally(() => setDone(true)); }, []);
  const plan = app?.features.billing_mode === 'open' ? 'Free access' : app?.features.billing_mode === 'paid_required' ? 'Subscription' : 'Invitation';
  // `period_limit_microusd` is the limit the customer chose for the period (null: none; Lumina sets no limit of its own).
  const limit: number | null = usage?.period_limit_microusd ?? null, spent = (usage?.reported_microusd ?? 0) + (usage?.held_microusd ?? 0);
  const pct = limit && limit > 0 ? Math.min(100, Math.round((spent / limit) * 100)) : 0;
  return <section className="panel card set-card" aria-labelledby="usage-h">
    <div className="set-head"><h2 id="usage-h">This period</h2><span className="badge alt">{plan}</span></div>
    {usage ? <>
      {limit ? <>
        <p className="set-big">{usd(usage.period_remaining_microusd)}<span> left of your {usd(limit)} limit</span></p>
        <div className="meter" role="img" aria-label={`${pct}% of your limit for this period used`}><i style={{ width: `${pct}%` }} /></div>
      </> : <p className="set-big">{usd(spent)}<span> used · no spending limit</span></p>}
      <dl className="set-facts"><div><dt>Used</dt><dd>{usd(usage.reported_microusd)}</dd></div><div><dt>Last 24 hours</dt><dd>{usd(usage.day_reported_microusd)}</dd></div>
        {usage.held_microusd > 0 && <div><dt>Held for running tasks</dt><dd>{usd(usage.held_microusd)}</dd></div>}</dl>
    </> : <p className="faint">{done ? 'Usage is not available right now.' : 'Loading…'}</p>}
  </section>;
}

export function Settings() {
  const { app, signOut } = useData(); const s = useSettings(); const [style, setStyle] = useAnswerStyle(); const frame = useFrame();
  const { section } = useParams(); const nav = useNavigate(); const list = useRef<HTMLDivElement>(null);
  // A link elsewhere opens a section directly: /settings/access (the older ?tab=access still works).
  const legacy = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('tab') : null;
  const asked = section ?? legacy ?? 'general';
  const tab: Tab = TABS.some(t => t.id === asked) ? asked as Tab : ALIASES[asked] ?? 'general';
  useSelection({ looking: { kind: 'page', page: 'settings' }, words: `Settings, ${TABS.find(t => t.id === tab)!.label}`, actions: [] });
  const choose = (next: Tab) => { void nav(`/settings/${next}`); if (frame?.sheet === 'context') frame.setSheet(null); };
  const move = (e: React.KeyboardEvent, i: number) => {
    const forward = e.key === 'ArrowDown' || e.key === 'ArrowRight', back = e.key === 'ArrowUp' || e.key === 'ArrowLeft';
    const next = forward ? (i + 1) % TABS.length : back ? (i + TABS.length - 1) % TABS.length : e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : -1;
    if (next < 0) return; e.preventDefault(); choose(TABS[next].id); window.setTimeout(() => list.current?.querySelectorAll<HTMLElement>('[role=tab]')[next]?.focus(), 0);
  };
  if (section && section !== tab) return <Navigate to={`/settings/${tab}`} replace />;
  const sections = <div className="set-sections" role="tablist" aria-label="Settings sections" aria-orientation="vertical" ref={list}>{TABS.map((t, i) =>
    <button key={t.id} type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} tabIndex={tab === t.id ? 0 : -1} className="files-folder" onClick={() => choose(t.id)} onKeyDown={e => move(e, i)}>{t.label}</button>)}</div>;
  return (
    <Workspace title={TABS.find(t => t.id === tab)!.label} context={sections} contextLabel="Settings" className="settings-page">
      <div className="set-panel center" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'general' && <>
          <section className="panel card set-card" aria-labelledby="look-h"><h2 id="look-h">Look and feel</h2>
            <div className="toggle-list"><Toggle label="Reduce motion" hint="Stops the planet and animations" checked={s.reducedMotion} onChange={s.setReducedMotion} />
              <Toggle label="Compact layout" hint="Tighter spacing and shorter rows throughout (Shift+D)" checked={s.compact} onChange={s.setCompact} /></div>
            <div className="set-row"><span id="contrast-h">Contrast</span>
              <div className="seg" role="radiogroup" aria-labelledby="contrast-h">{([['system', 'Like this device'], ['normal', 'Normal'], ['more', 'More contrast']] as const).map(([k, label]) =>
                <button key={k} type="button" role="radio" aria-checked={s.contrast === k} className="seg-item" onClick={() => s.setContrast(k)}>{label}</button>)}</div></div>
            <p className="faint small">More contrast makes text and outlines stronger. “Like this device” follows your system’s own contrast setting.</p></section>
          <section className="panel card set-card" aria-labelledby="answer-style-h"><h2 id="answer-style-h">Answer style</h2>
            <div className="seg wide" role="radiogroup" aria-labelledby="answer-style-h">{STYLES.map(k =>
              <button key={k} type="button" role="radio" aria-checked={style === k} className="seg-item" onClick={() => setStyle(k)}>{STYLE_INFO[k].label}</button>)}</div>
            <p className="muted" aria-live="polite">{STYLE_INFO[style].hint}</p>
            <p className="faint">Longer answers cost a little more. Ultra (generated code in a sandbox) is planned and not available.</p></section></>}
        {tab === 'assistant' && <><YourBrowser /><OwnModel /><MemoryNotes /></>}
        {tab === 'access' && <AccessPage />}
        {tab === 'integrations' && <Integrations />}
        {tab === 'usage' && <><UsageCard /><SpendingLimits /><Credits /></>}
        {tab === 'account' && <><section className="panel card set-card" aria-labelledby="acct-h"><h2 id="acct-h" className="sr">Account</h2>
          <div className="set-id"><span className="set-avatar" aria-hidden="true">{(app?.user.email?.[0] ?? '?').toUpperCase()}</span><div><b>{app?.user.email}</b><p className="faint">Signed in</p></div></div>
          <div className="int-row"><button className="btn" onClick={signOut}>Sign out</button><a className="btn tertiary" href="/account/">Classic view</a></div></section><Organization /><DataControls /></>}
      </div>
    </Workspace>);
}
