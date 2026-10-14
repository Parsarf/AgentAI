import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import Backdrop from './Backdrop';

const settings = vi.hoisted(() => ({ reducedMotion: false }));
vi.mock('../state/settings', () => ({ useSettings: () => settings }));
vi.mock('./Globe', () => ({ default: () => <div data-testid="loaded-globe" /> }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); settings.reducedMotion = false; });

describe('decorative backdrop', () => {
  it('replaces the fallback when the globe loads', async () => {
    vi.stubGlobal('requestIdleCallback', (fn: () => void) => { fn(); return 1; });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as any);
    const { container } = render(<Backdrop />);
    await screen.findByTestId('loaded-globe');
    expect(container.querySelector('.globe-fallback')).toBeNull();
  });
  it('uses only the static fallback when motion is disabled', () => {
    settings.reducedMotion = true;
    const { container } = render(<Backdrop />);
    expect(container.querySelectorAll('.globe-fallback')).toHaveLength(1);
    expect(screen.queryByTestId('loaded-globe')).toBeNull();
  });
});
