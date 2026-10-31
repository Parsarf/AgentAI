import { useNavigate } from 'react-router-dom';
import * as I from './Icons';
import { describeOwnBrowser, useOwnBrowser } from '../lib/ownBrowser';

/** The switch at the top of every chat: run my browser tasks in my own Chrome. Hidden until the browser service says the feature is there. */
export default function BrowserToggle() {
  const b = useOwnBrowser(); const nav = useNavigate();
  if (!b.ready || !b.available) return null;
  const { state, label } = describeOwnBrowser(b);
  const click = async () => {
    const turningOn = !b.use;
    const ok = await b.setUse(turningOn);
    if (ok && turningOn && !b.paired) void nav('/settings#your-browser');      // nothing to run it on yet: take them to where a browser is connected
  };
  return (
    <button type="button" className="iconbtn small ghost own-browser" data-state={state} aria-pressed={b.use} aria-label={label} title={label} onClick={click}>
      <I.OwnBrowser width={18} height={18} />{state === 'live' && <span className="dot live" aria-hidden="true" />}{state === 'waiting' && <span className="dot waiting" aria-hidden="true" />}
    </button>);
}
