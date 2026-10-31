import { useEffect, useRef, type SVGProps } from 'react';
import { useSafety } from '../../lib/useSafety';
import SafetyDialog from './SafetyDialog';

/** Same drawing language as Icons.tsx (24 grid, 1.6 stroke, currentColor); kept here so the feature stays one folder. */
const Shield = (p: SVGProps<SVGSVGElement>) => (
  <svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden {...p}>
    <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" />
  </svg>);

/** The one thing the rest of the app knows about this feature. Renders nothing unless this account is the owner or was granted the menu. Mount it inside the sidebar's <nav>:
 *  `.nav button` already gives it the look of the other items, and `.lbl` folds away with the sidebar. */
export default function SafetyButton() {
  const model = useSafety(); const button = useRef<HTMLButtonElement>(null); const wasOpen = useRef(false);
  useEffect(() => { if (wasOpen.current && !model.open) button.current?.focus(); wasOpen.current = model.open; }, [model.open]);       // focus goes back where it came from
  if (!model.account) return null;
  const off = model.account.off_count;
  return (<>
    <button type="button" ref={button} data-safety="button" title="Safety" onClick={model.show}>
      <Shield width={20} height={20} /><span className="lbl">Safety{off > 0 ? ` · ${off} off` : ''}</span>
    </button>
    {model.open && <SafetyDialog model={model} />}
  </>);
}
