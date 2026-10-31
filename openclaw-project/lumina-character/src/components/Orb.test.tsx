import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, waitFor } from '@testing-library/react';
import { SettingsProvider } from '../state/settings';

const addOrb = vi.fn(() => () => {});
vi.mock('../lib/orbLoop', () => ({ addOrb: (...a: unknown[]) => (addOrb as any)(...a) }));
import Orb from './Orb';

const noopCtx = new Proxy({}, { get: () => () => {}, set: () => true });
function stubSystem(osReducedMotion: boolean) {
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: osReducedMotion && q.includes('reduce'), addEventListener() {}, removeEventListener() {}, media: q }));
}
const show = (ui = <Orb state="working" size={20} />) => render(<SettingsProvider>{ui}</SettingsProvider>);

beforeEach(() => { localStorage.clear(); addOrb.mockClear(); vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(noopCtx as any); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('Orb', () => {
  it('animates by default', async () => {
    stubSystem(false); show();
    await waitFor(() => expect(addOrb).toHaveBeenCalled());
  });

  it('is a still frame when the system asks for reduced motion and Lumina has not been told otherwise', async () => {
    stubSystem(true); show();
    await new Promise(r => setTimeout(r, 50));
    expect(addOrb).not.toHaveBeenCalled();
  });

  it("follows Lumina's own switch: turning animations on in Lumina animates the orb even when the system setting is on", async () => {
    stubSystem(true); localStorage.setItem('lumina.reducedMotion', '0'); show();
    await waitFor(() => expect(addOrb).toHaveBeenCalled());
  });

  it("is still when Lumina's Reduce motion is on, whatever the system says", async () => {
    stubSystem(false); localStorage.setItem('lumina.reducedMotion', '1'); show();
    await new Promise(r => setTimeout(r, 50));
    expect(addOrb).not.toHaveBeenCalled();
  });

  it('is decorative unless it is given a label', () => {
    stubSystem(false);
    const plain = show(); const c = plain.container.querySelector('canvas')!;
    expect(c.getAttribute('aria-hidden')).toBe('true'); expect(c.getAttribute('role')).toBe('presentation'); plain.unmount();
    const named = show(<Orb state="searching" size={64} label="Searching" />); const n = named.container.querySelector('canvas')!;
    expect(n.getAttribute('role')).toBe('img'); expect(n.getAttribute('aria-label')).toBe('Searching'); expect(n.getAttribute('aria-hidden')).toBeNull();
  });

  it('animates at most three orbs at once', async () => {
    stubSystem(false);
    show(<><Orb /><Orb /><Orb /><Orb /><Orb /></>);
    await waitFor(() => expect(addOrb).toHaveBeenCalled());
    await new Promise(r => setTimeout(r, 50));
    expect(addOrb).toHaveBeenCalledTimes(3);
  });
});
