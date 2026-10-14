import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import Orb from './Orb';
const mock = vi.hoisted(() => ({
  reducedMotion: false,
  draw: vi.fn(),
  frame: undefined as undefined | ((seconds: number) => void),
  stop: vi.fn(),
}));
vi.mock('../state/settings', () => ({ useSettings: () => ({ reducedMotion: mock.reducedMotion }) }));
vi.mock('../vendor/thinking-orbs', () => ({
  resolvePreset: () => ({ mode: 'test', speed: 1, opts: {} }),
  MODE_DRAWS: { test: (...args: unknown[]) => mock.draw(...args) },
}));
vi.mock('../lib/orbLoop', () => ({ addOrb: (_canvas: unknown, entry: { draw(seconds: number): void }) => { mock.frame = entry.draw; return mock.stop; } }));
let now = 0;
let ctx: { globalAlpha: number; setTransform: ReturnType<typeof vi.fn>; clearRect: ReturnType<typeof vi.fn>; drawImage: ReturnType<typeof vi.fn> };
beforeEach(() => {
  now = 0; mock.reducedMotion = false; mock.frame = undefined;
  ctx = { globalAlpha: 1, setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn() };
  vi.spyOn(performance, 'now').mockImplementation(() => now * 1000);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx as any);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });
describe('calm orb motion', () => {
  it('renders a 48px avatar using the 64px geometry and runs at 55% speed', () => {
    const { container } = render(<Orb size={48} />);
    expect((container.firstChild as HTMLElement).style.width).toBe('48px');
    const before = mock.draw.mock.calls.at(-1)![2] as number;
    mock.frame!(0.1);
    expect((mock.draw.mock.calls.at(-1)![2] as number) - before).toBeCloseTo(0.055);
    expect(mock.draw.mock.calls.at(-1)![1]).toBe(64);
  });
  it('blends states over 600ms without restarting the motion timeline', () => {
    const alphas: number[] = [];
    mock.draw.mockImplementation(() => alphas.push(ctx.globalAlpha));
    const { rerender } = render(<Orb state="breathing" size={48} />);
    mock.frame!(0.1); now = 0.1;
    const before = mock.draw.mock.calls.at(-1)![2] as number;
    rerender(<Orb state="searching" size={48} />);
    expect(mock.draw.mock.calls.at(-1)![2]).toBe(before);
    expect(alphas.at(-1)).toBe(0);
    mock.frame!(0.4);
    expect(alphas.at(-1)).toBeCloseTo(0.5);
    // Interrupt halfway through: preserve the current blend, not a blank frame.
    now = 0.4; rerender(<Orb state="composing" size={48} />);
    expect(ctx.drawImage).toHaveBeenCalled();
    expect(alphas.at(-1)).toBe(0);
    mock.frame!(1.0);
    expect(alphas.at(-1)).toBeCloseTo(1);
  });
  it('switches directly to a static state when motion is reduced', () => {
    mock.reducedMotion = true;
    const { rerender } = render(<Orb state="breathing" size={48} />);
    rerender(<Orb state="searching" size={48} />);
    expect(ctx.drawImage).not.toHaveBeenCalled();
    expect(ctx.globalAlpha).toBe(1);
    expect(mock.frame).toBeUndefined();
  });
  it('avoids jumping ahead after a hidden-tab or typing pause', () => {
    render(<Orb size={48} />);
    const before = mock.draw.mock.calls.at(-1)![2] as number;
    mock.frame!(60);
    expect((mock.draw.mock.calls.at(-1)![2] as number) - before).toBeCloseTo(0.055);
  });
});
