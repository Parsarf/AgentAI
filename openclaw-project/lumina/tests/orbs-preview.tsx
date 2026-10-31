// Manual motion fixture: npm run dev, then /app/tests/orbs.html.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import Orb from '../src/components/Orb';
import { Spark } from '../src/components/Icons';
import { ORB_LABELS, type OrbState } from '../src/lib/orbs';
import { SettingsProvider, useSettings } from '../src/state/settings';
import '../src/styles/tokens.css';
import '../src/styles/ui.css';
import './orbs-preview.css';

function Preview() {
  const [state, setState] = useState<OrbState>('lumina');
  const [size, setSize] = useState<20 | 48 | 64>(64);
  const { reducedMotion, setReducedMotion } = useSettings();
  return <main>
    <header><Spark /><h1>Lumina motion</h1></header>
    <p>The spark settles into each activity and returns to thinking. Select another state mid-transition to check continuity.</p>
    <section className="stage" aria-label="Orb preview">
      <Orb state={state} size={size} label={ORB_LABELS[state]} />
      <span role="status">{state === 'lumina' ? 'Lumina · Thinking' : `${ORB_LABELS[state]} · ${state}`}</span>
    </section>
    <div className="controls" aria-label="Preview size">{([20, 48, 64] as const).map(s =>
      <button className="chip" key={s} aria-pressed={size === s} onClick={() => setSize(s)}>{s}px</button>)}
      <button className="chip" aria-pressed={reducedMotion} onClick={() => setReducedMotion(!reducedMotion)}>Reduce motion</button>
    </div>
    <div className="states" aria-label="Orb states">{(Object.keys(ORB_LABELS) as OrbState[]).map(s =>
      <button className="chip" key={s} aria-pressed={state === s} onClick={() => setState(s)}>
        <Orb state={s} size={48} still /><span>{s === 'lumina' ? 'Lumina' : s}</span>
      </button>)}</div>
  </main>;
}
createRoot(document.getElementById('root')!).render(<SettingsProvider><Preview /></SettingsProvider>);
